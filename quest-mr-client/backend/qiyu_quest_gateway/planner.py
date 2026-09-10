"""AvatarIntent v1.1 规划器。

定位：
- 这是“结构化意图翻译层”，不是动作控制器；
- 复用 Qiyu 现有 LLM 通道（由 quest_server 注入 LLMClient.complete_json）；
- LLM 只输出 goal/target/attention/emotion/style/urgency；
- 路径、速度、脚步、骨骼、IK、Animator 参数全部由 Quest 本地 Behavior Runtime 决定；
- 目标物体必须存在于 Quest 上报的 WorldState 中，否则清空该目标。

兼容：
- 旧 v1.0 AvatarIntent.action 会由 goal 确定性映射，供旧客户端使用；
- 旧 SpatialAction 仍可由显式 spatial_hint 或旧测试输入派生，但新客户端不再消费它。
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from qiyu_quest_gateway.models import AvatarIntent, SpatialAction, SpatialHint
from qiyu_quest_gateway.world_state import render_world_state_for_llm

LLMComplete = Callable[[str, str, float], Awaitable[str]]

_VALID_GOALS = {
    "idle", "listen_user", "think", "speak", "observe_user",
    "observe_object", "approach_user", "maintain_distance", "retreat",
    "follow_user", "go_to_object", "point_at_object", "inspect_object",
    "invite_to_object", "sit", "stand", "reposition", "wave", "nod",
    "shake_head", "laugh", "sigh", "surprised", "comfort_user",
}
_VALID_EMOTIONS = {
    "neutral", "happy", "calm", "sad", "annoyed", "angry",
    "excited", "shy", "confused", "tired", "surprised",
    "curious", "embarrassed",
}
_VALID_STYLES = {
    "neutral", "casual", "warm", "shy", "playful",
    "serious", "tired", "excited", "guarded",
}
_VALID_SPEECH_ACTS = {
    "greet", "answer", "comment", "question", "comfort", "refuse",
    "apologize", "observe", "celebrate", "tease", "acknowledge",
}
_VALID_LEGACY_ACTIONS = {
    "idle", "look_at_user", "look_away", "look_at_object", "nod",
    "shake", "wave", "lean_in", "sigh", "laugh", "blush",
}
_VALID_SPATIAL = {
    "move_to", "approach", "move_away", "face_user", "face_object",
    "look_at", "play_animation", "interact", "stop",
}
_VALID_ANCHOR = {"world", "head", "left_hand", "right_hand", "surface", "object"}

_GOAL_TO_LEGACY_ACTION = {
    "observe_user": "look_at_user",
    "listen_user": "look_at_user",
    "speak": "look_at_user",
    "comfort_user": "lean_in",
    "observe_object": "look_at_object",
    "point_at_object": "look_at_object",
    "inspect_object": "look_at_object",
    "invite_to_object": "look_at_object",
    "wave": "wave",
    "nod": "nod",
    "shake_head": "shake",
    "laugh": "laugh",
    "sigh": "sigh",
    "surprised": "look_at_user",
    "retreat": "look_away",
    "idle": "idle",
}

_SYSTEM_PROMPT = """你是 Qiyu MR 角色的“高层意图规划器”。
你的唯一任务：根据角色台词、真实房间状态、角色情绪和关系，决定角色此刻想做什么。
你不负责生成台词，不负责路径，不负责动画，不负责骨骼、IK、脚步或逐帧控制。

只输出一个 JSON 对象，不要 Markdown、不要解释：
{
  "avatar_intent": {
    "goal": "idle|listen_user|think|speak|observe_user|observe_object|approach_user|maintain_distance|retreat|follow_user|go_to_object|point_at_object|inspect_object|invite_to_object|sit|stand|reposition|wave|nod|shake_head|laugh|sigh|surprised|comfort_user",
    "target": "允许列表中的目标 id；没有则空字符串",
    "attention": "允许列表中的目标 id；没有则空字符串",
    "emotion": "neutral|happy|calm|sad|annoyed|angry|excited|shy|confused|tired|surprised|curious|embarrassed",
    "emotion_intensity": 0.0,
    "behavior_style": "neutral|casual|warm|shy|playful|serious|tired|excited|guarded",
    "urgency": 0.0,
    "social_priority": 0.5,
    "duration_hint_ms": 0,
    "speech_act": "greet|answer|comment|question|comfort|refuse|apologize|observe|celebrate|tease|acknowledge",
    "priority": 1,
    "speaking": true,
    "prosody": {"rate": 1.0, "pitch": 1.0, "volume": 1.0},
    "spatial_hint": null
  }
}

