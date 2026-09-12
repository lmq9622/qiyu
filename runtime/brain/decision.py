# -*- coding: utf-8 -*-
"""Qiyu Runtime · BrainDecision（内部控制数据，绝不直接展示给用户）。

P0：所有消息先经 MiniMind，MiniMind 产出/参与产出的唯一内部决策结构。
字段与用户规格一致；to_internal() 只给 Pipeline / MainBrain / 日志消费。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrainDecision:
    mode: str = "main"                 # direct / main / tool / vision / fallback_main
    need_main_brain: bool = True
    need_tool: bool = False
    need_vision: bool = False
    topic: str = ""
    previous_topic: str = ""
    topic_transition: str = "continue"  # continue / natural / abrupt / repeat_recent
    topic_age: float = 0.0
    unfinished: bool = False
    intent: str = ""
    intent_summary: str = ""
    memory_hint: str = ""
    memory_relevance: float = 0.0
    emotion: dict = field(default_factory=dict)
    emotion_delta: dict = field(default_factory=dict)
    patience: float = 0.0
    patience_delta: int = 0
    relationship: str = ""
    relationship_delta: int = 0
    candidate_reply: str = ""
    confidence: float = 0.0
    reason: str = ""
    response_mode: str = ""       # single / immediate_then_final / none
    immediate_reaction: str = ""
    mainbrain_required: bool = True
    tool_query: str = ""
    vision_query: str = ""
    voice_emotion: str = ""
    voice_intensity: float = 0.0
    avatar_emotion: str = ""
    avatar_intensity: float = 0.0
    proactive_allowed: bool = True
    storycheck_allowed: bool = True
    model: str = ""
    backend: str = ""
    mini_ran: bool = False
    mini_error: str = ""
    meta: dict = field(default_factory=dict)

    def to_internal(self) -> dict:
        """转内部 dict。仅 MainBrain/日志/QA 使用，严禁进客户端消息。"""
        return {
            "mode": self.mode,
            "need_main_brain": bool(self.need_main_brain),
            "need_tool": bool(self.need_tool),
            "need_vision": bool(self.need_vision),
            "topic": str(self.topic or ""),
            "previous_topic": str(self.previous_topic or ""),
            "topic_transition": str(self.topic_transition or "continue"),
            "topic_age": round(float(self.topic_age or 0.0), 2),
            "unfinished": bool(self.unfinished),
            "intent": str(self.intent or ""),
            "intent_summary": str(self.intent_summary or ""),
            "memory_hint": str(self.memory_hint or ""),
            "memory_relevance": round(float(self.memory_relevance or 0.0), 3),
            "emotion": dict(self.emotion or {}),
            "emotion_delta": dict(self.emotion_delta or {}),
            "patience": round(float(self.patience or 0.0), 2),
            "patience_delta": int(self.patience_delta or 0),
            "relationship": str(self.relationship or ""),
            "relationship_delta": int(self.relationship_delta or 0),
            "candidate_reply": str(self.candidate_reply or ""),
            "confidence": round(float(self.confidence or 0.0), 3),
            "reason": str(self.reason or ""),
            "response_mode": str(self.response_mode or ""),
            "immediate_reaction": str(self.immediate_reaction or ""),
            "mainbrain_required": bool(self.mainbrain_required),
            "tool_query": str(self.tool_query or ""),
            "vision_query": str(self.vision_query or ""),
            "voice_emotion": str(self.voice_emotion or ""),
            "voice_intensity": round(float(self.voice_intensity or 0.0), 2),
            "avatar_emotion": str(self.avatar_emotion or ""),
            "avatar_intensity": round(float(self.avatar_intensity or 0.0), 2),
            "proactive_allowed": bool(self.proactive_allowed),
            "storycheck_allowed": bool(self.storycheck_allowed),
            "model": str(self.model or ""),
            "backend": str(self.backend or ""),
            "mini_ran": bool(self.mini_ran),
            "mini_error": str(self.mini_error or ""),
        }


def decision_to_main_context(d: BrainDecision) -> str:
    """MiniMind 压缩理解 → MainBrain 直接使用的内部上下文块。"""
    lines = ["【MiniMind 预判（内部，已读，不必重新推断）】"]
    if d.topic:
        lines.append(f"- 话题：{d.topic}")
    if d.topic_transition:
        lines.append(f"- 话题状态：{d.topic_transition}")
    if d.intent_summary:
        lines.append(f"- 用户意图：{d.intent_summary}")
    if d.memory_hint:
        lines.append(f"- 相关记忆提示：{d.memory_hint}")
    if d.emotion:
        try:
            lines.append(f"- 情绪上下文：{d.emotion}")
        except Exception:
            pass
    if d.need_tool:
        lines.append("- 判断需要工具/搜索，最终内容必须以真实工具结果为准。")
    if d.need_vision:
        lines.append("- 判断需要视觉/图片输入。")
    return "\n".join(lines)


__all__ = ["BrainDecision", "decision_to_main_context"]
