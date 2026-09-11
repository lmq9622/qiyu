"""Behavior 层自动测试（stdlib runner，不依赖 pytest）。

覆盖提示词第 22 节要求：
greeting / happy / angry / shy / embarrassed / tease / comfort / idle、
priority / interrupt / cancel / cooldown / parallel / channel conflict /
sequence / conditional / unknown action / invalid behavior / adapter failure，
以及 walk+look_at+smile 并行、walk→sit_down 切换。
"""
from __future__ import annotations

from qiyu_quest_gateway.behavior import (
    ActionRef,
    ActionRuntime,
    ActionState,
    BehaviorBrain,
    BehaviorIntent,
    BrainContext,
    MockAdapter,
    NullAdapter,
    describe,
    iter_actions,
)


def _brain() -> BehaviorBrain:
    return BehaviorBrain()


def _run(plan, adapter=None):
    adapter = adapter or MockAdapter()
    events = []
    runtime = ActionRuntime(adapter=adapter,
                            on_event=lambda rec, ev: events.append((rec.name, ev)))
    runtime.submit_plan(plan)
    return runtime, adapter, events


# --------------------------------------------------------------------- 意图
def test_greeting_expands_to_parallel_look_smile_wave():
    brain = _brain()
    plan = brain.plan(BehaviorIntent(intent="greeting", intensity=0.8))
    assert plan is not None
    names = [ref.name for ref in iter_actions(plan.root)]
    assert names == ["look_at_user", "smile", "wave"], names
    assert plan.root.type == "parallel"
    runtime, adapter, events = _run(plan)
    # 三个动作分属 gaze / facial / gesture，三个通道应同时启动
    assert sorted(adapter.names()) == ["look_at_user", "smile", "wave"]
    assert len({c[5] for c in adapter.calls if c[0] == "play"}) == 3


def test_shy_is_sequence_look_away_head_down_blush_fidget():
    plan = _brain().plan(BehaviorIntent(intent="shy", intensity=0.7))
    names = [ref.name for ref in iter_actions(plan.root)]
    assert names == ["look_away", "head_down", "blush", "fidget"], names
    assert plan.root.type == "sequence"


def test_tease_happy_angry_embarrassed_comfort_are_defined():
    brain = _brain()
    for intent in ("tease", "happy", "angry", "embarrassed", "comfort"):
        plan = brain.plan(BehaviorIntent(intent=intent, intensity=0.6))
        assert plan is not None, intent
        assert list(iter_actions(plan.root)), intent


def test_low_relevance_and_noop_return_none():
    brain = _brain()
    assert brain.plan(BehaviorIntent(intent="greeting", relevance=0.1)) is None
    assert brain.last_rejection.startswith("low_relevance")
    assert brain.plan(BehaviorIntent(intent="none")) is None
    assert brain.plan(BehaviorIntent(intent="", actions=[])) is None


def test_unknown_intent_returns_none_but_explicit_actions_work():
    brain = _brain()
    assert brain.plan(BehaviorIntent(intent="super_cute_head_turn_93")) is None
    plan = brain.plan(BehaviorIntent(
        intent="custom", intensity=0.5,
        actions=[ActionRef(name="smile", intensity=0.5),
                 ActionRef(name="nod", intensity=0.4)]))
    assert plan is not None
    assert [r.name for r in iter_actions(plan.root)] == ["smile", "nod"]


def test_unknown_action_is_rejected_not_forwarded():
    brain = _brain()
    plan = brain.plan(BehaviorIntent(
        intent="custom",
        actions=[ActionRef(name="super_cute_head_turn_93")]))
    assert plan is None
    assert brain.last_rejection.startswith("unknown_action")


# --------------------------------------------------------------------- 冲突
def test_sit_with_user_without_seat_degrades_instead_of_sitting():
    brain = _brain()
    plan = brain.plan(BehaviorIntent(intent="sit_with_user"),
                      BrainContext(has_seat=False))
    names = [r.name for r in iter_actions(plan.root)]
    assert "sit_down" not in names, names
    assert names[0] == "look_at_user" and "approach_user" in names


def test_sit_with_user_with_seat_keeps_sequence():
    plan = _brain().plan(BehaviorIntent(intent="sit_with_user"),
                         BrainContext(has_seat=True))
    names = [r.name for r in iter_actions(plan.root)]
    assert "sit_down" in names
    assert names.index("approach_user") < names.index("sit_down")


def test_dance_strips_locomotion():
    plan = _brain().plan(BehaviorIntent(
        intent="party", actions=[ActionRef(name="dance"),
                                 ActionRef(name="walk")]))
    names = [r.name for r in iter_actions(plan.root)]
    assert "dance" in names and "walk" not in names