规则：
1. 只输出高层目标；禁止输出坐标、路径、速度、脚步、关节角度、Animator 参数。
2. 没有明确空间需求时 spatial_hint 必须为 null。
3. target/attention 只能从“允许的目标 id 列表”里选；列表为空时留空。
4. 用户正在说话 → goal 优先 listen_user，attention=user，不要抢动作。
5. 角色正在回答 → goal=speak，speaking=true；必要时 attention=user。
6. 用户明确要求靠近/远离/看向/操作真实物体时，用对应 goal + target；
   spatial_hint 最多只填 target_id / desired_distance_m / face_target。
7. 关系亲密、情绪好奇时可以提高 social_priority，但不要因此强行移动。
8. 不确定时选 idle 或 observe_user，不要编造目标。
"""


class QuestResponsePlanner:
    def __init__(self, llm_complete: Optional[LLMComplete] = None) -> None:
        self._llm_complete = llm_complete

    def set_llm_complete(self, fn: Optional[LLMComplete]) -> None:
        self._llm_complete = fn

    async def plan(
        self,
        *,
        reply_text: str,
        world_state: Optional[dict],
        emotion_state: Optional[dict] = None,
        relationship: Optional[dict] = None,
        user_visible: bool = True,
    ) -> dict[str, Any]:
        """返回 {avatar_intent, spatial_action, source}。"""
        reply_text = (reply_text or "").strip()
        targets = _collect_targets(world_state)
        spatial_context = render_world_state_for_llm(world_state, max_anchors=24, max_objects=16)

        if self._llm_complete is not None and reply_text:
            try:
                raw = await self._llm_complete(
                    _SYSTEM_PROMPT,
                    _build_user_prompt(reply_text, spatial_context, targets,
                                       emotion_state, relationship),
                    0.2,
                )
                parsed = _extract_json(raw)
                if parsed is not None:
                    intent, action = _validate(parsed, targets)
                    if intent is not None:
                        return {
                            "avatar_intent": intent,
                            "spatial_action": action,
                            "source": "llm",
                        }
                    logger.warning("[QuestPlanner] LLM 输出无法通过 schema 校验，使用 fallback")
            except Exception as e:
                logger.warning(f"[QuestPlanner] LLM 规划失败，使用 fallback: {e}")

        intent = _fallback_intent(reply_text, emotion_state, user_visible)
        return {"avatar_intent": intent, "spatial_action": None, "source": "fallback"}


def _collect_targets(world_state: Optional[dict]) -> list[dict]:
    targets: list[dict] = []
    if not isinstance(world_state, dict):
        return targets
    for raw in world_state.get("anchors") or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "unknown")
        if label in ("floor", "ceiling", "wall", "room"):
            continue
        anchor_id = str(raw.get("id") or "").strip()
        if not anchor_id:
            continue
        targets.append({
            "id": anchor_id,
            "label": label,
            "kind": "anchor",
            "position": (raw.get("pose") or {}).get("position"),
        })
    for raw in world_state.get("objects") or []:
        if not isinstance(raw, dict):
            continue
        object_id = str(raw.get("id") or "").strip()
        if not object_id:
            continue
        targets.append({
            "id": object_id,
            "label": str(raw.get("label") or "object"),
            "kind": "object",
            "position": raw.get("position"),
        })
    return targets


def _build_user_prompt(reply_text: str, spatial_context: str,
                       targets: list[dict], emotion_state: Optional[dict],
                       relationship: Optional[dict]) -> str:
    if targets:
        target_lines = "\n".join(
            f"- id={t['id']} | label={t['label']} | kind={t['kind']}"
            for t in targets[:40]
        )
    else:
        target_lines = "（空：本轮没有可用的真实目标，target/attention 必须留空）"

    emo = emotion_state or {}
    emo_line = ""
    if emo:
        emo_line = (
            f"\n【角色当前情绪向量（0-100，供参考）】joy={emo.get('joy')} "
            f"excitement={emo.get('excitement')} sadness={emo.get('sadness')} "
            f"anxiety={emo.get('anxiety')} fear={emo.get('fear')}"
        )
    rel = relationship or {}
    rel_line = ""
    if rel:
        rel_line = (
            f"\n【与用户的关系（长期 Memory/Relationship，供语气参考）】"
            f"亲密度={rel.get('affinity')} 友情={rel.get('friendship')} "
            f"阶段={rel.get('tier') or rel.get('relationship') or ''}"
        )

    return (
        f"【角色最终台词】\n{reply_text}\n"
        f"{emo_line}{rel_line}\n"
        f"\n【允许的目标 id 列表】\n{target_lines}\n"
        f"\n【真实房间空间状态】\n{spatial_context or '（本轮无 WorldState）'}\n"
        "\n请输出 JSON。"
    )


def _extract_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def _validate(parsed: dict, targets: list[dict]) -> tuple[Optional[AvatarIntent], Optional[SpatialAction]]:
    intent_raw = parsed.get("avatar_intent")
    if not isinstance(intent_raw, dict):
        return None, None

    # "user" 是协议约定的特殊目标，不属于 WorldState anchors/objects。
    valid_ids = {t["id"] for t in targets} | {"user"}
    goal = str(intent_raw.get("goal") or "").strip()
    legacy_action = str(intent_raw.get("action") or "").strip()
    if goal not in _VALID_GOALS:
        goal = _legacy_action_to_goal(legacy_action)
    if goal not in _VALID_GOALS:
        goal = "idle"

    target = str(intent_raw.get("target") or "").strip()
    if target and target not in valid_ids:
        logger.warning(f"[QuestPlanner] 丢弃不存在目标: {target}")
        target = ""
    attention = str(intent_raw.get("attention") or "").strip()
    if attention and attention not in valid_ids:
        logger.warning(f"[QuestPlanner] 丢弃不存在关注目标: {attention}")
        attention = ""

    emotion = str(intent_raw.get("emotion") or "neutral")
    if emotion not in _VALID_EMOTIONS:
        emotion = "neutral"
    style = str(intent_raw.get("behavior_style") or "neutral")
    if style not in _VALID_STYLES:
        style = "neutral"
    speech_act = str(intent_raw.get("speech_act") or "").strip()
    if speech_act not in _VALID_SPEECH_ACTS:
        speech_act = ""

    intensity = _clamp(
        intent_raw.get("emotion_intensity", intent_raw.get("intensity")),
        0.0, 1.0, 0.0,
    )
    duration_hint_ms = int(_clamp(
        intent_raw.get("duration_hint_ms", intent_raw.get("duration_ms")),
        0, 600000, 0,
    ))
    spatial_hint = _parse_spatial_hint(intent_raw.get("spatial_hint"), valid_ids)

    legacy = legacy_action if legacy_action in _VALID_LEGACY_ACTIONS else ""
    if not legacy:
        legacy = _GOAL_TO_LEGACY_ACTION.get(goal, "idle")

    intent = AvatarIntent(
        id=uuid.uuid4().hex,
        intent_id=uuid.uuid4().hex,
        goal=goal,
        target=target,
        attention=attention,
        behavior_style=style,
        urgency=_clamp(intent_raw.get("urgency"), 0.0, 1.0, 0.0),
        social_priority=_clamp(intent_raw.get("social_priority"), 0.0, 1.0, 0.5),
        duration_hint_ms=duration_hint_ms,
        speech_act=speech_act,
        priority=int(_clamp(intent_raw.get("priority"), 0, 5, 1)),
        interrupt_policy=_normalize_interrupt_policy(intent_raw.get("interrupt_policy")),
        emotion=emotion,
        intensity=intensity,
        emotion_intensity=intensity,
        expression=str(intent_raw.get("expression") or "")[:64],
        gesture=str(intent_raw.get("gesture") or "")[:64],
        action=legacy,
        speaking=bool(intent_raw.get("speaking", True)),
        prosody=intent_raw.get("prosody") if isinstance(intent_raw.get("prosody"), dict) else None,
        text="",
        duration_ms=duration_hint_ms,
        cancel_on_barge_in=bool(intent_raw.get("cancel_on_barge_in", True)),
        spatial_hint=spatial_hint,
    )

    # 兼容旧 v1.0 测试/客户端：显式 spatial_action 仍然校验；
    # 新版 LLM 不应输出该字段，新客户端也不消费它。
    spatial_raw = parsed.get("spatial_action")
    if isinstance(spatial_raw, dict):
        return intent, _validate_legacy_spatial(spatial_raw, valid_ids)

    if spatial_hint is None:
        return intent, None

    legacy_spatial = _compile_legacy_spatial(goal, spatial_hint)
    return intent, legacy_spatial


def _parse_spatial_hint(raw: Any, valid_ids: set[str]) -> Optional[SpatialHint]:
    if not isinstance(raw, dict):
        return None
    target_id = str(raw.get("target_id") or "").strip()
    if not target_id or target_id not in valid_ids:
        return None
    return SpatialHint(
        target_id=target_id,
        desired_distance_m=_clamp(raw.get("desired_distance_m"), 0.2, 5.0, 0.9),
        face_target=bool(raw.get("face_target", True)),
    )


def _compile_legacy_spatial(goal: str, hint: SpatialHint) -> Optional[SpatialAction]:
    if goal in ("go_to_object", "inspect_object"):
        action = "move_to"
    elif goal in ("observe_object", "point_at_object", "invite_to_object"):
        action = "look_at"
    elif goal == "sit":
        action = "move_to"
    else:
        return None
    return SpatialAction(
        action=action,
        target_id=hint.target_id,
        stop_distance_m=hint.desired_distance_m,
        face_target=hint.face_target,
        priority=2,
    )


def _validate_legacy_spatial(spatial_raw: dict, valid_ids: set[str]) -> Optional[SpatialAction]:
    spatial_action = str(spatial_raw.get("action") or "")
    if spatial_action not in _VALID_SPATIAL:
        return None
    target_id = str(spatial_raw.get("target_id") or "").strip()
    if target_id and target_id not in valid_ids:
        logger.warning(f"[QuestPlanner] 丢弃不存在目标的 SpatialAction: {target_id}")
        return None
    if spatial_action in ("move_to", "approach", "move_away", "face_object",
                          "look_at", "interact") and not target_id:
        return None
    anchor = str(spatial_raw.get("anchor") or "world")
    if anchor not in _VALID_ANCHOR:
        anchor = "world"
    return SpatialAction(
        action=spatial_action,
        target_id=target_id,
        anchor=anchor,
        speed=_clamp(spatial_raw.get("speed"), 0.1, 2.0, 1.0),
        stop_distance_m=_clamp(spatial_raw.get("stop_distance_m"), 0.1, 5.0, 0.5),
        min_distance_m=_clamp(spatial_raw.get("min_distance_m"), 0.0, 5.0, 0.0),
        face_target=bool(spatial_raw.get("face_target", True)),
        avoid_obstacles=bool(spatial_raw.get("avoid_obstacles", True)),
        priority=int(_clamp(spatial_raw.get("priority"), 0, 3, 1)),
        duration_ms=int(_clamp(spatial_raw.get("duration_ms"), 0, 600000, 0)),
        animation=str(spatial_raw.get("animation") or "")[:64],
    )


def _legacy_action_to_goal(action: str) -> str:
    return {
        "look_at_user": "observe_user",
        "look_away": "retreat",
        "look_at_object": "observe_object",
        "nod": "nod",
        "shake": "shake_head",
        "wave": "wave",
        "lean_in": "comfort_user",
        "sigh": "sigh",
        "laugh": "laugh",
        "blush": "idle",
        "idle": "idle",
    }.get(action, "idle")


def _normalize_interrupt_policy(value: Any) -> str:
    text = str(value or "on_higher_priority")
    if text in ("never", "on_higher_priority", "on_barge_in", "always"):
        return text
    return "on_higher_priority"


def _clamp(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, num))


def _fallback_intent(reply_text: str, emotion_state: Optional[dict],
                     user_visible: bool) -> AvatarIntent:
    """LLM 不可用时的确定性降级：只做情绪→表情/看向，不猜空间动作。"""
    emo = emotion_state or {}
    joy = float(emo.get("joy", 20) or 20)
    excitement = float(emo.get("excitement", 15) or 15)
    sadness = float(emo.get("sadness", 5) or 5)
    anxiety = float(emo.get("anxiety", 8) or 8)
    fear = float(emo.get("fear", 5) or 5)

    emotion = "neutral"
    intensity = 0.2
    if excitement >= 60:
        emotion, intensity = "excited", min(1.0, excitement / 100.0)
    elif joy >= 60:
        emotion, intensity = "happy", min(1.0, joy / 100.0)
    elif sadness >= 55:
        emotion, intensity = "sad", min(1.0, sadness / 100.0)
    elif anxiety >= 55:
        emotion, intensity = "confused", min(1.0, anxiety / 100.0)
    elif fear >= 55:
        emotion, intensity = "surprised", min(1.0, fear / 100.0)
    elif joy >= 40:
        emotion, intensity = "calm", 0.4

    goal = "observe_user" if user_visible else "idle"
    action = "look_at_user" if user_visible else "idle"
    return AvatarIntent(
        id=uuid.uuid4().hex,
        intent_id=uuid.uuid4().hex,
        goal=goal,
        target="",
        attention="",
        behavior_style="casual" if user_visible else "neutral",
        urgency=0.0,
        social_priority=0.5,
        emotion=emotion,
        intensity=round(intensity, 2),
        emotion_intensity=round(intensity, 2),
        action=action,
        speaking=bool(reply_text),
        prosody={"rate": 1.0, "pitch": 1.0, "volume": 1.0},
    )


__all__ = ["QuestResponsePlanner"]
