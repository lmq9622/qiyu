# -*- coding: utf-8 -*-
"""栖语 · Realtime Omni 音频前端（规格 §4 / §14）。

两个纯 Python、零依赖的组件：

- ``EnergyVad``：能量 VAD。用来做 partial speech / turn detection 的最前置一层，
  只回答「这一段有没有人在说话」，不做识别。
- ``BargeInDetector``：**插话检测**。`avatar 正在说话 + 用户开口` → 立刻打断，
  不需要等上一轮 completion。

真正做 turn detection 的模型可以替换 ``is_speech`` 的实现，接口保持不变。
"""

from __future__ import annotations

import array
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from runtime.omni.types import AudioChunk, SpeakerId


def pcm_rms(pcm: Any) -> float:
    """计算 PCM 的 RMS（0~1）。兼容 float 序列与 int16 bytes。"""
    if pcm is None:
        return 0.0
    if isinstance(pcm, (bytes, bytearray, memoryview)):
        try:
            arr = array.array("h")
            arr.frombytes(bytes(pcm)[: len(bytes(pcm)) // 2 * 2])
        except Exception:
            return 0.0
        if not arr:
            return 0.0
        # int16 → -1.0~1.0
        return math.sqrt(sum((v / 32768.0) ** 2 for v in arr) / len(arr))
    try:
        n = len(pcm)
    except TypeError:
        return 0.0
    if n == 0:
        return 0.0
    try:
        return math.sqrt(sum(float(v) ** 2 for v in pcm) / n)
    except Exception:
        return 0.0


@dataclass
class EnergyVad:
    """能量 VAD。

    - ``threshold``：RMS 门限，低于它算静音
    - ``hangover_ms``：说过话后保持「仍在说话」多久，避免句中停顿被切断
    - ``min_speech_ms``：连续超过门限多久才算真正开口（抗爆音）
    """

    threshold: float = 0.012
    hangover_ms: float = 250.0
    min_speech_ms: float = 120.0
    _speaking: bool = False
    _last_voice_ts: float = 0.0
    _voice_ms: float = 0.0

    def is_speech(self, chunk: AudioChunk) -> bool:
        rms = pcm_rms(chunk.pcm)
        dur = chunk.duration_ms() or 20.0
        now = time.time()
        if rms >= self.threshold:
            self._voice_ms += dur
            self._last_voice_ts = now
            if self._voice_ms >= self.min_speech_ms:
                self._speaking = True
        else:
            if self._speaking and (now - self._last_voice_ts) * 1000.0 > self.hangover_ms:
                self._speaking = False
                self._voice_ms = 0.0
        return self._speaking

    def reset(self) -> None:
        self._speaking = False
        self._last_voice_ts = 0.0
        self._voice_ms = 0.0


@dataclass
class BargeInEvent:
    """一条插话判定结果。"""

    fired: bool = False
    speaker_id: str = SpeakerId.LOCAL_USER.value
    rms: float = 0.0
    latency_ms: float = 0.0
    reason: str = ""


@dataclass
class BargeInDetector:
    """用户插话检测（规格 §14）。

    规则：avatar 正在说话时，**本地用户**开口超过 ``min_speech_ms`` 就判定插话。
    远端用户默认不触发插话（避免视频通话里对方说话把我们打断），
    需要时把 ``remote_can_barge_in`` 打开。

    判定必须够快：目标 interrupt latency < 200ms（规格 §21）。
    """

    vad: EnergyVad = field(default_factory=EnergyVad)
    min_speech_ms: float = 160.0
    cooldown_ms: float = 400.0
    remote_can_barge_in: bool = False

    _voice_ms: float = 0.0
    _last_fire_ts: float = 0.0

    def observe(self, chunk: AudioChunk, *, avatar_speaking: bool,
                now: Optional[float] = None) -> BargeInEvent:
        now = now if now is not None else time.time()
        rms = pcm_rms(chunk.pcm)
        speaker = chunk.speaker_id or SpeakerId.LOCAL_USER.value

        if not avatar_speaking:
            self._voice_ms = 0.0
            return BargeInEvent(fired=False, speaker_id=speaker, rms=rms, reason="avatar 未在说话")

        if speaker == SpeakerId.REMOTE_USER.value and not self.remote_can_barge_in:
            return BargeInEvent(fired=False, speaker_id=speaker, rms=rms, reason="远端用户不触发插话")

        if (now - self._last_fire_ts) * 1000.0 < self.cooldown_ms:
            return BargeInEvent(fired=False, speaker_id=speaker, rms=rms, reason="冷却中")

        if rms >= self.vad.threshold:
            self._voice_ms += (chunk.duration_ms() or 20.0)
        else:
            self._voice_ms = max(0.0, self._voice_ms - (chunk.duration_ms() or 20.0))

        if self._voice_ms >= self.min_speech_ms:
            self._last_fire_ts = now
            fired_after = self._voice_ms
            self._voice_ms = 0.0
            return BargeInEvent(
                fired=True, speaker_id=speaker, rms=rms,
                latency_ms=fired_after, reason="用户开口 → barge-in",
            )
        return BargeInEvent(fired=False, speaker_id=speaker, rms=rms, reason="累积中")

    def reset(self) -> None:
        self.vad.reset()
        self._voice_ms = 0.0


@dataclass
class TurnState:
    """turn detection 状态：谁在说、说到哪了。"""

    active_speaker: str = ""
    turn_index: int = 0
    last_speech_ts: float = 0.0
    silence_ms: float = 0.0


@dataclass
class TurnDetector:
    """轻量 turn detection：靠 VAD + 静音时长切 turn。

    规格 §4 要求「不要等整句话结束」——所以这里只用来标记 turn 边界，
    音频仍然是一边收一边往 Omni 送 partial。
    """

    vad: EnergyVad = field(default_factory=EnergyVad)
    end_silence_ms: float = 600.0
    state: TurnState = field(default_factory=TurnState)

    def observe(self, chunk: AudioChunk) -> TurnState:
        speaking = self.vad.is_speech(chunk)
        dur = chunk.duration_ms() or 20.0
        if speaking:
            if self.state.active_speaker and self.state.active_speaker != chunk.speaker_id:
                self.state.turn_index += 1
            self.state.active_speaker = chunk.speaker_id
            self.state.last_speech_ts = chunk.timestamp
            self.state.silence_ms = 0.0
        else:
            self.state.silence_ms += dur
            if self.state.silence_ms >= self.end_silence_ms:
                self.state.active_speaker = ""
        return self.state


__all__ = [
    "BargeInDetector",
    "BargeInEvent",
    "EnergyVad",
    "TurnDetector",
    "TurnState",
    "pcm_rms",
]
