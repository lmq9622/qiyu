# -*- coding: utf-8 -*-
"""网关侧呼叫信令桥：把 WebSocket 信号接进 MediaSession。

    Browser/Quest  <--WebSocket(JSON)-->  CallSignalingBridge  <-->  MediaSession  <--> Remote Peer

为什么要有这一层：
``runtime/media`` 只知道 ``SignalingTransport`` 抽象，不知道 WebSocket 的存在；
网关只知道 WebSocket，不知道 WebRTC。这一层是两者之间唯一的口子。

协议（文本 JSON，与 ``SignalMessage.to_wire()`` 同构）：

    客户端 -> 服务端               服务端 -> 客户端
    {"type":"hello","role":"offerer"}       {"type":"hello.ack", ...}
    {"type":"answer","payload":{"sdp":...}} {"type":"offer","payload":{"sdp":...}}
    {"type":"candidate","payload":{...}}    {"type":"candidate", ...}
    {"type":"quality"}                      {"type":"quality","payload":{...}}
    {"type":"stats"}                        {"type":"stats","payload":{...}}
    {"type":"bye"}                          {"type":"bye","payload":{stats}}
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Awaitable, Callable, Optional

from runtime.media.adaptation import BandwidthAdapter
from runtime.media.service import VideoCallService
from runtime.media.signaling import QueueSignaling
from runtime.media.types import MediaQualitySample

CONTROL_TYPES = ("hello", "quality", "stats", "adapt", "bye", "ping")


class CallSignalingBridge:
    """一条 WebSocket 连接 = 一次视频通话会话（server 侧 peer）。"""

    def __init__(self, service: Optional[VideoCallService] = None,
                 session_kwargs: Optional[dict] = None,
                 adapt: bool = True):
        self.service = service or VideoCallService()
        self.session_kwargs = dict(session_kwargs or {})
        self.adapt = adapt
        self.connections = 0
        self.last_close_stats: dict = {}

    async def run(self, send_json: Callable[[str], Awaitable[None]],
                  recv_json: Callable[[], Awaitable[Optional[dict]]]) -> dict:
        self.connections += 1
        hello = await recv_json() or {}
        role = str(hello.get("role") or "offerer")
        if role not in ("offerer", "answerer"):
            role = "offerer"
        sig = QueueSignaling(identity=str(hello.get("from") or f"caller-{self.connections}"))
        await sig.open()
        session = await self.service.create_session(role, sig, **self.session_kwargs)
        adapter = BandwidthAdapter(current_fps=float(
            self.session_kwargs.get("video_fps", 10.0))) if self.adapt else None
        quality_task: Optional[asyncio.Task] = None

        await send_json(json.dumps({
            "type": "hello.ack", "session_id": session.session_id, "role": role,
            "ice_servers": [s.to_dict() for s in session.config.ice_servers],
        }, ensure_ascii=False))

        out_task = asyncio.create_task(self._pump_outbox(sig, send_json))
        start_task = asyncio.create_task(session.start())

        async def quality_loop():
            while True:
                await asyncio.sleep(2.0)
                try:
                    sample = await session.link.stats() if session.link else MediaQualitySample()
                    payload = sample.to_dict()
                    if adapter is not None:
                        decision = adapter.decide(sample)
                        if decision.changed:
                            payload["adaptation"] = adapter.apply(session, decision)
                        payload["level"] = adapter.level
                        payload["target_fps"] = adapter.current_fps
                    await send_json(json.dumps({"type": "quality", "payload": payload},
                                               ensure_ascii=False))
                except Exception:
                    return

        if adapter is not None:
            quality_task = asyncio.create_task(quality_loop())

        try:
            while True:
                raw = await recv_json()
                if raw is None:
                    break
                mtype = str(raw.get("type") or "")
                if mtype == "quality":
                    sample = await session.link.stats() if session.link else MediaQualitySample()
                    await send_json(json.dumps({"type": "quality", "payload": sample.to_dict()},
                                               ensure_ascii=False))
                elif mtype == "adapt":
                    if adapter is not None:
                        decision = adapter.decide(MediaQualitySample(**{
                            k: v for k, v in (raw.get("payload") or {}).items()
                            if k in MediaQualitySample.__dataclass_fields__}))
                        await send_json(json.dumps(
                            {"type": "adapt", "payload": adapter.apply(session, decision)},
                            ensure_ascii=False))
                elif mtype == "stats":
                    await send_json(json.dumps({"type": "stats",
                                                "payload": session.stats().to_dict()},
                                               ensure_ascii=False))
                elif mtype in ("bye", "ping"):
                    if mtype == "bye":
                        break
                else:
                    await sig.feed(raw)
        finally:
            for t in (quality_task, out_task):
                if t is not None:
                    t.cancel()
            try:
                await start_task
            except Exception:
                pass
            stats = session.stats().to_dict()
            try:
                await session.close()
            except Exception:
                pass
            self.last_close_stats = stats
            try:
                await send_json(json.dumps({"type": "bye", "payload": stats},
                                           ensure_ascii=False))
            except Exception:
                pass
        return self.last_close_stats

    @staticmethod
    async def _pump_outbox(sig: QueueSignaling,
                           send_json: Callable[[str], Awaitable[None]]) -> None:
        while True:
            msg = await sig.outbox.get()
            try:
                await send_json(json.dumps(msg.to_wire(), ensure_ascii=False))
            except Exception:
                return
