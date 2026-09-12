# -*- coding: utf-8 -*-
"""栖语 · Omni 后端基类。

把「流式会话」的公共机械部分收口，具体后端只需要实现 ``_produce()``：

- 输入侧（``push_audio`` / ``push_video`` / ``push_text`` / ``push_event``）统一进
  ``PendingInput`` 队列，后端自己决定怎么消费；
- 输出侧统一走 ``emit()`` 往 ``asyncio.Queue`` 里塞 ``UnifiedBrainEvent``，
  ``outputs()`` 把它变成异步生成器；
- ``interrupt()`` 会清空未消费的输入与待发输出，并推一条 ``interrupted`` 事件。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from runtime.omni.interface import IRealtimeOmniBackend, IRealtimeOmniStream
from runtime.omni.types import (
    AudioChunk,
    BackendCapabilities,
    ConversationOutput,
    HumanInteractionEvent,
    OmniOutputKind,
    SessionConfig,
    SessionState,
    UnifiedBrainEvent,
    VideoFrame,
    WorldEvent,
)

_STOP = object()


@dataclass
class PendingInput:
    kind: str = ""                     # text / audio / video / event
    payload: Any = None
    speaker_id: str = ""
    ts: float = field(default_factory=time.time)


class QueueStream(IRealtimeOmniStream):
    """基于队列的流式会话。后端子类实现 ``_produce()`` 即可。"""

    def __init__(self, config: SessionConfig, backend_name: str = "") -> None:
        self.config = config
        self.backend_name = backend_name
        self.inbox: deque = deque(maxlen=512)
        self._out: asyncio.Queue = asyncio.Queue()
        self._closed = False
        self._interrupted = False
        self._seq = 0
        self._producer: Optional[asyncio.Task] = None
        self.state = SessionState.CONNECTING.value
        self.started_at = time.time()
        self.log: list = []                # 供 REAL_CONVERSATION_TEST 记录

    # ---------- 输入 ----------

    async def push_audio(self, chunk: AudioChunk) -> None:
        self.inbox.append(PendingInput("audio", chunk, chunk.speaker_id))

    async def push_video(self, frame: VideoFrame) -> None:
        self.inbox.append(PendingInput("video", frame))

    async def push_text(self, text: str, *, speaker_id: str = "local_user") -> None:
        self.inbox.append(PendingInput("text", text, speaker_id))

    async def push_event(self, payload: dict) -> None:
        self.inbox.append(PendingInput("event", payload))

    # ---------- 输出 ----------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    async def emit(self, event: UnifiedBrainEvent) -> None:
        if self._closed:
            return
        if not event.seq:
            event.seq = self._next_seq()
        if not event.session_id:
            event.session_id = self.config.session_id
        event.state = self.state
        self._out.put_nowait(event)

    async def emit_text(self, text: str, *, final: bool = False, **kw) -> None:
        await self.emit(UnifiedBrainEvent(
            kind=OmniOutputKind.CONVERSATION.value,
            conversation=ConversationOutput(text=text, is_final=final, **kw),
        ))

    async def emit_audio(self, audio: Any, *, sample_rate: int = 24000,
                         audio_format: str = "pcm_f32", emotion: str = "",
                         final: bool = False, latency_ms: Optional[dict] = None) -> None:
        await self.emit(UnifiedBrainEvent(
            kind=OmniOutputKind.CONVERSATION.value,
            conversation=ConversationOutput(
                audio=audio, audio_format=audio_format, sample_rate=sample_rate,
                emotion=emotion, is_final=final, latency_ms=latency_ms or {},
            ),
        ))

    async def emit_intent(self, intent, **kw) -> None:
        await self.emit(UnifiedBrainEvent(
            kind=OmniOutputKind.AVATAR_INTENT.value,
            avatar_intent=intent,
            payload=kw,
        ))

    async def emit_event(self, name: str, **payload) -> None:
        await self.emit(UnifiedBrainEvent(
            kind=OmniOutputKind.EVENT.value,
            payload={"event": name, **payload},
        ))

    async def outputs(self) -> AsyncIterator[UnifiedBrainEvent]:
        while True:
            item = await self._out.get()
            if item is _STOP:
                break
            yield item

    # ---------- 打断 ----------

    async def interrupt(self, reason: str = "") -> None:
        self._interrupted = True
        self.state = SessionState.INTERRUPTED.value
        self.inbox.clear()
        # 清空待发输出：这就是「立即停止 TTS/audio playback」在服务端的对应动作
        dropped = 0
        while not self._out.empty():
            try:
                self._out.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        self.log.append({"event": "interrupt", "reason": reason, "dropped": dropped, "ts": time.time()})
        await self.emit_event("interrupted", reason=reason, dropped=dropped)
        await self._on_interrupt(reason)
        self.state = SessionState.LISTENING.value

    async def _on_interrupt(self, reason: str) -> None:
        """子类可覆盖：真正让模型停止生成。"""

    # ---------- 生命周期 ----------

    def start_producer(self) -> None:
        if self._producer is None:
            self._producer = asyncio.create_task(self._run_producer())

    async def _run_producer(self) -> None:
        try:
            await self._produce()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover
            await self.emit_event("backend_error", error=repr(e))
            self.state = SessionState.ERROR.value

    async def _produce(self) -> None:
        """子类实现：消费 inbox、产出事件。"""

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.state = SessionState.CLOSED.value
        if self._producer is not None:
            self._producer.cancel()
            try:
                await self._producer
            except (asyncio.CancelledError, Exception):
                pass
        self._out.put_nowait(_STOP)

    def pop_inputs(self, kinds: Optional[tuple] = None) -> list:
        """取出并返回待处理输入（可只取指定 kind）。"""
        out = []
        keep = deque()
        while self.inbox:
            item = self.inbox.popleft()
            if kinds is None or item.kind in kinds:
                out.append(item)
            else:
                keep.append(item)
        self.inbox = keep
        return out


class BaseBackend(IRealtimeOmniBackend):
    """后端公共实现：load/unload/health 默认值。"""

    name = "base"
    display_name = "基类后端"
    requires = ()                     # 依赖的 python 包名

    def __init__(self, **options) -> None:
        self.options = options
        self._loaded = False
        self._last_error = ""
        self._load_ms = 0.0

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities()

    def available(self) -> bool:
        return True

    async def load(self) -> dict:
        t0 = time.time()
        try:
            await self._do_load()
            self._loaded = True
            self._load_ms = round((time.time() - t0) * 1000.0, 1)
            return {"ok": True, "backend": self.name, "load_ms": self._load_ms}
        except Exception as e:
            self._last_error = repr(e)
            return {"ok": False, "backend": self.name, "error": self._last_error}

    async def _do_load(self) -> None:
        ...

    async def unload(self) -> dict:
        self._loaded = False
        return {"ok": True, "backend": self.name}

    def health(self) -> dict:
        return {
            "backend": self.name,
            "display_name": self.display_name,
            "available": bool(self.available()),
            "loaded": bool(self._loaded),
            "load_ms": self._load_ms,
            "last_error": self._last_error,
            "capabilities": self.capabilities().to_dict(),
        }

    async def open_stream(self, config: SessionConfig) -> IRealtimeOmniStream:
        raise NotImplementedError

    # 依赖检查工具
    @classmethod
    def missing_requires(cls) -> list:
        import importlib.util

        missing = []
        for mod in cls.requires:
            if importlib.util.find_spec(mod) is None:
                missing.append(mod)
        return missing


__all__ = ["BaseBackend", "PendingInput", "QueueStream"]
