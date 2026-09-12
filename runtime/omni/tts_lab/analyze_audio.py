#!/usr/bin/env python3
"""TTS 音频取证分析：10ms 包络、静音占比、削顶、周期开合、窗口边界。

用法:
  python analyze_audio.py <wav> [<wav> ...] [--json out.json] [--png out.png]
                          [--window-samples 24000,24000,...] [--ref <wav>]
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

FRAME_MS = 10.0


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        n_ch = w.getnchannels()
        width = w.getsampwidth()
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    elif width == 1:
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported sample width {width}")
    if n_ch > 1:
        x = x.reshape(-1, n_ch).mean(axis=1)
    return x, sr


def frame_rms(x: np.ndarray, sr: int, ms: float = FRAME_MS) -> np.ndarray:
    hop = int(round(sr * ms / 1000.0))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    return np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20)


def envelope_periodicity(env: np.ndarray, frame_ms: float = FRAME_MS) -> dict:
    """在 10ms RMS 包络上找主周期性（去均值自相关 + 峰位）。"""
    e = env - env.mean()
    if len(e) < 16 or not np.any(np.abs(e) > 1e-12):
        return {}
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac = ac / (ac[0] + 1e-20)
    lo = max(2, int(round(20.0 / frame_ms)))
    hi = min(len(ac) - 1, int(round(400.0 / frame_ms)))
    if hi <= lo:
        return {}
    seg = ac[lo:hi]
    lag = int(np.argmax(seg)) + lo
    # 周期性强度：峰自相关值
    return {
        "period_ms": round(lag * frame_ms, 1),
        "period_strength": round(float(ac[lag]), 4),
        "ac_40ms": round(float(ac[int(round(40 / frame_ms))]) if len(ac) > int(round(40 / frame_ms)) else 0.0, 4),
        "ac_60ms": round(float(ac[int(round(60 / frame_ms))]) if len(ac) > int(round(60 / frame_ms)) else 0.0, 4),
        "ac_120ms": round(float(ac[int(round(120 / frame_ms))]) if len(ac) > int(round(120 / frame_ms)) else 0.0, 4),
    }


def gate_events(active: np.ndarray, frame_ms: float = FRAME_MS) -> dict:
    if len(active) == 0:
        return {}
    d = np.diff(active.astype(np.int8))
    starts = np.flatnonzero(d == 1)
    ends = np.flatnonzero(d == -1)
    if active[0]:
        starts = np.r_[0, starts]
    if active[-1]:
        ends = np.r_[ends, len(active) - 1]
    n = min(len(starts), len(ends))
    if n == 0:
        return {"segments": 0, "seg_len_ms_p50": 0.0, "gap_len_ms_p50": 0.0}
    lens = (ends[:n] - starts[:n] + 1) * frame_ms
    m = min(len(starts) - 1, len(ends) - 1)
    gaps = (starts[1 : m + 1] - ends[:m] + 1) * frame_ms if m > 0 else np.zeros(0)
    return {
        "segments": int(n),
        "seg_len_ms_p50": round(float(np.percentile(lens, 50)), 1),
        "seg_len_ms_p90": round(float(np.percentile(lens, 90)), 1),
        "gap_len_ms_p50": round(float(np.percentile(gaps, 50)), 1) if len(gaps) else 0.0,
        "gap_len_ms_p10": round(float(np.percentile(gaps, 10)), 1) if len(gaps) else 0.0,
    }


def analyze(x: np.ndarray, sr: int, window_samples: list[int] | None = None) -> dict:
    env = frame_rms(x, sr)
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    # 静音阈值：-45 dBFS（绝对），同时报告相对语音中位数的比例
    abs_thr = 10 ** (-45.0 / 20.0)
    if len(env) and np.any(env > abs_thr):
        rel = float(np.median(env[env > abs_thr]))
    else:
        rel = float(np.median(env)) if len(env) else 0.0
    active_abs = env > abs_thr
    out = {
        "samples": int(len(x)),
        "duration_s": round(len(x) / sr, 4),
        "peak": round(peak, 5),
        "rms": round(float(np.sqrt(np.mean(x ** 2) + 1e-20)) if len(x) else 0.0, 5),
        "dbfs_peak": round(20 * np.log10(max(peak, 1e-9)), 2),
        "clip_frac_99": round(float(np.mean(np.abs(x) >= 0.99)) if len(x) else 0.0, 5),
        "clip_frac_997": round(float(np.mean(np.abs(x) >= 0.997)) if len(x) else 0.0, 5),
        "frames_10ms": int(len(env)),
        "silence_ratio_abs45db": round(float(1.0 - active_abs.mean()) if len(env) else 0.0, 4),
        "voice_rms_median": round(rel, 5),
        "env_rms_median": round(float(np.median(env)) if len(env) else 0.0, 6),
        "env_rms_p10": round(float(np.percentile(env, 10)) if len(env) else 0.0, 6),
        "env_rms_p90": round(float(np.percentile(env, 90)) if len(env) else 0.0, 6),
        "env_dynamic_db": round(
            float(20 * np.log10((np.percentile(env, 95) + 1e-9) / (np.percentile(env, 5) + 1e-9)))
            if len(env) else 0.0, 2),
    }
    out.update({f"periodicity_{k}": v for k, v in envelope_periodicity(env).items()})
    out.update({f"gate_{k}": v for k, v in gate_events(active_abs).items()})
    # 逐窗口边界处的能量（判断拼接 gap）
    if window_samples:
        bounds = np.cumsum([0] + list(window_samples))
        cuts = []
        for i in range(1, len(bounds) - 1):
            c = int(bounds[i])
            for back in (240, 480, 960, 1440):
                seg = x[max(0, c - back): c + back]
                if len(seg) < 2 * back:
                    continue
                a = np.sqrt(np.mean(seg[:back] ** 2))
                b = np.sqrt(np.mean(seg[back:] ** 2))
                cuts.append({
                    "cut": i, "at_s": round(c / sr, 4), "half_ms": back * 1000 // sr,
                    "rms_before": round(float(a), 5), "rms_after": round(float(b), 5),
                    "ratio_db": round(float(20 * np.log10((b + 1e-9) / (a + 1e-9))), 2),
                })
        out["cut_analysis"] = cuts
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wavs", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--window-samples")
    ap.add_argument("--label", action="append", default=[])
    args = ap.parse_args()

    win = None
    if args.window_samples:
        win = [int(v) for v in args.window_samples.split(",") if v.strip()]

    report = {}
    for i, p in enumerate(args.wavs):
        path = Path(p)
        x, sr = read_wav(path)
        label = args.label[i] if i < len(args.label) else path.stem
        r = analyze(x, sr, win)
        r["sample_rate"] = sr
        report[label] = r
        print(f"=== {label} ({path})")
        for k in ("duration_s", "samples", "sample_rate", "peak", "rms", "clip_frac_99",
                  "silence_ratio_abs45db", "voice_rms_median", "env_dynamic_db",
                  "periodicity_period_ms", "periodicity_period_strength", "periodicity_ac_60ms",
                  "periodicity_ac_120ms", "gate_segments", "gate_seg_len_ms_p50", "gate_gap_len_ms_p50"):
            if k in r:
                print(f"    {k:32s} = {r[k]}")
        for c in r.get("cut_analysis", []):
            if c["half_ms"] == 20:
                print(f"    cut{c['cut']} @{c['at_s']:8.4f}s  before={c['rms_before']:.5f} "
                      f"after={c['rms_after']:.5f}  {c['ratio_db']:+.2f} dB")

    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
