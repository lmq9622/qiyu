#!/usr/bin/env python3
"""暴力定位 mel_new 在 mel_in 中的真实位置，以及 cache 的真实来源。"""
from __future__ import annotations

import pathlib
import sys

import numpy as np


def m(d: pathlib.Path, name: str, i: int) -> np.ndarray:
    return np.fromfile(d / f"call{i:04d}_{name}.bin", dtype="<f4").reshape(-1, 80).T


def main() -> int:
    d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    i = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    mn, mi = m(d, "mel_new", i), m(d, "mel_in", i)
    C, Tm = mn.shape
    print(f"call{i:04d}: mel_new[T={Tm}] mel_in[T={mi.shape[1]}]")
    print("-- 在 mel_in 中滑动比对 mel_new（整块 80x50）:")
    for off in range(0, max(1, mi.shape[1] - Tm + 1)):
        blk = mi[:, off : off + Tm]
        md = float(np.abs(blk - mn).max())
        # 逐通道相关性
        cc = float(np.corrcoef(blk.ravel(), mn.ravel())[0, 1])
        print(f"   offset={off:2d}  maxdiff={md:8.4f}  corr={cc:+.4f}")
    print("-- mel_in 开头 8 帧 与 上一窗 mel_new 尾 8 帧 的逐通道差异（前 5 通道）:")
    if i > 0:
        prev = m(d, "mel_new", i - 1)
        for c in range(5):
            print(f"   c={c:2d} cache={np.round(mi[c, :4], 3)}  prevTail={np.round(prev[c, -4:], 3)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
