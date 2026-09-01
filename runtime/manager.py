# -*- coding: utf-8 -*-
"""Qiyu Runtime · RuntimeManager（M2）。

负责：启动 / 停止 / 状态 / backend 选择 / 模型加载卸载 / 崩溃恢复 / 日志。
目标：Qiyu.exe → RuntimeManager → RealtimeBrain / MainBrain / TTS / STT / Tool / Memory
所有服务生命周期统一管理。
"""
from __future__ import annotations

import time
from typing import Optional

from loguru import logger

from runtime.hardware import BackendCapability, HardwareDetector, HardwareProfile
from runtime.providers import ProviderKind, ProviderRegistry, RealtimeBrainProvider
from runtime.realtime import UnavailableRealtimeBackend

# backend 优先级：NVIDIA+CUDA → Vulkan → CPU
# 注意：不是「检测到 GPU 就使用 GPU」；CPU 在低端设备上可能更合适。
BACKEND_PRIORITY = ("cuda", "vulkan", "cpu")


class RuntimeManager:
    """Qiyu 运行时管理器：统一管理 Provider 生命周期与 backend 选择。"""

    def __init__(self) -> None:
        self.registry = ProviderRegistry()
        self.hardware = HardwareDetector()
        self.profile: Optional[HardwareProfile] = None
        self.backends: list[BackendCapability] = []
        self._started_at: float = 0.0
        self._realtime: Optional[RealtimeBrainProvider] = None
        self._realtime_backend: Optional[BackendCapability] = None
        self._crashes: dict[str, list[float]] = {}  # provider_id -> 崩溃时间戳

    # ---------- 启动/停止 ----------
    def start(self) -> None:
        self.profile = self.hardware.detect()
        self.backends = self.hardware.probe_backends()
        self._started_at = time.time()
        # Realtime Brain：当前分发走诚实兜底（未内置 MiniMind-O）
        self._realtime = UnavailableRealtimeBackend()
        self.registry.register(self._realtime, fallback_ids=[])
        self._realtime_backend = self.select_backend("realtime")
        logger.info(f"[Runtime] 启动完成，Realtime Brain={self._realtime_backend.backend if self._realtime_backend else '无'}")

    def stop(self) -> None:
        self._started_at = 0.0
        logger.info("[Runtime] 已停止")

    @property
    def running(self) -> bool:
        return self._started_at > 0

    # ---------- backend 选择 ----------
    def select_backend(self, role: str) -> Optional[BackendCapability]:
        """按优先级选 backend；cuda/vulkan 可用且能力满足时才选，否则回退 CPU。"""
        available = [c for c in self.backends if c.available]
        if role == "realtime":
            # Realtime 对 text 有硬要求
            candidates = [c for c in available if c.text]
        else:
            candidates = available
        for prio in BACKEND_PRIORITY:
            for c in candidates:
                if c.backend == prio:
                    return c
        return available[0] if available else None

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
        return {
            "running": self.running,
            "started_at": round(self._started_at, 3),
            "hardware": self.profile.to_dict() if self.profile else {},
            "backends": [c.to_dict() for c in self.backends],
            "realtime": {
                "backend": self._realtime_backend.backend if self._realtime_backend else "",
                "provider": self.realtime.to_dict(),
            },
            "providers": self.registry.list(),
            "crashes": {k: len(v) for k, v in self._crashes.items()},
        }
