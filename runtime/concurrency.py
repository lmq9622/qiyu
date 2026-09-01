# -*- coding: utf-8 -*-
"""Qiyu Runtime · 全局并发限制器（GlobalConcurrencyLimiter，规格§25）。

并行请求选项：auto / 1 / 2 / 3 / 4 / unlimited。
- auto：根据 CPU 核心数 / 内存 / GPU / VRAM / 并发能力自动决定（低端设备保守）。
- Tool Agent / Main Brain / Memory / Vision / TTS 共用同一把总闸，禁止无限制创建任务；
  每类另有分闸（tool 联网类更保守，避免真实搜索风暴）。

统一接口：`await limiter.acquire("llm")` / `limiter.release("llm")`，
或 `async with limiter.slot("llm", burst="tool"):`（联网工具类走更小的子闸）。
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from loguru import logger

KINDS = ("llm", "tool", "memory", "vision", "tts", "stt", "avatar")

# 每类并行默认权重（相对总闸）——工具联网类最保守
_KIND_WEIGHT = {"llm": 1.0, "tool": 0.4, "memory": 0.8, "vision": 0.6,
                "tts": 0.5, "stt": 0.5, "avatar": 0.6}


def auto_limit() -> int:
    """auto 模式：按硬件并发能力决定总并行数（1~4）。"""
    try:
        import psutil
        cores = psutil.cpu_count(logical=True) or 2
    except Exception:
        cores = 2
    try:
        import os
        total_ram_gb = 0
        if psutil is not None:
            total_ram_gb = (psutil.virtual_memory().total or 0) / 1024 ** 3
    except Exception:
        total_ram_gb = 0
    if cores <= 2 or total_ram_gb < 4:
        return 1
    if cores <= 4:
        return 2
    if cores <= 8:
        return 3
    return 4


class GlobalConcurrencyLimiter:
    """统一并发闸：总闸 + 分闸，均可用 asyncio.Semaphore 限流。

    总并行上限 = parallel_requests 设置（auto/1/2/3/4/unlimited）。
    分闸上限 = 总上限 × KIND_WEIGHT（至少 1）。
    """

    def __init__(self) -> None:
        self._global = asyncio.Semaphore(4)
        self._slots: dict[str, asyncio.Semaphore] = {k: asyncio.Semaphore(2) for k in KINDS}
        self._limit = 4
        self._inflight: dict[str, int] = {}
        self._total = 0
        self._peak = 0

    def configured_limit(self) -> int:
        """读取运行时设置里的 parallel_requests 并换算为整数（0=unlimited）。"""
        try:
            from companion.settings import load_runtime_settings
            v = str((load_runtime_settings().get("parallel_requests") or "auto")).strip().lower()
        except Exception:
            v = "auto"
        if v in ("0", "unlimited", "no", "off", "none"):
            return 0
        if v == "auto":
            return auto_limit()
        try:
            return max(1, min(4, int(v)))
        except Exception:
            return auto_limit()

    def _apply_limit(self, limit: int) -> None:
        # 重建信号量（asyncio 信号量无法改大小；重建是安全的，等当前持有者释放后生效）
        self._global = asyncio.Semaphore(limit) if limit > 0 else None
        for k in KINDS:
            sub = max(1, int(limit * _KIND_WEIGHT.get(k, 0.5))) if limit > 0 else 0
            self._slots[k] = asyncio.Semaphore(sub) if sub > 0 else None
        self._limit = limit
        logger.info(f"[并发] GlobalConcurrencyLimiter 上限={limit or 'unlimited'}")

    def refresh(self) -> None:
        """按最新设置重建信号量（幂等，可在运行时开关变化后调用）。"""
        limit = self.configured_limit()
        if limit != self._limit:
            self._apply_limit(limit)

    def kind_limit(self, kind: str) -> int:
        if self._limit <= 0:
            return 0
        sub = max(1, int(self._limit * _KIND_WEIGHT.get(kind, 0.5)))
        return sub

    async def acquire(self, kind: str = "llm") -> bool:
        kind = kind if kind in self._slots else "llm"
        self.refresh()
        if self._global is not None:
            await self._global.acquire()
        sem = self._slots.get(kind)
        if sem is not None:
            await sem.acquire()
        self._inflight[kind] = self._inflight.get(kind, 0) + 1
        self._total += 1
        self._peak = max(self._peak, self._total)
        return True

    def release(self, kind: str = "llm") -> None:
        kind = kind if kind in self._slots else "llm"
        self._inflight[kind] = max(0, self._inflight.get(kind, 0) - 1)
        self._total = max(0, self._total - 1)
        sem = self._slots.get(kind)
        if sem is not None:
            try:
                sem.release()
            except Exception:
                pass
        if self._global is not None:
            try:
                self._global.release()
            except Exception:
                pass

    def slot(self, kind: str = "llm"):
        """async with limiter.slot('llm'): ..."""
        return _Slot(self, kind)

    def stats(self) -> dict:
        return {
            "limit": self._limit,
            "inflight": dict(self._inflight),
            "total_inflight": self._total,
            "peak": self._peak,
            "kind_limits": {k: self.kind_limit(k) for k in KINDS},
        }


class _Slot:
    def __init__(self, lim: GlobalConcurrencyLimiter, kind: str):
        self._lim = lim
        self._kind = kind

    async def __aenter__(self):
        await self._lim.acquire(self._kind)
        return self

    async def __aexit__(self, *exc):
        self._lim.release(self._kind)
        return False


concurrency_limiter = GlobalConcurrencyLimiter()

__all__ = [
    "KINDS",
    "GlobalConcurrencyLimiter",
    "auto_limit",
    "concurrency_limiter",
]
