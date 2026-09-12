#!/usr/bin/env python3
"""验证 mel cache 是否真的是上一窗 mel_in 的尾部（A1/A2 关键断言）。"""
from __future__ import annotations

import pathlib
import sys

import numpy as np


def load_mel_in(d: pathlib.Path, i: int) -> np.ndarray:
    x = np.fromfile(d / f"call{i:04d}_mel_in.bin", dtype="<f4")
    return x.reshape(-1, 80).T


def main() -> int:
    d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    n = len(list(d.glob("call*_mel_in.bin")))
    print(f"mel_in 文件数 = {n}")
    for i in range(n - 1):
        a, b = load_mel_in(d, i), load_mel_in(d, i + 1)
        if a.shape[1] < 8 or b.shape[1] < 8:
            continue
        md = float(np.abs(a[:, -8:] - b[:, :8]).max())
        best = (None, 1e9)
        for off in range(0, b.shape[1] - 7):
            dm = float(np.abs(a[:, -8:] - b[:, off : off + 8]).max())
            if dm < best[1]:
                best = (off, dm)
        c = float(np.corrcoef(a[:, -8:].ravel(), b[:, :8].ravel())[0, 1])
        print(f"call{i:04d} tail8  vs  call{i+1:04d} head8 : maxdiff={md:.6f} corr={c:+.4f} "
              f"| 该尾部在下一窗中的最佳位置 offset={best[0]} maxdiff={best[1]:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
