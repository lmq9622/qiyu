# -*- coding: utf-8 -*-
"""Qiyu Runtime · RuntimeManager（规格§12）。

负责：启动 / 停止 / 检测 / backend 选择 / 模型加载卸载 / 进程管理 / 崩溃恢复 / 日志。
目标：Qiyu.exe → RuntimeManager → RealtimeBrain / MainBrain / TTS / STT / Tool / Memory
所有服务生命周期统一管理。

backend 选择（规格§4/§13）：HardwareDetector + BackendCapability + MicroBenchmark 共同决定，
不是「检测到 GPU 就用 GPU」。
"""
from __future__ import annotations

import time
from typing import Optional

from loguru import logger

from runtime.benchmark import BenchmarkResult, micro_benchmark
from runtime.hardware import BackendCapability, HardwareDetector, HardwareProfile
from runtime.providers import ProviderKind, ProviderRegistry, RealtimeBrainProvider
from runtime.realtime import UnavailableRealtimeBackend, discover_models
from runtime.realtime_unified import build_realtime_provider

# backend 优先级：NVIDIA+CUDA → Vulkan → CPU（仅作初始候选排序，最终由 MicroBenchmark 定夺）
BACKEND_PRIORITY = ("cuda", "vulkan", "cpu")

_runtime_manager_instance = None


def get_runtime_manager():
    """demo/Router 使用的全局 RuntimeManager（进程内单实例约定）。"""
    return _runtime_manager_instance


