"""Quest WebSocket Gateway。

P0：hello/heartbeat/echo/bye/session/world_state。
P1：WorldState 进入 WorldStateStore；`on_user_text` 接入 Qiyu MessageGateway；
    每轮对话以独立 asyncio task 执行，因此回合进行中仍可接收 barge_in，
    新一轮输入会取消旧一轮，符合语音对话的实时语义。

Gateway 自身不实现 Agent/LLM，只做协议、会话与转发。
"""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from fastapi import WebSocket
from loguru import logger

from qiyu_quest_gateway.audio import (
    AudioError,
    pcm16_to_wav,
    synthesize_pcm16,
    transcribe_pcm16,
)
from qiyu_quest_gateway.binary_frame import (
    BinaryFrameError,
    KIND_AUDIO_IN_PCM16,
    KIND_TTS_OUT_PCM16,
    KIND_VISION_JPEG,
    pack_frame,
    unpack_frame,
)
from qiyu_quest_gateway.protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    Envelope,
    EnvelopeError,
)
from qiyu_quest_gateway.session import QuestSession, SessionRegistry
from qiyu_quest_gateway.models import (
    AutonomyRequest,
    BehaviorState,
    CharacterState,
    HumanMotionSnapshot,
    InteractionEvent,
    WorldState,
)
from qiyu_quest_gateway.world_state import WorldStateStore

UserTextHandler = Callable[[QuestSession, str, dict], Awaitable[dict]]
BargeInHandler = Callable[[QuestSession], Awaitable[None]]
VisionHandler = Callable[[QuestSession, bytes, dict, str], Awaitable[dict]]
AutonomyHandler = Callable[[QuestSession, dict], Awaitable[dict]]
InteractionHandler = Callable[[QuestSession, dict], Awaitable[None]]


