#!/usr/bin/env python3
"""判断 t2m 输出的 mel 是否具备语音 log-mel 的结构特征。

语音 log-mel：相邻帧高度相关、相邻频带高度相关、低频带宽动态大。
噪声型输出：相邻帧/相邻频带相关接近 0。
"""
from __future__ import annotations

import pathlib
import re
import sys

import numpy as np


def load(d: pathlib.Path, tag: str) -> list[np.ndarray]:
    out = []
    for p in sorted(d.glob(f"*_{tag}.bin"), key=lambda p: int(re.search(r"(?:call|seq)(\d+)", p.name).group(1))):
        out.append(np.fromfile(p, dtype="<f4").reshape(80, -1))
    return out


def main() -> int:
    d = pathlib.Path(sys.argv[1])
    mels = load(d, "mel_new")
    print(f"窗口数 = {len(mels)}")
    tf, cf, en = [], [], []
    for m in mels:
        x = m - m.mean()
        if m.shape[1] > 2:
            a, b = m[:, :-1].ravel(), m[:, 1:].ravel()
            tf.append(np.corrcoef(a, b)[0, 1])
        a, b = m[:-1, :].ravel(), m[1:, :].ravel()
        cf.append(np.corrcoef(a, b)[0, 1])
        en.append(m.std())
    print(f"相邻时间帧相关  : mean={np.mean(tf):+.3f}  min={np.min(tf):+.3f} max={np.max(tf):+.3f}")
    print(f"相邻频带相关    : mean={np.mean(cf):+.3f}  min={np.min(cf):+.3f} max={np.max(cf):+.3f}")
    print(f"每窗 mel 标准差 : mean={np.mean(en):.3f}")
    m = mels[min(1, len(mels) - 1)]
    print("\n单窗(seq0001) 前 6 帧、每 10 个频带采样:")
    print(np.round(m[::10, :6], 2))
    print("\n单窗逐帧按频带均值（每帧一个数，前 50 帧）:")
    print(np.round(m.mean(axis=0)[:50], 2))
    print("\n逐帧能量(10*log10 sum m^2) 前 50 帧:")
    e = 10 * np.log10((m ** 2).sum(axis=0) + 1e-12)
    print(np.round(e[:50], 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
