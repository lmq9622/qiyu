# -*- coding: utf-8 -*-
"""Qiyu Runtime · MicroBenchmark（规格§4/§5/§13）。

不能简单「检测到 GPU 就用 GPU」：MiniMind-O 很小，CPU 在某些设备上可能比核显更合适。
HardwareDetector + BackendCapability + MicroBenchmark 共同决定最终 backend。

本模块：
- 对候选 backend 做一次真实微基准（若后端提供 bench_inference 回调 → 测 TTFT/tok/s）；
- 没有真实运行时（当前分发未内置推理后端）时，用硬件启发式评分兜底，并如实标注
  `measured=False`，绝不假装测过；
- 产出排序 + 分数 + 原因，由 RuntimeManager 决定最终 backend。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from loguru import logger

from runtime.hardware import BackendCapability, HardwareProfile

# 参考基准：目标是最小实时模型（约 0.1B，256 上下文）的 TTFT / 首 token
_TTFT_REF = {
    # (threads/cores 或显存) → 估算 TTFT ms（启发式，measured=False 时用）
    "cpu": lambda prof: max(120.0, 900.0 - (prof.cpu_threads or 4) * 55.0),
    "vulkan": lambda prof: max(90.0, 260.0 - (prof.vram_mb or 0) / 8192.0 * 120.0),
    "cuda": lambda prof: max(50.0, 160.0 - (prof.vram_mb or 0) / 8192.0 * 90.0),
}


@dataclass
class BenchmarkResult:
    backend: str
    device: str = ""
    measured: bool = False          # 是否真实跑过微基准
    ttft_ms: float = 0.0            # 估算/实测首 token 延迟
    decode_tok_s: float = 0.0       # 估算/实测解码速度
    score: float = 0.0              # 综合分（越高越优）
    reason: str = ""
    # —— 实测元数据（measured=True 时由 backend.bench_inference() 回填，规格§/QA6）——
    load_ms: float = 0.0            # 模型加载耗时（首轮实测）
    rss_delta_mb: float = 0.0       # 加载前后进程 RSS 增量
    rss_mb: float = 0.0             # 当前进程 RSS
    model: str = ""                 # 实际模型文件名/标签

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "device": self.device,
            "measured": self.measured,
            "ttft_ms": round(self.ttft_ms, 1),
            "decode_tok_s": round(self.decode_tok_s, 1),
            "load_ms": round(self.load_ms, 1),
            "rss_delta_mb": round(self.rss_delta_mb, 1),
            "rss_mb": round(self.rss_mb, 1),
            "model": self.model,
            "score": round(self.score, 3),
            "reason": self.reason,
        }


class MicroBenchmark:
    """候选 backend 微基准 + 决策。"""

    def __init__(self) -> None:
        self._results: list[BenchmarkResult] = []
        self._last_ran_at: float = 0.0

    def estimate(self, cap: BackendCapability, prof: HardwareProfile) -> BenchmarkResult:
        fn = _TTFT_REF.get(cap.backend)
        ttft = fn(prof) if fn else 400.0
        tok_s = max(5.0, 60.0 - ttft / 20.0)   # TTFT 越低解码越快（启发式）
        # 分数：TTFT 越短越高；CPU 在低端设备加分（避免核显/驱动问题）
        score = 100.0 - ttft / 10.0
        if cap.backend == "cpu" and (prof.cpu_threads or 0) <= 8:
            score += 8.0
        return BenchmarkResult(
            backend=cap.backend, device=cap.device, measured=False,
            ttft_ms=ttft, decode_tok_s=tok_s, score=score,
            reason="硬件启发式估算（当前分发未内置真实推理运行时，未实测）",
        )

    async def benchmark(self, candidates: list[BackendCapability],
                        profile: Optional[HardwareProfile] = None,
                        bench_fn: Optional[Callable[[BackendCapability], Awaitable[dict]]] = None,
                        ) -> list[BenchmarkResult]:
        """对每个可用候选做基准：有 bench_fn 就实测，否则启发式估算。

        bench_fn 返回 {ttft_ms, decode_tok_s}（真实运行时的自测结果）。
        """
        prof = profile or HardwareProfile()
        results: list[BenchmarkResult] = []
        for cap in candidates:
            if not cap.available:
                results.append(BenchmarkResult(
                    backend=cap.backend, device=cap.device, score=-1.0,
                    reason=cap.reason or "backend 不可用",
                ))
                continue
            measured = None
            if bench_fn is not None:
                try:
                    t0 = time.time()
                    measured = await bench_fn(cap)
                    _took = (time.time() - t0) * 1000.0
                except Exception as e:
                    logger.debug(f"[基准] {cap.backend} 实测失败: {e}")
                    measured = None
            if measured and measured.get("ttft_ms") is not None:
                ttft = float(measured.get("ttft_ms") or 0)
                tok_s = float(measured.get("decode_tok_s") or 0)
                score = 100.0 - ttft / 10.0 + min(20.0, tok_s)
                results.append(BenchmarkResult(
                    backend=cap.backend, device=cap.device, measured=True,
                    ttft_ms=ttft, decode_tok_s=tok_s, score=score,
                    load_ms=float(measured.get("load_ms") or 0.0),
                    rss_delta_mb=float(measured.get("rss_delta_mb") or 0.0),
                    rss_mb=float(measured.get("rss_mb") or 0.0),
                    model=str(measured.get("model") or ""),
                    reason=f"实测微基准（TTFT={ttft:.0f}ms, {tok_s:.1f} tok/s, "
                           f"load={float(measured.get('load_ms') or 0.0):.0f}ms, "
                           f"rss={float(measured.get('rss_mb') or 0.0):.0f}MB）",
                ))
            else:
                results.append(self.estimate(cap, prof))
        results.sort(key=lambda r: r.score, reverse=True)
        self._results = results
        self._last_ran_at = time.time()
        for r in results:
            logger.info(f"[基准] {r.backend}@{r.device or '-'} score={r.score:.1f} "
                        f"ttft={r.ttft_ms:.0f}ms measured={r.measured}")
        return results

    @property
    def last_results(self) -> list[BenchmarkResult]:
        return self._results

    def summary(self) -> dict:
        return {
            "ran_at": round(self._last_ran_at, 3),
            "results": [r.to_dict() for r in self._results],
        }


micro_benchmark = MicroBenchmark()

__all__ = [
    "BenchmarkResult",
    "MicroBenchmark",
    "micro_benchmark",
]
