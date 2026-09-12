# -*- coding: utf-8 -*-
"""栖语 · MockOmniBackend。

**存在的意义**：在没有 MiniCPM-o 权重、没有 AMD 后端的机器上，也能把
「OmniSession + 全双工 + barge-in + VideoScheduler + AvatarIntent +
UnifiedBrainEvent + 指标采集」这整条新链路**真跑一遍**。

它不是拿假数据糊弄：
- 输入真的进 inbox，输出真的走异步队列；
- 文本是增量 delta，音频是分片 chunk；
- 打断真的会清空待发输出；
- 延迟可以注入（``step_ms``），所以 TTFA / interrupt latency 是真实测出来的。

它对应规格里的验证等级 ``SIMULATED``，绝不冒充 ``LOCAL GPU VERIFIED``。
"""

from __future__ import annotations

import asyncio
import math
import time
from typing import Optional

from runtime.omni.backends.base import BaseBackend, PendingInput, QueueStream
from runtime.omni.interface import IRealtimeOmniStream
from runtime.omni.types import (
    AudioChunk,
    AvatarIntent,
    AvatarIntentName,
    BackendCapabilities,
    FrameKind,
    SessionConfig,
    SessionState,
    VideoFrame,
)

# 关键词 → AvatarIntent。第一版规则化，接入真模型后由 Omni 输出替换。
INTENT_RULES: tuple = (
    (("击掌", "high five", "highfive"), AvatarIntentName.HIGH_FIVE.value, "user"),
    (("过来", "come here", "来一下"), AvatarIntentName.APPROACH.value, "user"),
    (("别过来", "停下", "等一下", "stop"), AvatarIntentName.RETREAT.value, "user"),
    (("跟着我", "跟我", "follow"), AvatarIntentName.FOLLOW.value, "user"),
    (("看这个", "看看这个", "你看我手里"), AvatarIntentName.LOOK_AT.value, "object:held"),
    (("那是什么", "你在看啥", "看啥"), AvatarIntentName.LOOK_AT.value, "shared_focus"),
    (("看看", "你看", "这个是啥", "这是什么"), AvatarIntentName.LOOK_AT.value, "shared_focus"),
    (("挥个手", "招手", "hello"), AvatarIntentName.WAVE.value, "user"),
    (("坐下", "坐吧"), AvatarIntentName.SIT.value, "location:seat"),
    (("点一下", "指一下"), AvatarIntentName.POINT.value, "shared_focus"),
)

# 事件名 → VideoScheduler 提速键
VIDEO_EVENT_MAP = {
    "point": "point",
    "wave": "hand_raise",
    "reach": "reach",
    "object_appeared": "object_appeared",
    "object_picked": "object_picked",
    "look_request": "user_look_request",
    "remote_motion": "remote_motion",
    "scene_change": "scene_change",
}