class RuntimeManager:
    """Qiyu 运行时管理器：统一管理 Provider 生命周期与 backend 选择。"""

    def __init__(self) -> None:
        global _runtime_manager_instance
        _runtime_manager_instance = self
        self.registry = ProviderRegistry()
        self.hardware = HardwareDetector()
        self.profile: Optional[HardwareProfile] = None
        self.backends: list[BackendCapability] = []
        self._started_at: float = 0.0
        self._realtime: Optional[RealtimeBrainProvider] = None
        self._realtime_backend: Optional[BackendCapability] = None
        self._crashes: dict[str, list[float]] = {}  # provider_id -> 崩溃时间戳
        self._bench_results: list[BenchmarkResult] = []

    # ---------- 启动/停止 ----------
    def start(self) -> None:
        self.profile = self.hardware.detect()
        self.backends = self.hardware.probe_backends()
        self._started_at = time.time()
        # v0.0.26：统一 Auto Provider —— 业务只认 RealtimeBrainProvider，
        # 实际 official/gguf/cuda 候选由 Auto 启动实测后选择，不做固定优先级
        self._realtime = build_realtime_provider(auto_bench=True)
        self.registry.register(self._realtime, fallback_ids=[])
        self._realtime_backend = None
        logger.info(
            f"[Runtime] 启动完成，Realtime Brain={self._realtime.id} "
            f"候选={sorted(getattr(self._realtime, 'candidates', {}) or {}) or '无'}"
        )

    def stop(self) -> None:
        self._started_at = 0.0
        logger.info("[Runtime] 已停止")

    @property
    def running(self) -> bool:
        return self._started_at > 0

    # ---------- 微基准 + backend 选择（规格§4/§13） ----------
    async def bench(self, bench_fn=None) -> list[dict]:
        """v0.0.26：把实测交给统一 Auto Provider（不在这里做固定优先级/启发式兜底）。"""
        if self._realtime is not None:
            self._bench_results = await self._realtime.benchmark()
            return self._bench_results
        return []

    def select_backend(self, role: str) -> Optional[BackendCapability]:
        """先看基准结果，没有则按能力矩阵 + 优先级选择（CPU 永远是底线）。"""
        candidates = [c for c in self.backends if c.available]
        if role == "realtime":
            candidates = [c for c in candidates if c.text]
            # 只保留当前 Realtime 后端真实能跑的 backend（如 MiniMind-O 只有 cpu/cuda）
            supported = getattr(self._realtime, "supported_backends", None)
            if callable(supported):
                sup = set(supported())
                candidates = [c for c in candidates if c.backend in sup]
        if self._bench_results:
            top = self._bench_results[0]
            hit = next((c for c in candidates if c.backend == top.backend), None)
            if hit is not None:
                return hit
        for prio in BACKEND_PRIORITY:
            for c in candidates:
                if c.backend == prio:
                    return c
        return candidates[0] if candidates else None

    # ---------- 模型加载/卸载（规格§12/§11） ----------
    def model_status(self) -> dict:
        """MiniMind-O 模型清单 + Auto 已选后端（每组件独立 backend，规格§6）。"""
        model = discover_models()
        plan = []
        if self._realtime is not None and hasattr(self._realtime, "model_plan"):
            try:
                plan = self._realtime.model_plan(self.backends)
            except Exception:
                plan = []
        omni = getattr(self._realtime, "_runtime", None)
        _rt = getattr(self._realtime, "_runtime", "") if self._realtime else ""
        if not isinstance(_rt, str):
            # omni 后端的 _runtime 是加载器对象：只上报字符串标签，绝不把对象塞进状态
            _rt = str(getattr(self._realtime, "runtime_label", "")) or type(_rt).__name__
        return {
            "models_dir": str(model.root),
            "thinker_present": model.has_thinker(),
            "components": model.present_components(),
            "plan": [p.to_dict() for p in plan],
            "runtime": _rt,
            "realtime_available": (self._realtime.health().get("ok") if self._realtime else False),
            "selected_backend": self._active_backend_name(),
            "selected_model": self._active_model_name(),
            "auto": {
                "candidates": getattr(self._realtime, "to_dict", lambda: {})().get("candidates", []),
                "selection_reason": getattr(self._realtime, "selection_reason", ""),
                "benchmarks": getattr(self._realtime, "bench_results", []),
            } if self._realtime is not None else None,
        }

    def _active_backend_name(self) -> str:
        if self._realtime is None:
            return ""
        try:
            return str(self._realtime.health().get("backend") or "")
        except Exception:
            return ""

    def _active_model_name(self) -> str:
        if self._realtime is None:
            return ""
        try:
            return str(self._realtime.health().get("model") or "")
        except Exception:
            return ""

    async def load_model(self, path: str = "") -> dict:
        """加载 MiniMind-O Thinker 权重（安装器下载后调用）；成功返回 status。"""
        if self._realtime is None:
            return {"ok": False, "reason": "Realtime Provider 未初始化"}
        r = await self._realtime.load(backend=str(path or "auto"))
        r["path"] = str(path or "")
        r["status"] = self.model_status()
        return r

    async def unload_model(self) -> dict:
        """卸载 Realtime 模型（释放内存；下次 judge 重新加载）。"""
        if self._realtime is not None:
            try:
                return await self._realtime.unload()
            except Exception as e:
                logger.warning(f"[Runtime] 卸载 Realtime 模型失败: {e}")
        return {"ok": True}

    # ---------- Realtime Brain ----------
    @property
    def realtime(self) -> RealtimeBrainProvider:
        if self._realtime is None:
            self._realtime = UnavailableRealtimeBackend()
        return self._realtime

    async def realtime_judge(self, user_text: str, context: Optional[dict] = None):
        return await self.realtime.judge(user_text, context)

    # ---------- 崩溃恢复（轻量） ----------
    def record_crash(self, provider_id: str) -> None:
        now = time.time()
        self._crashes.setdefault(provider_id, []).append(now)
        self._crashes[provider_id] = [t for t in self._crashes[provider_id] if now - t < 600]
        logger.warning(f"[Runtime] {provider_id} 崩溃，10 分钟内 {len(self._crashes[provider_id])} 次")

    def crash_backoff_ok(self, provider_id: str, max_in_window: int = 5) -> bool:
        return len(self._crashes.get(provider_id, [])) < max_in_window

    # ---------- 状态 ----------
    def status(self) -> dict:
        from runtime.perf import perf_monitor
        bench = []
        if self._realtime is not None:
            bench = getattr(self._realtime, "bench_results", []) or []
        return {
            "running": self.running,
            "started_at": round(self._started_at, 3),
            "hardware": self.profile.to_dict() if self.profile else {},
            "backends": [c.to_dict() for c in self.backends],
            "benchmark": {
                "ran_at": round(getattr(self._realtime, "_bench_at", 0.0), 3),
                "results": bench,
            },
            "realtime": {
                "backend": self._active_backend_name(),
                "model": self._active_model_name(),
                "provider": self.realtime.to_dict(),
            },
            "models": self.model_status(),
            "providers": self.registry.list(),
            "crashes": {k: len(v) for k, v in self._crashes.items()},
            "perf": perf_monitor.snapshot(),
        }
