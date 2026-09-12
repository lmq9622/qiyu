# -*- coding: utf-8 -*-
"""本地意图规则：HumanInteractionEvent -> AvatarIntent 的兜底映射。

用在哪：真实模型后端（MiniCPM-o WS）目前只产出文本/音频，不产出结构化
``AvatarIntent``。既然「用户指了杯子 → Avatar 看过去」这种反应不应该等模型，
这里提供一条**规则兜底**：本地识别出的事件直接映射成封闭集合里的意图。

优先级：模型给出的 AvatarIntent > 本地规则兜底。
标签：REAL LOCAL（规则）；模型驱动的意图 NOT VERIFIED。
"""

from __future__ import annotations

from typing import Optional

from runtime.omni.types import AvatarIntent, AvatarIntentName

# 手势 -> (意图, 目标)
RULE_MAP = {
    "wave": (AvatarIntentName.WAVE.value, "user"),
    "point": (AvatarIntentName.POINT.value, "shared_focus"),
    "come_here": (AvatarIntentName.APPROACH.value, "user"),
    "stop": (AvatarIntentName.RETREAT.value, "user"),
    "high_five": (AvatarIntentName.HIGH_FIVE.value, "user"),
    "follow_me": (AvatarIntentName.FOLLOW.value, "user"),
    "nod": (AvatarIntentName.NOD.value, "user"),
    "shake_head": (AvatarIntentName.SHAKE_HEAD.value, "user"),
    "reach": (AvatarIntentName.APPROACH.value, "user"),
    "give": (AvatarIntentName.HIGH_FIVE.value, "user"),
    "sit": (AvatarIntentName.SIT.value, "location:seat"),
    "stand": (AvatarIntentName.STAND.value, "location:floor"),
    "look": (AvatarIntentName.LOOK_AT.value, "shared_focus"),
}

_EMOTION_HINT = {
    "wave": ("happy", 0.6), "high_five": ("happy", 0.7),
    "come_here": ("happy", 0.5), "stop": ("neutral", 0.4),
    "nod": ("happy", 0.5), "shake_head": ("neutral", 0.5),
}


def intent_from_interaction(event) -> Optional[AvatarIntent]:
    """把一条 HumanInteractionEvent 映射成 AvatarIntent（不认识就返回 None）。"""
    name = getattr(event, "name", "") or ""
    rule = RULE_MAP.get(name)
    if rule is None:
        return None
    intent, target = rule
    payload = getattr(event, "payload", None) or {}
    if name == "point" and payload.get("ray_dir"):
        target = "shared_focus"
    emotion, inten = _EMOTION_HINT.get(name, ("", 0.0))
    return AvatarIntent(
        intent=intent,
        target=(getattr(event, "target", "") or target),
        emotion=emotion,
        urgency=float(getattr(event, "confidence", 0.0) or 0.0),
        attention=payload.get("target_label", "") or ("用户指向的目标" if name == "point" else ""),
        style="reflex_fast",
        reason=f"human_interaction:{name}",
        meta={"confidence": float(getattr(event, "confidence", 0.0) or 0.0),
              "payload": payload},
    )


def intent_from_shared_attention(snapshot) -> Optional[AvatarIntent]:
    """共享注意力 -> look_at 意图（用户看/指了某个东西时）。"""
    if snapshot is None:
        return None
    data = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
    target = data.get("shared_target") or data.get("human_focus") or ""
    if not target or target == "unknown":
        return None
    return AvatarIntent(
        intent=AvatarIntentName.LOOK_AT.value,
        target=target,
        urgency=float(data.get("attention_confidence") or 0.0),
        attention=target,
        style="soft_attention",
        reason="shared_attention",
        meta={"gaze_alignment": data.get("gaze_alignment")},
    )
