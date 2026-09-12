# -*- coding: utf-8 -*-
"""栖语 · Omni 性能采集（规格 §21）。

提示词写得很明确：**不要用普通文本 tok/s 判断 Omni 是否实时。**
真正重要的是 TTFA、RTF、interrupt latency、长时间稳定性。

这里采集的指标：

| 指标 | 含义 | 目标 |
|---|---|---|
| ``model_load_ms`` | 模型加载耗时 | — |
| ``vram_peak_mb`` | 显存峰值 | ≤ 12GB 卡要留余量 |
| ``sys_ram_mb`` | 系统内存占用 | — |
| ``audio_in_rtf`` | 音频输入实时率（处理耗时 / 音频时长），<1 才算跟得上 | < 1.0 |
| ``video_fps`` | 视频侧有效处理帧率 | ≥ 调度目标 |
| ``ttft_ms`` | 首 token 时间 | — |
| ``ttfa_ms`` | **首音频时间**（最重要） | 越低越好 |
| ``response_latency_ms`` | 持续响应延迟（说话过程中不断更新的间隔） | 稳定不爬升 |
| ``interrupt_latency_ms`` | **插话打断延迟** | < 200ms |
| ``webrtc_latency_ms`` | 媒体面延迟 | — |
| ``e2e_latency_ms`` | 端到端 | — |
| ``cpu_pct`` / ``gpu_pct`` | 占用 | — |

没有 psutil / pynvml 时自动降级，不阻塞主流程。
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from typing import Optional

try:  # 可选依赖
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore

try:  # 可选依赖（NVIDIA 才有；AMD 走 rocm-smi，见 probe_gpu_util）
    import pynvml  # type: ignore
except Exception:  # pragma: no cover
    pynvml = None  # type: ignore


def sys_ram_mb() -> float:
    if psutil is None:
        return 0.0
    try:
        return round(psutil.Process().memory_info().rss / 1048576.0, 1)
    except Exception:
        return 0.0


def cpu_pct() -> float:
    if psutil is None:
        return 0.0
    try:
        return round(psutil.Process().cpu_percent(interval=None), 1)
    except Exception:
        return 0.0


@dataclass
class Sample:
    name: str
    value: float
    ts: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)


@dataclass
class Series:
    """一组同类采样 + 汇总。"""

    name: str
    unit: str = "ms"
    samples: list = field(default_factory=list)

    def add(self, value: float, **meta) -> None:
        self.samples.append(Sample(self.name, float(value), meta=meta))

    def count(self) -> int:
        return len(self.samples)

    def summary(self) -> dict:
        vals = [s.value for s in self.samples]
        if not vals:
            return {"count": 0}
        out = {
            "count": len(vals),
            "min": round(min(vals), 2),
            "max": round(max(vals), 2),
            "avg": round(sum(vals) / len(vals), 2),
            "unit": self.unit,
        }
        if len(vals) >= 2:
            out["p50"] = round(statistics.median(vals), 2)
            try:
                out["p95"] = round(statistics.quantiles(vals, n=20)[18], 2)
            except Exception:
                pass
        return out


class OmniMetrics:
    """一次会话 / 一次基准测试的指标收集器。"""

    def __init__(self, label: str = "") -> None:
        self.label = label
        self.started_at = time.time()
        self.series: dict = {}
        self.facts: dict = {}          # 单值事实：model_load_ms / vram_peak_mb ...
        self._marks: dict = {}

    # ---------- 通用 ----------

    def series_of(self, name: str, unit: str = "ms") -> Series:
        if name not in self.series:
            self.series[name] = Series(name, unit)
        return self.series[name]

    def record(self, name: str, value: float, unit: str = "ms", **meta) -> None:
        self.series_of(name, unit).add(value, **meta)

    def fact(self, name: str, value) -> None:
        self.facts[name] = value

    # ---------- 计时 ----------

    def mark(self, name: str, ts: Optional[float] = None) -> None:
        self._marks[name] = ts if ts is not None else time.time()

    def since_mark_ms(self, name: str) -> float:
        if name not in self._marks:
            return 0.0
        return round((time.time() - self._marks[name]) * 1000.0, 2)

    # ---------- 语音/流式 ----------

    def mark_first_text(self) -> None:
        if "ttft_ms" not in self.facts:
            self.facts["ttft_ms"] = self.since_mark_ms("request")

    def mark_first_audio(self) -> None:
        if "ttfa_ms" not in self.facts:
            self.facts["ttfa_ms"] = self.since_mark_ms("request")

    def mark_interrupt(self, reason: str = "") -> None:
        self.mark("interrupt")
        if reason:
            self.facts["interrupt_reason"] = reason

    def mark_interrupt_done(self, scope: str = "interrupt") -> float:
        """结束一次打断计时。返回本次打断耗时（ms）。"""
        start = self._marks.get(scope)
        if start is None:
            return 0.0
        ms = round((time.time() - start) * 1000.0, 2)
        self.facts["interrupt_latency_ms"] = ms
        if scope != "interrupt":
            self.facts["interrupt_latency_ms"] = ms
        else:
            # 保留历史最差一次，长稳测试更有意义
            prev = float(self.facts.get("interrupt_latency_worst_ms") or 0.0)
            self.facts["interrupt_latency_worst_ms"] = round(max(prev, ms), 2)
        return ms

    def record_rtf(self, process_ms: float, audio_duration_ms: float) -> float:
        """音频输入 RTF = 处理耗时 / 音频时长。<1 才算跟得上实时。"""
        if audio_duration_ms <= 0:
            return 0.0
        rtf = float(process_ms) / float(audio_duration_ms)
        self.record("audio_in_rtf", rtf, unit="ratio")
        worst = float(self.facts.get("audio_in_rtf_worst") or 0.0)
        self.facts["audio_in_rtf_worst"] = round(max(worst, rtf), 4)
        return round(rtf, 3)

    def record_latency(self, name: str, ms: float, unit: str = "ms") -> None:
        self.record(name, ms, unit=unit)

    # ---------- 显存 / 硬件 ----------

    def sample_resources(self) -> dict:
        ram = sys_ram_mb()
        cpu = cpu_pct()
        out = {"sys_ram_mb": ram, "cpu_pct": cpu}
        if ram:
            self.facts["sys_ram_mb"] = ram
        if cpu:
            self.facts["cpu_pct"] = cpu
        return out

    def record_vram(self, mb: float) -> None:
        if mb <= 0:
            return
        cur = float(self.facts.get("vram_peak_mb") or 0.0)
        self.facts["vram_peak_mb"] = round(max(cur, mb), 1)

    # ---------- 输出 ----------

    def report(self) -> dict:
        return {
            "label": self.label,
            "duration_s": round(time.time() - self.started_at, 2),
            "facts": dict(self.facts),
            "series": {k: v.summary() for k, v in self.series.items()},
        }

    def pretty(self) -> str:
        rep = self.report()
        lines = [f"== Omni 指标 [{rep['label']}] 时长 {rep['duration_s']}s =="]
        for k, v in sorted(rep["facts"].items()):
            lines.append(f"  {k:24s} = {v}")
        for k, v in sorted(rep["series"].items()):
            if v.get("count"):
                lines.append(
                    f"  {k:24s} : n={v['count']} min={v.get('min')} p50={v.get('p50')} "
                    f"p95={v.get('p95')} max={v.get('max')} {v.get('unit','')}"
                )
        return "\n".join(lines)


__all__ = ["OmniMetrics", "Sample", "Series", "cpu_pct", "sys_ram_mb"]
