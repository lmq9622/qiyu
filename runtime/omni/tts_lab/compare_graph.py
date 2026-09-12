#!/usr/bin/env python3
"""逐节点比较两次 vocoder 图导出（CPU vs GPU），按拓扑顺序找首个发散节点。

用法: python compare_graph.py <dirA> <dirB> [--top 40] [--tol 1e-3]
"""
from __future__ import annotations

import argparse
import pathlib
import re

import numpy as np


def load(dirpath: pathlib.Path) -> dict[int, tuple[np.ndarray, str]]:
    out = {}
    for p in sorted(dirpath.glob("*_node*.bin")):
        m = re.search(r"_node(\d+)\.bin$", p.name)
        if not m:
            continue
        i = int(m.group(1))
        meta = p.with_suffix(".txt")
        txt = meta.read_text(encoding="utf-8", errors="replace").strip() if meta.exists() else ""
        out[i] = (np.fromfile(p, dtype="<f4"), txt)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--tol", type=float, default=1e-3)
    args = ap.parse_args()
    A, B = load(pathlib.Path(args.a)), load(pathlib.Path(args.b))
    common = sorted(set(A) & set(B))
    print(f"共同节点 {len(common)}（A={len(A)} B={len(B)}）")
    rows = []
    for i in common:
        xa, meta = A[i]
        xb, _ = B[i]
        n = min(len(xa), len(xb))
        if n == 0:
            continue
        d = np.abs(xa[:n] - xb[:n])
        scale = max(1e-6, float(np.abs(xa[:n]).max()))
        rel = float(d.max()) / scale
        corr = float(np.corrcoef(xa[:n], xb[:n])[0, 1]) if xa[:n].std() > 1e-9 and xb[:n].std() > 1e-9 else float("nan")
        rows.append((i, n, float(d.max()), rel, corr, scale, meta))
    div = [r for r in rows if r[3] > args.tol]
    print(f"超过 tol={args.tol} 的发散节点数 = {len(div)} / {len(rows)}")
    print("\n== 按拓扑顺序的首批发散节点 ==")
    for r in div[: args.top]:
        print(f"  node{r[0]:04d} n={r[1]:7d} max|Δ|={r[2]:.6g} rel={r[3]:.3e} corr={r[4]:+.4f} scale={r[5]:.4g}")
        print(f"           {r[6]}")
    if div:
        print(f"\n首个发散节点: node{div[0][0]:04d}  {div[0][6]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
