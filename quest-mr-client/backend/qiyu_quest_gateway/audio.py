"""Quest 语音通道：PCM16 ↔ WAV，复用 Qiyu 现有 STT/TTS Provider。

不新增语音模型：STT 走 runtime.stt.stt_provider（sherpa-onnx），
TTS 走 runtime.tts.tts_provider（System.Speech / edge-tts）。
"""
from __future__ import annotations

import asyncio
import io
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_SAMPLE_WIDTH = 2


class AudioError(RuntimeError):
    pass


@dataclass
class AudioTurnBuffer:
    """按 session 缓存上行 PCM16，直到收到 user.audio_end。"""

    sample_rate: int = TARGET_SAMPLE_RATE
    channels: int = TARGET_CHANNELS
    chunks: list[bytes] = field(default_factory=list)

    def append(self, pcm: bytes) -> None:
        if pcm:
            self.chunks.append(bytes(pcm))

    def byte_len(self) -> int:
        return sum(len(c) for c in self.chunks)

    def duration_s(self) -> float:
        bytes_per_sample = TARGET_SAMPLE_WIDTH * max(1, self.channels)
        return self.byte_len() / float(max(1, self.sample_rate) * bytes_per_sample)

    def take(self) -> bytes:
        data = b"".join(self.chunks)
        self.chunks.clear()
        return data

    def clear(self) -> None:
        self.chunks.clear()


def pcm16_to_wav(pcm: bytes, sample_rate: int = TARGET_SAMPLE_RATE,
                 channels: int = TARGET_CHANNELS) -> bytes:
    if not pcm:
        return b""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(int(channels))
        w.setsampwidth(TARGET_SAMPLE_WIDTH)
        w.setframerate(int(sample_rate))
        w.writeframes(bytes(pcm))
    return buf.getvalue()