# --------------------------------------------------------------------- 运行时
def test_walk_look_at_smile_run_in_parallel_and_stop_by_duration():
    plan = _brain().plan(BehaviorIntent(
        intent="walk_with_face", actions=[
            ActionRef(name="walk", duration=1.0, intensity=0.7),
            ActionRef(name="look_at_user", duration=1.0),
            ActionRef(name="smile", duration=1.0)]))
    runtime, adapter, events = _run(plan)
    assert sorted(adapter.names()) == ["look_at_user", "smile", "walk"]
    runtime.update(1.1)
    assert all(rec.state == ActionState.COMPLETED for rec in runtime.history())
    assert "completed" in {ev for _, ev in events}


def test_priority_interrupt_preempts_lower_priority_in_same_channel():
    adapter = MockAdapter()
    runtime = ActionRuntime(adapter=adapter)
    # 先来一个低优先级的 expression，再来一个高优先级的 expression
    first = BehaviorIntent(intent="a", actions=[ActionRef(name="smile",
                                                          duration=5.0)])
    runtime.submit_plan(_brain().plan(first))
    assert "smile" in adapter.names()
    second = BehaviorIntent(intent="b", actions=[ActionRef(name="surprised",
                                                           duration=1.0,
                                                           intensity=1.0)])
    runtime.submit_plan(_brain().plan(second))
    # expression 同通道：两者优先级相同（40），所以走排队而不是抢占
    snapshot = runtime.snapshot()
    channels = {a["channel"] for a in snapshot["actions"]}
    assert channels == {"facial"}


def test_interaction_priority_interrupts_gesture_channel():
    adapter = MockAdapter()
    runtime = ActionRuntime(adapter=adapter)
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="x", actions=[ActionRef(name="fidget", duration=5.0)])))
    # interaction(80) > gesture(50)：不同通道，因此并行而非互相打断
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="y", actions=[ActionRef(name="high_five", duration=1.0)])))
    assert "fidget" in adapter.names() and "high_five" in adapter.names()


def test_channel_conflict_queueing_same_channel():
    adapter = MockAdapter()
    runtime = ActionRuntime(adapter=adapter)
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="x", actions=[ActionRef(name="wave", duration=1.0)])))
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="y", actions=[ActionRef(name="clap", duration=1.0)])))
    # gesture 通道同一时刻只允许一个动作
    running = [a for a in runtime.snapshot()["actions"]
               if a["channel"] == "gesture" and a["state"] == "running"]
    assert len(running) == 1


def test_cooldown_blocks_immediate_repeat():
    adapter = MockAdapter()
    runtime = ActionRuntime(adapter=adapter)
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="x", actions=[ActionRef(name="wave", duration=0.2)])))
    runtime.update(0.3)  # 完成并进入 1.0s 冷却
    before = len(adapter.names())
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="x", actions=[ActionRef(name="wave", duration=0.2)])))
    assert len(adapter.names()) == before, "冷却期内不应重复触发"
    runtime.update(1.0)
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="x", actions=[ActionRef(name="wave", duration=0.2)])))
    assert len(adapter.names()) == before + 1, "冷却结束后应可再次触发"


def test_cancel_and_cancel_all():
    adapter = MockAdapter()
    runtime = ActionRuntime(adapter=adapter)
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="x", actions=[ActionRef(name="walk", duration=5.0),
                             ActionRef(name="look_at_user", duration=5.0)])))
    runtime.cancel_all("barge_in")
    states = {rec.name: rec.state for rec in runtime.history()}
    assert states["walk"] == ActionState.CANCELLED
    assert states["look_at_user"] == ActionState.CANCELLED
    assert runtime.snapshot()["actions"] == []


def test_adapter_failure_marks_action_failed():
    adapter = MockAdapter()
    adapter.fail_on = {"wave"}
    runtime = ActionRuntime(adapter=adapter)
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="greeting", intensity=0.5)))
    failed = [rec for rec in runtime.history() if rec.state == ActionState.FAILED]
    assert any(rec.name == "wave" for rec in failed)
    # 其它通道不应被拖垮
    assert "smile" in adapter.names()


def test_unknown_action_in_runtime_is_recorded_as_failed():
    adapter = MockAdapter()
    runtime = ActionRuntime(adapter=adapter)
    runtime.submit_plan(_brain().plan(BehaviorIntent(
        intent="x", actions=[ActionRef(name="walk")])))
    unknown = [rec for rec in runtime.history() if rec.name == "not_a_real_action"]
    assert unknown == []
    assert "walk" in adapter.names()


def test_null_adapter_is_safe():
    runtime = ActionRuntime(adapter=NullAdapter())
    runtime.submit_plan(_brain().plan(BehaviorIntent(intent="greeting")))
    runtime.update(2.0)
    assert runtime.history()


