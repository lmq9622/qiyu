# -*- coding: utf-8 -*-
"""信令抽象（signaling abstraction）。

媒体面与「怎么交换 SDP/ICE」解耦：同一份 ``MediaSession`` 代码，
既能在本机用 ``InProcessSignaling`` 做**真实 WebRTC 回环**，
也能挂到 WebSocket / HTTP 信令服务器上（``WebSocketSignaling`` 适配位）。

消息只走声明式的 :class:`SignalMessage`，不塞业务语义。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional


class SignalKind(str, Enum):
    HELLO = "hello"            # 上线/声明自己
    OFFER = "offer"
    ANSWER = "answer"
    CANDIDATE = "candidate"
    TRACK_STATE = "track_state"   # mute / camera / 轨道增删
    QUALITY = "quality"
    BYE = "bye"
    ERROR = "error"


@dataclass
class SignalMessage:
    kind: str
    session_id: str = ""
    from_id: str = ""
    to_id: str = ""
    payload: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    seq: int = 0
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_wire(self) -> dict:
        return {
            "type": self.kind,
            "session_id": self.session_id,
            "from": self.from_id,
            "to": self.to_id,
            "payload": self.payload,
            "ts": self.ts,
            "seq": self.seq,
            "msg_id": self.msg_id,
        }

    @staticmethod
    def from_wire(raw: Any) -> "SignalMessage":
        d = json.loads(raw) if isinstance(raw, (str, bytes)) else dict(raw)
        return SignalMessage(
            kind=d.get("type", ""), session_id=d.get("session_id", ""),
            from_id=d.get("from", ""), to_id=d.get("to", ""),
            payload=d.get("payload") or {}, ts=d.get("ts", time.time()),
            seq=d.get("seq", 0), msg_id=d.get("msg_id", uuid.uuid4().hex[:12]),
        )


class SignalingTransport:
    """信令传输接口。实现方只负责「把消息送到对端」。"""

    name = "abstract"

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def send(self, msg: SignalMessage) -> None:
        raise NotImplementedError

    def on_message(self, handler: Callable[[SignalMessage], Awaitable[None]]) -> None:
        raise NotImplementedError

    @property
    def identity(self) -> str:
        return ""


class InProcessSignaling(SignalingTransport):
    """本机回环信令：两个 endpoint 在同一个进程里直连。

    ⚠️ 它不是「假 WebRTC」——SDP/ICE/DTLS/SRTP 全是 aiortc 真跑的，
    只有「信令怎么送」这一跳省掉了网络。报告里标注为
    ``REAL WEBRTC (loopback, in-process signaling)``。
    """

    name = "in-process"
    _registry: dict = {}

    def __init__(self, identity: str = "", peer_identity: str = ""):
        self._identity = identity or f"ep-{uuid.uuid4().hex[:8]}"
        self._peer_identity = peer_identity
        self._handler: Optional[Callable[[SignalMessage], Awaitable[None]]] = None
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._pump: Optional[asyncio.Task] = None
        self._closed = False

    @property
    def identity(self) -> str:
        return self._identity

    def bind(self, peer: "InProcessSignaling") -> None:
        """双向绑定：两个 endpoint 互相收对方的消息。"""
        self._peer_identity = peer.identity
        peer._peer_identity = self.identity
        InProcessSignaling._registry[self.identity] = self
        InProcessSignaling._registry[peer.identity] = peer

    @staticmethod
    def pair() -> tuple:
        """造一对互相绑定的 endpoint。"""
        a = InProcessSignaling("quest")
        b = InProcessSignaling("remote")
        a.bind(b)
        return a, b

    async def open(self) -> None:
        self._closed = False
        if self._pump is None:
            self._pump = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while not self._closed:
            try:
                msg = await asyncio.wait_for(self._inbox.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            if self._handler is not None:
                try:
                    await self._handler(msg)
                except Exception:
                    pass

    async def send(self, msg: SignalMessage) -> None:
        msg.from_id = msg.from_id or self.identity
        target = InProcessSignaling._registry.get(self._peer_identity)
        if target is None:
            raise RuntimeError(f"信令对端不在线: {self._peer_identity}")
        await target._inbox.put(msg)

    def on_message(self, handler: Callable[[SignalMessage], Awaitable[None]]) -> None:
        self._handler = handler

    async def close(self) -> None:
        self._closed = True
        if self._pump is not None:
            self._pump.cancel()
            try:
                await self._pump
            except (asyncio.CancelledError, Exception):
                pass
            self._pump = None


class QueueSignaling(SignalingTransport):
    """把消息塞进 asyncio 队列的传输，供上层 WebSocket 服务器桥接。

    上层（``gateway``）只要把队列里的消息发到浏览器/Quest，把收到的消息
    用 :meth:`feed` 喂回来即可。这样媒体层不需要知道 WebSocket 的存在。
    """

    name = "queue"

    def __init__(self, identity: str = ""):
        self._identity = identity or f"ep-{uuid.uuid4().hex[:8]}"
        self.outbox: asyncio.Queue = asyncio.Queue()
        self._handler: Optional[Callable[[SignalMessage], Awaitable[None]]] = None
        self._closed = False

    @property
    def identity(self) -> str:
        return self._identity

    async def open(self) -> None:
        self._closed = False

    async def close(self) -> None:
        self._closed = True

    async def send(self, msg: SignalMessage) -> None:
        msg.from_id = msg.from_id or self.identity
        await self.outbox.put(msg)

    async def feed(self, raw: Any) -> None:
        """外部把收到的原始消息喂进来。"""
        msg = SignalMessage.from_wire(raw)
        if self._handler is not None:
            await self._handler(msg)

    def on_message(self, handler: Callable[[SignalMessage], Awaitable[None]]) -> None:
        self._handler = handler
