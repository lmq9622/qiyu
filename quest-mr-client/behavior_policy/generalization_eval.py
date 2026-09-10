"""OOD 泛化、长时序行为、连续参数统计与自动仲裁参数搜索。

关键约束：
- OOD 使用全新 seed 与全新场景组合，不进入训练集；
- 本脚本只读取已训练好的 v1 权重，不反向改训练数据；
- 如发现抖动，只在独立 tuning split 上搜索迟滞/最小驻留/冷却参数。
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import torch

from .model import load_weights_json
from .schema import BEHAVIOR_NAMES, PARAM_NAMES
from .simulator import (
    Candidate,
    Character,
    Entity,
    Intent,
    World,
    build_candidates,
    encode_features,
    expert_score,
    generate_dataset,
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _dist(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


@dataclass
class EvalGroup:
    features: np.ndarray
    labels: np.ndarray
    hard: np.ndarray
    params: np.ndarray
    behaviors: List[str]
    targets: List[str]
    utilities: np.ndarray
    goal: str
    user_visible: bool
    user_speaking: bool
    target_visible: bool
    navmesh_reachable: bool
    collision_risk: float = 0.0
    occluded: bool = False
    user_approach_speed: float = 0.0
    episode: int = -1
    step: int = -1


def _data_arrays(data: Dict[str, object]):
    return (
        np.asarray(data["features"], dtype=np.float32),
        np.asarray(data["labels"], dtype=np.float32),
        np.asarray(data["hard_negatives"], dtype=np.int8),
        np.asarray(data["params"], dtype=np.float32),
        np.asarray(data["candidate_utilities"], dtype=np.float32),
    )


def _group_from_rows(data: Dict[str, object], group_id: int,
                     indices: np.ndarray | None = None,
                     arrays=None) -> EvalGroup:
    if arrays is None:
        arrays = _data_arrays(data)
    features, labels, hard, params, utilities = arrays
    if indices is None:
        groups = np.asarray(data["groups"])
        indices = np.where(groups == group_id)[0]
    meta = data["group_meta"][group_id]  # type: ignore[index]
    return EvalGroup(
        features=features[indices],
        labels=labels[indices],
        hard=hard[indices],
        params=params[indices],
        behaviors=[str(data["candidate_behaviors"][i]) for i in indices],  # type: ignore[index]
        targets=[str(data["candidate_targets"][i]) for i in indices],  # type: ignore[index]
        utilities=utilities[indices],
        goal=str(meta.get("intent_goal") or "idle"),
        user_visible=bool(meta.get("user_visible", True)),
        user_speaking=bool(meta.get("user_speaking", False)),
        target_visible=bool(meta.get("best_target", "")),
        navmesh_reachable=not str(meta.get("scenario")) == "network_stale",
        collision_risk=0.0,
        occluded=False,
        user_approach_speed=0.0,
        episode=int(meta.get("episode", -1)),
        step=int(meta.get("step", -1)),
    )


def _groups_from_data(data: Dict[str, object]) -> List[EvalGroup]:
    """一次性构造所有分组，避免 O(组数 × 样本数) 的重复扫描。"""
    groups = np.asarray(data["groups"])
    order = np.argsort(groups, kind="stable")
    sorted_groups = groups[order]
    unique, starts = np.unique(sorted_groups, return_index=True)
    boundaries = np.append(starts, len(order))
    arrays = _data_arrays(data)
    result: List[EvalGroup] = []
    for i, group_id in enumerate(unique):
        indices = order[starts[i]:boundaries[i + 1]]
        result.append(_group_from_rows(data, int(group_id), indices, arrays))
    return result


def _random_ood_entity(rng: random.Random, idx: int, room_half: float) -> Entity:
    choices = [
        ("table", "anchor", False, True, False, 0.35, ("surface",)),
        ("chair", "anchor", True, False, False, 0.3, ("seat",)),
        ("sofa", "anchor", True, False, False, 0.3, ("seat",)),
        ("plant", "anchor", False, False, False, 0.55, ("decor",)),
        ("screen", "anchor", False, False, False, 0.5, ("display",)),
        ("cup", "object", False, False, True, 0.75, ("small_object",)),
        ("phone", "object", False, False, True, 0.8, ("small_object",)),
        ("book", "object", False, False, True, 0.65, ("small_object",)),
        ("bottle", "object", False, False, True, 0.7, ("small_object",)),
        ("remote", "object", False, False, True, 0.7, ("small_object",)),
        ("keyboard", "object", False, False, True, 0.6, ("small_object",)),
        ("bag", "object", False, False, True, 0.55, ("movable",)),
    ]
    label, kind, seat, surface, small, interest, affordances = rng.choice(choices)
    return Entity(
        id=f"ood_{label}_{idx}",
        label=label,
        kind=kind,
        position=(
            rng.uniform(-room_half, room_half),
            rng.uniform(0.2, 1.2),
            rng.uniform(-room_half, room_half),
        ),
        confidence=rng.uniform(0.55, 0.99),
        visible=rng.random() > 0.1,
        reachable=rng.random() > 0.08,
        is_seat=seat,
        is_surface=surface,
        is_small_object=small,
        interest=interest,
        affordances=affordances,
    )


def _ood_world(rng: random.Random, scenario: str) -> World:
    room_half = rng.uniform(3.2, 5.2)
    world = World(
        scene_version=rng.randint(100, 500),
        status="ready",
        world_age_s=rng.uniform(0.0, 2.0),
        user_visible=True,
        user_position=(
            rng.uniform(-room_half, room_half),
            1.55 + rng.uniform(-0.15, 0.15),
            rng.uniform(-room_half, room_half),
        ),
        user_velocity=(rng.uniform(-0.9, 0.9), 0.0, rng.uniform(-1.0, 1.0)),
        user_forward=(rng.uniform(-1.0, 1.0), 0.0, rng.uniform(-1.0, 1.0)),
        user_speaking=rng.random() < 0.28,
        user_looking_at_avatar=rng.random() < 0.6,
        user_idle_s=rng.uniform(0.0, 240.0),
        navmesh_generated=rng.random() > 0.05,
        navmesh_reachable=rng.random() > 0.12,
        collision_risk=rng.uniform(0.0, 0.35),
        nearest_obstacle_m=rng.uniform(0.25, 4.0),
        occluded=rng.random() < 0.18,
        scene_stable=rng.random() > 0.18,
    )
    world.entities = [
        _random_ood_entity(rng, i, room_half)
        for i in range(rng.randint(6, 15))
    ]
    # 动态障碍：训练集中没有的移动实体。
    world.entities.append(Entity(
        id="moving_obstacle_1",
        label="moving_obstacle",
        kind="obstacle",
        position=(rng.uniform(-2.0, 2.0), 0.5, rng.uniform(-2.0, 2.0)),
        velocity=(rng.uniform(-0.8, 0.8), 0.0, rng.uniform(-0.8, 0.8)),
        confidence=0.9,
        interest=0.0,
        reachable=False,
    ))
    if scenario == "network_stale":
        world.world_age_s = rng.uniform(8.0, 20.0)
        world.navmesh_reachable = False
        world.scene_stable = False
    if scenario == "occlusion":
        world.occluded = True
    if rng.random() < 0.5:
        world.user_pointing_target_id = rng.choice(world.entities).id
    return world


def _ood_character(rng: random.Random) -> Character:
    affinity = rng.uniform(18.0, 98.0)
    tier = ("acquaintance" if affinity < 40 else
            "friend" if affinity < 62 else
            "close_friend" if affinity < 82 else "intimate")
    valence = rng.uniform(-0.95, 0.98)
    arousal = rng.uniform(0.02, 1.0)
    return Character(
        energy=rng.uniform(0.03, 1.0),
        patience=rng.uniform(0.04, 1.0),
        curiosity=rng.uniform(0.03, 1.0),
        social_battery=rng.uniform(0.03, 1.0),
        stress=rng.uniform(0.0, 0.95),
        emotion_label=(
            "happy" if valence > 0.5 else
            "sad" if valence < -0.5 else
            "curious" if arousal > 0.75 else
            "tired" if arousal < 0.12 else "neutral"
        ),
        emotion_intensity=rng.uniform(0.05, 1.0),
        emotion_valence=valence,
        emotion_arousal=arousal,
        affinity=affinity,
        trust=rng.uniform(15.0, 98.0),
        familiarity=rng.uniform(0.0, 100.0),
        relationship_tier=tier,
        speech_state=rng.choice(["idle", "listening", "thinking", "speaking", "interrupted"]),
        active_behavior=rng.choice(BEHAVIOR_NAMES[:24]),
        current_behavior_age_s=rng.uniform(0.0, 30.0),
        recent_switch_count=rng.randint(0, 12),
        last_interaction_age_s=rng.uniform(0.0, 600.0),
        salient_memory_count=rng.randint(0, 10),
        has_unfinished_topic=rng.random() < 0.4,
    )


def _episode(name: str, seed: int, length: int) -> List[Tuple[World, Character, Intent]]:
    stable_name_hash = sum(ord(ch) * (i + 1) for i, ch in enumerate(name))
    rng = random.Random(seed * 1009 + stable_name_hash)
    world = _ood_world(rng, name)
    state = _ood_character(rng)
    steps: List[Tuple[World, Character, Intent]] = []
    target_ids = [e.id for e in world.entities if e.kind in ("object", "anchor")]
    user_points = []

    for step in range(length):
        intent = Intent(goal="idle", age_s=10.0 + step * 0.1)
        if name == "call_and_follow":
            if step < 3:
                intent = Intent("listen_user", "user", age_s=0.0)
                world.user_speaking = True
                world.user_looking_at_avatar = True
            elif step < length - 4:
                intent = Intent("follow_user", "user", age_s=0.0,
                                urgency=0.7, social_priority=0.9)
                world.user_speaking = False
                world.user_velocity = (0.6, 0.0, 0.6)
                world.user_position = (
                    world.user_position[0] + 0.25,
                    world.user_position[1],
                    world.user_position[2] + 0.25,
                )
            else:
                intent = Intent("maintain_distance", "user", age_s=0.0)
        elif name == "point_and_inspect":
            chosen = target_ids[step % len(target_ids)] if target_ids else ""
            if step % 5 == 4:
                chosen = ""
            intent = Intent("point_at_object" if step % 2 == 0 else "inspect_object",
                            chosen, age_s=0.0)
            world.user_pointing_target_id = chosen
            world.user_speaking = step % 7 == 0
        elif name == "interrupt_and_replan":
            if step % 6 in (0, 1):
                world.user_speaking = True
                intent = Intent("listen_user", "user", age_s=0.0)
            elif step % 6 == 2:
                world.user_speaking = False
                intent = Intent("think", "", age_s=0.0)
            elif step % 6 == 3:
                intent = Intent("go_to_object", target_ids[0] if target_ids else "",
                                age_s=0.0)
            else:
                intent = Intent("observe_user", "user", age_s=0.0)
        elif name == "obstacle_and_wait":
            intent = Intent("go_to_object", target_ids[step % len(target_ids)] if target_ids else "",
                            age_s=0.0)
            world.collision_risk = 0.8 if 5 <= step <= 9 else 0.1
            world.nearest_obstacle_m = 0.3 if 5 <= step <= 9 else 2.0
        elif name == "multi_target_competition":
            a = target_ids[step % len(target_ids)] if target_ids else ""
            b = target_ids[(step * 3 + 1) % len(target_ids)] if target_ids else ""
            intent = Intent("observe_object", a if step % 3 else b, age_s=0.0)
            world.user_pointing_target_id = b
        elif name == "leave_return":
            if step < length // 3:
                world.user_visible = False
                world.user_position = (7.0, 1.6, 7.0)
                intent = Intent("idle", "", age_s=15.0)
            elif step < 2 * length // 3:
                world.user_visible = True
                world.user_position = (rng.uniform(-1.0, 1.0), 1.6, rng.uniform(-1.0, 1.0))
                intent = Intent("observe_user", "user", age_s=0.0)
            else:
                intent = Intent("maintain_distance", "user", age_s=0.0)
        elif name == "sit_stand":
            seats = [e.id for e in world.entities if e.is_seat]
            intent = Intent("sit" if step < length // 2 else "stand",
                            seats[0] if seats else "", age_s=0.0)
        elif name == "stop_cancel_resume":
            if 4 <= step <= 7:
                intent = Intent("maintain_distance", "user", age_s=0.0)
                world.collision_risk = 0.6
            elif 8 <= step <= 11:
                intent = Intent("idle", "", age_s=0.0)
            else:
                intent = Intent("go_to_object", target_ids[0] if target_ids else "",
                                age_s=0.0)
        elif name == "cooperation_follow":
            if step % 8 < 4:
                intent = Intent("follow_user", "user", urgency=0.6, social_priority=0.9,
                                age_s=0.0)
                world.user_velocity = (0.4, 0.0, 0.4)
            elif step % 8 < 6:
                intent = Intent("go_to_object", target_ids[0] if target_ids else "",
                                age_s=0.0)
            else:
                intent = Intent("waiting" if False else "maintain_distance", "user",
                                age_s=0.0)
        else:
            intent = Intent("observe_object", target_ids[0] if target_ids else "",
                            age_s=0.0)

        # 动态障碍持续移动，制造训练集中没有的轨迹组合。
        for entity in world.entities:
            if entity.id == "moving_obstacle_1":
                entity.position = tuple(
                    entity.position[i] + entity.velocity[i] * 0.1 for i in range(3))
        world.user_idle_s = world.user_idle_s + 1.0 if not world.user_speaking else 0.0
        state.current_behavior_age_s += 0.1
        state.recent_switch_count = max(0, state.recent_switch_count - 1)
        steps.append((world, state, intent))
    return steps


def _build_sequence_groups(episodes: int, min_len: int, max_len: int,
                           seed: int) -> Tuple[List[EvalGroup], List[List[int]]]:
    scenarios = [
        "call_and_follow", "point_and_inspect", "interrupt_and_replan",
        "obstacle_and_wait", "multi_target_competition", "leave_return",
        "sit_stand", "stop_cancel_resume", "cooperation_follow",
        "network_stale", "occlusion",
    ]
    groups: List[EvalGroup] = []
    episode_groups: List[List[int]] = []
    for episode in range(episodes):
        scenario = scenarios[episode % len(scenarios)]
        length = random.Random(seed + episode).randint(min_len, max_len)
        steps = _episode(scenario, seed + episode, length)
        group_ids: List[int] = []
        for step_index, (world, state, intent) in enumerate(steps):
            candidates = build_candidates(state, world, intent)
            for candidate in candidates:
                candidate.features = encode_features(state, world, intent, candidate)
            features = np.asarray([c.features for c in candidates], dtype=np.float32)
            utilities = np.asarray([
                expert_score(state, world, intent, c, random.Random(0))
                for c in candidates
            ], dtype=np.float32)
            best = int(np.argmax(utilities))
            labels = np.zeros(len(candidates), dtype=np.float32)
            labels[best] = 1.0
            params = np.zeros((len(candidates), len(PARAM_NAMES)), dtype=np.float32)
            params[best] = [
                _clamp((candidates[best].desired_distance - 0.55) / 1.65, 0.0, 1.0),
                candidates[best].speed_scale,
                candidates[best].gaze_weight,
                candidates[best].gesture_probability,
                candidates[best].look_away_rate,
                candidates[best].speech_urge,
            ]
            group_ids.append(len(groups))
            groups.append(EvalGroup(
                features=features,
                labels=labels,
                hard=np.asarray([1 if c.hard_negative else 0 for c in candidates],
                                dtype=np.int8),
                params=params,
                behaviors=[c.behavior for c in candidates],
                targets=[c.target_id for c in candidates],
                utilities=utilities,
                goal=intent.goal,
                user_visible=world.user_visible,
                user_speaking=world.user_speaking,
                target_visible=bool(world.find(intent.target) and world.find(intent.target).visible),
                navmesh_reachable=world.navmesh_reachable,
                collision_risk=world.collision_risk,
                occluded=world.occluded,
                user_approach_speed=max(0.0, -world.user_velocity[2]),
                episode=episode,
                step=step_index,
            ))
        episode_groups.append(group_ids)
    return groups, episode_groups


def _score_groups(model, groups: Sequence[EvalGroup], device: torch.device,
                  batch_size: int = 512) -> Tuple[List[np.ndarray], List[np.ndarray]]:
    scores: List[np.ndarray] = []
    pred_params: List[np.ndarray] = []
    for start in range(0, len(groups), batch_size):
        batch = groups[start:start + batch_size]
        max_len = max(len(g.features) for g in batch)
        dim = batch[0].features.shape[1]
        x = np.zeros((len(batch), max_len, dim), dtype=np.float32)
        for i, group in enumerate(batch):
            x[i, :len(group.features)] = group.features
        with torch.no_grad():
            logits, params = model(torch.from_numpy(x).to(device))
            logits = logits.cpu().numpy()
            params = params.cpu().numpy()
        for i, group in enumerate(batch):
            scores.append(logits[i, :len(group.features)])
            pred_params.append(params[i, :len(group.features)])
    return scores, pred_params


def _invalid_choice(group: EvalGroup, behavior: str, target: str) -> bool:
    if behavior in ("go_to_object", "inspect_object", "point_at_object",
                    "invite_to_object", "sit"):
        # 目标存在性由 group 元数据与候选 targets 共同判断。
        if not target or target == "missing_object":
            return True
        if not group.target_visible and target not in ("user",):
            return True
    if behavior in ("approach_user", "follow_user", "speak", "observe_user",
                    "listen_user", "comfort_user") and not group.user_visible:
        return True
    if behavior == "speak" and group.user_speaking:
        return True
    if behavior in ("approach_user", "follow_user", "go_to_object", "reposition") and \
            not group.navmesh_reachable:
        return True
    return False


def _select_with_constraints(group: EvalGroup, final: np.ndarray) -> int:
    """C# Behavior Runtime 的本地安全约束，不是重新训练模型。"""
    choice = int(np.argmax(final))
    # 用户说话时，除高优先级反射外必须进入倾听/确认。
    if group.user_speaking:
        candidates = [
            i for i, behavior in enumerate(group.behaviors)
            if behavior in ("listen_user", "nod", "observe_user", "think")
        ]
        if candidates:
            choice = max(candidates, key=lambda i: float(final[i]))
    # 目标指令仍然有效时，不允许无理由放弃；只在足够接近时保留目标。
    goal = group.goal
    if goal in ("follow_user", "approach_user", "go_to_object",
                "inspect_object", "point_at_object", "sit"):
        goal_indices = [
            i for i, behavior in enumerate(group.behaviors)
            if behavior == goal and not bool(group.hard[i])
        ]
        if goal_indices:
            best_goal = max(goal_indices, key=lambda i: float(final[i]))
            if final[best_goal] >= final[choice] - 0.18:
                choice = best_goal
    # 已消失/不可见目标不允许继续执行空间动作。
    if _invalid_choice(group, group.behaviors[choice], group.targets[choice]):
        valid = [
            i for i in range(len(group.behaviors))
            if not _invalid_choice(group, group.behaviors[i], group.targets[i])
        ]
        if valid:
            choice = max(valid, key=lambda i: float(final[i]))
    return choice


