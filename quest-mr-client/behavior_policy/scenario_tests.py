"""自动化行为场景测试。

不是只看模型 loss，而是模拟 Quest 会遇到的真实交互序列，检查：
- 行为合理性；
- 中断响应；
- 目标一致性；
- 空间正确性；
- 重复/抽搐/无意义移动。

该测试用 Python 复现 C# Behavior Runtime 的候选/打分/滞回逻辑，
用于策略迭代门禁；真机视觉/动画仍需 P7 验收。
"""
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import torch

from .model import load_weights_json
from .schema import BEHAVIOR_NAMES
from .simulator import (
    Candidate,
    Character,
    Entity,
    Intent,
    World,
    build_candidates,
    encode_features,
    expert_score,
)


def _base_world(seed: int) -> World:
    rng = random.Random(seed)
    world = World(
        scene_version=1,
        status="ready",
        world_age_s=0.2,
        user_visible=True,
        user_position=(0.0, 1.6, 1.1),
        user_forward=(0.0, 0.0, -1.0),
        user_idle_s=2.0,
        navmesh_generated=True,
        navmesh_reachable=True,
    )
    world.entities = [
        Entity("table_1", "table", "anchor", (1.4, 0.7, 1.8), is_surface=True,
               interest=0.35),
        Entity("chair_1", "chair", "anchor", (-1.0, 0.5, 1.6), is_seat=True,
               interest=0.3),
        Entity("cup_1", "cup", "object", (1.35, 0.9, 1.75), confidence=0.92,
               is_small_object=True, interest=0.8),
        Entity("phone_1", "phone", "object", (-0.4, 0.8, 2.0), confidence=0.86,
               is_small_object=True, interest=0.85),
    ]
    return world


def _base_character(seed: int) -> Character:
    rng = random.Random(seed)
    return Character(
        energy=rng.uniform(0.55, 0.95),
        patience=rng.uniform(0.55, 0.95),
        curiosity=rng.uniform(0.45, 0.9),
        social_battery=rng.uniform(0.55, 0.95),
        stress=rng.uniform(0.02, 0.2),
        emotion_label="neutral",
        emotion_intensity=0.3,
        emotion_valence=rng.uniform(-0.1, 0.25),
        emotion_arousal=rng.uniform(0.2, 0.55),
        affinity=rng.uniform(60.0, 85.0),
        trust=rng.uniform(60.0, 90.0),
        familiarity=rng.uniform(35.0, 90.0),
        relationship_tier="close_friend",
        speech_state="idle",
        active_behavior="idle",
        current_behavior_age_s=4.0,
        recent_switch_count=0,
        last_interaction_age_s=3.0,
    )


def _intent(goal: str, target: str = "", age: float = 0.0,
            speaking: bool = False) -> Intent:
    return Intent(goal=goal, target=target, attention=target, age_s=age,
                  speaking=speaking)


def _choose(model, world: World, state: Character, intent: Intent,
            previous: str, rng: random.Random, device: torch.device) -> Tuple[str, str]:
    candidates = build_candidates(state, world, intent)
    features = [encode_features(state, world, intent, c) for c in candidates]
    with torch.no_grad():
        logits, _ = model(torch.tensor(features, dtype=torch.float32, device=device))
        learned = torch.sigmoid(logits).cpu().tolist()
    best: Candidate | None = None
    best_score = -1e9
    for candidate, learned_score in zip(candidates, learned):
        utility = expert_score(state, world, intent, candidate, rng)
        final = 0.65 * utility + 0.35 * learned_score
        if candidate.behavior == previous:
            final += 0.14
        if candidate.hard_negative:
            final -= 0.35
        final -= min(0.08, state.recent_switch_count / 12.0 * 0.08)
        if best is None or final > best_score:
            best = candidate
            best_score = final
    if best is None:
        return "idle", ""
    return best.behavior, best.target_id