class MockOmniStream(QueueStream):
    def __init__(self, config: SessionConfig, step_ms: float = 0.0,
                 reply_prefix: str = "（听到）") -> None:
        super().__init__(config, backend_name="mock_omni")
        self.step_ms = step_ms
        self.reply_prefix = reply_prefix
        self.state = SessionState.LISTENING.value
        self.frames_seen = 0
        self.audio_ms_seen = 0.0
        self.interrupt_count = 0

    async def _on_interrupt(self, reason: str) -> None:
        self.interrupt_count += 1

    async def _tick(self) -> None:
        if self.step_ms > 0:
            await asyncio.sleep(self.step_ms / 1000.0)

    # ---------- 产出 ----------

    async def _produce(self) -> None:
        while not self._closed:
            items = self.pop_inputs()
            if not items:
                await asyncio.sleep(0.01)
                continue
            for item in items:
                if self._closed:
                    return
                await self._handle(item)

    async def _handle(self, item: PendingInput) -> None:
        if item.kind == "audio":
            chunk: AudioChunk = item.payload
            self.audio_ms_seen += (chunk.duration_ms() or 0.0)
            return
        if item.kind == "video":
            frame: VideoFrame = item.payload
            self.frames_seen += 1
            if frame.kind == FrameKind.SNAPSHOT.value and self._looks_like_look_request():
                await self.emit_event("omni_vision_request", frame_id=frame.frame_id)
            return
        if item.kind == "event":
            await self._handle_event(item.payload)
            return
        if item.kind == "text":
            await self._handle_text(str(item.payload), item.speaker_id)

    async def _handle_event(self, payload: dict) -> None:
        name = str((payload or {}).get("name") or (payload or {}).get("event") or "")
        if name in ("point", "user_point"):
            await self.emit_intent(AvatarIntent(
                intent=AvatarIntentName.LOOK_AT.value,
                target=str((payload or {}).get("target") or "shared_focus"),
                attention="用户指向的目标", reason="human_interaction:point",
            ))
            await self.emit_event("video_boost", key=VIDEO_EVENT_MAP["point"], why="用户指向")
        elif name in ("wave",):
            await self.emit_intent(AvatarIntent(
                intent=AvatarIntentName.WAVE.value, target="user",
                emotion="happy", reason="human_interaction:wave",
            ))
        elif name in ("stop", "reject"):
            # 规格 §25：用户说「等一下，别过来」→ 本地高优先级 interrupt
            await self.interrupt(reason="human_interaction:stop")
        elif name in ("high_five",):
            await self.emit_intent(AvatarIntent(
                intent=AvatarIntentName.HIGH_FIVE.value, target="user",
                emotion="happy", urgency=0.6, reason="human_interaction:high_five",
            ))
        elif name in ("come_here", "come"):
            await self.emit_intent(AvatarIntent(
                intent=AvatarIntentName.APPROACH.value, target="user",
                emotion="warm", urgency=0.5, reason="human_interaction:come_here",
            ))
        elif name in ("follow",):
            await self.emit_intent(AvatarIntent(
                intent=AvatarIntentName.FOLLOW.value, target="user",
                reason="human_interaction:follow",
            ))
        elif name in ("sit", "stand"):
            await self.emit_intent(AvatarIntent(
                intent=(AvatarIntentName.SIT.value if name == "sit" else AvatarIntentName.STAND.value),
                target=("location:seat" if name == "sit" else ""),
                reason="human_interaction:" + name,
            ))
        elif name in ("look", "nod", "shake_head", "give", "observe"):
            await self.emit_intent(AvatarIntent(
                intent=name, target=str((payload or {}).get("target") or ""),
                reason="human_interaction:" + name,
            ))
        elif name in VIDEO_EVENT_MAP:
            await self.emit_event("video_boost", key=VIDEO_EVENT_MAP[name], why=name)

    def _looks_like_look_request(self) -> bool:
        return "看" in (self.config.topic_state or "")

    async def _handle_text(self, text: str, speaker_id: str) -> None:
        self.state = SessionState.THINKING.value
        # 1) 事件语义 → AvatarIntent
        for keys, intent, target in INTENT_RULES:
            if any(k in text for k in keys):
                await self.emit_intent(AvatarIntent(
                    intent=intent, target=target, emotion="warm",
                    attention=text[:24], reason=f"rule:{keys[0]}",
                ))
                break

        # 2) 流式文本（逐字 delta）
        reply = f"{self.reply_prefix}{text}"
        accrued = ""
        self.state = SessionState.SPEAKING.value
        for ch in reply:
            if self._closed:
                return
            if self._interrupted:
                self._interrupted = False
                return
            await self._tick()
            accrued += ch
            await self.emit_text(ch, final=False,
                                 latency_ms={"since_input_ms": round((time.time() - self.started_at) * 1000, 1)})
        await self.emit_text("", final=True)

        # 3) 流式音频（分片，模拟原生 speech output）
        n_chunks = max(1, min(8, math.ceil(len(reply) / 3)))
        for i in range(n_chunks):
            if self._closed:
                return
            if self._interrupted:
                self._interrupted = False
                return
            await self._tick()
            await self.emit_audio(
                audio=("mock_pcm", len(reply), i), sample_rate=24000,
                audio_format="pcm_f32", emotion="warm", final=(i == n_chunks - 1),
            )
        self.state = SessionState.LISTENING.value


class MockOmniBackend(BaseBackend):
    """可真实运行的参考后端。用于 E2E / 回归 / 指标口径校验。"""

    name = "mock_omni"
    display_name = "Mock Omni（本地模拟，SIMULATED）"
    requires = ()

    def __init__(self, step_ms: float = 0.0, **options) -> None:
        super().__init__(**options)
        self.step_ms = step_ms

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            audio_in=True, audio_out=True, video_in=True, text_in=True, text_out=True,
            streaming=True, full_duplex=True, barge_in=True, native_speech=True,
            languages=("zh",), backends=("cpu",),
            notes="本地模拟后端：验证编排链路，不产生真实语音。",
        )

    async def open_stream(self, config: SessionConfig) -> IRealtimeOmniStream:
        stream = MockOmniStream(config, step_ms=self.step_ms)
        stream.start_producer()
        return stream


__all__ = ["INTENT_RULES", "VIDEO_EVENT_MAP", "MockOmniBackend", "MockOmniStream"]