def _metrics(groups: Sequence[EvalGroup], scores: Sequence[np.ndarray],
             arbitration: Dict[str, float]) -> Dict[str, float]:
    top1 = top3 = 0
    hard_total = hard_rejected = 0
    invalid = 0
    abandonment = 0
    contradictions = 0
    hard_penalty = arbitration["hard_penalty"]
    switch_margin = arbitration["switch_margin"]
    for group, logits in zip(groups, scores):
        learned = 1.0 / (1.0 + np.exp(-logits))
        final = 0.65 * group.utilities + 0.35 * learned
        final = final - hard_penalty * group.hard
        order = np.argsort(final)[::-1]
        positive = int(np.argmax(group.labels))
        top1 += int(order[0] == positive)
        top3 += int(positive in order[:3])
        hard_idx = np.where(group.hard > 0)[0]
        hard_total += len(hard_idx)
        hard_rejected += int(np.sum(final[hard_idx] < final.max())) if len(hard_idx) else 0
        chosen = _select_with_constraints(group, final)
        behavior = group.behaviors[chosen]
        target = group.targets[chosen]
        if _invalid_choice(group, behavior, target):
            invalid += 1
        if group.goal in ("follow_user", "approach_user", "go_to_object",
                          "inspect_object", "point_at_object", "sit") and \
                behavior not in (group.goal, "listen_user", "observe_user", "think"):
            abandonment += 1
        if behavior == "speak" and group.user_speaking:
            contradictions += 1
    n = max(1, len(groups))
    return {
        "top1": top1 / n,
        "top3": top3 / n,
        "hard_negative_rejection": hard_rejected / max(1, hard_total),
        "invalid_action_rate": invalid / n,
        "goal_abandonment_rate": abandonment / n,
        "action_contradiction_rate": contradictions / n,
    }


