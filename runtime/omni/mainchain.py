# -*- coding: utf-8 -*-
"""正式主链：Realtime Omni 作为唯一认知入口。

    Audio / Video / Text / WorldEvent / MotionEvent
                    |
              Realtime Omni  (IRealtimeOmni -> OmniSession -> MiniCPMOBackend)
                    |
        +-----------+-----------+
        |                       |
   Conversation            AvatarIntent
   (流式文本/音频)          (封闭行为名，绝不含骨骼)
                                |
                        Behavior Policy v1
                                |
                        Utility / Reflex
                                |
                           Quest Avatar

复杂任务才走深推理：

    Realtime Omni -> DeepReasoningBackend -> 结果回注 Omni Session

约束（规格 B / G / K）：
- **MiniMind 运行时默认不参与**：由 ``runtime/legacy_gate.py`` 把关，
  这里只做状态读取，绝不在主链里调用它；
- AvatarIntent 只能取 ``AvatarIntentName`` 里的值，出界即拒绝；
- 动捕**只以事件 + 摘要**进入 Omni，绝不转发每帧骨骼。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from runtime.omni.types import (
    AudioChunk, AvatarIntent, AvatarIntentName, ConversationOutput, EventKind,
    FrameKind, HumanInteractionEvent, SpeakerId, VideoFrame, WorldEvent,
)

FORBIDDEN_INTENT_KEYS = ("bone", "bones", "transform", "ik", "footstep",
                         "animator", "joint", "pose_matrix", "skeleton")


def avatar_intent_to_behavior_request(intent: AvatarIntent) -> dict:
    """AvatarIntent -> Behavior Policy 的请求（协议 v1.1 兼容，无骨骼）。"""
    return {
        "type": "avatar_intent",
        "intent": intent.intent,
        "target": intent.target,
        "emotion": intent.emotion,
        "urgency": round(float(intent.urgency), 3),
        "attention": intent.attention,
        "behavior_style": intent.style,
        "reason": intent.reason,
        "ts": intent.timestamp,
        "source": "realtime_omni",
    }


@dataclass
class ChainStats:
    text_in: int = 0
    audio_in: int = 0
    video_in: int = 0
    world_events_in: int = 0
    motion_frames_in: int = 0
    motion_events_to_omni: int = 0
    motion_summaries_to_omni: int = 0
    conversation_out: int = 0
    audio_out: int = 0
    intents_out: int = 0
    intents_rejected: int = 0
    deep_reasoning_calls: int = 0
    started_at: float = 0.0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["uptime_s"] = round(time.time() - self.started_at, 1) if self.started_at else 0.0
        return d


class OmniMainChain:
    """把 Omni 会话 + 动捕聚合 + AvatarIntent 路由 串成正式主链。"""

    def __init__(self, omni=None, backend: str = "minicpm_ws",
                 motion=None, shared_attention=None,
                 on_conversation: Optional[Callable[[ConversationOutput], Awaitable[None]]] = None,
                 on_intent: Optional[Callable[[dict], Awaitable[None]]] = None,
                 on_event: Optional[Callable[[dict], Awaitable[None]]] = None,
                 deep_reasoning: Optional[Callable[..., Awaitable[dict]]] = None,
                 config=None):
        self._omni_injected = omni is not None
        self.omni = omni
        self.backend_name = backend
        self.config = config
        self.motion = motion
        self.shared_attention = shared_attention
        self.on_conversation = on_conversation
        self.on_intent = on_intent
        self.on_event = on_event
        self.deep_reasoning_fn = deep_reasoning
        self.stats = ChainStats()
        self._last_motion_forward = 0.0
        self._pump_task: Optional[asyncio.Task] = None
        self._closed = False
        self.recent_intents: list = []
        self.recent_conversation: list = []

    # ---------- 生命周期 ----------
    async def start(self, config=None) -> str:
        if self.omni is None:
            from runtime.omni.registry import get_registry
            from runtime.omni.session import OmniSession
            backend = get_registry().select(prefer=self.backend_name)
            if backend is None:
                raise RuntimeError(
                    f"没有可用的 Omni 后端（prefer={self.backend_name!r}）"
                    "；真实链路需要本机 llama-omni-server，测试可注入 MockOmniBackend")
            self.omni = OmniSession(backend=backend)
        sid = await self.omni.start_session(config or self.config)
        self.stats.started_at = time.time()
        return sid

    async def stop(self) -> None:
        self._closed = True
        if self._pump_task is not None:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except (asyncio.CancelledError, Exception):
                pass
        if self.omni is not None:
            try:
                await self.omni.close()
            except Exception:
                pass

    def legacy_status(self) -> dict:
        """旧小脑（MiniMind）状态：默认 disabled，主链不调用。"""
        try:
            from runtime import legacy_gate
            return legacy_gate.status()
        except Exception as e:
            return {"minimind_enabled": False, "error": str(e)}

    # ---------- 输入 ----------
    async def send_text(self, text: str, speaker_id: str = SpeakerId.LOCAL_USER.value) -> None:
        self.stats.text_in += 1
        await self.omni.send_text(text, speaker_id=speaker_id)

    async def send_audio(self, pcm, sample_rate: int = 16000,
                         speaker_id: str = SpeakerId.LOCAL_USER.value,
                         is_speech: Optional[bool] = None) -> None:
        self.stats.audio_in += 1
        await self.omni.send_audio_chunk(AudioChunk(
            pcm=pcm, sample_rate=sample_rate, speaker_id=speaker_id, is_speech=is_speech))

    async def send_video(self, data, *, kind: str = FrameKind.KEYFRAME.value,
                         source: str = "quest_camera", speaker_id: str = "",
                         frame_id: int = 0, meta: Optional[dict] = None) -> None:
        self.stats.video_in += 1
        await self.omni.send_video_frame(VideoFrame(
            data=data, kind=kind, source=source, speaker_id=speaker_id,
            frame_id=frame_id, meta=meta or {}))

    async def send_world_event(self, kind: str = EventKind.WORLD_STATE.value,
                               payload: Optional[dict] = None, priority: int = 0,
                               source: str = "quest") -> None:
        self.stats.world_events_in += 1
        await self.omni.send_world_event(WorldEvent(
            kind=kind, payload=payload or {}, priority=priority, source=source))

    async def ingest_motion(self, state, force: bool = False) -> dict:
        """本地 30~60Hz 喂进来；只有事件/摘要才会真的进 Omni。"""
        if self.motion is None:
            return {"forwarded": False, "reason": "no_motion_aggregator"}
        self.stats.motion_frames_in += 1
        new_events = self.motion.ingest(state)
        now = state.timestamp or time.time()
        due = (now - self._last_motion_forward) >= 1.0
        if not new_events and not due and not force:
            return {"forwarded": False, "pending_events": 0}
        payload = self.motion.to_omni_payload()
        forwarded_events = []
        for ev in payload["events"]:
            self.stats.motion_events_to_omni += 1
            forwarded_events.append(ev)
            await self.omni.send_motion_event(HumanInteractionEvent(
                name=ev["name"], confidence=ev["confidence"],
                target=ev.get("target", "avatar"), payload=ev.get("payload") or {},
                timestamp=ev.get("timestamp", now)))
        if payload.get("summary"):
            self.stats.motion_summaries_to_omni += 1
            await self.omni.send_world_event(WorldEvent(
                kind=EventKind.MOTION.value, payload={"motion_summary": payload["summary"]},
                priority=10, source="quest_motion"))
        self._last_motion_forward = now
        return {"forwarded": True, "events": forwarded_events,
                "event_count": len(payload["events"]),
                "summary": payload.get("summary") is not None}

    async def send_shared_attention(self, snapshot=None) -> None:
        snap = snapshot or (self.shared_attention.snapshot() if self.shared_attention else None)
        if snap is None:
            return
        data = snap.to_dict() if hasattr(snap, "to_dict") else dict(snap)
        await self.omni.send_world_event(WorldEvent(
            kind=EventKind.SHARED_ATTENTION.value, payload={"shared_attention": data},
            priority=30, source="quest_attention"))

    # ---------- 输出 ----------
    async def _dispatch(self, event) -> None:
        kind = getattr(event, "kind", "")
        conv = getattr(event, "conversation", None)
        intent = getattr(event, "avatar_intent", None)
        if conv is not None:
            self.stats.conversation_out += 1
            if getattr(conv, "audio", None) is not None:
                self.stats.audio_out += 1
            self.recent_conversation = (self.recent_conversation + [conv.text])[-10:]
            if self.on_conversation is not None:
                await self.on_conversation(conv)
        if intent is not None:
            payload = avatar_intent_to_behavior_request(intent)
            bad = [k for k in FORBIDDEN_INTENT_KEYS if k in payload]
            allowed = {n.value for n in AvatarIntentName}
            if bad or intent.intent not in allowed:
                self.stats.intents_rejected += 1
                if self.on_event is not None:
                    await self.on_event({"type": "intent_rejected",
                                         "reason": "forbidden_key" if bad else "unknown_intent",
                                         "payload": payload})
                return
            self.stats.intents_out += 1
            self.recent_intents = (self.recent_intents + [payload])[-10:]
            if self.on_intent is not None:
                await self.on_intent(payload)
        if self.on_event is not None and conv is None and intent is None:
            await self.on_event({"type": "omni_event", "kind": kind,
                                 "payload": getattr(event, "payload", {}) or {}})

    async def pump(self, duration_s: Optional[float] = None) -> int:
        """消费 Omni 输出并路由到「话」与「AvatarIntent」。"""
        n = 0
        deadline = (time.time() + duration_s) if duration_s else None
        async for event in self.omni.receive_event():
            await self._dispatch(event)
            n += 1
            if deadline is not None and time.time() >= deadline:
                break
        return n

    def start_pump(self) -> None:
        if self._pump_task is None:
            self._pump_task = asyncio.create_task(self.pump())

    # ---------- 复杂任务 ----------
    async def deep_reasoning(self, text: str, context: Optional[dict] = None) -> dict:
        """复杂任务才调用深推理（MainBrain / DeepReasoningBackend）。"""
        if self.deep_reasoning_fn is None:
            return {"available": False,
                    "reason": "未注入 DeepReasoningBackend（MainBrain 侧适配未接）"}
        self.stats.deep_reasoning_calls += 1
        result = await self.deep_reasoning_fn(text, context or {})
        return {"available": True, "result": result}

    async def maybe_deep_reason(self, text: str,
                                context: Optional[dict] = None) -> dict:
        """只有判定为「复杂任务」才真的调用深推理；否则明确说明跳过。"""
        gate = getattr(self.deep_reasoning_fn, "is_complex", None)
        if gate is not None and not gate(text, context):
            return {"available": True, "invoked": False, "reason": "simple_request"}
        out = await self.deep_reasoning(text, context)
        out["invoked"] = out.get("available", False)
        return out

    # ---------- 状态 ----------
    def stats_dict(self) -> dict:
        d = self.stats.to_dict()
        d["backend"] = getattr(self.omni, "backend_name", self.backend_name)
        d["omni_state"] = getattr(self.omni, "state", "")
        d["legacy"] = self.legacy_status().get("minimind_enabled")
        d["motion"] = self.motion.stats_dict() if self.motion is not None else None
        d["attention"] = (self.shared_attention.stats_dict()
                          if self.shared_attention is not None else None)
        return d
