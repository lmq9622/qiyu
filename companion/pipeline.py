# -*- coding: utf-8 -*-
"""Qiyu 多消息流水线 / 会话投入状态 / 动态冷却（规格§15/§17/§36）。

§15 多消息流水线：用户连续发 消息1..4，不能每条都单独完整推理。
- 第一条到达立即开始推理；后续消息进 pending queue；
- 下一次 prefill 把未处理用户消息作为结构化批次喂给模型（pending_messages）。
§17 故事聊天：conversation_engagement_state（听众是否在场）控制故事推进/等待/收尾。
§36 ConversationCooldown：聊天结束后短时间不突然新开话题，冷却随
  关系 / 耐心 / 聊天长度 / 用户活跃 动态变化。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from companion.conv import _conv_state
from companion.settings import _desire_value
from companion.relations import _clamp_int, _init_relation


class PendingMessageQueue:
    """每用户待处理消息队列（FIFO）。

    第一条消息到达即触发推理；随后到达的消息入队，下次 prefill 时整体取出，
    以 pending_messages 结构化批次交给模型，避免逐条重复推理。
    """

    def __init__(self) -> None:
        self._queues: dict[str, list] = {}

    def enqueue(self, user_id: str, msg: dict) -> None:
        self._queues.setdefault(user_id, []).append(msg)

    def drain(self, user_id: str) -> list:
        return self._queues.pop(user_id, [])

    def pending(self, user_id: str) -> list:
        return list(self._queues.get(user_id, []))

    def clear(self, user_id: str) -> None:
        self._queues.pop(user_id, None)


pending_queue = PendingMessageQueue()


def build_pending_messages_block(messages: list) -> str:
    """把多条未处理用户消息格式化成规格§15 的结构化批次（注入系统提示词）。"""
    if not messages:
        return ""
    lines = []
    for m in messages[:6]:
        text = (m.get("text") or "").strip()[:300]
        ts = m.get("timestamp") or 0
        lines.append(
            '{"id": "%s", "text": "%s", "timestamp": "%s"}'
            % (str(m.get("id") or "")[:24], _json_escape(text),
               time.strftime("%H:%M:%S", time.localtime(ts)) if ts else "")
        )
    return (
        "【用户连续发来了多条消息（不是多轮对话）】对方一口气发了下面几条，"
        "中间没有等你回复。把它们当成同一轮里连发的消息，综合回应，不要逐条重复回答：\n"
        "{\n  \"pending_messages\": [\n    " + ",\n    ".join(lines) + "\n  ]\n}"
    )


def _json_escape(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")


# ---------------- §17 会话投入状态（故事/长文聊天） ----------------
@dataclass
class EngagementState:
    state: str = "engaged"          # engaged / waiting / sleeping / ended
    since: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return {"state": self.state, "since": round(self.since, 3), "reason": self.reason}


def conversation_engagement_state(user_id: str, char_id: str, now: float | None = None) -> EngagementState:
    """判断听众是否还在场：角色讲故事/长文后，用户长时间没回 → 等待 → 收尾。

    由关系 / 耐心 / 氛围 / 时间 / 历史行为共同控制，不固定触发（规格§17）。
    """
    now = now or time.time()
    if not user_id or not char_id:
        return EngagementState("engaged", now)
    cs = _conv_state(user_id, char_id)
    last_u = float(cs.get("last_user_at") or 0)
    last_ai = float(cs.get("last_ai_at") or 0)
    story = bool(cs.get("story_active"))
    idle = now - max(last_u, last_ai) if (last_u or last_ai) else 0.0
    rel = _init_relation(user_id, char_id)
    aff = _clamp_int(rel.get("affinity"), 50)
    pat = _desire_value(user_id, char_id)
    if idle > 240 and story:
        return EngagementState("waiting", now, f"讲故事后用户 {int(idle//60)} 分钟没回")
    if idle > 600:
        if aff >= 70 and pat >= 60:
            return EngagementState("sleeping", now, "用户很久没回，关系允许温柔收尾")
        return EngagementState("ended", now, "用户长时间没回，不再自说自话")
    return EngagementState("engaged", now, "")


def engagement_prompt_block(user_id: str, char_id: str) -> str:
    """注入提示词的听众状态（只用于把握节奏，不展示给用户）。"""
    eg = conversation_engagement_state(user_id, char_id)
    if eg.state == "engaged":
        return ""
    if eg.state == "waiting":
        return ("【听众状态（内部）】你刚讲了一段/发了一长串，对方还没接话。"
                "别再继续铺内容，最多一句轻唤（喂？/睡着了？），然后停下等对方。")
    if eg.state == "sleeping":
        return ("【听众状态（内部）】对方很久没回了，像是不在。可以很轻地收个尾"
                "（晚安/那我先忙啦），但不要说教、不要自说自话一大段。")
    return ("【听众状态（内部）】对方很久没回，这场对话已经冷场。"
            "不要再继续输出内容；如果真要发，只允许一句很短的收尾。")

# ---------------- §36 ConversationCooldown（动态） ----------------
def conversation_cooldown_seconds(user_id: str, char_id: str, now: float | None = None) -> float:
    """聊天结束后的冷却：基础 1 小时，随 关系/耐心/聊天长度/活跃 动态调整。

    关系越好、耐心越高 → 冷却可缩短；聊得很长（话题投入深）→ 冷却反而拉长；
    用户一直很活跃 → 不适用冷却（本来就在聊）。
    """
    now = now or time.time()
    cs = _conv_state(user_id, char_id)
    last_u = float(cs.get("last_user_at") or 0)
    if last_u and now - last_u < 600:
        return 0.0  # 用户还在聊，不设冷却
    base = 3600.0
    rel = _init_relation(user_id, char_id)
    aff = _clamp_int(rel.get("affinity"), 50)
    pat = _desire_value(user_id, char_id)
    if aff >= 75:
        base = max(1500.0, base - 900.0)     # 很熟：30 分钟起
    elif aff <= 30:
        base = min(7200.0, base + 1800.0)    # 不熟：更久
    if pat < 35:
        base += 1200.0
    # 聊天长度：当天消息越多，说明刚聊得投入，别马上另起话题
    try:
        from memory import get_memory_manager
        n = get_memory_manager().day_message_count(user_id, char_id)
        if n >= 60:
            base += 1200.0
        elif n >= 20:
            base += 600.0
    except Exception:
        pass
    return min(7200.0, max(1200.0, base))


__all__ = [
    "EngagementState",
    "PendingMessageQueue",
    "build_pending_messages_block",
    "conversation_cooldown_seconds",
    "conversation_engagement_state",
    "engagement_prompt_block",
    "pending_queue",
]