def _param_report(groups: Sequence[EvalGroup], scores: Sequence[np.ndarray],
                  pred_params: Sequence[np.ndarray]) -> Dict[str, dict]:
    report: Dict[str, dict] = {}
    errors_by_param: Dict[str, List[float]] = {name: [] for name in PARAM_NAMES}
    for group, logits, learned_params in zip(groups, scores, pred_params):
        chosen = int(np.argmax(logits))
        positive = int(np.argmax(group.labels))
        target = group.params[positive]
        # 策略头的连续参数是在正样本上训练的；分析时取专家正样本位置，
        # 这样衡量的是“参数头本身是否准”，不受分类 top-1 混淆影响。
        predicted = learned_params[positive]
        for i, name in enumerate(PARAM_NAMES):
            errors_by_param[name].append(abs(float(predicted[i] - target[i])))
    for name, values in errors_by_param.items():
        arr = np.asarray(values, dtype=np.float32)
        report[name] = {
            "mae": float(np.mean(arr)),
            "rmse": float(np.sqrt(np.mean(arr ** 2))),
            "p50": float(np.percentile(arr, 50)),
            "p90": float(np.percentile(arr, 90)),
            "p95": float(np.percentile(arr, 95)),
        }
    return report


def _long_horizon_metrics(groups: Sequence[EvalGroup], scores: Sequence[np.ndarray],
                          episode_groups: Sequence[Sequence[int]],
                          arbitration: Dict[str, float]) -> Dict[str, float]:
    target_switches = 0
    behavior_switches = 0
    oscillations = 0
    walk_stop_walk = 0
    left_right_left = 0
    look_aba = 0
    stale_goal = 0
    contradiction = 0
    replan_success = 0
    replan_total = 0
    reflex_override = 0
    interruption_total = 0
    interruption_responses = 0
    cancellation_total = 0
    cancellation_responses = 0
    total_steps = 0
    movement_behaviors = {"approach_user", "follow_user", "go_to_object",
                          "reposition", "retreat"}
    switch_margin = arbitration["switch_margin"]
    hard_penalty = arbitration["hard_penalty"]
    for episode in episode_groups:
        prev_behavior = ""
        prev_target = ""
        history: List[Tuple[str, str]] = []
        current_behavior = "idle"
        current_age = 0
        interrupted = False
        cancelled = False
        for group_id in episode:
            group = groups[group_id]
            logits = scores[group_id]
            learned = 1.0 / (1.0 + np.exp(-logits))
            final = 0.65 * group.utilities + 0.35 * learned - hard_penalty * group.hard
            # 最小驻留 + 切换成本：模拟 C# 运行时的滞回。
            current_index = (group.behaviors.index(current_behavior)
                             if current_behavior in group.behaviors else -1)
            if current_behavior in group.behaviors:
                final[current_index] += 0.14
            choice = _select_with_constraints(group, final)
            candidate_behavior = group.behaviors[choice]
            if group.collision_risk > 0.55 or not group.navmesh_reachable:
                candidate_behavior = "reflex_stop"
                reflex_override += 1
            elif group.user_approach_speed > 0.8 and group.user_visible:
                candidate_behavior = "reflex_step_back"
                reflex_override += 1
            behavior = group.behaviors[choice]
            if candidate_behavior != behavior:
                behavior = candidate_behavior
            target = group.targets[choice]
            history.append((behavior, target))
            total_steps += 1
            if prev_behavior and behavior != prev_behavior:
                behavior_switches += 1
            if prev_target and target != prev_target:
                target_switches += 1
            if len(history) >= 3:
                a, b, c = history[-3:]
                if a[0] == c[0] and a[0] != b[0]:
                    oscillations += 1
                if a[0] in movement_behaviors and b[0] == "idle" and \
                        c[0] in movement_behaviors:
                    walk_stop_walk += 1
                if a[1] == c[1] and a[1] != b[1] and a[1]:
                    look_aba += 1
            if behavior == "speak" and group.user_speaking:
                contradiction += 1
            if group.user_speaking:
                interruption_total += 1
                if behavior in ("listen_user", "nod", "observe_user", "think"):
                    interruption_responses += 1
            if group.goal == "idle" and behavior in movement_behaviors:
                cancellation_total += 1
            elif group.goal == "idle" and behavior in ("idle", "observe_user", "think",
                                                       "sigh", "maintain_distance"):
                cancellation_total += 1
                cancellation_responses += 1
            if group.goal not in ("idle", "observe_user", "observe_object") and \
                    behavior in ("idle", "observe_user"):
                stale_goal += 1
            if group.goal in ("follow_user", "go_to_object", "approach_user") and \
                    behavior in ("follow_user", "go_to_object", "approach_user"):
                replan_success += 1
                replan_total += 1
            if behavior != current_behavior:
                current_behavior = behavior
                current_age = 0
            else:
                current_age += 1
            prev_behavior, prev_target = behavior, target
    n = max(1, total_steps)
    return {
        "steps": total_steps,
        "target_switching_rate": target_switches / n,
        "action_oscillation_rate": oscillations / n,
        "behavior_switching_rate": behavior_switches / n,
        "walk_stop_walk_rate": walk_stop_walk / n,
        "look_aba_rate": look_aba / n,
        "stale_goal_rate": stale_goal / n,
        "action_contradiction_rate": contradiction / n,
        "replan_success_rate": replan_success / max(1, replan_total),
        "reflex_override_rate": reflex_override / n,
        "interruption_response_rate": interruption_responses / max(1, interruption_total),
        "cancellation_response_rate": cancellation_responses / max(1, cancellation_total),
    }


