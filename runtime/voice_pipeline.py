# -*- coding: utf-8 -*-
"""Qiyu Voice Pipeline（P2 骨架，真实可跑版本）。

目标：文本→句子分块→Emotion Prosody→逐句 TTS→AudioChunk 流；随时可打断。
不引入额外引擎：优先复用 runtime.tts 已注册 Provider（Windows SAPI / edge-tts）。
真人音色克隆在无参考音频前不声明可用（voice_reference 为空 → 不装模作样）。
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from loguru import logger

EMOTION_PROFILE = {
    "happy": {"speed": 1.10, "pitch": 1.05, "energy": 1.10},
    "excited": {"speed": 1.15, "pitch": 1.10, "energy": 1.20},
    "sad": {"speed": 0.90, "pitch": 0.95, "energy": 0.70},
    "soft": {"speed": 0.92, "pitch": 1.00, "energy": 0.75},
    "annoyed": {"speed": 1.05, "pitch": 0.98, "energy": 1.05},
    "angry": {"speed": 1.10, "pitch": 0.95, "energy": 1.15},
    "tired": {"speed": 0.85, "pitch": 0.95, "energy": 0.60},
    "neutral": {"speed": 1.0, "pitch": 1.0, "energy": 1.0},
}


@dataclass
class VoiceProfile:
    voice_id: str = ""
    voice_reference: str = ""          # 音频克隆参考（无则 UNVERIFIED）
    speaking_style: str = ""
    pitch: float = 1.0
    speed: float = 1.0
    energy: float = 1.0
    emotion_style: str = "neutral"
    pause_style: str = "normal"
    breath_style: str = "normal"


@dataclass
class AudioChunk:
    index: int
    text: str
    path: str
    format: str = "wav"
    duration_ms: int = 0
    emotion: str = "neutral"
    intensity: float = 0.0
    speed: float = 1.0
    pitch: float = 1.0
    energy: float = 1.0
    interrupted: bool = False


class SentenceSegmenter:
    """自然聊天分句：短句优先，避免把整段喂给 TTS。"""

    def __init__(self, max_len: int = 42) -> None:
        self.max_len = max_len
        self._split_re = re.compile(r"(?<=[。！？!?；;……\n])")

    def split(self, text: str) -> list[str]:
        if not text:
            return []
        parts = [p.strip() for p in self._split_re.split(text) if p.strip()]
        if not parts:
            parts = [text.strip()]
        out: list[str] = []
        for p in parts:
            if len(p) > self.max_len:
                # 超长句按逗号再切，保证首包快
                sub = re.split(r"(?<=[，,、：:])", p)
                cur = ""
                for s in sub:
                    if len(cur) + len(s) > self.max_len and cur:
                        out.append(cur)
                        cur = s
                    else:
                        cur += s
                if cur:
                    out.append(cur)
            else:
                out.append(p)
        return out


def emotion_to_prosody(emotion_state: dict | None, profile: VoiceProfile) -> dict:
    """由情绪状态 + VoiceProfile 得到本句 prosody（速度/音高/能量/风格）。"""
    mood = (emotion_state or {}).get("mood") or (emotion_state or {}).get("dominant_emotion") or "neutral"
    base = EMOTION_PROFILE.get(mood, EMOTION_PROFILE["neutral"])
    intensity = float((emotion_state or {}).get("intensity") or 0.5)
    return {
        "emotion": mood,
        "intensity": round(max(0.0, min(1.0, intensity)), 2),
        "speed": round(base["speed"] * profile.speed, 2),
        "pitch": round(base["pitch"] * profile.pitch, 2),
        "energy": round(base["energy"] * profile.energy, 2),
        "pause_style": profile.pause_style,
        "breath_style": profile.breath_style,
    }


class VoicePipeline:
    def __init__(self, segmenter: Optional[SentenceSegmenter] = None,
                 profile: Optional[VoiceProfile] = None) -> None:
        self.segmenter = segmenter or SentenceSegmenter()
        self.profile = profile or VoiceProfile(voice_id="default-sapi")
        self._interrupt = asyncio.Event()
        self.active = False

    async def interrupt(self) -> dict:
        self._interrupt.set()
        self.active = False
        return {"ok": True, "interrupted": True}

    async def reset(self) -> None:
        self._interrupt.clear()

    async def synthesize_stream(self, text: str, emotion_state: dict | None = None,
                                provider=None, tts_voice: str = "",
                                first_chunk_ms: int = 3000) -> AsyncIterator[AudioChunk]:
        """逐句合成：每句一个 AudioChunk；interrupt() 后立即停止。"""
        if provider is None:
            from runtime.tts import tts_provider
            provider = tts_provider
        if not provider.status().available:
            logger.warning("[VoicePipeline] TTS Provider 不可用，不生成假音频")
            return
        self._interrupt.clear()
        self.active = True
        chunks = self.segmenter.split(text)
        prosody = emotion_to_prosody(emotion_state, self.profile)
        for i, chunk in enumerate(chunks):
            if self._interrupt.is_set() or not self.active:
                yield AudioChunk(index=i, text=chunk, path="", interrupted=True,
                                 emotion=prosody["emotion"], intensity=prosody["intensity"])
                return
            try:
                r = await asyncio.wait_for(
                    provider.synthesize(
                        chunk,
                        voice=tts_voice or self.profile.voice_id,
                        speed=prosody["speed"],
                        pitch=prosody["pitch"]),
                    timeout=first_chunk_ms / 1000.0 if i == 0 else 30.0)
            except asyncio.TimeoutError:
                logger.warning(f"[VoicePipeline] 第 {i + 1} 句 TTS 超时，继续下一句")
                continue
            if not r:
                continue
            yield AudioChunk(
                index=i, text=chunk,
                path=str(r.get("path") or ""),
                format=str(r.get("format") or "wav"),
                duration_ms=int(r.get("duration_ms") or 0),
                emotion=prosody["emotion"], intensity=prosody["intensity"],
                speed=prosody["speed"], pitch=prosody["pitch"], energy=prosody["energy"])
        self.active = False


voice_pipeline = VoicePipeline()

__all__ = ["AudioChunk", "SentenceSegmenter", "VoicePipeline", "VoiceProfile",
           "emotion_to_prosody", "voice_pipeline"]
