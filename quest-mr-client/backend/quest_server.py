"""Qiyu + Quest Gateway 启动器。

在现有 Qiyu FastAPI app 上追加 /v1/quest/ws，不修改现有路由与前端。
Quest 语音/文本回合复用现有链路：
    Quest WS → QuestWebSocketGateway → demo._pipeline_web_chat_payload
    → MessageGateway → BrainPipeline → MiniMind-O → (需要时) MainBrain
    → 回到 Quest：agent.speech / avatar.intent / spatial.action

用法：
    cd ai-companion/quest-mr-client/backend
    python quest_server.py

环境变量：
    QIYU_QUEST_HOST=0.0.0.0
    QIYU_QUEST_PORT=8766
    QIYU_QUEST_TEMPERATURE=0.7
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo  # noqa: E402  加载现有 Qiyu FastAPI app
from qiyu_quest_gateway import (  # noqa: E402
    QuestResponsePlanner,
    QuestWebSocketGateway,
    render_world_state_for_llm,
)
from qiyu_quest_gateway.vision_detector import detect_objects  # noqa: E402

app = demo.app
quest_gateway = QuestWebSocketGateway()
quest_planner = QuestResponsePlanner()


async def _quest_llm_complete(system_prompt: str, user_prompt: str,
                              temperature: float) -> str:
    """复用现有 Qiyu LLMClient，不新建 LLM 通道/Agent。"""
    client = getattr(demo, "llm_client", None)
    if client is None:
        raise RuntimeError("Qiyu LLMClient 未就绪")
    return await client.complete_json(system_prompt, user_prompt, temperature)


quest_planner.set_llm_complete(_quest_llm_complete)


async def handle_quest_user_text(session, text: str, meta: dict) -> dict:
    """Quest 一轮输入：走现有 Qiyu 大脑链路，再规划高层 Avatar/Spatial 意图。"""
    world_state = quest_gateway.world_states.get(session.session_id)
    spatial_block = render_world_state_for_llm(world_state)
    extra_context: dict = {}
    if spatial_block:
        extra_context["_extra_brain_context"] = spatial_block
        extra_context["quest_world_state"] = world_state
        extra_context["quest_scene_version"] = (world_state or {}).get("scene_version", 0)
    behavior_block = _render_quest_character_state(
        session.behavior_state, session.character_state)
    if behavior_block:
        existing = extra_context.get("_extra_brain_context", "")
        extra_context["_extra_brain_context"] = (
            f"{existing}\n\n{behavior_block}" if existing else behavior_block)
        extra_context["quest_behavior_state"] = session.behavior_state or {}
        extra_context["quest_character_state"] = session.character_state or {}
    human_block = _render_quest_human_state(session)
    if human_block:
        existing = extra_context.get("_extra_brain_context", "")
        extra_context["_extra_brain_context"] = (
            f"{existing}\n\n{human_block}" if existing else human_block)
    vision_objects = (meta or {}).get("vision_objects")
    if isinstance(vision_objects, dict) and vision_objects.get("objects"):
        vision_lines = []
        for item in vision_objects.get("objects", [])[:8]:
            label = item.get("label_cn") or item.get("label") or "物体"
            conf = item.get("confidence")
            vision_lines.append(f"- {label}（置信度 {conf:.2f}）"
                                if isinstance(conf, (int, float)) else f"- {label}")
        vision_block = (
            "【Passthrough 视觉识别结果（真实图片，Qiyu VisionProvider）】\n"
            + "\n".join(vision_lines)
            + "\n这些是 Quest 刚刚拍到的真实物体，请基于它们回答；不要编造未识别到的物体。"
        )
        existing = extra_context.get("_extra_brain_context", "")
        extra_context["_extra_brain_context"] = (
            f"{existing}\n\n{vision_block}" if existing else vision_block)

    temperature = float(os.getenv("QIYU_QUEST_TEMPERATURE", "0.7"))
    result = await demo._pipeline_web_chat_payload(  # noqa: SLF001
        session.user_id,
        session.char_id,
        temperature,
        [{"role": "user", "content": text}],
        [text],
        [],
        extra_context=extra_context,
    )
    payload = result.get("payload") or {}
    pieces = payload.get("pieces") or []
    reply_text = "".join(str(p.get("text") or "") for p in pieces)
    if not reply_text:
        choices = payload.get("choices") or []
        if choices:
            reply_text = str((choices[0].get("message") or {}).get("content") or "")

    emotion_state = {}
    try:
        emotion_state = demo._emotion_state(session.user_id, session.char_id) or {}
    except Exception as e:
        logger.warning(f"[QuestServer] 读取情绪状态失败: {e}")
    relationship = {}
    try:
        relationship = demo._get_relation(session.user_id, session.char_id) or {}
    except Exception as e:
        logger.warning(f"[QuestServer] 读取关系状态失败: {e}")

    user_visible = bool(
        isinstance(world_state, dict)
        and (world_state.get("user") or {}).get("head")
    )
    plan = await quest_planner.plan(
        reply_text=reply_text,
        world_state=world_state,
        emotion_state=emotion_state,
        relationship=relationship,
        user_visible=user_visible,
    )
    intent = plan.get("avatar_intent")
    action = plan.get("spatial_action")
    logger.info(
        f"[QuestServer] turn user={session.user_id} char={session.char_id} "
        f"planner={plan.get('source')} reply_len={len(reply_text)} "
        f"spatial={getattr(action, 'action', None)}"
    )
    return {
        "response_id": payload.get("id"),
        "text": reply_text,
        "pieces": pieces,
        "avatar_intent": intent.model_dump(mode="json") if intent is not None else None,
        "spatial_action": action.model_dump(mode="json") if action is not None else None,
        "need_vision": bool((result.get("decision") or {}).get("need_vision")),
        "vision_query": str((result.get("decision") or {}).get("vision_query") or ""),
    }


async def handle_quest_barge_in(session) -> None:
    """打断：取消本轮 LLM/回合。TTS 停止由 P2 音频通道处理。"""
    logger.info(f"[QuestServer] barge_in session={session.session_id}")


async def handle_quest_interaction_event(session, event: dict) -> None:
    """本地高层动作事件进入 Deep 链；本地 Fast 链已先响应，不阻塞。"""
    event_type = str((event or {}).get("event_type") or "")
    if event_type == "gesture":
        logger.info(
            f"[QuestServer] human gesture session={session.session_id} "
            f"gesture={event.get('gesture')} intent={event.get('intent')} "
            f"target={event.get('target_id')} conf={event.get('confidence')}")


async def handle_quest_autonomy_request(session, request: dict) -> dict:
    """Quest 本地自主行为请求主动表达；仍走现有 Qiyu 主动消息链路。

    服务端有权保持沉默：没有自然话题、冷却未到、用户不在场时返回空。
    """
    world_state = quest_gateway.world_states.get(session.session_id)
    user_visible = bool(
        isinstance(world_state, dict)
        and (world_state.get("user") or {}).get("head")
        and str((world_state.get("status") or "ready")) in ("ready", "scanning")
    )
    if not user_visible:
        return {"accepted": False, "reason": "user_not_visible"}
    try:
        from companion.conv import _context_gate
        allowed, reason = _context_gate(session.user_id, session.char_id)
        if not allowed:
            logger.info(
                f"[QuestServer] autonomy 被 Context Gate 拦截 "
                f"{session.user_id}/{session.char_id}: {reason}")
            return {"accepted": False, "reason": reason}
    except Exception as e:
        logger.warning(f"[QuestServer] autonomy Context Gate 不可用: {e}")

    client = getattr(demo, "llm_client", None)
    if client is None or not getattr(client, "available", False):
        return {"accepted": False, "reason": "llm_unavailable"}
    try:
        messages = await client.generate_proactive(
            session.char_id, session.user_id, night=False)
    except Exception as e:
        logger.warning(f"[QuestServer] autonomy 生成失败: {e}")
        return {"accepted": False, "reason": "generation_failed"}
    if not messages:
        return {"accepted": False, "reason": "stayed_silent"}

    pieces = [
        {
            "text": str((m or {}).get("text") or "").strip(),
            "type": str((m or {}).get("type") or "statement"),
            "delay": int((m or {}).get("delay") or 0),
        }
        for m in messages
        if str((m or {}).get("text") or "").strip()
    ]
    reply_text = "".join(p["text"] for p in pieces)
    if not reply_text:
        return {"accepted": False, "reason": "stayed_silent"}
    emotion_state = {}
    relationship = {}
    try:
        emotion_state = demo._emotion_state(session.user_id, session.char_id) or {}
        relationship = demo._get_relation(session.user_id, session.char_id) or {}
    except Exception:
        pass
    plan = await quest_planner.plan(
        reply_text=reply_text,
        world_state=world_state,
        emotion_state=emotion_state,
        relationship=relationship,
        user_visible=user_visible,
    )
    intent = plan.get("avatar_intent")
    action = plan.get("spatial_action")
    return {
        "response_id": f"autonomy-{session.session_id[:8]}",
        "text": reply_text,
        "pieces": pieces,
        "avatar_intent": intent.model_dump(mode="json") if intent is not None else None,
        "spatial_action": action.model_dump(mode="json") if action is not None else None,
    }


def _render_quest_character_state(behavior_state: dict | None,
                                  character_state: dict | None) -> str:
    """把 Quest 本地行为/角色状态压成 LLM 可读的短上下文。"""
    lines: list[str] = []
    if isinstance(character_state, dict) and character_state:
        emo = character_state.get("emotion") or {}
        drives = character_state.get("drives") or {}
        rel = character_state.get("relationship") or {}
        lines.append("【角色本地状态（Quest 实时）】")
        lines.append(
            f"- 情绪：{emo.get('label', 'neutral')} "
            f"(强度={emo.get('intensity', 0):.2f})")
        lines.append(
            f"- 驱动：耐心={float(drives.get('patience', 0.7)):.2f} "
            f"精力={float(drives.get('energy', 0.8)):.2f} "
            f"好奇={float(drives.get('curiosity', 0.6)):.2f} "
            f"社交电量={float(drives.get('social_battery', 0.75)):.2f}")
        lines.append(
            f"- 关系：{rel.get('tier', '')} "
            f"好感={rel.get('affinity', 50)} 信任={rel.get('trust', 50)}")
    if isinstance(behavior_state, dict) and behavior_state:
        if not lines:
            lines.append("【角色本地状态（Quest 实时）】")
        lines.append(
            f"- 当前行为：{behavior_state.get('active_behavior', 'idle')} "
            f"目标={behavior_state.get('target_id', '')} "
            f"置信度={behavior_state.get('confidence', 0.0)}")
    return "\n".join(lines)


def _render_quest_human_state(session) -> str:
    """把 Quest 压缩动捕状态与最近手势事件压成 LLM 可读语义。"""
    lines: list[str] = []
    motion = getattr(session, "human_motion_state", None)
    if isinstance(motion, dict) and motion:
        lines.append("【用户本地动捕（压缩，5–15Hz）】")
        lines.append(
            f"- 手部追踪：左={bool(motion.get('left_hand_tracked'))} "
            f"右={bool(motion.get('right_hand_tracked'))}")
        lines.append(
            f"- Body Tracking：{bool(motion.get('body_tracked'))} "
            f"置信度={float(motion.get('body_confidence') or 0.0):.2f}")
        if motion.get("gesture"):
            lines.append(f"- 当前手势：{motion.get('gesture')}")
        if motion.get("gaze_target_id"):
            lines.append(f"- 用户注视目标：{motion.get('gaze_target_id')}")
    body = getattr(session, "user_body", None)
    if isinstance(body, dict) and body:
        if not lines:
            lines.append("【用户本地动捕（压缩，5Hz）】")
        lines.append(
            f"- 5 点身体：身高≈{float(body.get('body_height_m') or 0.0):.2f}m "
            f"前倾≈{float(body.get('lean_deg') or 0.0):.1f}° "
            f"置信度={float(body.get('confidence') or 0.0):.2f}")
        lines.append(
            f"- 手部来源：左={body.get('left_hand_source', 'none')} "
            f"右={body.get('right_hand_source', 'none')}")
    event = getattr(session, "last_interaction_event", None)
    if isinstance(event, dict) and event:
        lines.append(
            f"- 最近交互事件：{event.get('event_type', '')} "
            f"gesture={event.get('gesture', '')} "
            f"intent={event.get('intent', '')} "
            f"target={event.get('target_id', '')} "
            f"confidence={event.get('confidence', 0.0)}")
    return "\n".join(lines)


async def handle_quest_vision(session, frame: bytes, meta: dict, prompt: str) -> dict:
    """P4：Passthrough 帧 → Qiyu VisionProvider → 物体标签 + 粗 2D 框。"""
    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    return await detect_objects(
        frame, image_width=width, image_height=height, prompt=prompt)


quest_gateway.on_user_text = handle_quest_user_text
quest_gateway.on_barge_in = handle_quest_barge_in
quest_gateway.on_autonomy_request = handle_quest_autonomy_request
quest_gateway.on_interaction_event = handle_quest_interaction_event
quest_gateway.on_vision_query = handle_quest_vision
app.add_api_websocket_route("/v1/quest/ws", quest_gateway.handle_ws)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("QIYU_QUEST_HOST", "0.0.0.0"),
        port=int(os.getenv("QIYU_QUEST_PORT", "8766")),
        log_level="info",
    )
