# -*- coding: utf-8 -*-
"""Gateway ↔ OmniSession 会话中枢（规格 §一 / §二）。

一条 WebSocket = 一个 OmniSession；协议见 ``runtime/omni/protocol.py``。

    App / Quest  <--WebSocket(统一信封)-->  OmniGatewayHub  <-->  OmniMainChain  <-->  MiniCPM-o

职责：
- ``session.start`` -> 建链 -> ``session.ready``（返回 session_id 与服务端能力）
- ``input.*``       -> 进 OmniMainChain（音频带 speaker_id；动捕只进事件+摘要）
- ``output.*``      <- OmniMainChain 输出泵（text_delta / audio_chunk / avatar_intent / listen / done）
- ``control.*``     -> interrupt / cancel / resume / close
- **断线不立刻销毁**：``resume_grace_s`` 内允许同 session_id 重连（``session.resumed``），
  序号继续、stale 事件丢弃（由 SequenceTracker 判定）。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Awaitable, Callable, Optional

from runtime.omni.protocol import (
    CONTROL_CANCEL, CONTROL_CLOSE, CONTROL_INTERRUPT, CONTROL_RESUME,
    INPUT_AUDIO, INPUT_MOTION, INPUT_TEXT, INPUT_VIDEO, INPUT_WORLD,
    OUTPUT_AUDIO, OUTPUT_DONE, OUTPUT_ERROR, OUTPUT_INTENT, OUTPUT_LISTEN,
    OUTPUT_TEXT, SESSION_CLOSED, SESSION_READY, SESSION_RESUMED, SESSION_START,
    OmniEnvelope, SequenceTracker,
)


def _audio_b64(data) -> str:
    """把后端给的音频统一成 base64 PCM（浏览器端要 base64 才能播）。"""
    import base64
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        if isinstance(data, (bytes, bytearray, memoryview)):
            return base64.b64encode(bytes(data)).decode("ascii")
        try:
            import numpy as np
            arr = np.asarray(data)
            if arr.dtype != np.float32:
                arr = arr.astype(np.float32)
            return base64.b64encode(arr.reshape(-1).tobytes()).decode("ascii")
        except Exception:
            return ""
    except Exception:
        return ""


class HubSession:
    """一条活着的 Omni 会话（可与 WebSocket 解绑以支持重连）。"""

    def __init__(self, chain, session_id: str = ""):
        self.chain = chain
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.tracker = SequenceTracker(self.session_id)
        self.created = time.time()
        self.detached_at = 0.0
        self.closed = False
        self.send: Optional[Callable[[dict], Awaitable[None]]] = None
        self.pump_task: Optional[asyncio.Task] = None
        self.counters = {"in": 0, "out": 0, "dropped": 0, "control": 0}

    async def emit(self, event_type: str, payload: dict, speaker_id: str = "qiyu") -> None:
        if self.send is None:
            return
        env = OmniEnvelope(event_type=event_type, session_id=self.session_id,
                           sequence=self.tracker.note_outbound(), payload=payload,
                           speaker_id=speaker_id)
        await self.send(env.to_wire())
        self.counters["out"] += 1

    async def pump_outputs(self) -> None:
        """把 Omni 输出转成 output.* 事件（单点出口，保证序号单调）。"""
        try:
            async for ev in self.chain.omni.receive_event():
                kind = getattr(ev, "kind", "")
                conv = getattr(ev, "conversation", None)
                intent = getattr(ev, "avatar_intent", None)
                if conv is not None and getattr(conv, "text", ""):
                    await self.emit(OUTPUT_TEXT, {"text": conv.text,
                                                  "is_final": bool(conv.is_final)},
                                    speaker_id="qiyu")
                if conv is not None and getattr(conv, "audio", None) is not None:
                    await self.emit(OUTPUT_AUDIO, {
                        "audio": _audio_b64(conv.audio),
                        "sample_rate": conv.sample_rate, "channels": 1,
                        "format": conv.audio_format or "pcm_f32"}, speaker_id="qiyu")
                if intent is not None:
                    await self.emit(OUTPUT_INTENT, intent.to_wire(), speaker_id="qiyu")
                if kind == "event" and (getattr(ev, "payload", {}) or {}).get("listen"):
                    await self.emit(OUTPUT_LISTEN, {}, speaker_id="qiyu")
                if getattr(ev, "state", "") in ("listening", "speaking", "thinking"):
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as e:
            try:
                await self.emit(OUTPUT_ERROR, {"error": f"{type(e).__name__}: {e}"})
            except Exception:
                pass

    def snapshot(self) -> dict:
        return {"session_id": self.session_id, "created": self.created,
                "detached": bool(self.detached_at), "closed": self.closed,
                "counters": dict(self.counters), "sequence": self.tracker.snapshot(),
                "chain": self.chain.stats_dict() if self.chain else None}


class OmniGatewayHub:
    def __init__(self, chain_factory=None, resume_grace_s: float = 30.0):
        """``chain_factory(session_id) -> OmniMainChain``；不传则用真实后端建链。"""
        self.chain_factory = chain_factory
        self.resume_grace_s = float(resume_grace_s)
        self.sessions: dict = {}
        self.connections = 0
        self.resumed = 0
        self.rejected = 0

    # ---------- 建链 ----------
    async def _build_chain(self, session_id: str):
        if self.chain_factory is not None:
            made = self.chain_factory(session_id)
            return await made if asyncio.iscoroutine(made) else made
        from runtime.omni.mainchain import OmniMainChain
        chain = OmniMainChain(backend="minicpm_o")
        await chain.start()
        return chain

    async def handle(self, send_json: Callable[[dict], Awaitable[None]],
                     recv_json: Callable[[], Awaitable[Optional[dict]]],
                     on_close: Optional[Callable[[], Awaitable[None]]] = None) -> dict:
        self.connections += 1
        session: Optional[HubSession] = None
        try:
            first = await recv_json()
            if first is None:
                return {"reason": "no_hello"}
            env = OmniEnvelope.from_wire(first)
            if env.event_type != SESSION_START:
                await send_json(OmniEnvelope(event_type=OUTPUT_ERROR, session_id="",
                                             payload={"error": "expect_session_start"},
                                             ).to_wire())
                return {"reason": "expect_session_start"}

            want_resume = str(env.payload.get("resume_session_id") or "")
            existing = self.sessions.get(want_resume)
            now = time.time()
            if existing and not existing.closed and existing.detached_at and \
                    (now - existing.detached_at) <= self.resume_grace_s:
                session = existing
                session.detached_at = 0.0
                self.resumed += 1
                await send_json(OmniEnvelope(
                    event_type=SESSION_RESUMED, session_id=session.session_id,
                    sequence=session.tracker.note_outbound(),
                    payload={"resumed": True,
                             "last_sequence": session.tracker.out_seq},
                ).to_wire())
            else:
                sid = env.payload.get("session_id") or env.session_id or uuid.uuid4().hex[:12]
                chain = await self._build_chain(sid)
                session = HubSession(chain, sid)
                self.sessions[sid] = session
                await send_json(OmniEnvelope(
                    event_type=SESSION_READY, session_id=session.session_id,
                    sequence=session.tracker.note_outbound(),
                    payload={"mode": env.payload.get("mode", "full_duplex"),
                             "backend": getattr(chain.omni, "backend_name", ""),
                             "audio": {"sample_rate": 16000, "format": "pcm_f32",
                                       "channels": 1},
                             "video": {"default_fps": 10, "max_fps": 30},
                             "motion_events_only": True,
                             "resume_grace_s": self.resume_grace_s},
                ).to_wire())

            session.send = send_json
            if session.pump_task is None or session.pump_task.done():
                session.pump_task = asyncio.create_task(session.pump_outputs())

            # ---------- 主循环 ----------
            while True:
                raw = await recv_json()
                if raw is None:
                    break
                env = OmniEnvelope.from_wire(raw)
                rep = session.tracker.accept(env)
                if not rep.accepted:
                    session.counters["dropped"] += 1
                    self.rejected += 1
                    continue
                session.counters["in"] += 1
                if env.event_type in (INPUT_TEXT, INPUT_AUDIO, INPUT_VIDEO,
                                      INPUT_MOTION, INPUT_WORLD):
                    await self._apply_input(session, env)
                elif env.event_type in (CONTROL_INTERRUPT, CONTROL_CANCEL,
                                        CONTROL_RESUME, CONTROL_CLOSE):
                    await self._apply_control(session, env)
                    if env.event_type == CONTROL_CLOSE:
                        break
        finally:
            if session is not None and not session.closed:
                session.detached_at = time.time()
                session.send = None
            if on_close is not None:
                try:
                    await on_close()
                except Exception:
                    pass
        return session.snapshot() if session else {}

    # ---------- 输入分发 ----------
    async def _apply_input(self, session: HubSession, env: OmniEnvelope) -> None:
        chain = session.chain
        p = env.payload or {}
        if env.event_type == INPUT_TEXT:
            await chain.send_text(str(p.get("text") or ""), speaker_id=env.speaker_id)
        elif env.event_type == INPUT_AUDIO:
            import base64
            import numpy as np
            b64 = p.get("audio") or ""
            pcm = (np.frombuffer(base64.b64decode(b64), dtype="<f4")
                   if b64 else np.zeros(0, dtype=np.float32))
            await chain.send_audio(pcm, sample_rate=int(p.get("sample_rate") or 16000),
                                   speaker_id=env.speaker_id,
                                   is_speech=p.get("is_speech"))
        elif env.event_type == INPUT_VIDEO:
            await chain.send_video(p.get("frame") or p.get("data"),
                                   kind=str(p.get("kind") or "keyframe"),
                                   source=str(p.get("source") or "quest_camera"),
                                   speaker_id=env.speaker_id,
                                   frame_id=int(p.get("frame_id") or 0),
                                   meta=p.get("meta") or {})
        elif env.event_type == INPUT_MOTION:
            # 动捕：只有事件与摘要会进 Omni（chain 里已有闸门）
            summary = p.get("summary")
            for ev in (p.get("events") or []):
                await chain.send_world_event("motion", {"motion_event": ev}, priority=20,
                                             source="quest_motion")
            if summary:
                await chain.send_world_event("motion", {"motion_summary": summary},
                                             priority=10, source="quest_motion")
        elif env.event_type == INPUT_WORLD:
            await chain.send_world_event(str(p.get("kind") or "world_state"),
                                         p.get("payload") or {},
                                         priority=int(p.get("priority") or 0),
                                         source=str(p.get("source") or "quest"))

    async def _apply_control(self, session: HubSession, env: OmniEnvelope) -> None:
        session.counters["control"] += 1
        if env.event_type == CONTROL_INTERRUPT:
            await session.chain.omni.interrupt(str(env.payload.get("reason") or "user_barge_in"))
            await session.emit(OUTPUT_LISTEN, {"reason": "interrupted"}, speaker_id="qiyu")
        elif env.event_type == CONTROL_CANCEL:
            await session.chain.omni.cancel()
            await session.emit(OUTPUT_DONE, {"reason": "cancelled"}, speaker_id="qiyu")
        elif env.event_type == CONTROL_CLOSE:
            session.closed = True
            try:
                await session.chain.stop()
            except Exception:
                pass
            await session.emit(SESSION_CLOSED, {"reason": "client_close"}, speaker_id="qiyu")
            if session.pump_task is not None:
                session.pump_task.cancel()
        # CONTROL_RESUME：会话本来就还在（断线期间未销毁），这里只回执
        elif env.event_type == CONTROL_RESUME:
            await session.emit(SESSION_RESUMED, {"resumed": True}, speaker_id="qiyu")

    def stats(self) -> dict:
        return {"connections": self.connections, "active": len(self.sessions),
                "resumed": self.resumed, "rejected": self.rejected,
                "sessions": {k: v.snapshot() for k, v in self.sessions.items()}}
