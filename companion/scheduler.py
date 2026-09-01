# -*- coding: utf-8 -*-
"""Qiyu 主动消息调度器（Proactive Scheduler，M4）。

规格（十八/十九/二十/三十五/三十六）：
禁止简单 Timer → Generate；必须由
Scheduler + Context + Memory + Recent conversation + Last topic + Relationship
+ User activity + Duplicate detection + Cooldown 共同决定是否打扰用户。

主动消息先判断「现在适不适合打扰」：冷却未到 / 正在聊天 / 耐心不足 / 意愿低 /
有未完成任务 / 心情差 / 概率未命中 → 一律取消本次主动消息。
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass

from companion.state import _proactive_store
from companion.relations import (_char_share_boost, _init_relation, _is_night,
                                 _proactive_day_prob, _proactive_night_prob,
                                 _save_proactive)
from companion.conv import _context_gate, _conv_state
from companion.emotions import _mood_is_great
from companion.behavior import _topic_similarity


@dataclass
class ProactiveDecision:
    """调度器的单次决策结果。"""
    allowed: bool
    reason: str = ""            # 拦截原因（cooldown / context_gate / probability / ok）
    night: bool = False
    probability: float = 0.0    # 本次是否命中的概率（仅诊断用）


class ProactiveScheduler:
    """主动消息调度器：综合冷却 / 上下文门 / 关系 / 耐心 / 心情 / 概率决定是否打扰。"""

    BASE_COOLDOWN = 1500     # 25 分钟基础冷却
    MIN_COOLDOWN = 1200      # 关系很好时的最短冷却
    CONV_COOLDOWN = 3600     # 刚结束一场对话后的冷却（§36）

    @staticmethod
    def key(user_id: str, char_id: str) -> str:
        return f"{user_id}::{char_id}"

    def cooldown_seconds(self, user_id: str, char_id: str, now: float | None = None) -> float:
        """动态冷却（§36）：基础 25 分钟；刚结束对话 → 延长到 1 小时；关系好 → 可稍短。"""
        now = now or time.time()
        cooldown = float(self.BASE_COOLDOWN)
        cs = _conv_state(user_id, char_id)
        ended_at = float(cs.get("ended_at") or 0)
        if ended_at and now - ended_at < 1800:
            cooldown = max(cooldown, float(self.CONV_COOLDOWN))
        rel = _init_relation(user_id, char_id)
        affinity = int(rel.get("affinity", 50) or 50)
        if affinity >= 70:
            cooldown = min(cooldown, float(self.MIN_COOLDOWN))
        return cooldown

    def duplicate_detected(self, user_id: str, char_id: str, text: str) -> bool:
        """§19：与上次主动消息语义过相似（换说法也认），禁止重复发送。"""
        if not text:
            return False
        prev_text = ((_proactive_store.get(self.key(user_id, char_id)) or {}).get("last_text") or "").strip()
        return bool(prev_text and _topic_similarity(prev_text, text) > 0.6)

    def evaluate(self, user_id: str, char_id: str, now: float | None = None) -> ProactiveDecision:
        """完整判断现在适不适合主动打扰用户。"""
        if not user_id or not char_id:
            return ProactiveDecision(False, reason="no_user_or_char")
        now = now or time.time()
        # 1) 冷却：未到冷却时间一律不主动
        last = (_proactive_store.get(self.key(user_id, char_id)) or {}).get("last_at") or 0
        if now - last < self.cooldown_seconds(user_id, char_id, now):
            return ProactiveDecision(False, reason="cooldown")
        # 2) Context Gate：正在聊天 / 冷却 / 耐心不足 / 意愿低 / 有未完成任务
        allowed, reason = _context_gate(user_id, char_id, now)
        if not allowed:
            return ProactiveDecision(False, reason=reason or "context_gate")
        # 3) 概率：好感度驱动 + 人设加成 + 心情加成（心情差已被 Context Gate 拦截）
        rel = _init_relation(user_id, char_id)
        affinity = int(rel.get("affinity", 50) or 50)
        night = _is_night()
        prob = _proactive_night_prob(affinity) if night else _proactive_day_prob(affinity)
        prob = min(0.9, prob + _char_share_boost(char_id) + (0.2 if _mood_is_great(user_id, char_id) else 0.0))
        if random.random() > prob:
            return ProactiveDecision(False, reason="probability", night=night, probability=prob)
        return ProactiveDecision(True, reason="ok", night=night, probability=prob)

    def record_attempt(self, user_id: str, char_id: str) -> None:
        """触发主动生成前登记时间（无论生成是否成功都进入冷却，避免失败后立刻重试）。"""
        _proactive_store[self.key(user_id, char_id)] = {"last_at": time.time()}
        _save_proactive()

    def record_sent(self, user_id: str, char_id: str, text: str) -> None:
        """真正发送后登记文本，供下次重复检测使用。"""
        entry = dict(_proactive_store.get(self.key(user_id, char_id)) or {})
        entry["last_at"] = time.time()
        entry["last_text"] = (text or "")[:200]
        _proactive_store[self.key(user_id, char_id)] = entry
        _save_proactive()


proactive_scheduler = ProactiveScheduler()


__all__ = [
    "ProactiveDecision",
    "ProactiveScheduler",
    "proactive_scheduler",
]