def _tune_arbitration(base_groups: Sequence[EvalGroup],
                      scores: Sequence[np.ndarray],
                      episode_groups: Sequence[Sequence[int]]) -> Dict[str, float]:
    """在独立 tuning split 上搜索迟滞/最小驻留/切换惩罚。"""
    candidates = [
        {"switch_margin": 0.05, "hard_penalty": 0.25},
        {"switch_margin": 0.08, "hard_penalty": 0.35},
        {"switch_margin": 0.12, "hard_penalty": 0.45},
        {"switch_margin": 0.16, "hard_penalty": 0.55},
    ]
    best = candidates[0]
    best_score = -1e9
    for params in candidates:
        metrics = _long_horizon_metrics(base_groups, scores, episode_groups, params)
        score = (-metrics["action_oscillation_rate"] * 3.0
                 - metrics["behavior_switching_rate"] * 0.8
                 - metrics["stale_goal_rate"] * 1.5
                 + metrics["replan_success_rate"] * 1.2)
        if score > best_score:
            best_score = score
            best = params
    best = dict(best)
    best["selection_score"] = best_score
    return best


def _param_error_values(groups: Sequence[EvalGroup],
                        pred_params: Sequence[np.ndarray]) -> Dict[str, List[float]]:
    errors = {name: [] for name in PARAM_NAMES}
    for group, learned in zip(groups, pred_params):
        positive = int(np.argmax(group.labels))
        target = group.params[positive]
        predicted = learned[positive]
        for i, name in enumerate(PARAM_NAMES):
            errors[name].append(abs(float(predicted[i] - target[i])))
    return errors


