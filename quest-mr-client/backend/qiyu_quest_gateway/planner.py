"""AvatarIntent / SpatialAction 规划器。

定位：
- 这是“结构化意图翻译层”，不是新的 Agent 系统；
- 复用 Qiyu 现有 LLM 通道（由 quest_server 注入 LLMClient.complete_json）；
- LLM 只输出高层意图/动作，绝不输出骨骼或逐帧坐标；
- 目标物体必须存在于 Quest 上报的 WorldState 中，否则丢弃该空间动作，
  防止模型凭空编造不存在的物体。
"""
from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from qiyu_quest_gateway.models import AvatarIntent, SpatialAction
from qiyu_quest_gateway.world_state import render_world_state_for_llm

LLMComplete = Callable[[str, str, float], Awaitable[str]]

_VALID_ACTIONS = {
    "idle", "look_at_user", "look_away", "look_at_object", "nod",
    "shake", "wave", "lean_in", "sigh", "laugh", "blush",
}
_VALID_EMOTIONS = {
    "neutral", "happy", "calm", "sad", "annoyed", "angry",
    "excited", "shy", "confused", "tired", "surprised",
}
_VALID_SPATIAL = {
    "move_to", "approach", "move_away", "face_user", "face_object",
    "look_at", "play_animation", "interact", "stop",
}
_VALID_ANCHOR = {"world", "head", "left_hand", "right_hand", "surface", "object"}

_SYSTEM_PROMPT = """你是 Qiyu MR 客户端的“结构化动作规划器”。
你的唯一任务：把角色的最终台词 + 真实房间空间状态，翻译成高层 AvatarIntent，
必要时再给一个高层 SpatialAction。你不负责生成台词，也不负责控制骨骼。

只输出一个 JSON 对象，不要 Markdown、不要解释。格式：
{
  "avatar_intent": {
    "emotion": "neutral|happy|calm|sad|annoyed|angry|excited|shy|confused|tired|surprised",
    "intensity": 0.0~1.0,
    "expression": "可选，VRM/角色表情名",
    "gesture": "可选，动作名",
    "action": "idle|look_at_user|look_away|look_at_object|nod|shake|wave|lean_in|sigh|laugh|blush",
    "speaking": true,
    "prosody": {"rate": 1.0, "pitch": 1.0, "volume": 1.0},
    "duration_ms": 0
  },
  "spatial_action": null
}

规则：
1. 台词明显在说话 → speaking=true；语气平静 → emotion=neutral/calm。
2. 没有明确空间需求时 spatial_action 必须为 null，禁止为了“看起来像 MR”硬造动作。
3. 只有当台词明确要求角色靠近/远离/看向/操作某个真实物体时，才给 spatial_action。
4. spatial_action.target_id 只能从“允许的目标 id 列表”里选；列表为空或没有合适目标 → null。
5. spatial_action 只填高层意图（move_to/approach/face_object/look_at/interact 等），
   由 Quest 本地 NavMesh/动画系统决定具体路径与骨骼，禁止输出坐标序列。
6. spatial_action 可选字段：target_id, action, speed(0.1~2), stop_distance_m,
   min_distance_m, face_target(bool), avoid_obstacles(bool), priority(0~3),
   duration_ms, animation。
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
        target_lines = "（空：本轮没有可用的真实目标，spatial_action 必须为 null）"

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

    emotion = str(intent_raw.get("emotion") or "neutral")
    if emotion not in _VALID_EMOTIONS:
        emotion = "neutral"
    action = str(intent_raw.get("action") or "idle")
    if action not in _VALID_ACTIONS:
        action = "idle"

    intent = AvatarIntent(
        emotion=emotion,
        intensity=_clamp(intent_raw.get("intensity"), 0.0, 1.0, 0.0),
        expression=str(intent_raw.get("expression") or "")[:64],
        gesture=str(intent_raw.get("gesture") or "")[:64],
        action=action,
        speaking=bool(intent_raw.get("speaking", True)),
        prosody=intent_raw.get("prosody") if isinstance(intent_raw.get("prosody"), dict) else None,
        text="",
        duration_ms=int(_clamp(intent_raw.get("duration_ms"), 0, 600000, 0)),
    )

    spatial_raw = parsed.get("spatial_action")
    if not isinstance(spatial_raw, dict):
        return intent, None

    spatial_action = str(spatial_raw.get("action") or "")
    if spatial_action not in _VALID_SPATIAL:
        return intent, None
    target_id = str(spatial_raw.get("target_id") or "").strip()
    valid_ids = {t["id"] for t in targets}
    if target_id and target_id not in valid_ids:
        logger.warning(f"[QuestPlanner] 丢弃不存在目标的 SpatialAction: {target_id}")
        return intent, None
    if spatial_action in ("move_to", "approach", "move_away", "face_object",
                          "look_at", "interact") and not target_id:
        return intent, None

    anchor = str(spatial_raw.get("anchor") or "world")
    if anchor not in _VALID_ANCHOR:
        anchor = "world"
    action_obj = SpatialAction(
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
    return intent, action_obj


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

    action = "look_at_user" if user_visible else "idle"
    return AvatarIntent(
        emotion=emotion,
        intensity=round(intensity, 2),
        action=action,
        speaking=bool(reply_text),
        prosody={"rate": 1.0, "pitch": 1.0, "volume": 1.0},
    )


__all__ = ["QuestResponsePlanner"]