class QuestWebSocketGateway:
    """Quest 入口。业务回调由 quest_server 注入现有 Qiyu 链路。"""

    def __init__(
        self, *, handshake_timeout_s: float = 10.0,
        heartbeat_timeout_s: float = 20.0,
    ) -> None:
        self.registry = SessionRegistry()
        self.world_states = WorldStateStore()
        self.handshake_timeout_s = handshake_timeout_s
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.on_user_text: Optional[UserTextHandler] = None
        self.on_barge_in: Optional[BargeInHandler] = None
        self.on_vision_query: Optional[VisionHandler] = None
        self.on_autonomy_request: Optional[AutonomyHandler] = None
        self.on_interaction_event: Optional[InteractionHandler] = None

    async def handle_ws(self, ws: WebSocket) -> None:
        await ws.accept()
        session: Optional[QuestSession] = None
        try:
            first_item = await asyncio.wait_for(
                self._receive_any(ws), timeout=self.handshake_timeout_s)
            if not isinstance(first_item, Envelope) or first_item.type != "client.hello":
                await self._send(ws, None, self._error(
                    None, "handshake_required", "第一条消息必须是 client.hello"))
                await ws.close(code=4400)
                return
            first = first_item
            session = await self._handle_hello(ws, first)
            await self._send(
                ws, session,
                first.reply(
                    "server.hello_ack",
                    {
                        "session_id": session.session_id,
                        "protocol_version": PROTOCOL_VERSION,
                        "supported_protocol_versions": sorted(SUPPORTED_PROTOCOL_VERSIONS),
                        "capabilities": {
                            "p0": ["hello", "heartbeat", "echo", "world_state"],
                            "p1": ["user.text", "user.voice_transcript", "barge_in",
                                   "agent.speech", "avatar.intent", "spatial.action"],
                            "p4": ["vision_frame_meta", "vision_query",
                                   "server.object_detection"],
                            "world_state_v1": True,
                            "avatar_intent_v1": True,
                            "spatial_action_v1": True,
                            "character_schema_v1_1": True,
                            "behavior_state_v1_1": True,
                            "interaction_events_v1_1": True,
                            "autonomy_request_v1_1": True,
                            "world_state_delta_v1_1": True,
                            "human_motion_state_v1_1": True,
                            "user_body_v1": True,
                        },
                    },
                    session=session.session_id,
                ),
            )

            while True:
                item = await self._receive_any(ws)
                if item is None:
                    break
                if isinstance(item, bytes):
                    await self._handle_binary(ws, session, item)
                    continue
                msg = item
                if msg.session != session.session_id:
                    await self._send_error(ws, session, "invalid_session",
                                           "session 与当前连接不一致")
                    break
                if not self._track_sequence(session, msg):
                    continue
                if msg.type == "client.heartbeat":
                    self.registry.touch(session.session_id)
                    await self._send(ws, session, msg.reply(
                        "server.heartbeat", {"pong": True}, session=session.session_id))
                    continue
                if msg.type == "client.echo":
                    self.registry.touch(session.session_id)
                    await self._send(ws, session, msg.reply(
                        "server.echo", dict(msg.payload), session=session.session_id))
                    continue
                if msg.type == "client.world_state":
                    await self._handle_world_state(ws, session, msg)
                    continue
                if msg.type == "client.world_state_delta":
                    await self._handle_world_state_delta(ws, session, msg)
                    continue
                if msg.type == "client.behavior_state":
                    await self._handle_behavior_state(ws, session, msg)
                    continue
                if msg.type == "client.character_state":
                    await self._handle_character_state(ws, session, msg)
                    continue
                if msg.type == "client.interaction_event":
                    await self._handle_interaction_event(ws, session, msg)
                    continue
                if msg.type == "client.human_motion_state":
                    await self._handle_human_motion_state(ws, session, msg)
                    continue
                if msg.type == "client.user_body":
                    await self._handle_user_body(ws, session, msg)
                    continue
                if msg.type in ("user.text", "user.voice_transcript"):
                    await self._handle_user_text(ws, session, msg)
                    continue
                if msg.type == "user.audio_end":
                    await self._handle_audio_end(ws, session, msg)
                    continue
                if msg.type == "client.tts_config":
                    session.tts_enabled = bool(msg.payload.get("enabled", True))
                    await self._send(ws, session, msg.reply(
                        "server.ack", {"tts_enabled": session.tts_enabled},
                        session=session.session_id))
                    continue
                if msg.type == "client.vision_frame_meta":
                    session.vision_meta = dict(msg.payload)
                    await self._send(ws, session, msg.reply(
                        "server.ack", {"vision_meta": True},
                        session=session.session_id))
                    continue
                if msg.type == "client.vision_query":
                    await self._handle_vision_query(ws, session, msg)
                    continue
                if msg.type == "client.barge_in":
                    self.registry.touch(session.session_id)
                    self._cancel_turn(session)
                    if session.autonomy_task is not None and not session.autonomy_task.done():
                        session.autonomy_task.cancel()
                    session.autonomy_task = None
                    session.barge_in_epoch += 1
                    if self.on_barge_in is not None:
                        try:
                            await self.on_barge_in(session)
                        except Exception as e:
                            logger.warning(f"[QuestGateway] barge_in 回调异常: {e}")
                    await self._send(ws, session, msg.reply(
                        "server.ack", {"barge_in": True}, session=session.session_id))
                    continue
                if msg.type == "client.autonomy_request":
                    await self._handle_autonomy_request(ws, session, msg)
                    continue
                if msg.type == "client.bye":
                    self._cancel_turn(session)
                    await self._send(ws, session, msg.reply(
                        "server.ack", {"ok": True}, session=session.session_id))
                    break
                await self._send_error(ws, session, "unsupported_type",
                                       f"未实现消息类型: {msg.type}")
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
                self._cancel_turn(session)
                if session.autonomy_task is not None and not session.autonomy_task.done():
                    session.autonomy_task.cancel()
                session.autonomy_task = None
                self.registry.drop(session.session_id)
                self.world_states.drop(session.session_id)
            try:
                await ws.close()
            except Exception:
                pass

    async def _handle_world_state(self, ws: WebSocket, session: QuestSession,
                                  msg: Envelope) -> None:
        try:
            validated = WorldState.model_validate(dict(msg.payload))
        except Exception as e:
            await self._send_error(ws, session, "bad_world_state",
                                   f"WorldState schema 校验失败: {e}")
            return
        raw_debug = (msg.payload or {}).get("debug_passthrough")
        if isinstance(raw_debug, dict):
            logger.info(f"[QuestGateway] passthrough_debug={raw_debug}")
        normalized = validated.model_dump(mode="json")
        session.world_state_updates += 1
        if session.world_state_updates <= 2:
            _log_world_state_diagnostics(logger, normalized)
        self.registry.update_world_state(session.session_id, normalized)
        self.world_states.update(session.session_id, normalized)
        rev = normalized.get("scene_version", 0)
        await self._send(ws, session, msg.reply(
            "server.ack",
            {"accepted": True, "scene_version": rev, "schema_version": normalized.get("schema_version", "1.0")},
            session=session.session_id))

    async def _handle_world_state_delta(self, ws: WebSocket, session: QuestSession,
                                        msg: Envelope) -> None:
        """应用 WorldState 增量；失败时要求客户端重发全量，绝不猜缺失几何。"""
        payload = msg.payload or {}
        current = session.world_state or self.world_states.get(session.session_id)
        if not isinstance(current, dict):
            await self._send_error(ws, session, "world_state_base_missing",
                                   "收到增量但没有可用的全量 WorldState")
            return
        base = int(payload.get("base_scene_version") or 0)
        current_rev = int(current.get("scene_version") or 0)
        if base and base != current_rev:
            await self._send_error(
                ws, session, "world_state_revision_mismatch",
                f"增量基于 {base}，本地为 {current_rev}；请重发全量 WorldState")
            return
        changed = payload.get("changed")
        if not isinstance(changed, dict):
            await self._send_error(ws, session, "bad_world_state_delta",
                                   "changed 必须是对象")
            return
        merged = _apply_world_state_delta(current, changed, payload)
        try:
            validated = WorldState.model_validate(merged)
        except Exception as e:
            await self._send_error(ws, session, "bad_world_state_delta",
                                   f"增量合并后 schema 校验失败: {e}")
            return
        normalized = validated.model_dump(mode="json")
        self.registry.update_world_state(session.session_id, normalized)
        self.world_states.update(session.session_id, normalized)
        await self._send(ws, session, msg.reply(
            "server.ack",
            {"accepted": True, "scene_version": normalized.get("scene_version", 0), "delta": True},
            session=session.session_id))

    async def _handle_behavior_state(self, ws: WebSocket, session: QuestSession,
                                     msg: Envelope) -> None:
        try:
            validated = BehaviorState.model_validate(dict(msg.payload))
        except Exception as e:
            await self._send_error(ws, session, "bad_behavior_state", str(e))
            return
        normalized = validated.model_dump(mode="json")
        self.registry.update_behavior_state(session.session_id, normalized)
        await self._send(ws, session, msg.reply(
            "server.ack", {"accepted": True, "behavior": normalized.get("active_behavior", "")},
            session=session.session_id))

    async def _handle_character_state(self, ws: WebSocket, session: QuestSession,
                                      msg: Envelope) -> None:
        try:
            validated = CharacterState.model_validate(dict(msg.payload))
        except Exception as e:
            await self._send_error(ws, session, "bad_character_state", str(e))
            return
        normalized = validated.model_dump(mode="json")
        self.registry.update_character_state(session.session_id, normalized)
        await self._send(ws, session, msg.reply(
            "server.ack", {"accepted": True}, session=session.session_id))

    async def _handle_interaction_event(self, ws: WebSocket, session: QuestSession,
                                        msg: Envelope) -> None:
        try:
            validated = InteractionEvent.model_validate(dict(msg.payload))
        except Exception as e:
            await self._send_error(ws, session, "bad_interaction_event", str(e))
            return
        normalized = validated.model_dump(mode="json")
        session.last_interaction_event = normalized
        session.interaction_events += 1
        if self.on_interaction_event is not None:
            try:
                await self.on_interaction_event(session, normalized)
            except Exception as e:
                logger.warning(f"[QuestGateway] interaction_event 回调异常: {e}")
        await self._send(ws, session, msg.reply(
            "server.ack",
            {"accepted": True, "event_type": normalized.get("event_type", "")},
            session=session.session_id))

    async def _handle_human_motion_state(self, ws: WebSocket, session: QuestSession,
                                         msg: Envelope) -> None:
        """5–15Hz 压缩 motion 状态：只存不发 ACK，避免把上行带宽变成 ACK 风暴。"""
        try:
            validated = HumanMotionSnapshot.model_validate(dict(msg.payload))
        except Exception as e:
            await self._send_error(ws, session, "bad_human_motion_state", str(e))
            return
        session.human_motion_state = validated.model_dump(mode="json")
        session.human_motion_updates += 1

    async def _handle_user_body(self, ws: WebSocket, session: QuestSession,
                                msg: Envelope) -> None:
        """兼容 Quest 端既有 5 点用户身体上传；静默存储，不制造 ACK 风暴。"""
        payload = msg.payload or {}
        if not isinstance(payload, dict):
            await self._send_error(ws, session, "bad_user_body", "payload 必须是对象")
            return
        session.user_body = dict(payload)
        session.user_body_updates += 1

    async def _handle_autonomy_request(self, ws: WebSocket, session: QuestSession,
                                       msg: Envelope) -> None:
        """本地自主行为请求一次低频主动表达；服务端可以保持沉默。"""
        try:
            request = AutonomyRequest.model_validate(dict(msg.payload))
        except Exception as e:
            await self._send_error(ws, session, "bad_autonomy_request", str(e))
            return
        if self.on_autonomy_request is None:
            await self._send(ws, session, msg.reply(
                "server.autonomy_result",
                {"accepted": False, "reason": "autonomy_not_attached"},
                session=session.session_id))
            return
        task = session.autonomy_task
        if task is not None and not task.done():
            await self._send(ws, session, msg.reply(
                "server.autonomy_result",
                {"accepted": False, "reason": "autonomy_busy"},
                session=session.session_id))
            return
        session.autonomy_task = asyncio.create_task(
            self._run_autonomy_request(ws, session, msg, request))

    async def _run_autonomy_request(self, ws: WebSocket, session: QuestSession,
                                    request_msg: Envelope,
                                    request: AutonomyRequest) -> None:
        try:
            result = await self.on_autonomy_request(
                session, request.model_dump(mode="json")) if self.on_autonomy_request else {}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("[QuestGateway] autonomy request 失败")
            await self._send_error(ws, session, "autonomy_failed", str(e))
            return
        session.last_autonomy_at = time.time()
        result = dict(result or {})
        pieces = result.get("pieces") or []
        text = str(result.get("text") or "")
        if not pieces and text:
            pieces = [{"text": text, "type": "statement", "delay": 0}]
        if not text and not pieces:
            await self._send(ws, session, request_msg.reply(
                "server.autonomy_result",
                {"accepted": False, "reason": "stayed_silent"},
                session=session.session_id))
            return
        await self._send(ws, session, request_msg.reply(
            "server.autonomy_result",
            {"accepted": True, "response_id": result.get("response_id", "")},
            session=session.session_id))
        await self._emit_turn(ws, session, request_msg, result, session.barge_in_epoch)

    async def _handle_user_text(self, ws: WebSocket, session: QuestSession,
                                msg: Envelope) -> None:
        self.registry.touch(session.session_id)
        text = _extract_user_text(msg)
        if not text:
            await self._send_error(ws, session, "empty_user_text", "用户文本为空")
            return
        await self._start_turn(ws, session, msg, text)

    async def _handle_audio_end(self, ws: WebSocket, session: QuestSession,
                                msg: Envelope) -> None:
        """上行音频结束：复用 Qiyu STT 转写后再进入同一 BrainPipeline。"""
        payload = msg.payload or {}
        sample_rate = int(payload.get("sample_rate") or session.audio_buffer.sample_rate)
        pcm = session.audio_buffer.take()
        if not pcm:
            await self._send_error(ws, session, "audio_empty", "未收到任何音频帧")
            return
        if len(pcm) < 3200:  # 0.1s @16k mono
            await self._send_error(ws, session, "audio_too_short", "音频过短")
            return
        text = await transcribe_pcm16(pcm, sample_rate)
        if not text:
            await self._send_error(ws, session, "stt_empty",
                                   "STT 未识别出文本（不编造用户说了什么）")
            return
        await self._send(ws, session, msg.reply(
            "server.voice_transcript",
            {"text": text, "final": True, "engine": "qiyu-stt"},
            session=session.session_id))
        request = Envelope(
            "user.voice_transcript", {"text": text}, id=msg.id,
            session=session.session_id)
        await self._start_turn(ws, session, request, text)

    async def _handle_vision_query(self, ws: WebSocket, session: QuestSession,
                                   msg: Envelope) -> None:
        if self.on_vision_query is None:
            await self._send_error(ws, session, "vision_not_attached",
                                   "当前 Gateway 未挂接视觉识别回调")
            return
        frame = session.latest_vision_frame
        if not frame:
            await self._send_error(ws, session, "vision_frame_missing",
                                   "尚未收到 vision 二进制帧")
            return
        meta = dict(session.vision_meta or {})
        prompt = str(msg.payload.get("prompt") or "")
        try:
            result = await self.on_vision_query(session, frame, meta, prompt)
        except Exception as e:
            logger.warning(f"[QuestGateway] 视觉识别失败: {e}")
            await self._send_error(ws, session, "vision_failed", str(e))
            return
        await self._send(ws, session, msg.reply(
            "server.object_detection",
            dict(result or {}),
            session=session.session_id))
        # 如果这次识别是为某个待回答的问题触发的，用识别结果重跑同一问题
        if session.pending_vision_text:
            pending_text = session.pending_vision_text
            pending_request = session.pending_vision_request or msg
            session.pending_vision_text = ""
            session.pending_vision_request = None
            await self._start_turn(
                ws, session, pending_request, pending_text,
                extra_meta={"vision_objects": dict(result or {})})

    async def _start_turn(self, ws: WebSocket, session: QuestSession,
                          request: Envelope, text: str,
                          extra_meta: Optional[dict] = None) -> None:
        if self.on_user_text is None:
            await self._send_error(ws, session, "brain_not_attached",
                                   "当前 Gateway 尚未挂接 Qiyu BrainPipeline")
            return
        # 新一轮输入 = 对上一轮的隐式打断
        self._cancel_turn(session)
        session.barge_in_epoch += 1
        epoch = session.barge_in_epoch
        session.turn_task = asyncio.create_task(
            self._run_turn(ws, session, request, text, epoch, extra_meta or {}))

    async def _run_turn(self, ws: WebSocket, session: QuestSession, request: Envelope,
                        text: str, epoch: int, extra_meta: dict) -> None:
        try:
            meta = {"source": request.type, "payload": dict(request.payload)}
            meta.update(extra_meta)
            result = await self.on_user_text(
                session, text, meta)
        except asyncio.CancelledError:
            logger.info(f"[QuestGateway] 回合被取消(session={session.session_id})")
            raise
        except Exception as e:
            logger.exception("[QuestGateway] Quest 回合处理失败")
            if epoch == session.barge_in_epoch:
                await self._send_error(ws, session, "quest_turn_failed", str(e))
            return
        if epoch != session.barge_in_epoch:
            logger.info(f"[QuestGateway] 回合结果过期丢弃(session={session.session_id})")
            return
        await self._emit_turn(ws, session, request, result or {}, epoch)
        await self._maybe_request_vision(ws, session, request, text, result or {})

    async def _maybe_request_vision(self, ws: WebSocket, session: QuestSession,
                                    request: Envelope, user_text: str,
                                    result: dict) -> None:
        """BrainDecision 判定需要视觉时，向 Quest 请求一帧 Passthrough 图像。"""
        if not result.get("need_vision"):
            return
        session.pending_vision_text = str(user_text or "")
        session.pending_vision_request = request
        await self._send(ws, session, request.reply(
            "server.vision_request",
            {
                "reason": "brain_need_vision",
                "prompt": str(result.get("vision_query") or user_text or ""),
                "response_id": result.get("response_id"),
            },
            session=session.session_id))

    def _cancel_turn(self, session: QuestSession) -> None:
        task = session.turn_task
        if task is not None and not task.done():
            task.cancel()
        session.turn_task = None

    def _track_sequence(self, session: QuestSession, msg: Envelope) -> bool:
        """检测重复/乱序/缺口；重复消息不重复执行业务。"""
        if msg.ack:
            session.client_ack = max(session.client_ack, msg.ack)
        if msg.seq <= 0:
            return True
        if msg.id in session.recent_event_id_set:
            session.duplicate_client_events += 1
            return False
        if session.last_client_seq and msg.seq > session.last_client_seq + 1:
            session.dropped_client_events += msg.seq - session.last_client_seq - 1
        if msg.seq < session.last_client_seq:
            # 旧包只记录，不再触发业务；缺口由客户端重发全量状态修复。
            session.dropped_client_events += 1
            return False
        session.last_client_seq = max(session.last_client_seq, msg.seq)
        session.recent_event_ids.append(msg.id)
        session.recent_event_id_set.add(msg.id)
        while len(session.recent_event_ids) > 256:
            old = session.recent_event_ids.pop(0)
            session.recent_event_id_set.discard(old)
        return True

    async def _emit_turn(self, ws: WebSocket, session: QuestSession,
                         request: Envelope, result: dict, epoch: int) -> None:
        """把一轮 Qiyu 结果按协议 v1 回推 Quest。"""
        response_id = str(result.get("response_id") or request.id)
        pieces = result.get("pieces") or []
        text = str(result.get("text") or "")
        if not pieces and text:
            pieces = [{"text": text, "type": "statement", "delay": 0}]
        await self._send(ws, session, request.reply(
            "agent.speech",
            {
                "response_id": response_id,
                "text": text,
                "pieces": pieces,
                "final": True,
                "interrupted": False,
            },
            session=session.session_id,
        ))

        avatar_intent = result.get("avatar_intent")
        if isinstance(avatar_intent, dict):
            await self._send(ws, session, request.reply(
                "avatar.intent", avatar_intent, session=session.session_id))

        spatial_action = result.get("spatial_action")
        if isinstance(spatial_action, dict):
            await self._send(ws, session, request.reply(
                "spatial.action", spatial_action, session=session.session_id))

        if session.tts_enabled and text:
            await self._stream_tts(ws, session, request, response_id, pieces,
                                   avatar_intent, epoch)

    async def _stream_tts(self, ws: WebSocket, session: QuestSession,
                          request: Envelope, response_id: str, pieces: list,
                          avatar_intent: Optional[dict], epoch: int) -> None:
        """逐段合成并推送 TTS PCM16；被打断时立即停止并告知客户端。"""
        prosody = {}
        if isinstance(avatar_intent, dict) and isinstance(avatar_intent.get("prosody"), dict):
            prosody = dict(avatar_intent["prosody"])
        params = {
            "speed": _clamp(prosody.get("rate"), 0.5, 2.0, 1.0),
            "pitch": _clamp(prosody.get("pitch"), 0.5, 2.0, 1.0),
        }
        seq = 0
        try:
            for index, piece in enumerate(pieces):
                if epoch != session.barge_in_epoch:
                    return
                piece_text = str((piece or {}).get("text") or "").strip()
                if not piece_text:
                    continue
                try:
                    synth = await synthesize_pcm16(piece_text, **params)
                except AudioError as e:
                    logger.warning(f"[QuestGateway] TTS 失败: {e}")
                    await self._send(ws, session, request.reply(
                        "server.error",
                        {"code": "tts_failed", "message": str(e)},
                        session=session.session_id))
                    return
                pcm = synth["pcm"]
                await self._send(ws, session, request.reply(
                    "audio.tts_start",
                    {
                        "response_id": response_id,
                        "piece_index": index,
                        "format": "pcm_s16le",
                        "sample_rate": synth["sample_rate"],
                        "channels": synth["channels"],
                        "total_bytes": len(pcm),
                        "duration_ms": synth["duration_ms"],
                        "engine": synth["engine"],
                        "text": piece_text,
                    },
                    session=session.session_id))
                for offset in range(0, len(pcm), 8192):
                    if epoch != session.barge_in_epoch:
                        return
                    await self._send_bytes(
                        ws, session,
                        pack_frame(KIND_TTS_OUT_PCM16, seq,
                                   pcm[offset:offset + 8192]))
                    seq += 1
                    await asyncio.sleep(0)
                await self._send(ws, session, request.reply(
                    "audio.tts_end",
                    {
                        "response_id": response_id,
                        "piece_index": index,
                        "final": index == len(pieces) - 1,
                        "interrupted": False,
                    },
                    session=session.session_id))
        except asyncio.CancelledError:
            try:
                await self._send(ws, session, request.reply(
                    "audio.tts_end",
                    {"response_id": response_id, "interrupted": True, "final": False},
                    session=session.session_id))
            except Exception:
                pass
            raise

    async def _handle_hello(self, ws: WebSocket, msg: Envelope) -> QuestSession:
        p = msg.payload or {}
        if str(msg.v) not in SUPPORTED_PROTOCOL_VERSIONS:
            raise EnvelopeError(f"unsupported_protocol_version:{msg.v}")
        user_id = str(p.get("user_id") or p.get("userId") or "").strip()
        char_id = str(p.get("char_id") or p.get("charId") or "").strip()
        if not user_id or not char_id:
            logger.warning(
                f"[QuestGateway] invalid_hello payload_keys={sorted(p.keys())} "
                f"payload={p}")
            await self._send_error(ws, None, "invalid_hello", "user_id 与 char_id 必填")
            raise EnvelopeError("invalid_hello")
        caps = p.get("capabilities")
        if isinstance(caps, dict):
            capability_payload = dict(caps)
        elif isinstance(caps, list):
            capability_payload = {"features": [str(c) for c in caps]}
        else:
            capability_payload = {}
        return self.registry.create(
            user_id=user_id,
            char_id=char_id,
            device=str(p.get("device") or ""),
            client_version=str(p.get("client_version") or ""),
            protocol_version=str(msg.v),
            capabilities=capability_payload,
            remote=ws.client.host if ws.client else "",
        )

    async def _handle_binary(self, ws: WebSocket, session: QuestSession,
                             data: bytes) -> None:
        try:
            frame = unpack_frame(data)
        except BinaryFrameError as e:
            await self._send_error(ws, session, "bad_binary_frame", str(e))
            return
        if frame.kind == KIND_AUDIO_IN_PCM16:
            if session.audio_buffer.duration_s() > 30.0:
                session.audio_buffer.clear()
                await self._send_error(ws, session, "audio_too_long",
                                       "单次上行音频超过 30 秒，已丢弃")
                return
            session.audio_buffer.append(frame.payload)
            return
        if frame.kind == KIND_VISION_JPEG:
            session.latest_vision_frame = frame.payload
            return
        await self._send_error(ws, session, "unsupported_binary_kind",
                               f"未知二进制帧类型: {frame.kind}")

    async def _receive_any(self, ws: WebSocket):
        """返回 Envelope（文本帧）或 bytes（二进制帧），超时/断开返回 None。"""
        try:
            message = await asyncio.wait_for(ws.receive(), timeout=self.heartbeat_timeout_s)
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
        if message.get("type") == "websocket.disconnect":
            return None
        if message.get("bytes") is not None:
            return message["bytes"]
        raw = message.get("text")
        if raw is None:
            return None
        try:
            return Envelope.from_text(raw)
        except EnvelopeError as e:
            await self._send_error(ws, None, "bad_envelope", str(e))
            return None

    async def _send_error(self, ws: WebSocket, session: Optional[QuestSession],
                          code: str, message: str) -> None:
        await self._send(ws, session, self._error(session, code, message))

    @staticmethod
    def _error(session: Optional[QuestSession], code: str, message: str) -> Envelope:
        return Envelope(
            "server.error",
            {"code": code, "message": message},
            session=session.session_id if session else None,
        )

    async def _send(self, ws: WebSocket, session: Optional[QuestSession],
                    envelope: Envelope) -> None:
        if session is not None:
            if not envelope.seq:
                session.last_server_seq += 1
                envelope.seq = session.last_server_seq
            if not envelope.ack:
                envelope.ack = session.client_ack
            async with session.send_lock:
                await ws.send_text(envelope.to_json())
        else:
            await ws.send_text(envelope.to_json())

    async def _send_bytes(self, ws: WebSocket, session: Optional[QuestSession],
                          data: bytes) -> None:
        if session is not None:
            async with session.send_lock:
                await ws.send_bytes(data)
        else:
            await ws.send_bytes(data)


