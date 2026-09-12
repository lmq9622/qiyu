#!/usr/bin/env python3
"""TTS 音频可视化取证：波形 / 1ms 包络 / 频谱图 / 包络自相关。

用法:
  python plot_audio.py <wav> --png out.png [--start 0] [--end 3.0]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from scipy import signal  # noqa: E402


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), "rb") as w:
        n_ch = w.getnchannels()
        width = w.getsampwidth()
        sr = w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2:
        x = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, dtype="<i4").astype(np.float64) / 2147483648.0
    else:
        raise ValueError(f"unsupported width {width}")
    if n_ch > 1:
        x = x.reshape(-1, n_ch).mean(axis=1)
    return x, sr


def ms_envelope(x: np.ndarray, sr: int, ms: int = 1) -> np.ndarray:
    hop = max(1, int(round(sr * ms / 1000.0)))
    n = len(x) // hop
    return np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--png", required=True)
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    x, sr = read_wav(Path(args.wav))
    t0 = int(args.start * sr)
    t1 = int(args.end * sr) if args.end else len(x)
    seg = x[t0:t1]
    t = np.arange(len(seg)) / sr

    env1 = ms_envelope(seg, sr, 1)
    env10 = ms_envelope(seg, sr, 10)
    e = env1 - env1.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac = ac / (ac[0] + 1e-20)
    lags_ms = np.arange(len(ac))

    fig, axes = plt.subplots(4, 1, figsize=(16, 12))
    axes[0].plot(t, seg, lw=0.3)
    axes[0].set_title(f"{args.title or Path(args.wav).name}  waveform  (peak={np.max(np.abs(seg)):.4f})")
    axes[0].set_ylabel("amp")
    axes[0].grid(alpha=0.3)

    axes[1].semilogy(np.arange(len(env1)) / 1000.0 + args.start, env1 + 1e-7, lw=0.8)
    axes[1].set_title("1 ms RMS envelope (log)")
    axes[1].set_ylabel("rms")
    axes[1].grid(alpha=0.3)
    axes[1].set_yticks([1e-4, 1e-3, 1e-2, 1e-1, 1.0])

    f, tt, S = signal.spectrogram(seg, sr, nperseg=512, noverlap=384, window="hann")
    axes[2].pcolormesh(tt + args.start, f, 10 * np.log10(S + 1e-12), shading="auto", cmap="magma")
    axes[2].set_ylim(0, 8000)
    axes[2].set_title("spectrogram (0-8 kHz)")
    axes[2].set_ylabel("Hz")

    axes[3].plot(lags_ms, ac, lw=0.8)
    axes[3].set_xlim(0, 200)
    axes[3].set_title("1 ms envelope autocorrelation (0-200 ms)")
    axes[3].set_xlabel("lag (ms)")
    axes[3].grid(alpha=0.3)

    for ax in axes:
        ax.set_xlabel(ax.get_xlabel() or "time (s)")
    fig.tight_layout()
    fig.savefig(args.png, dpi=90)
    print(f"[ok] {args.png}")
    top = sorted(range(5, min(len(ac), 200)), key=lambda i: -ac[i])[:5]
    print("top envelope-autocorr lags (ms):", [(int(i), round(float(ac[i]), 3)) for i in top])
    return 0


if __name__ == "__main__":
    sys.exit(main())
