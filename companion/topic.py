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
    surprise: float = 0.0        # 0~1：相对上一话题的突变程度
    confidence: float = 0.0      # 0~1：当前话题确认度
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "current": self.current,
            "previous": self.previous,
            "transition": self.transition,
            "surprise": round(self.surprise, 3),
            "confidence": round(self.confidence, 3),
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
        surprise=surprise,
        confidence=confidence,
        updated_at=float(cs.get("updated_at") or 0.0),
    )


def _update_topic_state(user_id: str, char_id: str, *, current: str = "",
                        previous: str = "", transition: str = "none",
                        surprise: float = 0.0, confidence: float = 0.0) -> None:
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
    try:
        cs["last_topic_confidence"] = max(0.0, min(1.0, float(confidence or 0.0)))
    except Exception:
        pass
    cs["last_topic_shift"] = transition == "abrupt"
    cs["updated_at"] = time.time()
    _save_conv_store()


__all__ = [
    "TopicState",
    "_topic_state",
    "_update_topic_state",
]
