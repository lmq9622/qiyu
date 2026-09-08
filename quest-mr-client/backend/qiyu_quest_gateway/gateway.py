"""Quest WebSocket Gateway（P0：hello/heartbeat/echo/bye/session/world_state 暂存）。"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import WebSocket
from loguru import logger

from qiyu_quest_gateway.protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    Envelope,
    EnvelopeError,
)
from qiyu_quest_gateway.session import QuestSession, SessionRegistry
from qiyu_quest_gateway.models import WorldState


class QuestWebSocketGateway:
    """P0 Gateway。

    不接入 BrainPipeline，避免 P0 假连大脑；仅验证 Quest 连接、协议、
    session、heartbeat 和 WorldState 暂存。后续阶段把 brain 回调注入
    `self.on_user_message` 后即可让 Quest 语音进入现有 MessageGateway。
    """

    def __init__(
        self,
        *,
        handshake_timeout_s: float = 10.0,
        heartbeat_timeout_s: float = 20.0,
    ) -> None:
        self.registry = SessionRegistry()
        self.handshake_timeout_s = handshake_timeout_s
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.on_user_message: Optional[callable] = None

    async def handle_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        session: Optional[QuestSession] = None
        try:
            first = await asyncio.wait_for(self._receive(ws), timeout=self.handshake_timeout_s)
            if first is None or first.type != "client.hello":
                await self._send_error(ws, None, "handshake_required", "第一条消息必须是 client.hello")
                await ws.close(code=4400)
                return
            session = await self._handle_hello(ws, first)
            await self._send(
                ws,
                first.reply(
                    "server.hello_ack",
                    {
                        "session_id": session.session_id,
                        "protocol_version": PROTOCOL_VERSION,
                        "supported_protocol_versions": sorted(SUPPORTED_PROTOCOL_VERSIONS),
                        "capabilities": {
                            "p0": ["hello", "heartbeat", "echo", "world_state"],
                            "world_state_v1": True,
                            "avatar_intent_v1": True,
                            "spatial_action_v1": True,
                        },
                    },
                    session=session.session_id,
                ),
            )

            while True:
                msg = await self._receive(ws)
                if msg is None:
                    break
                if msg.session != session.session_id:
                    await self._send_error(ws, session, "invalid_session",
                                           "session 与当前连接不一致")
                    break
                if msg.type == "client.heartbeat":
                    self.registry.touch(session.session_id)
                    await self._send(ws, msg.reply("server.heartbeat", {"pong": True}, session=session.session_id))
                    continue
                if msg.type == "client.echo":
                    self.registry.touch(session.session_id)
                    await self._send(ws, msg.reply("server.echo", dict(msg.payload), session=session.session_id))
                    continue
                if msg.type == "client.world_state":
                    try:
                        validated = WorldState.model_validate(dict(msg.payload))
                    except Exception as e:
                        await self._send_error(ws, session, "bad_world_state",
                                               f"WorldState schema 校验失败: {e}")
                        continue
                    normalized = validated.model_dump(mode="json")
                    self.registry.update_world_state(session.session_id, normalized)
                    rev = normalized.get("scene_version", 0)
                    await self._send(
                        ws,
                        msg.reply("server.ack", {"accepted": True, "scene_version": rev},
                                  session=session.session_id),
                    )
                    continue
                if msg.type == "user.text":
                    if self.on_user_message is None:
                        await self._send_error(ws, session, "brain_not_attached",
                                               "当前 Gateway 尚未挂接 Qiyu BrainPipeline")
                    else:
                        await self.on_user_message(ws, session, msg)
                    continue
                if msg.type == "client.bye":
                    await self._send(ws, msg.reply("server.ack", {"ok": True}, session=session.session_id))
                    break
                await self._send_error(ws, session, "unsupported_type",
                                       f"P0 未实现消息类型: {msg.type}")
        except asyncio.TimeoutError:
            await self._send_error(ws, session, "handshake_timeout", "等待 client.hello 超时")
        except Exception as e:
            logger.warning(f"[QuestGateway] connection error: {e}")
            try:
                await self._send_error(ws, session, "internal_error", str(e))
            except Exception:
                pass
        finally:
            if session is not None:
                self.registry.drop(session.session_id)
            try:
                await ws.close()
            except Exception:
                pass

    async def _handle_hello(self, ws: WebSocket, msg: Envelope) -> QuestSession:
        p = msg.payload or {}
        if str(msg.v) not in SUPPORTED_PROTOCOL_VERSIONS:
            raise EnvelopeError(f"unsupported_protocol_version:{msg.v}")
        user_id = str(p.get("user_id") or "").strip()
        char_id = str(p.get("char_id") or "").strip()
        if not user_id or not char_id:
            await self._send_error(ws, None, "invalid_hello", "user_id 与 char_id 必填")
            raise EnvelopeError("invalid_hello")
        caps = p.get("capabilities")
        if isinstance(caps, dict):
            capability_payload = dict(caps)
        elif isinstance(caps, list):
            capability_payload = {"features": [str(c) for c in caps]}
        else:
            capability_payload = {}
        session = self.registry.create(
            user_id=user_id,
            char_id=char_id,
            device=str(p.get("device") or ""),
            client_version=str(p.get("client_version") or ""),
            protocol_version=str(msg.v),
            capabilities=capability_payload,
            remote=ws.client.host if ws.client else "",
        )
        return session

    async def _receive(self, ws: WebSocket) -> Optional[Envelope]:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=self.heartbeat_timeout_s)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        try:
            return Envelope.from_text(raw)
        except EnvelopeError as e:
            await self._send_error(ws, None, "bad_envelope", str(e))
            return None

    async def _send_error(
        self,
        ws: WebSocket,
        session: Optional[QuestSession],
        code: str,
        message: str,
    ) -> None:
        await self._send(
            ws,
            Envelope(
                "server.error",
                {"code": code, "message": message},
                session=session.session_id if session else None,
            ),
        )

    async def _send(self, ws: WebSocket, envelope: Envelope) -> None:
        await ws.send_text(envelope.to_json())