def _apply_world_state_delta(current: dict, changed: dict, payload: dict) -> dict:
    """合并 WorldState 增量。只接受显式结构，不做模糊猜测。"""
    merged = dict(current or {})
    if "scene_version" in payload:
        merged["scene_version"] = payload.get("scene_version")
    if "ts" in payload:
        merged["ts"] = payload.get("ts")
    if "world_epoch" in payload:
        merged["world_epoch"] = payload.get("world_epoch")
    if "status" in changed:
        merged["status"] = changed.get("status")
    if "room_id" in changed:
        merged["room_id"] = changed.get("room_id")

    if isinstance(changed.get("user"), dict):
        merged["user"] = _deep_merge_dict(merged.get("user") or {}, changed["user"])
    if isinstance(changed.get("avatar"), dict):
        merged["avatar"] = _deep_merge_dict(merged.get("avatar") or {}, changed["avatar"])
    if isinstance(changed.get("navmesh"), dict):
        merged["navmesh"] = _deep_merge_dict(merged.get("navmesh") or {}, changed["navmesh"])
    if isinstance(changed.get("interaction"), dict):
        merged["interaction"] = _deep_merge_dict(
            merged.get("interaction") or {}, changed["interaction"])

    if isinstance(changed.get("anchors"), list):
        merged["anchors"] = list(changed["anchors"])
    if isinstance(changed.get("objects"), list):
        merged["objects"] = list(changed["objects"])
    if isinstance(changed.get("anchors_upsert"), list):
        merged["anchors"] = _upsert_by_id(merged.get("anchors") or [], changed["anchors_upsert"])
    if isinstance(changed.get("objects_upsert"), list):
        merged["objects"] = _upsert_by_id(merged.get("objects") or [], changed["objects_upsert"])
    if isinstance(changed.get("anchors_remove"), list):
        remove = {str(x) for x in changed["anchors_remove"]}
        merged["anchors"] = [x for x in (merged.get("anchors") or []) if str(x.get("id") or "") not in remove]
    if isinstance(changed.get("objects_remove"), list):
        remove = {str(x) for x in changed["objects_remove"]}
        merged["objects"] = [x for x in (merged.get("objects") or []) if str(x.get("id") or "") not in remove]

    merged["schema_version"] = str(payload.get("schema_version") or "1.1")
    return merged