def _scenario_steps(name: str, seed: int) -> List[Tuple[World, Character, Intent]]:
    rng = random.Random(seed)
    world = _base_world(seed)
    state = _base_character(seed)
    steps: List[Tuple[World, Character, Intent]] = []
    for step in range(12):
        if name == "call_character":
            world.user_speaking = step < 3
            world.user_looking_at_avatar = True
            intent = _intent("listen_user", "user", speaking=False)
        elif name == "user_approach":
            world.user_position = (0.0, 1.6, max(0.45, 1.1 - step * 0.06))
            world.user_velocity = (0.0, 0.0, -0.5)
            intent = _intent("observe_user", "user")
        elif name == "user_leave":
            world.user_visible = step < 4
            world.user_position = (0.0, 1.6, 1.1 + step * 0.5)
            world.user_velocity = (0.0, 0.0, 0.8)
            intent = _intent("idle", "", age=10.0)
        elif name == "user_return":
            world.user_visible = step >= 3
            intent = _intent("observe_user", "user", age=10.0)
        elif name == "user_silence":
            world.user_speaking = False
            world.user_idle_s += 2.0
            intent = _intent("idle", "", age=10.0 + step)
        elif name == "point_object":
            world.user_pointing_target_id = "cup_1"
            world.user_speaking = False
            intent = _intent("point_at_object", "cup_1")
        elif name == "look_object":
            intent = _intent("observe_object", "phone_1")
        elif name == "follow_me":
            world.user_position = (0.0, 1.6, 1.1 + step * 0.18)
            world.user_velocity = (0.0, 0.0, 0.7)
            intent = _intent("follow_user", "user")
            intent.urgency = 0.7
            intent.social_priority = 0.9
        elif name == "sit_here":
            intent = _intent("sit", "chair_1")
        elif name == "dont_come":
            intent = _intent("maintain_distance", "user")
            world.user_position = (0.0, 1.6, 0.7)
        elif name == "interrupt":
            world.user_speaking = True
            state.speech_state = "speaking" if step == 0 else "listening"
            intent = _intent("listen_user", "user")
        elif name == "emotion_shift":
            state.emotion_valence = math.sin(step * 0.7) * 0.8
            state.emotion_arousal = 0.3 + abs(math.cos(step * 0.5)) * 0.6
            intent = _intent("observe_user", "user")
        elif name == "two_targets":
            world.user_pointing_target_id = "cup_1"
            intent = _intent("observe_object", "phone_1")
        elif name == "target_missing":
            intent = _intent("observe_object", "missing_object")
        elif name == "network_stale":
            world.world_age_s = 10.0 + step
            world.navmesh_reachable = False
            intent = _intent("idle", "", age=12.0)
        else:
            intent = _intent("idle", "", age=10.0)
        steps.append((world, state, intent))
    return steps


def _is_reasonable(name: str, behavior: str, target: str,
                   world: World) -> bool:
    if name in ("user_leave", "network_stale"):
        return behavior not in {
            "approach_user", "follow_user", "speak", "go_to_object",
            "inspect_object", "invite_to_object",
        }
    if name == "interrupt":
        return behavior in {"listen_user", "nod", "observe_user", "think"}
    if name == "target_missing":
        return target != "missing_object" and behavior not in {
            "go_to_object", "inspect_object", "point_at_object",
        }
    if name == "dont_come":
        return behavior not in {"approach_user", "follow_user"}
    if name == "call_character":
        return behavior in {"listen_user", "observe_user", "nod", "think"}
    if name == "point_object":
        return behavior in {"point_at_object", "observe_object", "inspect_object"}
    if name == "follow_me":
        return behavior in {"follow_user", "approach_user", "maintain_distance"}
    if name == "sit_here":
        return behavior in {"sit", "go_to_object"} and target == "chair_1"
    if name == "user_silence":
        return behavior in {"idle", "observe_object", "observe_user",
                            "reposition", "think", "sigh"}
    if name == "user_return":
        return behavior in {"observe_user", "listen_user", "approach_user",
                            "nod", "wave"}
    if name == "two_targets":
        return target in {"cup_1", "phone_1"}
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", type=str,
                        default="behavior_policy/artifacts/behavior_policy_v1.json")
    parser.add_argument("--out", type=str,
                        default="behavior_policy/artifacts/scenario_tests_v1.json")
    parser.add_argument("--device", type=str,
                        default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--seeds", type=int, default=30)
    args = parser.parse_args()

    model = load_weights_json(args.weights).to(torch.device(args.device))
    device = torch.device(args.device)
    scenarios = [
        "call_character", "user_approach", "user_leave", "user_return",
        "user_silence", "point_object", "look_object", "follow_me",
        "sit_here", "dont_come", "interrupt", "emotion_shift",
        "two_targets", "target_missing", "network_stale",
    ]
    report: Dict[str, dict] = {}
    for scenario in scenarios:
        reasonable = 0
        total = 0
        switches = 0
        missing_target_actions = 0
        samples = []
        for seed in range(args.seeds):
            previous = "idle"
            steps = _scenario_steps(scenario, 1000 + seed)
            for world, state, intent in steps:
                behavior, target = _choose(
                    model, world, state, intent, previous, random.Random(seed), device)
                total += 1
                if _is_reasonable(scenario, behavior, target, world):
                    reasonable += 1
                if behavior != previous:
                    switches += 1
                if behavior in {"go_to_object", "inspect_object", "point_at_object"}:
                    entity = world.find(target)
                    if entity is None or not entity.visible:
                        missing_target_actions += 1
                previous = behavior
                if len(samples) < 12:
                    samples.append({
                        "step": len(samples),
                        "behavior": behavior,
                        "target": target,
                    })
        report[scenario] = {
            "reasonable_rate": reasonable / max(1, total),
            "switch_rate": switches / max(1, total),
            "missing_target_actions": missing_target_actions,
            "samples": samples,
        }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    overall = sum(v["reasonable_rate"] for v in report.values()) / len(report)
    print(json.dumps({
        "overall_reasonable_rate": overall,
        "scenarios": {k: round(v["reasonable_rate"], 3) for k, v in report.items()},
        "missing_target_actions": sum(v["missing_target_actions"] for v in report.values()),
    }, ensure_ascii=False))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