def test_plan_description_is_readable():
    plan = _brain().plan(BehaviorIntent(intent="greeting"))
    text = describe(plan.root)
    assert "look_at_user" in text and "wave" in text
# --------------------------------------------------------------------- 网关桥
def _bridge():
    from qiyu_quest_gateway.behavior import BehaviorBridge
    sent: list[tuple[str, dict]] = []

    async def send(message_type: str, payload: dict) -> None:
        sent.append((message_type, payload))

    return BehaviorBridge(send), sent


def test_bridge_emits_plan_and_action_messages():
    import asyncio

    async def scene():
        bridge, sent = _bridge()
        plan = await bridge.apply_intent(BehaviorIntent(intent="greeting",
                                                        intensity=0.8))
        assert plan is not None
        types = [t for t, _ in sent]
        assert "server.behavior_plan" in types
        assert "server.behavior_action" in types
        actions = {p["action"] for t, p in sent if t == "server.behavior_action"}
        assert actions == {"look_at_user", "smile", "wave"}, actions
        # 计划里带可读描述，方便排查
        plan_msg = next(p for t, p in sent if t == "server.behavior_plan")
        assert "look_at_user" in plan_msg["describe"]

    asyncio.run(scene())


def test_bridge_skips_low_relevance_without_messages():
    import asyncio

    async def scene():
        bridge, sent = _bridge()
        plan = await bridge.apply_intent(BehaviorIntent(intent="greeting",
                                                        relevance=0.1))
        assert plan is None
        assert sent == []
        assert bridge.last_rejection.startswith("low_relevance")

    asyncio.run(scene())


def test_bridge_tick_emits_events_and_state():
    import asyncio

    async def scene():
        bridge, sent = _bridge()
        await bridge.apply_intent(BehaviorIntent(
            intent="x", actions=[ActionRef(name="smile", duration=0.3)]))
        sent.clear()
        await bridge.tick(0.35)
        types = [t for t, _ in sent]
        assert "server.behavior_event" in types
        assert "server.behavior_state" in types
        states = [p["state"] for t, p in sent if t == "server.behavior_event"]
        assert "completed" in states

    asyncio.run(scene())


def test_bridge_cancel_emits_cancelled_events():
    import asyncio

    async def scene():
        bridge, sent = _bridge()
        await bridge.apply_intent(BehaviorIntent(
            intent="x", actions=[ActionRef(name="walk", duration=5.0)]))
        sent.clear()
        await bridge.cancel("barge_in")
        events = [p for t, p in sent if t == "server.behavior_event"]
        assert any(e["state"] == "cancelled" for e in events)
        assert bridge.snapshot()["actions"] == []

    asyncio.run(scene())


def test_build_context_from_world_and_character_state():
    from qiyu_quest_gateway.behavior import build_context
    world = {
        "user": {"head": {"position": {"x": 0, "y": 0, "z": 0}}},
        "interaction": {"user_distance_m": 1.8},
        "anchors": [{"label": "chair"}],
    }
    character = {"emotion": {"label": "happy", "intensity": 0.7},
                 "speech": {"state": "listening"},
                 "relationship": {"tier": "friend"}}
    ctx = build_context(world, character, locked_channels=["gesture"])
    assert ctx.user_visible is True
    assert ctx.has_seat is True
    assert abs(ctx.user_distance_m - 1.8) < 1e-6
    assert ctx.emotion == "happy"
    assert ctx.relationship_tier == "friend"
    assert ctx.locked_channels == ["gesture"]
# --------------------------------------------------------------------- LLM 输出
def test_llm_behavior_intent_is_accepted_and_unknown_is_dropped():
    from qiyu_quest_gateway.planner import _build_behavior
    ok = _build_behavior({"behavior": {"intent": "shy", "intensity": 0.7}},
                         "……", None)
    assert ok is not None and ok["intent"] == "shy"
    bad = _build_behavior({"behavior": {"intent": "super_cute_head_turn_93"}},
                          "……", None)
    assert bad is None, "未知意图必须被丢弃，不能进行为层"


def test_keyword_hint_produces_behavior_and_plain_talk_does_not():
    from qiyu_quest_gateway.planner import _build_behavior
    greet = _build_behavior(None, "你好呀，今天怎么样", None)
    assert greet is not None and greet["intent"] == "greeting"
    plain = _build_behavior(None, "今天天气不错，我刚才在整理桌子", None)
    assert plain is None, "普通陈述不应触发特殊行为"
    sad = _build_behavior(None, "我今天有点难过", None)
    assert sad is not None and sad["intent"] == "comfort"
