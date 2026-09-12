# -*- coding: utf-8 -*-
"""栖语 · GGUF 头解析（不下载整个文件）。

用途：**在下载 4.68 GB 之前**先确认权重声明的 ``general.architecture``，
再回头检查 llama.cpp 是否编译进了这个 arch。

```bash
python -m runtime.omni.smoke.gguf_info --url <hf-resolve-url>     # 远程只取头部
python -m runtime.omni.smoke.gguf_info --file models/omni/x.gguf  # 本地文件
```
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import urllib.request
from pathlib import Path
from typing import Any, Optional

GGUF_MAGIC = b"GGUF"

# GGUF value type id → 名称
VALUE_TYPES = {
    0: "uint8", 1: "int8", 2: "uint16", 3: "int16", 4: "uint32", 5: "int32",
    6: "float32", 7: "bool", 8: "string", 9: "array", 10: "uint64", 11: "int64",
    12: "float64",
}

_SIMPLE = {
    0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2), 4: ("<I", 4),
    5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1), 10: ("<Q", 8), 11: ("<q", 8),
    12: ("<d", 8),
}


class _Reader:
    def __init__(self, buf: bytes) -> None:
        self.buf = buf
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.buf):
            raise EOFError("GGUF 头部缓冲不足，需要更大的 --bytes")
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]

    def string(self) -> str:
        n = self.u64()
        return self.take(n).decode("utf-8", "replace")

    def value(self, vtype: int) -> Any:
        if vtype == 8:
            return self.string()
        if vtype == 9:
            elem_type = self.u32()
            count = self.u64()
            if elem_type == 8:
                # 字符串数组：必须逐个读（才知长度），但不保留内容
                if count > 4096:
                    for _ in range(count):
                        self.string()
                    return f"<array of {count} strings>"
                return [self.string() for _ in range(count)]
            fmt, size = _SIMPLE.get(elem_type, ("<B", 1))
            # 定长数组：直接按字节跳过，不构造列表（词表可达十几万项）
            if count > 4096:
                self.pos += count * size
                return f"<array of {count} {VALUE_TYPES.get(elem_type, '?')}>"
            return [struct.unpack(fmt, self.take(size))[0] for _ in range(count)]
        fmt, size = _SIMPLE.get(vtype, ("<B", 1))
        return struct.unpack(fmt, self.take(size))[0]


def parse_gguf_header(buf: bytes, max_kv: int = 64) -> dict:
    r = _Reader(buf)
    magic = r.take(4)
    if magic != GGUF_MAGIC:
        return {"error": f"不是 GGUF 文件（magic={magic!r}）"}
    version = r.u32()
    tensor_count = r.u64()
    kv_count = r.u64()
    out: dict = {
        "magic": "GGUF", "version": version,
        "tensor_count": tensor_count, "kv_count": kv_count, "kv": {},
    }
    for _ in range(min(kv_count, max_kv)):
        try:
            key = r.string()
            vtype = r.u32()
            out["kv"][key] = r.value(vtype)
        except EOFError as e:
            out["truncated"] = str(e)
            break
        except Exception as e:  # pragma: no cover
            out["parse_error"] = repr(e)
            break
    return out


def fetch_remote_header(url: str, nbytes: int = 262144, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={
        "Range": f"bytes=0-{nbytes - 1}",
        "User-Agent": "qiyu-gguf-probe",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def summarize(info: dict) -> dict:
    kv = info.get("kv") or {}
    return {
        "version": info.get("version"),
        "architecture": kv.get("general.architecture"),
        "name": kv.get("general.name"),
        "tensor_count": info.get("tensor_count"),
        "kv_count": info.get("kv_count"),
        "truncated": info.get("truncated", ""),
        "sample_kv": {k: kv[k] for k in list(kv)[:18]},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="GGUF 头部解析")
    ap.add_argument("--url", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--bytes", type=int, default=262144)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.file:
        buf = Path(args.file).read_bytes()[: args.bytes]
    elif args.url:
        buf = fetch_remote_header(args.url, args.bytes)
    else:
        ap.error("需要 --url 或 --file")
        return 2

    info = parse_gguf_header(buf)
    s = summarize(info)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print(f"  version      : {s['version']}")
        print(f"  architecture : {s['architecture']}")
        print(f"  name         : {s['name']}")
        print(f"  tensors      : {s['tensor_count']}  kv={s['kv_count']}")
        if s["truncated"]:
            print(f"  (truncated: {s['truncated']})")
        for k, v in s["sample_kv"].items():
            if isinstance(v, str) and len(v) > 90:
                v = v[:90] + "…"
            print(f"    {k} = {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