def wav_bytes_to_pcm16(wav_bytes: bytes) -> tuple[bytes, int, int]:
    """解析 WAV → (pcm16, sample_rate, channels)，统一重采样到 16k 单声道。"""
    if not wav_bytes:
        raise AudioError("empty_wav")
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        channels = w.getnchannels()
        sample_width = w.getsampwidth()
        sample_rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    if channels not in (1, 2):
        raise AudioError(f"unsupported_channels:{channels}")
    if sample_width not in (1, 2, 3, 4):
        raise AudioError(f"unsupported_sample_width:{sample_width}")

    samples = _decode_samples(frames, sample_width, channels)
    if channels == 2:
        samples = [(samples[i] + samples[i + 1]) // 2 for i in range(0, len(samples), 2)]
    if sample_rate != TARGET_SAMPLE_RATE and samples:
        samples = _resample(samples, sample_rate, TARGET_SAMPLE_RATE)

    out = bytearray(len(samples) * 2)
    for i, s in enumerate(samples):
        v = max(-32768, min(32767, int(s)))
        out[i * 2] = v & 0xFF
        out[i * 2 + 1] = (v >> 8) & 0xFF
    return bytes(out), TARGET_SAMPLE_RATE, TARGET_CHANNELS


def _decode_samples(frames: bytes, sample_width: int, channels: int) -> list[int]:
    if sample_width == 2:
        count = len(frames) // 2
        return list(int.from_bytes(frames[i * 2:i * 2 + 2], "little", signed=True)
                    for i in range(count))
    if sample_width == 1:
        return [((b - 128) << 8) for b in frames]
    if sample_width == 3:
        out: list[int] = []
        for i in range(0, len(frames) - 2, 3):
            v = int.from_bytes(frames[i:i + 3], "little", signed=True)
            out.append(v >> 8)
        return out
    count = len(frames) // 4
    return list(int.from_bytes(frames[i * 4:i * 4 + 4], "little", signed=True) >> 16
                for i in range(count))


def _resample(samples: list[int], src_rate: int, dst_rate: int) -> list[int]:
    if src_rate == dst_rate or not samples:
        return samples
    ratio = dst_rate / float(src_rate)
    out_len = max(1, int(len(samples) * ratio))
    out: list[int] = []
    for i in range(out_len):
        pos = i / ratio
        idx = int(pos)
        frac = pos - idx
        a = samples[min(idx, len(samples) - 1)]
        b = samples[min(idx + 1, len(samples) - 1)]
        out.append(int(a + (b - a) * frac))
    return out


async def transcribe_pcm16(pcm: bytes, sample_rate: int = TARGET_SAMPLE_RATE) -> str:
    """复用 Qiyu STTProvider；失败返回空串（调用方必须如实处理）。"""
    if not pcm:
        return ""
    wav_bytes = pcm16_to_wav(pcm, sample_rate)
    try:
        from runtime.stt import stt_provider
    except Exception as e:
        logger.warning(f"[QuestAudio] STT Provider 不可用: {e}")
        return ""
    try:
        text = await stt_provider.transcribe(wav_bytes)
    except Exception as e:
        logger.warning(f"[QuestAudio] STT 失败: {e}")
        return ""
    return (text or "").strip()


async def synthesize_pcm16(text: str, **params) -> dict:
    """复用 Qiyu TTSProvider → 16k 单声道 PCM16。失败抛 AudioError（不假装发声）。"""
    text = (text or "").strip()
    if not text:
        raise AudioError("empty_text")
    try:
        from runtime.tts import tts_provider
    except Exception as e:
        raise AudioError(f"tts_provider_unavailable:{e}") from e
    result = await tts_provider.synthesize(text, **params)
    if not result or not result.get("path"):
        raise AudioError("tts_synthesis_failed")
    path = Path(str(result["path"]))
    if not path.exists():
        raise AudioError("tts_file_missing")
    fmt = str(result.get("format") or path.suffix.lstrip(".")).lower()
    raw = await asyncio.to_thread(path.read_bytes)
    if fmt == "wav":
        pcm, rate, channels = wav_bytes_to_pcm16(raw)
    else:
        pcm, rate, channels = await asyncio.to_thread(_convert_to_pcm16, raw, fmt)
    return {
        "pcm": pcm,
        "sample_rate": rate,
        "channels": channels,
        "duration_ms": int(result.get("duration_ms") or
                           (len(pcm) / (2.0 * max(1, channels) * rate) * 1000.0)),
        "engine": result.get("engine") or tts_provider.id,
        "format": fmt,
    }


def _convert_to_pcm16(raw: bytes, fmt: str) -> tuple[bytes, int, int]:
    """非 WAV（mp3 等）经 ffmpeg 转 16k 单声道；无 ffmpeg 时如实失败。"""
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise AudioError(f"ffmpeg_required_for_{fmt}")
    with tempfile.TemporaryDirectory(prefix="qiyu_tts_") as tmp:
        src = os.path.join(tmp, f"in.{fmt}")
        dst = os.path.join(tmp, "out.wav")
        with open(src, "wb") as f:
            f.write(raw)
        proc = subprocess.run(
            [ffmpeg, "-y", "-i", src, "-ar", str(TARGET_SAMPLE_RATE),
             "-ac", str(TARGET_CHANNELS), "-f", "wav", dst],
            capture_output=True, timeout=120)
        if proc.returncode != 0 or not os.path.exists(dst):
            raise AudioError(f"ffmpeg_convert_failed:{proc.stderr[:160]!r}")
        with open(dst, "rb") as f:
            return wav_bytes_to_pcm16(f.read())


def _find_ffmpeg() -> Optional[str]:
    for name in ("ffmpeg", "ffmpeg.exe"):
        try:
            subprocess.run([name, "-version"], capture_output=True, timeout=5)
            return name
        except Exception:
            continue
    return None


__all__ = [
    "AudioError",
    "AudioTurnBuffer",
    "TARGET_SAMPLE_RATE",
    "pcm16_to_wav",
    "synthesize_pcm16",
    "transcribe_pcm16",
    "wav_bytes_to_pcm16",
]
