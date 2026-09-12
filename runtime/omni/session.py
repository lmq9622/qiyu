# -*- coding: utf-8 -*-
"""栖语 · OmniSession（规格 §2 / §3 / §4 / §5 / §12 / §14）。

``OmniSession`` 是 ``IRealtimeOmni`` 的**真实实现**，也是新架构里唯一的会话对象。
它负责把「后端能力」编排成「产品行为」：

| 职责 | 实现位置 |
|---|---|
| 长连接 session（不是一次性请求） | ``start_session`` / ``close`` |
| 视频降采样（5~10FPS + 事件提速） | ``send_video_frame`` → ``VideoScheduler`` |
| 插话打断（barge-in） | ``send_audio_chunk`` → ``BargeInDetector`` → ``interrupt`` |
| 世界事件 / 动捕事件统一入口 | ``send_world_event`` / ``send_motion_event`` |
| 三路流式输出（text delta / audio chunk / event） | ``_fan_out`` + ``receive_*`` |
| Media Plane 与 AI Plane 分离 | 本类只吃「已经降采样的」音频/视频，不碰 WebRTC |
| 指标采集 | ``OmniMetrics`` |

**它不做的事**：不做 30/60FPS 处理、不做骨骼/IK/Animator、不做 WebRTC 传输。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncIterator, Optional

from runtime.omni.audio import BargeInDetector, EnergyVad, TurnDetector
from runtime.omni.interface import IRealtimeOmni, IRealtimeOmniBackend, IRealtimeOmniStream
from runtime.omni.metrics import OmniMetrics
from runtime.omni.types import (
    AudioChunk,
    BackendCapabilities,
    HumanInteractionEvent,
    OmniOutputKind,
    SessionConfig,
    SessionState,
    SpeakerId,
    UnifiedBrainEvent,
    VideoFrame,
    WorldEvent,
    normalize_world_state,
)
from runtime.omni.video_scheduler import VideoScheduler

_STOP = object()


class OmniSession(IRealtimeOmni):
    def __init__(
        self,
        backend: IRealtimeOmniBackend,
        *,
        video_scheduler: Optional[VideoScheduler] = None,
        barge_in: Optional[BargeInDetector] = None,
        metrics: Optional[OmniMetrics] = None,
        auto_interrupt_on_barge_in: bool = True,
    ) -> None:
        self.backend = backend
        self.video = video_scheduler or VideoScheduler()
        self.barge_in = barge_in or BargeInDetector(vad=EnergyVad())
        self.turn = TurnDetector(vad=self.barge_in.vad)
        self.metrics = metrics or OmniMetrics(label=backend.name)
        self.auto_interrupt_on_barge_in = auto_interrupt_on_barge_in

        self.config = SessionConfig()
        self.stream: Optional[IRealtimeOmniStream] = None
        self._state = SessionState.IDLE.value
        self._reader: Optional[asyncio.Task] = None
        self._text_q: asyncio.Queue = asyncio.Queue()
        self._audio_q: asyncio.Queue = asyncio.Queue()
        self._event_q: asyncio.Queue = asyncio.Queue()
        self._speaking = False
        self._cancelled = False
        self.world_state: dict = normalize_world_state(None)
        self.counters = {
            "audio_in": 0, "video_in": 0, "video_sent": 0, "text_in": 0,
            "world_events": 0, "motion_events": 0, "interrupts": 0,
            "text_deltas": 0, "audio_out": 0, "events": 0,
        }

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start_session(self, config: Optional[SessionConfig] = None) -> str:
        self.config = config or self.config
        self._state = SessionState.CONNECTING.value
        self.metrics.mark("session_start")
        load = await self.backend.load()
        self.metrics.fact("backend_load_ok", bool(load.get("ok")))
        if load.get("load_ms") is not None:
            self.metrics.fact("model_load_ms", load.get("load_ms"))
        if not load.get("ok", True):
            self._state = SessionState.ERROR.value
            raise RuntimeError(f"Omni 后端加载失败: {load.get('error') or load}")
        self.stream = await self.backend.open_stream(self.config)
        self._reader = asyncio.create_task(self._fan_out())
        self._state = SessionState.LISTENING.value
        return self.config.session_id

    async def close(self) -> None:
        if self.stream is not None:
            await self.stream.close()
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
            self._reader = None
        try:
            await self.backend.unload()
        except Exception:
            pass
        self._state = SessionState.CLOSED.value
        for q in (self._text_q, self._audio_q, self._event_q):
            q.put_nowait(_STOP)

    # ------------------------------------------------------------------
    # 输入
    # ------------------------------------------------------------------

    async def send_audio_chunk(self, chunk: AudioChunk) -> None:
        if self.stream is None:
            return
        if not chunk.speaker_id:
            chunk.speaker_id = SpeakerId.LOCAL_USER.value
        self.counters["audio_in"] += 1

        t0 = time.perf_counter()
        is_speech = self.barge_in.vad.is_speech(chunk)
        chunk.is_speech = is_speech
        self.turn.observe(chunk)

        # 插话判定：avatar 说话中 + 本地用户开口 → 立刻打断
        if self.config.allow_barge_in:
            ev = self.barge_in.observe(chunk, avatar_speaking=self._speaking)
            if ev.fired and self.auto_interrupt_on_barge_in:
                self.metrics.record("barge_in_trigger_ms", ev.latency_ms)
                await self.interrupt(reason=ev.reason)

        await self.stream.push_audio(chunk)
        self.metrics.record_rtf((time.perf_counter() - t0) * 1000.0, chunk.duration_ms() or 1.0)

    async def send_video_frame(self, frame: VideoFrame) -> None:
        """**只有调度器放行的帧才会进后端。** 这是「不把 30/60FPS 全推给模型」的落点。"""
        if self.stream is None:
            return
        self.counters["video_in"] += 1
        keep = self.video.offer(frame)
        if keep is None:
            return
        self.counters["video_sent"] += 1
        await self.stream.push_video(keep)

    async def send_text(self, text: str, *, speaker_id: str = SpeakerId.LOCAL_USER.value) -> None:
        if self.stream is None:
            return
        self.counters["text_in"] += 1
        self.metrics.mark("request")
        await self.stream.push_text(text, speaker_id=speaker_id)

    async def send_world_event(self, event: WorldEvent) -> None:
        if self.stream is None:
            return
        self.counters["world_events"] += 1
        payload = dict(event.payload or {})
        payload.setdefault("kind", event.kind)
        payload.setdefault("priority", event.priority)
        payload.setdefault("source", event.source)

        # 世界事件可以触发视频采样提速（规格 §5）
        trigger = str(payload.get("trigger") or payload.get("event") or "")
        if trigger:
            self.video.on_event(trigger)

        if event.payload and event.payload.get("world_state"):
            self.world_state = normalize_world_state(event.payload["world_state"])

        # 高优先级事件：直接打断当前输出（规格 §25「等一下，别过来」）
        if event.priority >= 80:
            await self.interrupt(reason=f"world_event:{trigger or event.kind}")

        await self.stream.push_event(payload)

    async def send_motion_event(self, event: HumanInteractionEvent) -> None:
        if self.stream is None:
            return
        self.counters["motion_events"] += 1
        name = event.name
        if name in ("stop", "reject") and self.config.allow_barge_in:
            await self.interrupt(reason=f"motion:{name}")
        if name in ("point", "reach", "wave"):
            self.video.on_event("point" if name == "point" else "reach")
        await self.stream.push_event({
            "name": name, "kind": "human_interaction",
            "confidence": event.confidence, "target": event.target,
            "payload": event.payload, "ts": event.timestamp,
        })

    # ------------------------------------------------------------------
    # 输出（三路扇出）
    # ------------------------------------------------------------------

    async def _fan_out(self) -> None:
        assert self.stream is not None
        try:
            async for ev in self.stream.outputs():
                self.counters["events"] += 1
                self._event_q.put_nowait(ev)

                if ev.conversation is not None:
                    if ev.conversation.text:
                        self.counters["text_deltas"] += 1
                        self.metrics.mark_first_text()
                        self._text_q.put_nowait(ev.conversation)
                    if ev.conversation.audio is not None:
                        self.counters["audio_out"] += 1
                        self.metrics.mark_first_audio()
                        self._audio_q.put_nowait(ev.conversation)

                    if ev.conversation.is_final:
                        self._speaking = False
                    else:
                        self._speaking = True
                        self._state = SessionState.SPEAKING.value
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._event_q.put_nowait(UnifiedBrainEvent(
                kind=OmniOutputKind.EVENT.value, payload={"event": "session_error", "error": repr(e)},
            ))
        finally:
            # 后端流结束（正常关闭或异常断开）必须让上层知道，不能静默
            self._event_q.put_nowait(UnifiedBrainEvent(
                kind=OmniOutputKind.EVENT.value,
                payload={"event": "stream_closed", "state": self._state},
            ))
            for q in (self._text_q, self._audio_q, self._event_q):
                q.put_nowait(_STOP)

    async def receive_text_delta(self) -> AsyncIterator[str]:
        while True:
            item = await self._text_q.get()
            if item is _STOP:
                return
            yield item.text

    async def receive_audio_chunk(self) -> AsyncIterator[AudioChunk]:
        while True:
            item = await self._audio_q.get()
            if item is _STOP:
                return
            yield AudioChunk(
                pcm=item.audio, sample_rate=item.sample_rate,
                speaker_id=item.speaker_id or SpeakerId.QIYU.value,
                meta={"format": item.audio_format, "emotion": item.emotion},
            )

    async def receive_event(self) -> AsyncIterator[UnifiedBrainEvent]:
        while True:
            item = await self._event_q.get()
            if item is _STOP:
                return
            yield item

    # ------------------------------------------------------------------
    # 打断
    # ------------------------------------------------------------------

    async def interrupt(self, reason: str = "") -> None:
        if self.stream is None:
            return
        self.counters["interrupts"] += 1
        self.metrics.mark_interrupt(reason)
        self._speaking = False
        self._state = SessionState.INTERRUPTED.value
        await self.stream.interrupt(reason)
        self.barge_in.reset()
        self.metrics.mark_interrupt_done()
        self._state = SessionState.LISTENING.value

    async def cancel(self) -> None:
        """取消当前一轮，但保持 session 存活。"""
        self._cancelled = True
        await self.interrupt(reason="cancel")
        self._cancelled = False

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------

    def capabilities(self) -> BackendCapabilities:
        return self.backend.capabilities()

    def health(self) -> dict:
        return {
            "state": self._state,
            "backend": self.backend.health(),
            "counters": dict(self.counters),
            "video": self.video.snapshot(),
            "speaking": self._speaking,
            "metrics": self.metrics.report(),
        }

    @property
    def state(self) -> str:
        return self._state

    @property
    def backend_name(self) -> str:
        return self.backend.name

    def snapshot(self) -> dict:
        return {
            "session_id": self.config.session_id,
            "state": self._state,
            "backend": self.backend.name,
            "counters": dict(self.counters),
            "video": self.video.snapshot(),
        }


__all__ = ["OmniSession"]