def _deep_merge_dict(base: dict, patch: dict) -> dict:
    out = dict(base or {})
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_dict(out[key], value)
        else:
            out[key] = value
    return out


def _upsert_by_id(items: list, patches: list) -> list:
    out = [dict(x) for x in items if isinstance(x, dict)]
    index = {str(x.get("id") or ""): i for i, x in enumerate(out)}
    for raw in patches:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "")
        if not item_id:
            continue
        if item_id in index:
            out[index[item_id]] = _deep_merge_dict(out[index[item_id]], raw)
        else:
            index[item_id] = len(out)
            out.append(dict(raw))
    return out


def _log_world_state_diagnostics(logger, world_state: dict) -> None:
    """一次性输出真实房间几何诊断，用于 NavMesh/空间行为验收。"""
    try:
        anchors = world_state.get("anchors") or []
        floors = [a for a in anchors if str(a.get("label") or "") == "floor"]
        nav = world_state.get("navmesh") or {}
        logger.info(
            f"[QuestGateway] world_diag scene={world_state.get('scene_version')} "
            f"room={world_state.get('room_id')} anchors={len(anchors)} "
            f"floors={len(floors)} navmesh_area={nav.get('walkable_area_m2')}")
        for floor in floors[:2]:
            pose = floor.get("pose") or {}
            rotation = pose.get("rotation") or {}
            extents = floor.get("extents") or {}
            bounds = floor.get("bounds") or {}
            logger.info(
                f"[QuestGateway] floor_diag id={floor.get('id')} "
                f"rot=({rotation.get('x')},{rotation.get('y')},"
                f"{rotation.get('z')},{rotation.get('w')}) "
                f"extents=({extents.get('x')},{extents.get('y')},"
                f"{extents.get('z')}) "
                f"bounds={bounds}")
    except Exception as e:
        logger.warning(f"[QuestGateway] world_diag failed: {e}")


def _extract_user_text(msg: Envelope) -> str:
    payload = msg.payload or {}
    for key in ("text", "transcript", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _clamp(value, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


__all__ = ["QuestWebSocketGateway"]
