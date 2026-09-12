#!/usr/bin/env python3
"""文本化 TTS 取证：10ms 包络 ASCII、调制谱、削顶、谐波性、跨窗重叠对比。

用法:
  python forensics.py <wav> [--ascii] [--mod] [--region a b]
  python forensics.py --overlap <chunkA_wav> <chunkB_wav> --n 3840
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as w:
        n_ch, width, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise ValueError("bad width")
    if n_ch > 1:
        x = x.reshape(-1, n_ch).mean(axis=1)
    return x, sr


def rms_env(x: np.ndarray, sr: int, ms: float) -> np.ndarray:
    hop = int(round(sr * ms / 1000.0))
    n = len(x) // hop
    return np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20)


def ascii_env(env: np.ndarray, per_line: int = 100, db_floor: float = -60.0, label: str = "") -> str:
    db = 20 * np.log10(env + 1e-12)
    chars = " .:-=+*#%@"
    out = [f"[ascii-envelope 10ms, floor {db_floor} dBFS] {label}"]
    for i in range(0, len(db), per_line):
        chunk = db[i : i + per_line]
        line = "".join(chars[int(np.clip((v - db_floor) / (0.0 - db_floor) * (len(chars) - 1), 0, len(chars) - 1))] for v in chunk)
        out.append(f"{i*10/1000:7.2f}s |{line}|")
    return "\n".join(out)


def modulation(env: np.ndarray, frame_ms: float) -> str:
    e = env - env.mean()
    n = len(e)
    if n < 32:
        return "env too short"
    w = np.hanning(n)
    sp = np.abs(np.fft.rfft(e * w))
    freqs = np.fft.rfftfreq(n, d=frame_ms / 1000.0)
    lines = ["[modulation spectrum of 10ms RMS envelope]"]
    for lo, hi, tag in ((2.0, 16.0, "2-16 Hz (60-500 ms)"), (16.0, 60.0, "16-60 Hz (17-60 ms)"), (60.0, 200.0, "60-200 Hz")):
        m = (freqs >= lo) & (freqs <= hi)
        if not np.any(m):
            continue
        k = np.argsort(-sp[m])[:4]
        picks = [f"{freqs[m][i]:.2f} Hz (p={sp[m][i]/ (sp.max()+1e-20):.3f})" for i in k]
        lines.append(f"  {tag}: " + ", ".join(picks))
    return "\n".join(lines)


def harmonicity(x: np.ndarray, sr: int, fmin: float = 60.0, fmax: float = 400.0) -> dict:
    """40ms 帧的 F0（自相关）与谐波-噪声比近似。"""
    win = int(0.04 * sr)
    hop = int(0.01 * sr)
    n = max(0, (len(x) - win) // hop)
    f0s, hnr = [], []
    lo, hi = int(sr / fmax), int(sr / fmin)
    for i in range(n):
        s = x[i * hop : i * hop + win]
        if np.sqrt(np.mean(s ** 2)) < 1e-3:
            continue
        s = s - s.mean()
        ac = np.correlate(s, s, mode="full")[win - 1:]
        ac = ac / (ac[0] + 1e-20)
        if hi >= len(ac):
            continue
        seg = ac[lo:hi]
        k = int(np.argmax(seg))
        f0s.append(sr / (k + lo))
        hnr.append(float(ac[k + lo]))
    if not f0s:
        return {"voiced_frames": 0}
    f0s = np.array(f0s)
    hnr = np.array(hnr)
    voiced = hnr > 0.3
    return {
        "voiced_frames": int(len(f0s)),
        "f0_median_hz": round(float(np.median(f0s[voiced])) if voiced.any() else float(np.median(f0s)), 1),
        "f0_p10": round(float(np.percentile(f0s, 10)), 1),
        "f0_p90": round(float(np.percentile(f0s, 90)), 1),
        "hnr_median": round(float(np.median(hnr)), 3),
        "voiced_frac": round(float(voiced.mean()), 3),
    }


def overlap_report(a: Path, b: Path, n: int) -> str:
    xa, sr = read_wav(a)
    xb, _ = read_wav(b)
    tail = xa[-n:]
    head = xb[:n]
    m = min(len(tail), len(head))
    tail, head = tail[:m], head[:m]
    rms = lambda v: float(np.sqrt(np.mean(v ** 2) + 1e-20))
    corr = float(np.corrcoef(tail, head)[0, 1]) if m > 2 else 0.0
    # 最佳延迟（±40ms）下的相关
    best = (0, -2.0)
    for lag in range(-960, 961, 10):
        if lag >= 0:
            u, v = tail[lag:], head[: m - lag]
        else:
            u, v = tail[: m + lag], head[-lag:]
        if len(u) < 200:
            continue
        c = float(np.corrcoef(u, v)[0, 1])
        if c > best[1]:
            best = (lag, c)
    return (
        f"[overlap] {a.name} tail vs {b.name} head  n={m}\n"
        f"    rms_tail={rms(tail):.5f} rms_head={rms(head):.5f} "
        f"corr={corr:.3f} best_lag={best[0]} samples ({best[0]/24.0:.2f} ms) corr={best[1]:.3f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", nargs="?")
    ap.add_argument("--ascii", action="store_true")
    ap.add_argument("--mod", action="store_true")
    ap.add_argument("--metrics", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--region", nargs=2, type=float)
    ap.add_argument("--overlap", nargs=2)
    ap.add_argument("--n", type=int, default=3840)
    args = ap.parse_args()

    if args.overlap:
        print(overlap_report(Path(args.overlap[0]), Path(args.overlap[1]), args.n))
        return 0
    if not args.wav:
        ap.error("wav required")

    x, sr = read_wav(Path(args.wav))
    if args.region:
        x = x[int(args.region[0] * sr) : int(args.region[1] * sr)]
    env = rms_env(x, sr, 10.0)
    print(f"file={args.wav} sr={sr} samples={len(x)} dur={len(x)/sr:.3f}s")
    if args.metrics or args.all:
        print(f"peak={np.max(np.abs(x)):.5f} rms={np.sqrt(np.mean(x**2)):.5f} "
              f"crest_db={20*np.log10(np.max(np.abs(x))/(np.sqrt(np.mean(x**2))+1e-20)):.2f} "
              f"clip>=0.99={np.mean(np.abs(x)>=0.99):.4f} "
              f"env_med={np.median(env):.5f} env_p5={np.percentile(env,5):.5f} env_p95={np.percentile(env,95):.5f}")
        print("harmonicity:", harmonicity(x, sr))
    if args.mod or args.all:
        print(modulation(env, 10.0))
    if args.ascii or args.all:
        print(ascii_env(env))
    return 0


if __name__ == "__main__":
    sys.exit(main())
