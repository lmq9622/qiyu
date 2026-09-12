#!/usr/bin/env python3
"""检查 mel_new / mel_in / cache 的布局与衔接关系（A1 核心断言）。"""
from __future__ import annotations

import pathlib
import re
import sys

import numpy as np


def units(d: pathlib.Path, name: str) -> list[int]:
    """返回按顺序排列的 dump 单元号（支持 call%04d 与 seq%04d_tid%zu 两种命名）。"""
    out = []
    for p in d.glob(f"*_{name}.bin"):
        mt = re.search(r"(?:^|_)(?:call|seq)(\d+)", p.name)
        if mt:
            out.append(int(mt.group(1)))
    return sorted(out)


def m(d: pathlib.Path, name: str, i: int) -> np.ndarray:
    for pat in (f"call{i:04d}_{name}.bin", f"*seq{i:04d}_*_{name}.bin"):
        hits = list(d.glob(pat))
        if hits:
            x = np.fromfile(hits[0], dtype="<f4")
            # 源码约定：mel 是 [B=1, C=80, T] 行主序（mem[c*T + t]），不是 [T, C]
            return x.reshape(80, -1)
    raise FileNotFoundError(f"seq{i:04d} {name}")


def dmax(a: np.ndarray, b: np.ndarray) -> float:
    n = min(a.shape[1], b.shape[1])
    return float(np.abs(a[:, :n] - b[:, :n]).max())


def main() -> int:
    d = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    ids = units(d, "mel_in")
    n = len(ids)
    print("== 同一次调用内部（布局自检）==")
    print(f"dump 单元数 = {n}  前几个 = {ids[:8]}")
    for i in ids[:3]:
        mn, mi = m(d, "mel_new", i), m(d, "mel_in", i)
        print(f"call{i:04d}: mel_new T={mn.shape[1]} mel_in T={mi.shape[1]}")
        if mi.shape[1] >= mn.shape[1] + 8:
            print(f"   mel_in[8:8+{mn.shape[1]}] vs mel_new  maxdiff={dmax(mi[:, 8:8+mn.shape[1]], mn):.6f} (期望 0)")
            print(f"   mel_in[:8]                vs mel_new[:8] maxdiff={dmax(mi[:, :8], mn[:, :8]):.6f}")
        else:
            print(f"   mel_in vs mel_new      maxdiff={dmax(mi, mn):.6f} (期望 0，首窗无 cache)")
        print(f"   mel_in[-8:] vs mel_new[-8:] maxdiff={dmax(mi[:, -8:], mn[:, -8:]):.6f} (期望 0)")

    print("\n== 跨调用 cache 衔接 ==")
    for a, b in zip(ids, ids[1:]):
        i = a
        mn, mi = m(d, "mel_new", i), m(d, "mel_in", i)
        mn2, mi2 = m(d, "mel_new", b), m(d, "mel_in", b)
        print(f"seq{i:04d}->{b:04d}")
        print(f"   上一窗 mel_in 尾 8 帧 vs 下一窗 mel_in 首 8 帧 : maxdiff={dmax(mi[:, -8:], mi2[:, :8]):.6f} (期望 0)")
        print(f"   上一窗 mel_new 尾 8 帧 vs 下一窗 mel_in 首 8 帧: maxdiff={dmax(mn[:, -8:], mi2[:, :8]):.6f}")
        print(f"   下一窗 mel_new 首 8 帧 vs 下一窗 mel_in 首 8 帧: maxdiff={dmax(mn2[:, :8], mi2[:, :8]):.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
