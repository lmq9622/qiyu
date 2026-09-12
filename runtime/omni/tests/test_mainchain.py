# -*- coding: utf-8 -*-
"""正式主链验证（注入 MockOmniBackend，标签 SIMULATION）。

验证的是**编排**，不是模型能力：
  1. 文本 / 音频 / 视频 / WorldEvent / MotionEvent 都能进 OmniSession；
  2. 输出被正确路由成 Conversation 与 AvatarIntent；
  3. AvatarIntent 只能取封闭集合，出现骨骼类字段一律拒绝；
  4. 动捕只以「事件 + 摘要」进 Omni（高频帧不进）；
  5. 默认运行时 MiniMind = disabled（legacy gate），主链不调用它；
  6. 深推理只在显式调用时发生。

NOT VERIFIED：真实模型输出（那部分由 docs/OMNI_LOCAL_VALIDATION.md 覆盖）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from runtime.omni.backends.mock import MockOmniBackend
from runtime.omni.mainchain import OmniMainChain
from runtime.omni.session import OmniSession
from runtime.omni.types import AvatarIntent, AvatarIntentName
from runtime.motion.aggregator import HumanMotionAggregator
from runtime.motion.shared_attention import AreaOfInterest, SharedAttentionTracker
from runtime.motion.types import HumanJoint, HumanMotionState

OUT = Path("runtime/omni/out")
RESULTS = {}


def _record(name, ok, detail=None):
    RESULTS[name] = {"ok": bool(ok), **(detail or {})}
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name,
                            json.dumps(detail or {}, ensure_ascii=False)))
    return bool(ok)


def wave_states(n=90, rate=60.0, moving=False):
    import math
    out = []
    t0 = time.time()
    for i in range(n):
        t = t0 + i / rate
        x = 0.35 + 0.18 * math.sin(2 * math.pi * 1.6 * i / rate)
        vx = 0.18 * 2 * math.pi * 1.6 * math.cos(2 * math.pi * 1.6 * i / rate)
        vel = (0.8, 0.0, 0.0) if moving else (0.0, 0.0, 0.0)
        out.append(HumanMotionState(
            timestamp=t, sequence=i,
            head=HumanJoint(position=(0, 1.65, 0), confidence=0.9, tracked=True),
            right_hand=HumanJoint(position=(x, 1.55, -0.35), velocity=(vx, 0, 0),
                                  confidence=0.9, tracked=True),
            head_height=1.65, gaze_direction=(0, 0, -1), facing_direction=(0, 0, -1),
            velocity=vel, confidence=0.9,
            capabilities={"head": True, "hands": True, "body": False,
                          "gaze": True, "body_velocity": True}))
    return out


async def main():
    print("=" * 70)
    print("正式主链验证（MockOmniBackend = SIMULATION）")
    print("=" * 70)

    intents, conversations, events = [], [], []

    async def on_intent(payload):
        intents.append(payload)

    async def on_conversation(conv):
        conversations.append(conv)

    async def on_event(ev):
        events.append(ev)

    omni = OmniSession(backend=MockOmniBackend())
    motion = HumanMotionAggregator(summary_hz=1.0)
    attention = SharedAttentionTracker()
    attention.register(AreaOfInterest(id="cup", position=(0.0, 1.2, -1.5), radius=0.35))
    chain = OmniMainChain(omni=omni, motion=motion, shared_attention=attention,
                          on_intent=on_intent, on_conversation=on_conversation,
                          on_event=on_event)
    sid = await chain.start()
    _record("chain_started", bool(sid), {"session_id": sid,
                                         "backend": omni.backend_name,
                                         "state": omni.state})
    chain.start_pump()

    await chain.send_text("你好")
    await chain.send_audio([0.0] * 320, sample_rate=16000)
    await chain.send_video(b"fake-jpeg", kind="snapshot", source="quest_camera")
    await chain.send_world_event("world_state", {"room": "living"}, priority=5)
    _record("inputs_accepted",
            chain.stats.text_in == 1 and chain.stats.audio_in == 1
            and chain.stats.video_in == 1 and chain.stats.world_events_in == 1,
            chain.stats.to_dict())

    states = wave_states(90)
    forwarded = 0
    forwarded_frames = 0
    for st in states:
        r = await chain.ingest_motion(st)
        if r.get("forwarded"):
            forwarded += 1
            forwarded_frames += 1
    # 事件驱动：只在「有新事件」或「满 1 秒摘要」时才进 Omni，远小于 90 帧
    _record("motion_decimated_for_omni",
            forwarded <= 10 and forwarded < chain.stats.motion_frames_in,
            {"high_freq_frames": chain.stats.motion_frames_in,
             "forward_windows": forwarded,
             "events_to_omni": chain.stats.motion_events_to_omni,
             "summaries_to_omni": chain.stats.motion_summaries_to_omni})

    attention.update_human((0.0, 1.65, 0.0), (0.0, -0.45, -1.5), confidence=0.9)
    attention.update_avatar("cup", point=(0.0, 1.2, -1.5))
    await chain.send_shared_attention(attention.snapshot())
    _record("shared_attention_forwarded",
            omni.counters["world_events"] >= 2,
            {"world_events": omni.counters["world_events"],
             "attention_stats": attention.stats_dict()})

    await asyncio.sleep(1.5)

    good = AvatarIntent(intent=AvatarIntentName.WAVE.value, target="user", urgency=0.5)
    await chain._dispatch(type("E", (), {"kind": "avatar_intent", "conversation": None,
                                         "avatar_intent": good, "payload": {}})())
    bad = AvatarIntent(intent="do_a_backflip", target="user")
    await chain._dispatch(type("E", (), {"kind": "avatar_intent", "conversation": None,
                                         "avatar_intent": bad, "payload": {}})())
    allowed = {n.value for n in AvatarIntentName}
    all_allowed = all(i["intent"] in allowed for i in intents)
    _record("avatar_intent_closed_set",
            all_allowed and intents[-1]["intent"] == "wave"
            and chain.stats.intents_rejected == 1,
            {"accepted_count": len(intents),
             "accepted_intents": [i["intent"] for i in intents],
             "all_in_closed_set": all_allowed,
             "rejected": chain.stats.intents_rejected})

    payload_text = json.dumps(intents, ensure_ascii=False).lower()
    forbidden = [k for k in ("bone", "transform", "ik_", "footstep", "animator", "joint")
                 if k in payload_text]
    _record("no_bone_data_in_intent", not forbidden, {"forbidden": forbidden})

    legacy = chain.legacy_status()
    _record("minimind_disabled_by_default",
            legacy.get("minimind_enabled") is False and legacy.get("deprecated") is True,
            {"minimind_enabled": legacy.get("minimind_enabled"),
             "final_version": legacy.get("final_version")})

    dr = await chain.deep_reasoning("帮我做一个三步计划")
    _record("deep_reasoning_opt_in",
            dr.get("available") is False and chain.stats.deep_reasoning_calls == 0,
            {"result": dr})

    await chain.stop()
    summary = {"label": "SIMULATION(MockOmniBackend) + REAL LOCAL(编排代码)",
               "results": RESULTS,
               "chain_stats": chain.stats_dict(),
               "passed": sum(1 for v in RESULTS.values() if v.get("ok")),
               "total": len(RESULTS)}
    verdict = all(v.get("ok") for v in RESULTS.values())
    summary["verdict"] = "PASS" if verdict else "FAIL"
    print("=" * 70)
    print("MAINCHAIN =", summary["verdict"], "(%d/%d)" % (summary["passed"], summary["total"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mainchain_tests.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT / "mainchain_tests.json")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
