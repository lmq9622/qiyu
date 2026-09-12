# -*- coding: utf-8 -*-
"""Qiyu 话题状态机（Topic State，M4）。

规格（十六）：模型不能无脑跟着用户话题，必须维护
current_topic / previous_topic / topic_transition / topic_surprise / topic_confidence。

用户突然从 A 跳到 B、又跳回刚聊完的 A 时：
- 不自动「哦我来回忆一下」，而是像真人一样「你咋又问这个？」；
- 话题变化分 none / natural / contextual / abrupt，只有 abrupt 才可能产生惊讶反应。

本模块把话题状态收敛为正式 TopicState，并持久化到 conv_state（每用户×角色独立）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from companion.conv import _conv_state, _save_conv_store


@dataclass
class TopicState:
    """单个(用户,角色)的话题状态。"""
    current: str = ""            # 当前话题
    previous: str = ""           # 上一个话题
    transition: str = "none"     # none / natural / contextual / abrupt
    status: str = "none"         # continue / natural / abrupt / repeat_recent / no_context
    transition_score: float = 0.0
    surprise: float = 0.0        # 0~1：相对上一话题的突变程度
    confidence: float = 0.0      # 0~1：当前话题确认度
    topic_age: float = 0.0       # 距上一个话题的秒数（0 表示无）
    unfinished: str = ""         # 未完成话题
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "current": self.current,
            "previous": self.previous,
            "transition": self.transition,
            "status": self.status,
            "transition_score": round(self.transition_score, 3),
            "surprise": round(self.surprise, 3),
            "confidence": round(self.confidence, 3),
            "topic_age": round(self.topic_age, 1),
            "unfinished": self.unfinished,
            "updated_at": round(self.updated_at, 3),
        }


def _topic_state(user_id: str, char_id: str) -> TopicState:
    """读取当前(用户,角色)的话题状态（无则返回空状态，不落库）。"""
    if not user_id or not char_id:
        return TopicState()
    cs = _conv_state(user_id, char_id)
    try:
        surprise = float(cs.get("topic_surprise") or 0.0)
    except Exception:
        surprise = 0.0
    try:
        confidence = float(cs.get("last_topic_confidence") or 0.0)
    except Exception:
        confidence = 0.0
    return TopicState(
        current=(cs.get("last_topic") or "").strip(),
        previous=(cs.get("previous_topic") or "").strip(),
        transition=str(cs.get("topic_transition") or "none"),
        status=str(cs.get("topic_status") or "none"),
        transition_score=float(cs.get("topic_transition_score") or 0.0),
        surprise=surprise,
        confidence=confidence,
        topic_age=float(cs.get("topic_age") or 0.0),
        unfinished=(cs.get("unfinished_topic") or "").strip(),
        updated_at=float(cs.get("updated_at") or 0.0),
    )


def _update_topic_state(user_id: str, char_id: str, *, current: str = "",
                        previous: str = "", transition: str = "none",
                        surprise: float = 0.0, confidence: float = 0.0,
                        status: str = "none", transition_score: float = 0.0,
                        topic_age: float = 0.0, unfinished: str = "") -> None:
    """持久化话题状态到 conv_state（分类结果由 behavior 层算出后传入，避免二次误分类）。"""
    if not user_id or not char_id:
        return
    cs = _conv_state(user_id, char_id)
    if previous:
        cs["previous_topic"] = previous[:80]
    if current:
        cs["last_topic"] = current[:80]
    cs["topic_transition"] = transition or "none"
    cs["topic_surprise"] = max(0.0, min(1.0, float(surprise or 0.0)))
    cs["topic_transition_score"] = max(0.0, float(transition_score or 0.0))
    cs["topic_age"] = float(topic_age or 0.0)
    cs["topic_status"] = str(status or transition or "none")
    if unfinished:
        cs["unfinished_topic"] = unfinished[:120]
    try:
        cs["last_topic_confidence"] = max(0.0, min(1.0, float(confidence or 0.0)))
    except Exception:
        pass
    cs["last_topic_shift"] = transition == "abrupt"
    cs["updated_at"] = time.time()
    _save_conv_store()


def _topic_signal(user_id: str, char_id: str, user_input: str) -> TopicState:
    """输入到达 Brain 前做一次话题信号判定（v0.0.27）。

    返回 TopicState；status 至少包含：
    continue / natural / abrupt / repeat_recent / no_context
    """
    import difflib
    now = time.time()
    base = _topic_state(user_id, char_id)
    cs = _conv_state(user_id, char_id)
    base.unfinished = (cs.get("unfinished_topic") or "").strip()
    if not user_input:
        return base

    def _sim(a, b):
        return difflib.SequenceMatcher(None, a or "", b or "").ratio()

    hist = []
    try:
        from memory import get_memory_manager
        hist = get_memory_manager().get_recent_history(user_id, limit=10, char_id=char_id) or []
    except Exception:
        pass
    # 找出当前输入之前的最后一条用户消息
    prev_user = ""
    prev_user_ts = 0.0
    seen_current = False
    for m in reversed(hist):
        if m.get("role") != "user":
            continue
        if not seen_current:
            seen_current = True
            continue
        prev_user = str(m.get("content") or "").strip()
        try:
            import datetime as _dt
            prev_user_ts = _dt.datetime.fromisoformat(str(m.get("timestamp") or "")[:19]).timestamp()
        except Exception:
            pass
        break
    sim_to_prev = _sim(prev_user, user_input)
    age = (now - prev_user_ts) if prev_user_ts else 0.0
    base.topic_age = round(age, 1)
    base.transition_score = round(1.0 - sim_to_prev, 3)

    # 1) 重复刚问过的话题：前一条用户消息高度相似且 1 小时内
    if prev_user and sim_to_prev >= 0.35 and 0 < age <= 3600:
        base.status = "repeat_recent"
        base.transition = "repeat_recent"
        base.previous = prev_user[:80]
        base.surprise = round(min(1.0, 0.35 + age / 3600 * 0.4), 3)
        return base
    # 2) 与最近记录的事实高度相似（换说法重复刚说过的事）
    try:
        facts = cs.get("recent_facts") or []
        for f in facts:
            if now - float(f.get("ts") or 0) <= 3600 and _sim(f.get("text", ""), user_input) >= 0.55:
                base.status = "repeat_recent"
                base.transition = "repeat_recent"
                base.previous = (f.get("text") or "")[:80]
                return base
    except Exception:
        pass
    # 3) 正常延续
    if base.current and _sim(base.current, user_input) >= 0.45:
        base.status = "continue"
        base.transition = "none"
        base.surprise = 0.0
        return base
    # 4) 明显突兀（上一条用户消息还在新鲜期内且几乎无共同字符）
    if prev_user and sim_to_prev < 0.12 and 0 < age <= 3600:
        base.status = "abrupt"
        base.transition = "abrupt"
        base.previous = prev_user[:80]
        base.surprise = round(min(1.0, 0.5 + (1.0 - sim_to_prev) * 0.5), 3)
        return base
    # 4) 无上文/距离很远重新开话题
    if not prev_user and not base.current:
        base.status = "no_context"
        base.transition = "none"
        return base
    # 5) contextual / natural / abrupt 沿用行为层分类
    from companion.behavior import _classify_topic_shift
    kind, prev = _classify_topic_shift(user_id, char_id, user_input)
    base.status = kind if kind in ("abrupt", "natural", "contextual") else "natural"
    base.transition = base.status
    base.previous = (prev or base.previous)[:80]
    return base


__all__ = [
    "TopicState",
    "_topic_signal",
    "_topic_state",
    "_update_topic_state",
]
