#!/usr/bin/env python3
"""逐窗对比两次 T2W 运行（A6：同 input 下 GPU/CPU、或服务端 vs 离线重放）。

用法:
  python compare_runs.py <dumpA> <dumpB> [--tags mel_new,wave_raw,wave_emit]
"""
from __future__ import annotations

import argparse
import pathlib
import re

import numpy as np

TAGS = ("mel_new", "mel_in", "wave_raw", "wave_xfade", "wave_emit")


def index(dirpath: pathlib.Path, tag: str) -> dict[int, pathlib.Path]:
    out = {}
    for p in dirpath.glob(f"*_{tag}.bin"):
        m = re.search(r"(?:call|seq)(\d+)", p.name)
        if m:
            out[int(m.group(1))] = p
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--tags", default=",".join(TAGS))
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    args = ap.parse_args()
    da, db = pathlib.Path(args.a), pathlib.Path(args.b)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]

    for tag in tags:
        ia, ib = index(da, tag), index(db, tag)
        common = sorted(set(ia) & set(ib))
        if not common:
            print(f"[{tag}] 无共同窗口（A={len(ia)} B={len(ib)}）")
            continue
        rows = []
        for k in common:
            xa, xb = np.fromfile(ia[k], dtype="<f4"), np.fromfile(ib[k], dtype="<f4")
            n = min(len(xa), len(xb))
            if n == 0:
                continue
            d = np.abs(xa[:n] - xb[:n])
            denom = max(1e-9, float(np.abs(xa[:n]).max()))
            corr = float(np.corrcoef(xa[:n], xb[:n])[0, 1]) if xa[:n].std() > 1e-9 and xb[:n].std() > 1e-9 else float("nan")
            rows.append((k, n, len(xa), len(xb), float(d.max()), float(d.mean()), corr, float(d.max()) / denom))
        mx = max(r[4] for r in rows)
        mc = min(r[6] for r in rows if not np.isnan(r[6])) if any(not np.isnan(r[6]) for r in rows) else float("nan")
        print(f"[{tag}] 共同窗口 {len(rows)} 个 | max|Δ| 最大 {mx:.6f} | 窗口相关最低 {mc:.4f}")
        for r in rows[:4] + (rows[-2:] if len(rows) > 6 else []):
            print(f"    seq{r[0]:04d} n={r[1]} lenA={r[2]} lenB={r[3]} max|Δ|={r[4]:.6f} mean|Δ|={r[5]:.6f} "
                  f"corr={r[6]:+.4f} rel={r[7]:.2e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
