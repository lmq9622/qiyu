# -*- coding: utf-8 -*-
"""Qiyu Runtime · 性能监控（PerformanceMonitor，规格§49）。

记录：TTFT / decode tok/s / prompt tokens / context length / memory retrieval time /
tool latency / STT latency / TTS first packet / avatar response latency /
GPU utilization / VRAM / RAM。

- `record(kind, **fields)` 追加一条指标（环形缓冲，按 kind 保留最近 N 条）。
- `snapshot()` 返回最近聚合（avg / p95 / count）供 /v1/perf 查询。
- 周期 flush 到 performance.log（分层日志，见 runtime/logging_setup.py）。
- 全部为尽力而为：任何子探测失败都降级为 0/None，不影响主链路。
"""
from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from typing import Any, Optional

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

KINDS = (
    "llm_ttft",        # 首 token 延迟 ms
    "llm_decode",      # 解码 tok/s
    "llm_prompt_tokens",
    "llm_context_len",
    "memory_retrieve", # 记忆检索 ms
    "tool_latency",    # 工具执行 ms
    "stt_latency",
    "tts_first_packet",
    "vision_latency",
    "avatar_latency",
)


class _Ring:
    __slots__ = ("maxlen", "items")

    def __init__(self, maxlen: int = 200):
        self.maxlen = maxlen
        self.items: deque = deque(maxlen=maxlen)

    def push(self, v: float):
        if v is not None:
            try:
                self.items.append(float(v))
            except Exception:
                pass

    def agg(self) -> dict:
        vals = list(self.items)
        if not vals:
            return {"count": 0}
        vals.sort()
        n = len(vals)
        p95 = vals[min(n - 1, int(n * 0.95))]
        return {
            "count": n,
            "avg": round(sum(vals) / n, 2),
            "min": round(vals[0], 2),
            "max": round(vals[-1], 2),
            "p95": round(p95, 2),
            "last": round(vals[-1], 2),
        }


class PerformanceMonitor:
    """性能指标采集与聚合（进程内单例）。"""

    def __init__(self) -> None:
        self._rings: dict[str, _Ring] = defaultdict(lambda: _Ring())
        self._events: deque = deque(maxlen=1000)   # 最近原始事件（诊断）
        self._started_at: float = time.time()
        self._last_util: float = 0.0
        self._last_util_at: float = 0.0

    # ---------- 采集 ----------
    def record(self, kind: str, **fields) -> None:
        if kind not in KINDS:
            kind = kind if kind else "other"
        val = fields.pop("value", None)
        self._rings[kind].push(val)
        try:
            self._events.append({"t": time.time(), "kind": kind, "v": val, "f": {k: v for k, v in fields.items() if v is not None}})
        except Exception:
            pass

    def time(self, kind: str, **fields):
        """上下文管理器：自动计时并 record 耗时(ms)。"""
        return _Timed(self, kind, fields)

    # ---------- 资源占用 ----------
    def _gpu_util(self) -> float:
        try:
            import shutil, subprocess
            smi = shutil.which("nvidia-smi")
            if not smi:
                smi = r"C:\Windows\System32\nvidia-smi.exe"
                if not os.path.exists(smi):
                    return 0.0
            out = subprocess.run(
                [smi, "--query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            first = (out.stdout or "").strip().splitlines()
            if not first:
                return 0.0
            util, _, vram_used = first[0].partition(",")
            self._last_util = float(util.strip() or 0)
            self._last_util_at = time.time()
            return self._last_util
        except Exception:
            return self._last_util

    def resources(self) -> dict:
        """当前资源占用快照（GPU util / VRAM / RAM）。"""
        out = {"ram_mb": 0, "ram_percent": 0.0, "gpu_util": self._last_util, "vram_mb": 0}
        if psutil is not None:
            try:
                vm = psutil.virtual_memory()
                out["ram_mb"] = int((vm.used or 0) / 1024 / 1024)
                out["ram_percent"] = round(float(vm.percent or 0), 1)
            except Exception:
                pass
        try:
            import shutil, subprocess
            smi = shutil.which("nvidia-smi")
            if not smi:
                smi = r"C:\Windows\System32\nvidia-smi.exe"
            if smi and os.path.exists(smi):
                r = subprocess.run(
                    [smi, "--query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
                line = (r.stdout or "").strip().splitlines()
                if line:
                    parts = [p.strip() for p in line[0].split(",")]
                    if len(parts) >= 2:
                        out["gpu_util"] = float(parts[0] or 0)
                        out["vram_mb"] = int(float(parts[1] or 0))
                        self._last_util = out["gpu_util"]
        except Exception:
            pass
        return out

    # ---------- 汇总 ----------
    def snapshot(self) -> dict:
        return {
            "uptime_s": round(time.time() - self._started_at, 1),
            "kinds": {k: r.agg() for k, r in sorted(self._rings.items())},
            "resources": self.resources(),
            "recent": list(self._events)[-100:],
        }

    def flush(self) -> None:
        """把最近聚合写入 performance.log（分层日志）。"""
        try:
            from runtime.logging_setup import logger_perf
            snap = self.snapshot()
            lines = []
            for k, a in snap["kinds"].items():
                if a.get("count"):
                    lines.append(f"{k}: count={a['count']} avg={a['avg']} p95={a['p95']}")
            res = snap["resources"]
            logger_perf.info(
                "PERF | " + " | ".join(lines) +
                f" | ram={res['ram_mb']}MB({res['ram_percent']}%) gpu={res['gpu_util']}% vram={res['vram_mb']}MB"
            )
        except Exception:
            pass


class _Timed:
    def __init__(self, mon: PerformanceMonitor, kind: str, fields: dict):
        self._mon = mon
        self._kind = kind
        self._fields = fields
        self._t0: Optional[float] = None

    def __enter__(self):
        self._t0 = time.time()
        return self

    def __exit__(self, *exc):
        dt = (time.time() - self._t0) * 1000.0 if self._t0 else 0.0
        self._mon.record(self._kind, value=dt, **self._fields)
        return False


perf_monitor = PerformanceMonitor()

__all__ = [
    "KINDS",
    "PerformanceMonitor",
    "perf_monitor",
]