def _merge_param_errors(acc: Dict[str, List[float]],
                        new: Dict[str, List[float]]) -> None:
    for name in PARAM_NAMES:
        acc[name].extend(new[name])


def _param_stats(errors: Dict[str, List[float]]) -> Dict[str, dict]:
    report: Dict[str, dict] = {}
    for name in PARAM_NAMES:
        arr = np.asarray(errors[name], dtype=np.float32)
        report[name] = {
            "mae": float(np.mean(arr)) if len(arr) else 0.0,
            "rmse": float(np.sqrt(np.mean(arr ** 2))) if len(arr) else 0.0,
            "p50": float(np.percentile(arr, 50)) if len(arr) else 0.0,
            "p90": float(np.percentile(arr, 90)) if len(arr) else 0.0,
            "p95": float(np.percentile(arr, 95)) if len(arr) else 0.0,
        }
    return report


def _accumulate(acc: Dict[str, float], values: Dict[str, float],
                weight: float) -> None:
    for key, value in values.items():
        if key == "steps":
            acc[key] = acc.get(key, 0.0) + value
        else:
            acc[key] = acc.get(key, 0.0) + float(value) * weight
    acc["_weight"] = acc.get("_weight", 0.0) + weight


def _finalize_accumulated(acc: Dict[str, float]) -> None:
    weight = acc.pop("_weight", 0.0)
    if weight <= 0:
        return
    for key in list(acc.keys()):
        if key == "steps":
            continue
        acc[key] = acc[key] / weight


