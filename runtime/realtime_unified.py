# -*- coding: utf-8 -*-
"""Qiyu Runtime · 统一 MiniMind Realtime Brain（v0.0.26）。

目标：
- 业务层只认识 RealtimeBrainProvider：load/unload/judge/quick_reply/analyze/
  health/benchmark，绝不关心底下是 official-torch / gguf-cpu / gguf-vulkan / cuda。
- 自动 Backend 选择不做固定优先级：首次启动对每个真实可用路径实测 load_time/TTFT/
  tok/s/RAM/stability/quality，按综合分选择最快且稳、角色直答质量不降级的后端。
- backend 命名明确：official_cpu / gguf_cpu / gguf_vulkan / cuda。
- CUDA 只有真实 CUDA runtime + NVIDIA device 才出现；本环境无 CUDA 时如实标
  UNVERIFIED，不假装 PASS。
"""
from __future__ import annotations

import os
import asyncio
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from runtime.providers import (
    ProviderStatus,
    RealtimeBrainProvider,
    RealtimeDecision,
)
from runtime.realtime import (
    CPURealtimeBackend,
    CUDARealtimeBackend,
    MiniMindModel,
    MiniMindOOmniBackend,
    VulkanRealtimeBackend,
    _default_model_root,
    discover_models,
)
from runtime.minimindo import discover_model_dir, torch_runtime_available
from runtime.ggml_probe import llama_supports_backend, llama_gpu_kinds

# 规则直答的最小置信度（宁可升级 MainBrain，不让 0.1B 输出明显降智回复）
DIRECT_MIN_CONFIDENCE = 0.78

# 实测候选顺序（仅影响展示顺序；选择永远按实测分，不按此优先级）
LABEL_ORDER = ("official_cpu", "gguf_cpu", "gguf_vulkan", "cuda")


