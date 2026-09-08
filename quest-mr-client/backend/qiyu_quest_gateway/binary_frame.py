"""Quest Protocol v1 二进制帧。

布局（小端）：
    bytes 0..1   magic  "QY"
    byte  2      version (1)
    byte  3      kind
    bytes 4..7   uint32 sequence
    bytes 8..    payload

kind:
    1 = 上行音频 PCM16（客户端 → 服务端）
    2 = 下行 TTS PCM16（服务端 → 客户端）
    3 = 上行视觉 JPEG（客户端 → 服务端，P4）

JSON Text Frame 负责控制流（hello/回合/开始结束），二进制帧只承载大块负载。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"QY"
VERSION = 1
KIND_AUDIO_IN_PCM16 = 1
KIND_TTS_OUT_PCM16 = 2
KIND_VISION_JPEG = 3

_HEADER = struct.Struct("<2sBBI")
HEADER_SIZE = _HEADER.size


class BinaryFrameError(ValueError):
    pass


@dataclass(frozen=True)
class BinaryFrame:
    kind: int
    seq: int
    payload: bytes


def pack_frame(kind: int, seq: int, payload: bytes) -> bytes:
    return _HEADER.pack(MAGIC, VERSION, int(kind) & 0xFF, int(seq) & 0xFFFFFFFF) + bytes(payload)


def unpack_frame(data: bytes) -> BinaryFrame:
    if data is None or len(data) < HEADER_SIZE:
        raise BinaryFrameError("frame_too_short")
    magic, version, kind, seq = _HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise BinaryFrameError("bad_magic")
    if version != VERSION:
        raise BinaryFrameError(f"unsupported_binary_version:{version}")
    return BinaryFrame(kind=kind, seq=seq, payload=data[HEADER_SIZE:])


__all__ = [
    "BinaryFrame",
    "BinaryFrameError",
    "HEADER_SIZE",
    "KIND_AUDIO_IN_PCM16",
    "KIND_TTS_OUT_PCM16",
    "KIND_VISION_JPEG",
    "MAGIC",
    "VERSION",
    "pack_frame",
    "unpack_frame",
]
