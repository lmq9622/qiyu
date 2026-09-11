"""BehaviorBridge：把行为层接到某个 Quest 会话上。

职责：
- 组装 BrainContext（用户可见性、距离、座位、情绪、被锁通道）；
- 调用 BehaviorBrain 得到计划；
- 提交给 ActionRuntime 调度；
- 把计划/动作事件/状态快照通过注入的 send 回调发回 Quest。

这一层只依赖协议消息类型（字符串），不依赖 FastAPI/WebSocket 具体实现，
因此可以在测试里用一个 list 收集器完整跑通。
"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

from .adapters import QuestAdapter
from .brain import BrainContext, BehaviorBrain
from .models import BehaviorIntent, BehaviorPlan
from .plan import describe
from .registry import ActionRegistry, default_registry
from .runtime import ActionRuntime

SendFn = Callable[[str, dict], Awaitable[None]]


class BehaviorBridge:
    def __init__(self, send: SendFn,
                 registry: Optional[ActionRegistry] = None,
                 tick_hz: float = 8.0) -> None:
        self._send = send
        self.registry = registry or default_registry
        self.brain = BehaviorBrain(self.registry)
        self.adapter = QuestAdapter(send=None)
        self.runtime = ActionRuntime(adapter=self.adapter,
                                     registry=self.registry,
                                     on_event=self._on_event)
        self.tick_hz = tick_hz
        self.last_plan: Optional[BehaviorPlan] = None
        self.last_intent: str = ""
        self.last_rejection: str = ""
        self.turn_count: int = 0
        self.behavior_turn_count: int = 0
        self._events: list[tuple[Any, str]] = []
        self._last_state_sent_at: float = 0.0

    # ------------------------------------------------------------------ 对外
    async def apply_intent(self, intent: Optional[BehaviorIntent],
                           context: Optional[BrainContext] = None) -> Optional[BehaviorPlan]:
        """一轮对话结束后调用。返回 None 表示本轮不触发特殊行为。"""
        self.turn_count += 1
        self.last_intent = intent.intent if intent else ""
        plan = self.brain.plan(intent, context) if intent else None
        self.last_rejection = self.brain.last_rejection
        if plan is None:
            await self._flush()
            return None
        plan.request_id = f"turn-{self.turn_count}"
        self.last_plan = plan
        self.behavior_turn_count += 1
        self.runtime.submit_plan(plan)
        await self._send("server.behavior_plan", {
            "version": plan.version,
            "request_id": plan.request_id,
            "intent": plan.intent,
            "intensity": round(plan.intensity, 3),
            "reason": plan.reason,
            "plan": plan.root.model_dump(exclude_none=True),
            "describe": describe(plan.root),
        })
        await self._flush()
        return plan

    async def tick(self, dt: float) -> None:
        self.runtime.update(dt)
        await self._flush()
        now = time.time()
        if now - self._last_state_sent_at >= 0.5:
            self._last_state_sent_at = now
            await self._send("server.behavior_state", self.runtime.snapshot())

    async def cancel(self, reason: str = "barge_in") -> None:
        self.runtime.cancel_all(reason)
        await self._flush()
        await self._send("server.behavior_state", self.runtime.snapshot())

    async def flush(self) -> None:
        await self._flush()

    def snapshot(self) -> dict:
        return self.runtime.snapshot()

    # ------------------------------------------------------------------ 内部
    def _on_event(self, record: Any, event: str) -> None:
        self._events.append((record, event))

    async def _flush(self) -> None:
        while self.adapter.sent:
            envelope = self.adapter.sent.pop(0)
            await self._send(envelope["type"], envelope["payload"])
        while self._events:
            record, event = self._events.pop(0)
            await self._send("server.behavior_event", {
                "action": record.name,
                "action_id": record.action_id,
                "channel": record.channel,
                "state": record.state.value,
                "event": event,
                "reason": record.cancel_reason,
            })


def build_context(world_state: Optional[dict],
                  character_state: Optional[dict],
                  locked_channels: Optional[list[str]] = None,
                  has_seat: Optional[bool] = None) -> BrainContext:
    """从现有 WorldState / CharacterState 组装 BrainContext。"""
    ws = world_state if isinstance(world_state, dict) else {}
    cs = character_state if isinstance(character_state, dict) else {}
    interaction = ws.get("interaction") or {}
    user = ws.get("user") or {}
    navmesh = ws.get("navmesh") or {}
    anchors = ws.get("anchors") or []

    user_visible = bool(user.get("head")) or bool(ws.get("user_visible", False))
    distance = float(interaction.get("user_distance_m") or 1.2)
    if has_seat is None:
        labels = {str(a.get("label") or "").lower() for a in anchors
                  if isinstance(a, dict)}
        has_seat = any(label in {"chair", "couch", "sofa", "seat", "bench"}
                       for label in labels)
    emotion = (cs.get("emotion") or {}) if isinstance(cs, dict) else {}
    relationship = (cs.get("relationship") or {}) if isinstance(cs, dict) else {}
    speech = (cs.get("speech") or {}) if isinstance(cs, dict) else {}
    return BrainContext(
        user_visible=user_visible,
        user_distance_m=distance,
        has_seat=bool(has_seat),
        is_moving=bool(navmesh.get("agent_moving", False)),
        is_speaking=str(speech.get("state") or "") == "speaking",
        emotion=str(emotion.get("label") or "neutral"),
        emotion_intensity=float(emotion.get("intensity") or 0.0),
        relationship_tier=str(relationship.get("tier") or "acquaintance"),
        locked_channels=list(locked_channels or []),
    )