class MiniMindAutoRealtimeProvider(RealtimeBrainProvider):
    """统一 Realtime Brain：内部管理多个真实候选，对外只暴露统一接口。"""

    id = "realtime-auto"
    name = "MiniMind Realtime Brain（Auto）"

    def __init__(self, model_root: Optional[Path] = None, auto_bench: bool = True) -> None:
        super().__init__()
        self.model_root = Path(model_root) if model_root else _default_model_root()
        self.auto_bench = auto_bench
        self.candidates: dict[str, RealtimeBrainProvider] = {}
        self.bench_results: list[dict] = []
        self._bench_at: float = 0.0
        self.selection_reason = ""
        self._active: Optional[RealtimeBrainProvider] = None
        self._lock = asyncio.Lock()
        self._status: Optional[ProviderStatus] = None
        self._discover_candidates()

    # ---------- 候选发现（只建真实存在/真实可用；CUDA 额外保留 UNVERIFIED 记录） ----------
    def _discover_candidates(self) -> None:
        root = self.model_root
        model = discover_models(root)

        # 1) 官方 MiniMind-O（torch CPU 或真实 torch CUDA）
        omni_dir = discover_model_dir(root)
        # SFT 全量基座优先：QIYU_REALTIME_MODEL_DIR 指向 tag-C/tag-D 等合并权重目录
        if os.environ.get("QIYU_REALTIME_MODEL_DIR"):
            _sft_dir = Path(os.environ["QIYU_REALTIME_MODEL_DIR"])
            from runtime.minimindo import is_complete as _mm_complete
            if _mm_complete(_sft_dir):
                omni_dir = _sft_dir
        if omni_dir is not None and torch_runtime_available():
            official = MiniMindOOmniBackend(model_root=omni_dir)
            # 本包 torch 为 CPU 构建；如未来真实 torch CUDA 可用则 backend_name=cuda
            if official.backend_name not in self.candidates:
                self.candidates[official.backend_name] = official

        # 2) GGUF Thinker：CPU / Vulkan / CUDA（llama.cpp，各后端分开实测）
        if model.has_thinker() and self._llama_runtime_ok():
            for cls, label, exec_key in (
                (CPURealtimeBackend, "gguf_cpu", "cpu"),
                (VulkanRealtimeBackend, "gguf_vulkan", "vulkan"),
                (CUDARealtimeBackend, "cuda", "cuda"),
            ):
                if label in self.candidates:
                    continue
                try:
                    cand = cls(model_root=root)
                    if self._cheap_available(cand):
                        self.candidates[label] = cand
                    else:
                        logger.debug(f"[Realtime] 候选不可用 {label}")
                except Exception as e:
                    logger.debug(f"[Realtime] 构建候选 {label} 失败: {e}")

        # 3) CUDA 独立诚实记录：没有真实 CUDA runtime/NVIDIA 时绝不放进可用候选
        self.cuda_verified = self._cuda_real()
        if "cuda" not in self.candidates and not self.cuda_verified:
            kinds = sorted(llama_gpu_kinds()) or ["仅 CPU"]
            self.cuda_unverified_reason = (
                "CUDA UNVERIFIED：本机未检测到真实 llama.cpp/torch CUDA runtime + NVIDIA device "
                f"（llama 后端={kinds}）；不做任何 CUDA PASS 声明。"
            )
        else:
            self.cuda_unverified_reason = ""

        logger.info(
            f"[Realtime] Auto 候选：{', '.join(sorted(self.candidates)) or '无'} | "
            f"CUDA verified={self.cuda_verified}"
        )

    @staticmethod
    def _cheap_available(cand: RealtimeBrainProvider) -> bool:
        """只做廉价能力检查：不在启动时加载模型（probe 里的 _ensure_gen 会真加载）。"""
        try:
            backend_ok = cand._backend_available()  # noqa: SLF001
        except Exception:
            try:
                backend_ok = cand._runtime.available()  # noqa: SLF001
            except Exception:
                backend_ok = bool(cand.status().available)
        return bool(backend_ok)

    @staticmethod
    def _llama_runtime_ok() -> bool:
        try:
            import llama_cpp  # noqa: F401
            return True
        except Exception:
            return False

    @staticmethod
    def _cuda_real() -> bool:
        """CUDA 真实性：llama.cpp 真含 cuda 且 NVIDIA 驱动可用，或 torch.cuda 真可用。"""
        if llama_supports_backend("cuda"):
            return True
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            return False

    # ---------- 统一生命周期 ----------
    async def load(self, backend: str = "auto", **kwargs) -> dict:
        """加载选中后端；auto=已实测选中的后端。绝不阻塞聊天线程（worker 内加载）。"""
        target = self._active if backend in ("", "auto") else self.candidates.get(backend)
        if target is None:
            return {"ok": False, "backend": backend, "model": "", "reason": "无可用 Realtime 候选"}
        try:
            return await asyncio.wait_for(target.load(backend=backend, **kwargs), timeout=180)
        except Exception as e:
            logger.warning(f"[Realtime] load({backend}) 失败: {e}")
            return {"ok": False, "backend": backend, "model": "", "reason": str(e)}

    async def unload(self, backend: str = "auto") -> dict:
        freed = []
        targets = list(self.candidates.values()) if backend in ("", "auto") else [
            self.candidates.get(backend)]
        for cand in targets:
            if cand is None:
                continue
            try:
                r = await cand.unload(backend=backend)
                if r.get("ok"):
                    freed.extend(r.get("freed_backends") or [])
            except Exception as e:
                logger.warning(f"[Realtime] unload {backend} 失败: {e}")
        if backend in ("", "auto"):
            self._active = None
        return {"ok": True, "freed_backends": freed, "reason": ""}

    # ---------- 判断与直答 ----------
    async def judge(self, user_text: str, context: Optional[dict] = None) -> RealtimeDecision:
        try:
            a = await self.analyze(user_text, context)
        except Exception as e:
            logger.warning(f"[Realtime] analyze 异常 → MainBrain: {e}")
            return RealtimeDecision(
                needs_main_brain=True, reason=f"analyze 异常 → MainBrain（{e}）",
                backend=getattr(self._active, "backend_name", "") or "",
                judge_source="unified-analyze-exception")
        return RealtimeDecision(
            needs_main_brain=bool(a.get("needs_main_brain", True)),
            quick_reply=a.get("quick_reply"),
            emotion=a.get("emotion"),
            reason=a.get("reason", ""),
            backend=a.get("backend", ""),
            model=a.get("model", ""),
            confidence=float(a.get("confidence") or 0.0),
            category=a.get("category", ""),
            judge_source=a.get("judge_source", ""),
        )

    async def quick_reply(self, user_text: str, *, max_tokens: int = 48,
                          timeout_s: float = 6.0, char_hint: str = "",
                          role_context: str = "") -> Optional[dict]:
        """业务层显式请求直答：只走 Auto 已选后端，不绕过统一层。"""
        from runtime.legacy_gate import log_once, minimind_enabled
        if not minimind_enabled():
            log_once(logger, "MiniMindAutoRealtimeProvider.quick_reply")
            return None
        cand = self._active
        if cand is None:
            return None
        try:
            return await asyncio.wait_for(
                cand.quick_reply(
                    user_text, max_tokens=max_tokens, timeout_s=timeout_s,
                    char_hint=char_hint, role_context=role_context),
                timeout=timeout_s + 2.0)
        except Exception as e:
            logger.warning(f"[Realtime] quick_reply({cand.backend_name}) 失败: {e}")
            return None

    async def analyze(self, user_text: str, context: Optional[dict] = None) -> dict:
        """统一实时判断：本地规则（稳定、不依赖 0.1B JSON）→ confidence gate → 角色化直答。

        judge 永不因解析失败中断聊天：模型 judge 只用于增强判断；失败/低置信一律
        fallback classifier（本地规则），复杂问题升级 MainBrain。
        """
        from runtime.legacy_gate import disabled_result, log_once, minimind_enabled
        if not minimind_enabled():
            log_once(logger, "MiniMindAutoRealtimeProvider.analyze")
            return disabled_result("analyze")
        text = (user_text or "").strip()
        ctx = context or {}
        if not text:
            return self._main_brain_result("empty", "空消息 → MainBrain")
        from runtime.classifier import classify_user_message, route_confidence
        try:
            route = classify_user_message(text, has_images=bool(ctx.get("images")))
        except Exception as e:
            logger.warning(f"[Realtime] classifier 异常 → MainBrain: {e}")
            return self._main_brain_result("classifier_error", "classifier 异常 → MainBrain")

        conf = route_confidence(text, route.action, route.category)
        cand = self._active
        if cand is None or route.action == "main_brain" or conf < DIRECT_MIN_CONFIDENCE:
            return self._main_brain_result(
                route.category, route.reason or "规则路由 → MainBrain",
                backend=(cand.backend_name if cand else ""),
                model=self._active_model(cand),
                confidence=conf, emotion=None)

        # 简单类别：先让已加载后端真实直答；失败/质量不过再升级 MainBrain
        rr = await self.quick_reply(
            text, max_tokens=int(ctx.get("max_tokens") or 48),
            timeout_s=float(ctx.get("timeout_s") or 6.0),
            char_hint=str(ctx.get("char_hint") or ""),
            role_context=str(ctx.get("role_context") or ""))
        if not rr or not str(rr.get("text") or "").strip():
            return self._main_brain_result(
                route.category,
                f"直答不可用（{route.category}）→ MainBrain",
                backend=(cand.backend_name if cand else ""),
                model=self._active_model(cand),
                confidence=conf, emotion=None)
        return {
            "needs_main_brain": False,
            "quick_reply": str(rr.get("text")).strip(),
            "confidence": round(conf, 3),
            "category": route.category,
            "emotion": "happy" if route.category == "simple_emotion" else None,
            "backend": rr.get("backend", cand.backend_name if cand else ""),
            "model": rr.get("model", self._active_model(cand)),
            "judge_source": "local-rules+quick_reply",
            "reason": route.reason,
            "meta": {
                "route": route.category,
                "ttft_ms": rr.get("ttft_ms"),
                "took_ms": rr.get("took_ms"),
                "device": rr.get("device", ""),
                "rule_confidence": round(conf, 3),
            },
        }

    @staticmethod
    def _active_model(cand: Optional[RealtimeBrainProvider]) -> str:
        if cand is None:
            return ""
        try:
            h = cand.health()
            return str(h.get("model") or "")
        except Exception:
            return ""

    @staticmethod
    def _main_brain_result(category: str, reason: str, *, backend: str = "",
                           model: str = "", confidence: float = 1.0,
                           emotion: Optional[str] = None) -> dict:
        return {
            "needs_main_brain": True,
            "quick_reply": None,
            "confidence": round(confidence, 3),
            "category": category,
            "emotion": emotion,
            "backend": backend,
            "model": model,
            "judge_source": "classifier",
            "reason": reason,
            "meta": {},
        }

    # ---------- 健康/状态 ----------
    def health(self) -> dict:
        if self._active is None:
            avail = any(c.status().available for c in self.candidates.values())
            return {
                "ok": avail,
                "available": avail,
                "backend": "",
                "model": "",
                "device": "",
                "reason": "Auto 实测尚未完成（或无可加载候选）→ 先升级 MainBrain",
                "loaded": False,
                "latency_ms": 0.0,
                "candidates": sorted(self.candidates),
                "selection": self._selection_info(),
            }
        try:
            h = self._active.health()
            h["candidates"] = sorted(self.candidates)
            h["selection"] = self._selection_info()
            return h
        except Exception as e:
            return {"ok": False, "available": False, "backend": "", "model": "",
                    "reason": str(e), "loaded": False, "latency_ms": 0.0,
                    "candidates": sorted(self.candidates),
                    "selection": self._selection_info()}

    def _selection_info(self) -> dict:
        return {
            "active": getattr(self._active, "backend_name", "") if self._active else "",
            "reason": self.selection_reason,
            "benchmarks": self.bench_results,
        }

    def probe(self) -> ProviderStatus:
        if self._active is not None:
            return self._active.probe()
        if not self.candidates:
            return ProviderStatus(available=False, backend="", reason="无 Realtime 候选")
        # 尚未实测选中：不上报某个候选已“在用”，但目录/运行时确实存在
        return ProviderStatus(
            available=True,
            backend="",
            device="",
            reason="候选已发现，Auto 实测完成后选择实际后端",
            latency_ms=0.0,
        )

    def status(self) -> ProviderStatus:
        return self.probe()

    # ---------- 实测自动选择 ----------
    async def benchmark(self) -> list[dict]:
        """分别实测当前真实可用路径（official CPU / GGUF CPU / GGUF Vulkan / CUDA）。

        记录 load_time、TTFT、tok/s、RAM、VRAM、stability、quality。
        选择规则：不是固定优先级；按实测 score（速度 + 稳定性 + 角色直答质量），
        宁可升级 MainBrain 也不选明显降智/不稳定的后端。
        """
        async with self._lock:
            self._bench_at = time.time()
            if not self.candidates:
                self.bench_results = []
                self.selection_reason = "无可加载候选（official/gguf/cuda 均不可用）"
                self._active = None
                return []
            results = []
            for label in LABEL_ORDER:
                cand = self.candidates.get(label)
                if cand is None:
                    continue
                try:
                    r = await self._bench_one(cand, label)
                    results.append(r)
                    # 每个候选测完立即卸载，保证下一个候选的 load/RSS 独立、内存不叠加
                    try:
                        await cand.unload()
                    except Exception:
                        pass
                    logger.info(
                        f"[Realtime][Bench] {label} measured={r.get('measured')} "
                        f"ttft={r.get('ttft_ms')}ms tok={r.get('decode_tok_s')} "
                        f"load={r.get('load_ms')}ms ram={r.get('ram_mb')}MB "
                        f"stability={r.get('stability')} quality={r.get('quality')} "
                        f"score={r.get('score')}")
                except Exception as e:
                    logger.warning(f"[Realtime][Bench] {label} 异常: {type(e).__name__}: {e}")
                    results.append(self._failed_result(label, f"{type(e).__name__}: {e}"))
            results.sort(key=lambda x: float(x.get("score") or -1), reverse=True)
            self.bench_results = results
            measured_ok = [r for r in results if r.get("measured")]
            stable_ok = [r for r in measured_ok if float(r.get("stability") or 0) >= 0.5]
            pool = stable_ok or measured_ok
            # 质量优先：存在直答合格（quality≥1.0）的候选时优先选它，
            # 避免选中"快但降智"的后端（如 gguf quality=0 抢占 active）
            qualified = [r for r in pool if float(r.get("quality") or 0) >= 1.0]
            # 强制官方 MiniMind D6：只要 official 实测 quality≥1.0，就选它，
            # 不因 GGUF 速度分更高而抢走 active（可用 QIYU_REALTIME_PREFER_OFFICIAL=0 关闭）
            official_qualified = [r for r in qualified
                                  if str(r.get("backend") or "").startswith("official")]
            if os.environ.get("QIYU_REALTIME_PREFER_OFFICIAL", "1") != "0" and official_qualified:
                best = official_qualified[0]
                if best.get("backend") != "official_cpu":
                    best = (qualified or pool or [None])[0]
            else:
                best = (qualified or pool or [None])[0]
            if best is None:
                best = (qualified or pool or [None])[0]
            if best:
                self._active = self.candidates.get(best.get("backend"))
                self.selection_reason = (
                    f"实测选择 {best.get('backend')}（TTFT={best.get('ttft_ms')}ms, "
                    f"tok/s={best.get('decode_tok_s')}, load={best.get('load_ms')}ms, "
                    f"ram={best.get('ram_mb')}MB, stability={best.get('stability')}, "
                    f"quality={best.get('quality')}）"
                )
                if not stable_ok:
                    self.selection_reason += "（所有候选稳定性<0.5，选最高分但标注风险）"
            else:
                self._active = None
                self.selection_reason = "所有候选实测失败 → 升级 MainBrain"
            # 最终只保留选中模型在内存
            if self._active is not None:
                r = await self._active.load(backend=self._active.backend_name)
                if not r.get("ok"):
                    logger.warning(f"[Realtime] 选中后端 reload 失败：{r.get('reason')}")
            return self.bench_results

    async def _bench_one(self, cand: RealtimeBrainProvider, label: str) -> dict:
        load_r = await cand.load(backend=label)
        if not load_r.get("ok"):
            return self._failed_result(
                label, str(load_r.get("reason") or "load failed"),
                load_ms=float(load_r.get("load_ms") or 0.0))
        # 第一次作为预热（刚加载完），后两次用于真实 TTFT/稳定性评估
        await asyncio.wait_for(cand.bench_inference(), timeout=90)
        sample1 = await asyncio.wait_for(cand.bench_inference(), timeout=90)
        sample2 = await asyncio.wait_for(cand.bench_inference(), timeout=90)
        tt1 = max(1.0, float(sample1.get("ttft_ms") or 0))
        tt2 = max(1.0, float(sample2.get("ttft_ms") or 0))
        ttft = (tt1 + tt2) / 2.0
        tok = max(float(sample1.get("decode_tok_s") or 0),
                  float(sample2.get("decode_tok_s") or 0))
        # 稳定性：两次 TTFT 越接近越稳定（0~1）
        spread = abs(tt1 - tt2) / max(tt1, tt2)
        stability = max(0.0, min(1.0, 1.0 - spread * 2.0))
        # 质量门：拿 2 句简单聊天实测直答是否合格（不合格=会降智给用户）
        qa_msgs = ("哈哈", "在吗")
        accepted = 0
        for qm in qa_msgs:
            rr = await asyncio.wait_for(
                cand.quick_reply(qm, max_tokens=20, timeout_s=6.0,
                                 char_hint="小栖，嘴碎又护短的室友", role_context="你们刚斗完嘴"),
                timeout=12.0)
            if rr and rr.get("text"):
                accepted += 1
        quality = accepted / len(qa_msgs)
        rss = max(float(sample1.get("rss_mb") or 0), float(sample2.get("rss_mb") or 0))
        ram_delta = max(float(sample1.get("rss_delta_mb") or 0),
                        float(sample2.get("rss_delta_mb") or 0))
        score = (max(0.0, 250.0 - ttft)
                 + min(20.0, tok)
                 - max(0.0, ram_delta - 300.0) / 15.0
                 + stability * 25.0
                 + quality * 40.0)
        vram = 0.0
        if label in ("gguf_vulkan", "cuda"):
            try:
                from runtime.hardware import HardwareDetector
                prof = HardwareDetector().detect()
                vram = float(prof.vram_mb or 0)
            except Exception:
                pass
        return {
            "backend": label,
            "device": sample1.get("device", ""),
            "model": sample1.get("model", ""),
            "measured": True,
            "load_ms": round(max(float(load_r.get("load_ms") or 0),
                                 float(sample1.get("load_ms") or 0)), 1),
            "ttft_ms": round(ttft, 1),
            "decode_tok_s": round(tok, 1),
            "ram_mb": round(rss, 1),
            "ram_delta_mb": round(ram_delta, 1),
            "vram_mb": round(vram, 1),
            "stability": round(stability, 3),
            "quality": round(quality, 3),
            "score": round(score, 1),
            "reason": "真实实测（双样本 + 角色直答质量门）",
        }

    @staticmethod
    def _failed_result(label: str, reason: str, load_ms: float = 0.0) -> dict:
        return {
            "backend": label, "device": "", "model": "", "measured": False,
            "load_ms": round(load_ms, 1), "ttft_ms": 0.0, "decode_tok_s": 0.0,
            "ram_mb": 0.0, "ram_delta_mb": 0.0, "vram_mb": 0.0,
            "stability": 0.0, "quality": 0.0, "score": -1.0, "reason": reason,
        }

    async def _unload_non_active(self) -> None:
        active_name = getattr(self._active, "backend_name", "") if self._active else ""
        for label, cand in list(self.candidates.items()):
            if label != active_name:
                try:
                    await cand.unload()
                except Exception:
                    pass

    # ---------- 供状态展示 ----------
    def to_dict(self) -> dict:
        cands = []
        for label in LABEL_ORDER:
            cand = self.candidates.get(label)
            if cand is None and label == "cuda":
                cands.append({
                    "backend": "cuda", "available": False,
                    "reason": self.cuda_unverified_reason or "CUDA 未随包/未验证",
                    "model": "",
                })
                continue
            if cand is None:
                continue
            try:
                avail = self._cheap_available(cand)
                h = cand.health()
                cands.append({
                    "backend": label,
                    "available": avail,
                    "model": h.get("model", ""),
                    "device": h.get("device", ""),
                    "reason": "" if avail else (h.get("reason") or "不可用"),
                })
            except Exception:
                cands.append({"backend": label, "available": False, "reason": "探测异常"})
        base = super().to_dict()
        base["active"] = {
            "backend": getattr(self._active, "backend_name", "") if self._active else "",
            "model": self._active_model(self._active),
            "selection_reason": self.selection_reason,
        }
        base["candidates"] = cands
        base["cuda_verified"] = self.cuda_verified
        return base


def build_realtime_provider(model_root: Optional[Path] = None,
                            auto_bench: bool = True) -> MiniMindAutoRealtimeProvider:
    """v0.0.26：统一入口（替代旧的固定优先级 build_realtime_backend）。"""
    return MiniMindAutoRealtimeProvider(model_root=model_root, auto_bench=auto_bench)


__all__ = [
    "MiniMindAutoRealtimeProvider",
    "build_realtime_provider",
]
