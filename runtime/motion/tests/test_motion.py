# -*- coding: utf-8 -*-
"""动捕 / 共享注意力 单元验证（合成轨迹驱动，模拟 60Hz）。

标签：SIMULATION（合成轨迹）+ REAL LOCAL（代码真跑）。
NOT VERIFIED：真 Quest 手柄/手势追踪精度（需要真机）。
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from runtime.motion.aggregator import HumanMotionAggregator
from runtime.motion.shared_attention import AreaOfInterest, SharedAttentionTracker
from runtime.motion.types import HumanJoint, HumanMotionState

OUT = Path("runtime/omni/out")
RESULTS = {}
RATE = 60.0


def _record(name, ok, detail=None):
    RESULTS[name] = {"ok": bool(ok), **(detail or {})}
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name,
                            json.dumps(detail or {}, ensure_ascii=False)))
    return bool(ok)


def _hand(x, y, z, vx=0.0, vy=0.0, vz=0.0, conf=0.9):
    return HumanJoint(position=(x, y, z), velocity=(vx, vy, vz),
                      confidence=conf, tracked=True)


def _state(seq, t, hand=None, head_rot=None, height=1.65, body_vel=(0, 0, 0),
           gaze=(0, 0, -1), facing=(0, 0, -1), caps=None):
    return HumanMotionState(
        timestamp=t, sequence=seq,
        head=HumanJoint(position=(0, height, 0), rotation=head_rot,
                        confidence=0.9, tracked=True),
        right_hand=hand, head_height=height,
        gaze_origin=(0, height, 0), gaze_direction=gaze,
        facing_direction=facing, velocity=body_vel, confidence=0.9,
        capabilities=caps or {"head": True, "hands": True, "body": False,
                              "gaze": True, "body_velocity": True})


def run_scenario(frames):
    agg = HumanMotionAggregator()
    got = set()
    for st in frames:
        for ev in agg.ingest(st):
            got.add(ev["name"])
    return got, agg


def wave_frames(moving_body=False):
    frames = []
    t0 = time.time()
    for i in range(int(3.0 * RATE)):
        t = t0 + i / RATE
        x = 0.35 + 0.18 * math.sin(2 * math.pi * 1.6 * i / RATE)
        vx = 0.18 * 2 * math.pi * 1.6 * math.cos(2 * math.pi * 1.6 * i / RATE)
        vel = (0.8, 0.0, 0.0) if moving_body else (0.0, 0.0, 0.0)
        frames.append(_state(i, t, hand=_hand(x, 1.55, -0.35, vx=vx), body_vel=vel))
    return frames


def point_frames():
    t0 = time.time()
    return [_state(i, t0 + i / RATE, hand=_hand(0.0, 1.0, -0.55, conf=0.95))
            for i in range(int(1.5 * RATE))]


def high_five_frames():
    t0 = time.time()
    return [_state(i, t0 + i / RATE, hand=_hand(0.0, 1.32, -0.5, conf=0.95))
            for i in range(int(1.5 * RATE))]


def stop_frames():
    t0 = time.time()
    return [_state(i, t0 + i / RATE, hand=_hand(0.25, 1.45, -0.35, conf=0.95))
            for i in range(int(1.8 * RATE))]


def come_here_frames():
    frames = []
    t0 = time.time()
    for i in range(int(3.0 * RATE)):
        t = t0 + i / RATE
        z = -0.35 + 0.18 * math.sin(2 * math.pi * 1.6 * i / RATE)
        frames.append(_state(i, t, hand=_hand(0.3, 1.2, z, conf=0.95)))
    return frames


def nod_frames():
    frames = []
    t0 = time.time()
    for i in range(int(3.0 * RATE)):
        t = t0 + i / RATE
        pitch = math.radians(10 * math.sin(2 * math.pi * 1.5 * i / RATE))
        frames.append(_state(i, t, hand=_hand(0.3, 0.9, -0.3), head_rot=(pitch, 0.0, 0.0)))
    return frames


def shake_frames():
    frames = []
    t0 = time.time()
    for i in range(int(3.0 * RATE)):
        t = t0 + i / RATE
        yaw = math.radians(14 * math.sin(2 * math.pi * 1.5 * i / RATE))
        frames.append(_state(i, t, hand=_hand(0.3, 0.9, -0.3), head_rot=(0.0, yaw, 0.0)))
    return frames


def sit_frames():
    frames = []
    t0 = time.time()
    for i in range(int(3.0 * RATE)):
        t = t0 + i / RATE
        h = 1.65 - min(0.5, 0.5 * (i / RATE))
        frames.append(_state(i, t, hand=_hand(0.3, h - 0.6, -0.3), height=h,
                             caps={"head": True, "hands": True, "body": True,
                                   "gaze": True, "body_velocity": True}))
    return frames


def look_frames():
    frames = []
    t0 = time.time()
    for i in range(int(2.0 * RATE)):
        t = t0 + i / RATE
        ang = math.radians(35) * min(1.0, i / (0.6 * RATE))
        gaze = (math.sin(ang), 0.0, -math.cos(ang))
        frames.append(_state(i, t, hand=_hand(0.3, 0.9, -0.3), gaze=gaze))
    return frames


def main():
    print("=" * 70)
    print("动捕 / 共享注意力 验证（合成 60Hz 轨迹）")
    print("=" * 70)

    checks = [
        ("wave", wave_frames(False), "wave"),
        ("follow_me", wave_frames(True), "follow_me"),
        ("point", point_frames(), "point"),
        ("high_five", high_five_frames(), "high_five"),
        ("stop", stop_frames(), "stop"),
        ("come_here", come_here_frames(), "come_here"),
        ("nod", nod_frames(), "nod"),
        ("shake_head", shake_frames(), "shake_head"),
        ("sit", sit_frames(), "sit"),
        ("look", look_frames(), "look"),
    ]
    for label, frames, expect in checks:
        got, _ = run_scenario(frames)
        _record("gesture_" + label, expect in got, {"got": sorted(got), "expect": expect})

    frames = wave_frames(False)
    agg = HumanMotionAggregator(summary_hz=1.0)
    for st in frames:
        agg.ingest(st)
    payload = agg.to_omni_payload()
    flat = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = [k for k in ("bone", "joint", "transform", "ik_", "footstep", "animator")
                 if k in flat]
    _record("omni_payload_is_events_and_summary_only",
            (not forbidden) and ("events" in payload) and payload["summary"] is not None,
            {"forbidden_keys": forbidden, "keys": sorted(payload.keys()),
             "summary_keys": sorted((payload.get("summary") or {}).keys()),
             "event_count": len(payload["events"])})
    _record("aggregator_rate", 50.0 <= agg.stats["effective_hz"] <= 70.0,
            {"effective_hz": agg.stats["effective_hz"], "frames_in": agg.stats["frames_in"]})

    tracker = SharedAttentionTracker()
    tracker.register(AreaOfInterest(id="cup", label="杯子", position=(0.0, 1.2, -1.5),
                                    radius=0.35))
    origin = (0.0, 1.65, 0.0)
    direction = (0.0, 1.2 - 1.65, -1.5)
    tracker.update_human(origin, direction, confidence=0.9)
    focus = tracker.human_focus
    target = tracker.resolve_point(origin, direction)
    tracker.update_avatar("cup", point=(0.0, 1.2, -1.5))
    snap = tracker.snapshot()
    _record("point_resolves_target", focus == "cup" and target == "object:cup",
            {"human_focus": focus, "target": target})
    _record("shared_target_and_alignment",
            snap.shared_target == "cup" and snap.gaze_alignment > 0.9, snap.to_dict())

    tracker2 = SharedAttentionTracker()
    tracker2.register(AreaOfInterest(id="cup", position=(0.0, 1.2, -1.5), radius=0.2))
    tracker2.update_human((0.0, 1.65, 0.0), (0.0, 0.0, 1.0))
    snap2 = tracker2.snapshot()
    _record("no_false_positive_when_looking_away",
            snap2.human_focus in ("", "unknown") and snap2.shared_target == "",
            snap2.to_dict())

    summary = {"label": "SIMULATION(合成轨迹) + REAL LOCAL(本地代码)",
               "results": RESULTS,
               "passed": sum(1 for v in RESULTS.values() if v.get("ok")),
               "total": len(RESULTS)}
    verdict = all(v.get("ok") for v in RESULTS.values())
    summary["verdict"] = "PASS" if verdict else "FAIL"
    print("=" * 70)
    print("MOTION =", summary["verdict"], "(%d/%d)" % (summary["passed"], summary["total"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "motion_tests.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT / "motion_tests.json")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