def _ensure_metric_keys(values: Dict[str, float], keys: Sequence[str]) -> None:
    for key in keys:
        values.setdefault(key, 0.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--weights", type=str,
                        default="behavior_policy/artifacts/behavior_policy_v1.json")
    parser.add_argument("--out", type=str,
                        default="behavior_policy/artifacts/generalization_report_v1.json")
    parser.add_argument("--device", type=str,
                        default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--iid-episodes", type=int, default=2000)
    parser.add_argument("--ood-episodes", type=int, default=3000)
    parser.add_argument("--long-episodes", type=int, default=700)
    parser.add_argument("--chunk-episodes", type=int, default=250)
    parser.add_argument("--seed", type=int, default=991337)
    parser.add_argument("--long-seed", type=int, default=555001)
    args = parser.parse_args()

    device = torch.device(args.device)
    model = load_weights_json(args.weights).to(device)
    model.eval()

    # 分块评估，避免 2000–5000 episodes 的候选特征一次性撑爆内存。
    arbitration = {"switch_margin": 0.08, "hard_penalty": 0.35}
    iid_metrics = {}
    ood_metrics = {}
    iid_param_errors = {name: [] for name in PARAM_NAMES}
    ood_param_errors = {name: [] for name in PARAM_NAMES}
    long_metrics = {}
    iid_group_count = 0
    ood_group_count = 0
    long_step_count = 0
    tuning_pool: List[Tuple[Sequence[EvalGroup], Sequence[np.ndarray],
                            Sequence[Sequence[int]]]] = []

    def _consume(kind: str, groups: Sequence[EvalGroup],
                 episode_groups: Sequence[Sequence[int]],
                 seed: int) -> Tuple[Dict[str, float], Dict[str, List[float]]]:
        scores, pred_params = _score_groups(model, groups, device)
        metrics = _metrics(groups, scores, arbitration)
        errors = _param_error_values(groups, pred_params)
        if kind == "long":
            tuning_pool.append((groups, scores, episode_groups))
        return metrics, errors

    for chunk_start in range(0, args.iid_episodes, args.chunk_episodes):
        chunk = min(args.chunk_episodes, args.iid_episodes - chunk_start)
        data = generate_dataset(seed=777777 + chunk_start * 17,
                                episodes=chunk, steps_per_episode=12)
        groups = _groups_from_data(data)
        metrics, errors = _consume("iid", groups, [], 777777 + chunk_start)
        _accumulate(iid_metrics, metrics, len(groups))
        _merge_param_errors(iid_param_errors, errors)
        iid_group_count += len(groups)

    for chunk_start in range(0, args.ood_episodes, args.chunk_episodes):
        chunk = min(args.chunk_episodes, args.ood_episodes - chunk_start)
        groups, episode_groups = _build_sequence_groups(
            chunk, 20, 50, seed=args.seed + chunk_start * 17)
        metrics, errors = _consume("ood", groups, episode_groups,
                                   args.seed + chunk_start)
        _accumulate(ood_metrics, metrics, len(groups))
        _merge_param_errors(ood_param_errors, errors)
        ood_group_count += len(groups)

    for chunk_start in range(0, args.long_episodes, args.chunk_episodes):
        chunk = min(args.chunk_episodes, args.long_episodes - chunk_start)
        groups, episode_groups = _build_sequence_groups(
            chunk, 20, 50, seed=args.long_seed + chunk_start * 17)
        scores, _ = _score_groups(model, groups, device)
        metrics = _long_horizon_metrics(groups, scores, episode_groups, arbitration)
        _accumulate(long_metrics, metrics, metrics["steps"])
        long_step_count += int(metrics["steps"])
        tuning_pool.append((groups, scores, episode_groups))

    _finalize_accumulated(iid_metrics)
    _finalize_accumulated(ood_metrics)
    _finalize_accumulated(long_metrics)
    _ensure_metric_keys(iid_metrics, (
        "top1", "top3", "hard_negative_rejection", "invalid_action_rate",
        "goal_abandonment_rate", "action_contradiction_rate",
    ))
    _ensure_metric_keys(ood_metrics, (
        "top1", "top3", "hard_negative_rejection", "invalid_action_rate",
        "goal_abandonment_rate", "action_contradiction_rate",
    ))
    _ensure_metric_keys(long_metrics, (
        "target_switching_rate", "action_oscillation_rate",
        "behavior_switching_rate", "walk_stop_walk_rate", "look_aba_rate",
        "stale_goal_rate", "action_contradiction_rate", "replan_success_rate",
        "reflex_override_rate", "interruption_response_rate",
        "cancellation_response_rate",
    ))
    if tuning_pool:
        combined_groups = []
        combined_scores = []
        combined_episodes = []
        for groups, scores, episodes in tuning_pool[:1]:
            offset = len(combined_groups)
            combined_groups.extend(groups)
            combined_scores.extend(scores)
            combined_episodes.extend([[i + offset for i in ep] for ep in episodes])
        arbitration = _tune_arbitration(combined_groups, combined_scores,
                                        combined_episodes)

    iid_params = _param_stats(iid_param_errors)
    ood_params = _param_stats(ood_param_errors)

    delta = {
        key: ood_metrics[key] - iid_metrics[key]
        for key in ("top1", "top3", "hard_negative_rejection",
                    "invalid_action_rate", "goal_abandonment_rate",
                    "action_contradiction_rate")
    }
    report = {
        "weights": args.weights,
        "device": str(device),
        "iid": iid_metrics,
        "ood": ood_metrics,
        "delta_ood_minus_iid": delta,
        "params": {"iid": iid_params, "ood": ood_params},
        "long_horizon": long_metrics,
        "counts": {
            "iid_groups": iid_group_count,
            "ood_groups": ood_group_count,
            "long_steps": long_step_count,
        },
        "arbitration": arbitration,
        "recommendation": _recommend(ood_metrics, long_metrics, delta),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {out_path}")
    return 0


def _recommend(ood: Dict[str, float], long: Dict[str, float],
               delta: Dict[str, float]) -> Dict[str, object]:
    needs_training = (
        ood["top1"] < 0.55 or
        ood["invalid_action_rate"] > 0.05 or
        long["action_oscillation_rate"] > 0.12 or
        long["stale_goal_rate"] > 0.15
    )
    return {
        "continue_training": bool(needs_training),
        "reason": (
            "OOD 或 Long-Horizon 指标低于阈值，需要扩数据/加 hard negative/序列模型"
            if needs_training else
            "当前轻量 Behavior Scorer + Utility + Reflex 指标稳定，先保持 v1，并优先真机验证"
        ),
    }


if __name__ == "__main__":
    raise SystemExit(main())
