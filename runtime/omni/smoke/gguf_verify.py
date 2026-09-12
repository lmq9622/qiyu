# -*- coding: utf-8 -*-
"""GGUF 完整性校验：解析全部 KV + 张量表，算出文件应有的最小尺寸。

只对大小是不够的 —— 下载中断/损坏会产生「字节数对但内容坏」的文件。
这里做真正的结构校验：

1. 头 + 全部 KV 能否完整解析；
2. 全部 tensor 的 (偏移, 字节数) 能否算出真实结束位置；
3. 实际文件大小是否 >= 结束位置（否则就是截断）。

```bash
python -m runtime.omni.smoke.gguf_verify
python -m runtime.omni.smoke.gguf_verify --file <path>
```
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from runtime.omni.smoke.gguf_info import _Reader, GGUF_MAGIC, _SIMPLE  # noqa: E402
from runtime.omni.smoke.fetch_models import MANIFEST, dest_dir  # noqa: E402

# ggml_type -> (block_size, type_size)
GGML_TYPES = {
    0: (1, 4), 1: (1, 2), 2: (32, 18), 3: (32, 20), 4: (32, 20), 5: (32, 20),
    6: (32, 22), 7: (32, 24), 8: (32, 34), 9: (32, 36), 10: (256, 84),
    11: (256, 110), 12: (256, 118), 13: (256, 136), 14: (256, 150),
    15: (256, 172), 16: (256, 186), 17: (256, 202), 18: (256, 210),
    19: (256, 226), 20: (256, 242), 21: (256, 258), 22: (256, 274),
    23: (256, 292), 24: (1, 1), 25: (1, 2), 26: (1, 4), 27: (1, 4),
    28: (1, 8), 29: (1, 8), 30: (1, 2), 31: (1, 4), 32: (1, 4), 33: (1, 4),
    34: (1, 8), 35: (1, 8), 36: (1, 16), 37: (1, 16), 38: (1, 4), 39: (1, 4),
}


def type_size_bytes(ttype: int, n_elements: int) -> Optional[int]:
    info = GGML_TYPES.get(ttype)
    if not info:
        return None
    blk, tsz = info
    if blk == 1:
        return n_elements * tsz
    return (n_elements // blk) * tsz


def verify(path: Path, buf_bytes: int = 0) -> dict:
    out = {"file": str(path), "name": path.name}
    if not path.exists():
        out["ok"] = False
        out["error"] = "文件不存在"
        return out
    size = path.stat().st_size
    out["size"] = size
    # 自适应读取窗口：tokenizer 词表是巨型字符串数组，32MB 不够。
    sizes = [buf_bytes] if buf_bytes > 0 else [64 << 20, 256 << 20, 1024 << 20]
    last_err = None
    for head in sizes:
        with path.open("rb") as f:
            buf = f.read(head)
        try:
            return _verify_buf(path, size, buf, out)
        except EOFError as e:
            last_err = e
            continue
    out["ok"] = None
    out["error"] = "头部缓冲不足（已尝试到 %dMB）: %s" % (sizes[-1] >> 20, last_err)
    return out


def _verify_buf(path: Path, size: int, buf: bytes, out: dict) -> dict:
    try:
        r = _Reader(buf)
        if r.take(4) != GGUF_MAGIC:
            out["ok"] = False
            out["error"] = "不是 GGUF"
            return out
        version = r.u32()
        n_tensors = r.u64()
        n_kv = r.u64()
        kv = {}
        for _ in range(n_kv):
            k = r.string()
            kv[k] = r.value(r.u32())
        align = int(kv.get("general.alignment", 32) or 32)
        # 需要读完整张量表：如果头缓冲不够，直接扩大读取（表格紧随 KV）
        need_offset = r.pos
        tensors = []
        for _ in range(n_tensors):
            tname = r.string()
            n_dims = r.u32()
            dims = [r.u64() for _ in range(n_dims)]
            ttype = r.u32()
            toff = r.u64()
            n_el = 1
            for d in dims:
                n_el *= d
            tensors.append((tname, ttype, toff, n_el))
        out["version"] = version
        out["n_tensors"] = n_tensors
        out["n_kv"] = n_kv
        out["architecture"] = kv.get("general.architecture")
        out["alignment"] = align
        # 数据区起点 = 表结束位置向上对齐
        data_start = (r.pos + align - 1) // align * align
        worst = 0
        unknown = 0
        for tname, ttype, toff, n_el in tensors:
            nbytes = type_size_bytes(ttype, n_el)
            if nbytes is None:
                unknown += 1
                continue
            worst = max(worst, toff + nbytes)
        required = data_start + worst
        out["data_start"] = data_start
        out["required_size"] = required
        out["unknown_types"] = unknown
        out["ok"] = size >= required
        if not out["ok"]:
            out["error"] = f"截断：实际 {size} < 需要 {required}（缺 {required - size} 字节）"
    except EOFError:
        # 头缓冲不够：向上抛，让 verify() 换更大的窗口重试
        raise
    except Exception as e:
        out["ok"] = False
        out["error"] = repr(e)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="")
    ap.add_argument("--bytes", type=int, default=0)
    args = ap.parse_args()

    targets = []
    if args.file:
        targets = [Path(args.file)]
    else:
        d = dest_dir()
        targets = [d / rel.replace("/", os.sep) for rel, *_ in MANIFEST]

    ok_all = True
    print("%-46s %12s %12s %s" % ("file", "size", "required", "结论"))
    for t in targets:
        r = verify(t, args.bytes)
        if r.get("ok") is False:
            ok_all = False
        if r.get("ok") is None:
            ok_all = False
        print("%-46s %12s %12s %s" % (
            r["name"], r.get("size", "-"), r.get("required_size", "-"),
            ("OK arch=%s" % r.get("architecture")) if r.get("ok") else ("FAIL " + str(r.get("error")))))
    print("\n总体:", "全部通过" if ok_all else "存在问题")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
