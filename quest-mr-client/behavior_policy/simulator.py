"""自动行为仿真器。

目标不是做一个“游戏”，而是生成大量真实约束下的行为决策样本：
WorldState + CharacterState + AvatarIntent + 候选行为 → 专家偏好 + 硬负样本。

所有数据都是自动生成，不需要手工逐条编写。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .schema import (
    BEHAVIOR_NAMES,
    CANDIDATE_FEATURE_COUNT,
    FEATURE_NAMES,
    GOAL_FEATURE_COUNT,
    GOAL_GROUPS,
    INPUT_DIM,
    MOTION_COST,
    PARAM_NAMES,
    STATE_FEATURE_COUNT,
    TARGET_TYPE_FEATURES,
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _dist(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _norm3(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    length = math.sqrt(sum(x * x for x in v))
    if length < 1e-6:
        return (0.0, 0.0, 0.0)
    return tuple(x / length for x in v)  # type: ignore[return-value]


def _signed_angle_deg(forward: Tuple[float, float, float],
                      direction: Tuple[float, float, float]) -> float:
    f = _norm3(forward)
    d = _norm3(direction)
    dot = _clamp(f[0] * d[0] + f[2] * d[2], -1.0, 1.0)
    angle = math.degrees(math.acos(dot))
    cross_y = f[2] * d[0] - f[0] * d[2]
    return -angle if cross_y > 0 else angle


@dataclass
class Entity:
    id: str
    label: str
    kind: str
    position: Tuple[float, float, float]
    velocity: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    confidence: float = 0.8
    last_seen_age_s: float = 0.0
    visible: bool = True
    reachable: bool = True
    is_seat: bool = False
    is_surface: bool = False
    is_small_object: bool = False
    interest: float = 0.3
    affordances: Tuple[str, ...] = ()


@dataclass
class World:
    scene_version: int = 1
    status: str = "ready"
    world_age_s: float = 0.0
    user_visible: bool = True
    user_position: Tuple[float, float, float] = (0.0, 1.6, 0.0)
    user_velocity: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    user_forward: Tuple[float, float, float] = (0.0, 0.0, 1.0)
    user_speaking: bool = False
    user_looking_at_avatar: bool = False
    user_pointing_target_id: str = ""
    user_idle_s: float = 10.0
    navmesh_generated: bool = True
    navmesh_reachable: bool = True
    collision_risk: float = 0.0
    nearest_obstacle_m: float = 2.0
    occluded: bool = False
    scene_stable: bool = True
    entities: List[Entity] = field(default_factory=list)

    def find(self, entity_id: str) -> Optional[Entity]:
        for entity in self.entities:
            if entity.id == entity_id:
                return entity
        return None

    def nearest_interesting(self, max_distance: float = 6.0) -> Optional[Entity]:
        best = None
        best_score = -1e9
        for entity in self.entities:
            if entity.kind != "object" or not entity.visible:
                continue
            distance = _dist(self.user_position, entity.position)
            if distance > max_distance:
                continue
            score = entity.interest * 2.0 - distance * 0.25 + entity.confidence * 0.5
            if score > best_score:
                best_score = score
                best = entity
        return best


@dataclass
class Character:
    energy: float = 0.8
    patience: float = 0.7
    curiosity: float = 0.6
    social_battery: float = 0.75
    stress: float = 0.1
    emotion_label: str = "neutral"
    emotion_intensity: float = 0.3
    emotion_valence: float = 0.0
    emotion_arousal: float = 0.3
    affinity: float = 55.0
    trust: float = 55.0
    familiarity: float = 20.0
    relationship_tier: str = "acquaintance"
    speech_state: str = "idle"
    active_behavior: str = "idle"
    active_target_id: str = ""
    attention_target_id: str = ""
    attention_focus: float = 0.5
    last_interaction_age_s: float = 10.0
    salient_memory_count: int = 0
    has_unfinished_topic: bool = False
    current_behavior_age_s: float = 2.0
    recent_switch_count: int = 0
    last_autonomy_request_age_s: float = 999.0


@dataclass
class Intent:
    goal: str = "idle"
    target: str = ""
    attention: str = ""
    emotion: str = "neutral"
    emotion_intensity: float = 0.2
    behavior_style: str = "neutral"
    urgency: float = 0.0
    social_priority: float = 0.5
    duration_hint_ms: int = 0
    speaking: bool = False
    age_s: float = 0.0
    spatial_target_id: str = ""
    desired_distance_m: float = 0.9


@dataclass
class Candidate:
    behavior: str
    target_id: str = ""
    desired_distance: float = 0.9
    speed_scale: float = 0.7
    gaze_weight: float = 0.7
    gesture_probability: float = 0.2
    look_away_rate: float = 0.15
    speech_urge: float = 0.05
    energy_cost: float = 0.1
    interruptibility: float = 1.0
    novelty: float = 0.4
    hard_negative: bool = False
    reason: str = ""
    features: Optional[List[float]] = None


def _goal_group(goal: str) -> int:
    return GOAL_GROUPS.get(goal, 0)


def _target_type(target_id: str, target: Optional[Entity]) -> int:
    if target_id == "user":
        return 1
    if target is None:
        return 0
    if target.is_seat:
        return 4
    if target.is_surface:
        return 5
    return 3 if target.kind == "object" else 2


def _relationship_norm(tier: str) -> float:
    return {
        "stranger": 0.0,
        "acquaintance": 0.25,
        "friend": 0.5,
        "close_friend": 0.75,
        "intimate": 1.0,
    }.get(tier, 0.4)


def _motion_cost(behavior: str) -> float:
    return MOTION_COST.get(behavior, 0.2)


def _affordance_match(behavior: str, target: Optional[Entity]) -> float:
    if behavior == "sit":
        return 1.0 if target and target.is_seat else 0.0
    if behavior in ("inspect_object", "observe_object", "point_at_object"):
        return 1.0 if target and target.is_small_object else 0.2
    if behavior == "go_to_object":
        return 0.8 if target else 0.0
    return 0.5


def _distance_fit(behavior: str, world: World, candidate: Candidate) -> float:
    if not world.user_visible:
        return 0.5
    if behavior in ("approach_user", "follow_user"):
        return 1.0 if _dist(world.user_position, (0, 0, 0)) > candidate.desired_distance + 0.2 else 0.0
    if behavior == "retreat":
        return 1.0 if _dist(world.user_position, (0, 0, 0)) < 0.9 else 0.1
    if behavior == "maintain_distance":
        return 1.0 if abs(_dist(world.user_position, (0, 0, 0)) - candidate.desired_distance) < 0.35 else 0.2
    return 0.6


def _social_fit(behavior: str, state: Character, world: World) -> float:
    social = behavior in {
        "observe_user", "listen_user", "speak", "comfort_user", "wave", "nod",
    }
    if not social:
        return 0.5
    return _clamp(
        state.social_battery * 0.5 + state.affinity / 200.0 +
        (0.25 if world.user_speaking else 0.0),
        0.0, 1.0,
    )


def _emotion_match(behavior: str, state: Character) -> float:
    valence = state.emotion_valence
    arousal = state.emotion_arousal
    if behavior in ("laugh", "wave"):
        return _clamp(valence * 0.7 + arousal * 0.3, 0.0, 1.0)
    if behavior in ("comfort_user", "listen_user"):
        return _clamp((1.0 - valence) * 0.3 + state.patience * 0.7, 0.0, 1.0)
    if behavior == "sigh":
        return _clamp((1.0 - valence) * 0.6 + (1.0 - arousal) * 0.4, 0.0, 1.0)
    if behavior == "surprised":
        return _clamp(arousal, 0.0, 1.0)
    if behavior == "think":
        return _clamp(state.curiosity, 0.0, 1.0)
    return 0.5


def _repetition_penalty(state: Character) -> float:
    return _clamp(state.recent_switch_count / 8.0, 0.0, 1.0) * 0.5 + \
        (1.0 - _clamp(state.current_behavior_age_s / 8.0, 0.0, 1.0)) * 0.5


def encode_features(state: Character, world: World, intent: Intent,
                    candidate: Candidate) -> List[float]:
    """必须与 Unity BehaviorFeatureEncoder.Encode 一致。"""
    features: List[float] = []

    features += [
        state.energy,
        state.patience,
        state.curiosity,
        state.social_battery,
        state.stress,
        (state.emotion_valence + 1.0) * 0.5,
        state.emotion_arousal,
        state.emotion_intensity,
        state.affinity / 100.0,
        state.trust / 100.0,
        state.familiarity / 100.0,
        intent.urgency,
        intent.social_priority,
        _clamp(intent.age_s / 10.0, 0.0, 1.0),
        1.0 if world.user_visible else 0.0,
        _clamp(_dist(world.user_position, (0, 0, 0)) / 5.0, 0.0, 1.0),
        _clamp(_signed_angle_deg(world.user_forward,
                                 _norm3(world.user_position)) / 180.0, -1.0, 1.0),
        _clamp(max(0.0, _approach_speed(world)) / 2.0, 0.0, 1.0),
        _clamp(max(0.0, -_approach_speed(world)) / 2.0, 0.0, 1.0),
        1.0 if world.user_speaking else 0.0,
        1.0 if world.user_looking_at_avatar else 0.0,
        1.0 if world.user_pointing_target_id else 0.0,
        _clamp(world.user_idle_s / 30.0, 0.0, 1.0),
        1.0 if state.speech_state == "speaking" else 0.0,
        1.0 if state.speech_state == "listening" else 0.0,
        1.0 if state.speech_state == "thinking" else 0.0,
        _clamp(state.current_behavior_age_s / 10.0, 0.0, 1.0),
        _clamp(state.recent_switch_count / 10.0, 0.0, 1.0),
        _clamp(world.collision_risk, 0.0, 1.0),
        _clamp(world.nearest_obstacle_m / 2.0, 0.0, 1.0),
        1.0 if world.navmesh_generated and world.navmesh_reachable else 0.0,
    ]

    target = world.find(candidate.target_id)
    features += [
        1.0 if target else 0.0,
        _clamp(_dist(world.user_position, target.position) / 6.0, 0.0, 1.0)
        if target else 1.0,
        _clamp(_signed_angle_deg(world.user_forward,
                                 tuple(target.position[i] - world.user_position[i]
                                       for i in range(3))) / 180.0, -1.0, 1.0)
        if target else 1.0,
        1.0 if target and target.visible else 0.0,
        _clamp(target.last_seen_age_s / 30.0, 0.0, 1.0) if target else 1.0,
        1.0 if target and target.is_seat else 0.0,
        1.0 if target and target.is_surface else 0.0,
        1.0 if target and target.is_small_object else 0.0,
        target.interest if target else 0.0,
        _clamp(len(world.entities) / 12.0, 0.0, 1.0),
        _nearest_object_distance_norm(world),
        1.0 if world.scene_stable else 0.0,
        _clamp(world.world_age_s / 10.0, 0.0, 1.0),
        1.0 if intent.age_s > 12.0 else 0.0,
        _clamp(state.salient_memory_count / 6.0, 0.0, 1.0),
        _relationship_norm(state.relationship_tier),
        _clamp(state.last_interaction_age_s / 60.0, 0.0, 1.0),
        1.0 if state.last_autonomy_request_age_s > 45.0 else 0.0,
        _repetition_penalty(state),
        _distance_preference_error(world, candidate),
        candidate.energy_cost,
    ]

    goal_onehot = [0.0] * GOAL_FEATURE_COUNT
    goal_onehot[_goal_group(intent.goal)] = 1.0
    behavior_onehot = [0.0] * len(BEHAVIOR_NAMES)
    if candidate.behavior in BEHAVIOR_NAMES:
        behavior_onehot[BEHAVIOR_NAMES.index(candidate.behavior)] = 1.0
    target_onehot = [0.0] * len(TARGET_TYPE_FEATURES)
    target_onehot[_target_type(candidate.target_id, target)] = 1.0
    features += goal_onehot + behavior_onehot + target_onehot

    features += [
        _affordance_match(candidate.behavior, target),
        _distance_fit(candidate.behavior, world, candidate),
        _social_fit(candidate.behavior, state, world),
        candidate.energy_cost,
        candidate.interruptibility,
        _motion_cost(candidate.behavior),
        candidate.novelty,
        _emotion_match(candidate.behavior, state),
        1.0 if candidate.behavior == intent.goal else 0.0,
    ]
    if len(features) != INPUT_DIM:
        raise AssertionError(f"特征维度 {len(features)} != {INPUT_DIM}")
    return features


def _nearest_object_distance_norm(world: World) -> float:
    best = 99.0
    for entity in world.entities:
        if entity.kind == "object" and entity.visible:
            best = min(best, _dist(world.user_position, entity.position))
    return _clamp(best / 6.0, 0.0, 1.0)


def _approach_speed(world: World) -> float:
    direction = _norm3(world.user_position)
    if direction == (0.0, 0.0, 0.0):
        return 0.0
    return sum(world.user_velocity[i] * direction[i] for i in range(3))


def _distance_preference_error(world: World, candidate: Candidate) -> float:
    if not world.user_visible:
        return 0.0
    return _clamp(abs(_dist(world.user_position, (0, 0, 0)) -
                      candidate.desired_distance) / 3.0, 0.0, 1.0)


def _candidate(behavior: str, target: str = "", desired: float = 0.9,
               speed: float = 0.7, gaze: float = 0.7, gesture: float = 0.2,
               look_away: float = 0.15, speech: float = 0.05,
               energy: float = 0.1, interruptible: float = 1.0,
               novelty: float = 0.4, hard_negative: bool = False,
               reason: str = "") -> Candidate:
    return Candidate(
        behavior=behavior,
        target_id=target,
        desired_distance=desired,
        speed_scale=speed,
        gaze_weight=gaze,
        gesture_probability=gesture,
        look_away_rate=look_away,
        speech_urge=speech,
        energy_cost=energy,
        interruptibility=interruptible,
        novelty=novelty,
        hard_negative=hard_negative,
        reason=reason,
    )


def build_candidates(state: Character, world: World, intent: Intent) -> List[Candidate]:
    """生成候选；包含真实选择与硬负样本。"""
    user_visible = world.user_visible
    user_distance = _dist(world.user_position, (0, 0, 0))
    desired = _desired_distance(state, intent)
    target = world.find(intent.target) or world.nearest_interesting()
    target_visible = bool(target and target.visible)
    social_available = state.social_battery > 0.15 and state.energy > 0.08
    candidates: List[Candidate] = []

    candidates.append(_candidate("idle", desired=desired, gaze=0.15,
                                 gesture=0.05, energy=0.0, novelty=0.15))
    candidates.append(_candidate("observe_user", "user", desired=desired,
                                 gaze=0.72, gesture=0.08, energy=0.0,
                                 hard_negative=not user_visible))
    candidates.append(_candidate("listen_user", "user", desired=desired,
                                 gaze=0.85, gesture=0.04, energy=0.02,
                                 hard_negative=not user_visible))
    candidates.append(_candidate("speak", "user", desired=desired, gaze=0.75,
                                 gesture=0.35, speech=0.8, energy=0.08,
                                 interruptible=0.8,
                                 hard_negative=not user_visible or world.user_speaking))
    candidates.append(_candidate("think", target.id if target else "",
                                 desired=desired, gaze=0.45, gesture=0.08,
                                 look_away=0.22, energy=0.01))

    if target is None:
        candidates.append(_candidate("go_to_object", "", desired=desired,
                                     energy=0.8, interruptible=0.2,
                                     hard_negative=True, reason="target_missing"))
        candidates.append(_candidate("observe_object", "", desired=desired,
                                     gaze=0.0, energy=0.05,
                                     hard_negative=True, reason="target_missing"))
    else:
        target_distance = _dist(world.user_position, target.position)
        candidates.append(_candidate("observe_object", target.id, desired=desired,
                                     gaze=0.78, gesture=0.08,
                                     hard_negative=not target_visible))
        candidates.append(_candidate("go_to_object", target.id,
                                     desired=max(0.45, desired), speed=0.72,
                                     gaze=0.6, gesture=0.12, energy=0.8,
                                     interruptible=0.65,
                                     hard_negative=not target_visible or
                                     not world.navmesh_reachable or state.energy < 0.12))
        candidates.append(_candidate("inspect_object", target.id,
                                     desired=max(0.45, desired * 0.75), speed=0.55,
                                     gaze=0.9, gesture=0.3, energy=0.45,
                                     interruptible=0.7,
                                     hard_negative=not target_visible or
                                     not target.is_small_object))
        candidates.append(_candidate("point_at_object", target.id, desired=desired,
                                     gaze=0.65, gesture=0.65, energy=0.25,
                                     interruptible=0.85,
                                     hard_negative=not target_visible))
        candidates.append(_candidate("invite_to_object", target.id,
                                     desired=max(0.55, desired), speed=0.4,
                                     gaze=0.7, gesture=0.5, energy=0.55,
                                     interruptible=0.65,
                                     hard_negative=not target_visible or
                                     not user_visible))
        candidates.append(_candidate("sit", target.id, desired=0.35,
                                     speed=0.0, gaze=0.4, gesture=0.05,
                                     energy=0.55, interruptible=0.6,
                                     hard_negative=not target.is_seat or
                                     not target_visible))

    candidates += [
        _candidate("approach_user", "user", desired=desired, speed=0.62,
                   gaze=0.7, gesture=0.08, energy=0.7, interruptible=0.7,
                   hard_negative=not user_visible or not social_available or
                   user_distance <= desired),
        _candidate("maintain_distance", "user", desired=desired, speed=0.25,
                   gaze=0.55, gesture=0.04, energy=0.18,
                   hard_negative=not user_visible),
        _candidate("retreat", "user", desired=max(0.8, desired), speed=0.5,
                   gaze=0.5, gesture=0.02, energy=0.45,
                   hard_negative=not user_visible or user_distance > 1.0),
        _candidate("follow_user", "user", desired=desired, speed=0.68,
                   gaze=0.72, gesture=0.05, energy=0.85, interruptible=0.55,
                   hard_negative=not user_visible or not social_available or
                   state.affinity < 45.0),
        _candidate("wave", "user", desired=desired, gaze=0.7, gesture=0.85,
                   energy=0.2, interruptible=0.8,
                   hard_negative=not user_visible),
        _candidate("nod", "user", desired=desired, gaze=0.75, gesture=0.8,
                   energy=0.08, interruptible=0.95,
                   hard_negative=not user_visible),
        _candidate("shake_head", "user", desired=desired, gaze=0.6,
                   gesture=0.7, energy=0.08, interruptible=0.9,
                   hard_negative=not user_visible),
        _candidate("laugh", "user", desired=desired, gaze=0.55,
                   gesture=0.6, energy=0.12, interruptible=0.85,
                   hard_negative=not user_visible),
        _candidate("sigh", desired=desired, gaze=0.25, gesture=0.35,
                   look_away=0.22, energy=0.05),
        _candidate("surprised", "user", desired=desired, gaze=0.65,
                   gesture=0.55, energy=0.05, interruptible=0.95,
                   hard_negative=not user_visible),
        _candidate("comfort_user", "user", desired=max(0.55, desired),
                   speed=0.2, gaze=0.8, gesture=0.35, energy=0.3,
                   interruptible=0.75,
                   hard_negative=not user_visible or state.patience < 0.2),
    ]

    # 自主行为候选：用户长时间沉默且 intent 已过期时出现。
    if intent.age_s >= 8.0:
        candidates += [
            _candidate("observe_object", target.id if target else "",
                       desired=desired, gaze=0.65, gesture=0.08,
                       look_away=0.2, energy=0.01,
                       hard_negative=target is None),
            _candidate("reposition", desired=desired, speed=0.35, gaze=0.4,
                       gesture=0.08, look_away=0.22, energy=0.6,
                       interruptible=0.8,
                       hard_negative=state.energy < 0.25 or
                       not world.navmesh_reachable),
            _candidate("observe_user", "user", desired=desired, gaze=0.7,
                       gesture=0.06, energy=0.0,
                       hard_negative=not user_visible),
        ]

    # 额外硬负样本：不必要移动/抢话/高频切换/不存在目标。
    candidates += [
        _candidate("approach_user", "user", desired=desired, speed=0.7,
                   energy=0.8, interruptible=0.5, hard_negative=True,
                   reason="unnecessary_movement"),
        _candidate("go_to_object", target.id if target else "missing",
                   desired=desired, speed=0.7, energy=0.9, interruptible=0.4,
                   hard_negative=True, reason="unnecessary_movement"),
        _candidate("speak", "user", desired=desired, gaze=0.6, gesture=0.5,
                   speech=0.8, energy=0.1, interruptible=0.4,
                   hard_negative=world.user_speaking, reason="speak_while_user_speaks"),
        _candidate("observe_object", target.id if target else "missing",
                   desired=desired, gaze=0.9, energy=0.0,
                   hard_negative=True, reason="target_missing_or_invisible"),
        _candidate("reposition", desired=desired, speed=0.4, energy=0.7,
                   interruptible=0.4, hard_negative=state.recent_switch_count > 2,
                   reason="high_frequency_switching"),
    ]
    return candidates


def _desired_distance(state: Character, intent: Intent) -> float:
    distance = 1.1 - (state.affinity - 50.0) / 200.0
    distance -= max(0.0, state.emotion_valence) * 0.15
    if intent.behavior_style == "shy":
        distance += 0.35
    if intent.behavior_style == "warm":
        distance -= 0.2
    if intent.spatial_target_id == "user":
        distance = intent.desired_distance_m
    return _clamp(distance, 0.55, 2.2)


def expert_score(state: Character, world: World, intent: Intent,
                 candidate: Candidate, rng: random.Random) -> float:
    """专家偏好：自然、稳定、符合情绪/关系/上下文。"""
    score = 0.0
    goal = intent.goal
    user_distance = _dist(world.user_position, (0, 0, 0))
    target = world.find(candidate.target_id)
    behavior = candidate.behavior

    if behavior == goal:
        score += 0.65
    if goal in ("follow_user", "approach_user") and behavior == goal:
        score += intent.urgency * 0.55 + intent.social_priority * 0.25
    if behavior == "idle" and intent.urgency > 0.5:
        score -= 0.35 + intent.urgency * 0.45
    if world.user_speaking:
        if behavior in ("listen_user", "nod", "observe_user"):
            score += 0.65
        if behavior == "speak":
            score -= 0.9
    if not world.user_visible:
        if behavior in ("observe_user", "listen_user", "speak", "approach_user",
                        "follow_user", "wave", "comfort_user"):
            score -= 0.85
    if candidate.hard_negative:
        score -= 1.2
    if behavior in ("go_to_object", "inspect_object", "invite_to_object", "sit"):
        if target is None or not target.visible:
            score -= 1.1
        elif target.is_small_object:
            score += 0.25
    if behavior in ("approach_user", "follow_user", "go_to_object", "reposition"):
        score -= (1.0 - state.energy) * 0.7
        score -= 0.25
    if behavior == "approach_user":
        if user_distance > 1.4:
            score += 0.35
        if user_distance < 0.75:
            score -= 0.75
        if state.affinity < 45:
            score -= 0.4
    if behavior == "retreat":
        score += 0.55 if user_distance < 0.65 else -0.35
    if behavior == "maintain_distance":
        score += 0.35 if 0.8 <= user_distance <= 1.8 else -0.2
    if behavior == "listen_user" and state.patience < 0.25:
        score -= 0.45
    if behavior == "comfort_user":
        if state.emotion_valence < -0.2:
            score += 0.45
        if state.patience < 0.25:
            score -= 0.5
    if behavior in ("wave", "laugh") and state.emotion_valence > 0.25:
        score += 0.35
    if behavior == "sigh" and state.emotion_valence < -0.25:
        score += 0.35
    if behavior == "think" and state.curiosity > 0.6:
        score += 0.3
    if behavior == "observe_object" and target and target.interest > 0.5:
        score += 0.3
    if behavior == "reposition":
        if state.recent_switch_count > 2:
            score -= 0.9
        if state.energy < 0.3:
            score -= 0.6
    if behavior == "idle":
        score += 0.12 if intent.age_s < 6 else -0.05
    if behavior == "observe_user":
        score += 0.1 if world.user_visible else -0.5
    if behavior == "nod" and world.user_speaking:
        score += 0.2
    if behavior == "speak" and intent.speaking:
        score += 0.5
    if behavior in ("reflex_stop", "reflex_step_back", "reflex_dodge",
                    "reflex_freeze", "reflex_look_at_threat"):
        # 反射层由本地硬覆盖处理，正常行为策略不主动选择反射动作。
        score -= 1.5
    if state.recent_switch_count > 4 and behavior != state.active_behavior:
        score -= 0.35
    if behavior == state.active_behavior:
        score += 0.12 * _clamp(state.current_behavior_age_s / 5.0, 0.0, 1.0)
    score += rng.uniform(-0.035, 0.035)
    return score


def _softmax(values: List[float], temperature: float = 0.18) -> List[float]:
    if not values:
        return []
    max_v = max(values)
    exps = [math.exp((v - max_v) / temperature) for v in values]
    total = sum(exps)
    return [e / total for e in exps]


def _params_for(candidate: Candidate) -> List[float]:
    return [
        _clamp((candidate.desired_distance - 0.55) / 1.65, 0.0, 1.0),
        candidate.speed_scale,
        candidate.gaze_weight,
        candidate.gesture_probability,
        candidate.look_away_rate,
        candidate.speech_urge,
    ]


def _random_entity(rng: random.Random, idx: int, room_half: float = 2.4) -> Entity:
    choices = [
        ("table", "anchor", False, True, False, 0.35, ("surface", "reachable")),
        ("chair", "anchor", True, False, False, 0.3, ("seat", "rest")),
        ("sofa", "anchor", True, False, False, 0.3, ("seat", "rest")),
        ("plant", "anchor", False, False, False, 0.55, ("decor",)),
        ("cup", "object", False, False, True, 0.75, ("small_object", "movable")),
        ("phone", "object", False, False, True, 0.8, ("small_object", "movable")),
        ("book", "object", False, False, True, 0.65, ("small_object", "movable")),
    ]
    label, kind, seat, surface, small, interest, affordances = rng.choice(choices)
    return Entity(
        id=f"{label}_{idx}",
        label=label,
        kind=kind,
        position=(
            rng.uniform(-room_half, room_half),
            rng.uniform(0.25, 0.9),
            rng.uniform(-room_half, room_half),
        ),
        confidence=rng.uniform(0.65, 0.98),
        visible=rng.random() > 0.06,
        is_seat=seat,
        is_surface=surface,
        is_small_object=small,
        interest=interest,
        affordances=affordances,
    )


def _random_world(rng: random.Random) -> World:
    world = World(
        scene_version=rng.randint(1, 20),
        status="ready",
        world_age_s=rng.uniform(0.0, 1.5),
        user_visible=True,
        user_position=(rng.uniform(-0.6, 0.6), 1.6, rng.uniform(-0.6, 0.6)),
        user_velocity=(rng.uniform(-0.5, 0.5), 0.0, rng.uniform(-0.8, 0.8)),
        user_forward=(rng.uniform(-0.5, 0.5), 0.0, 1.0),
        user_speaking=rng.random() < 0.22,
        user_looking_at_avatar=rng.random() < 0.65,
        user_idle_s=rng.uniform(0.0, 120.0),
        navmesh_generated=True,
        navmesh_reachable=rng.random() > 0.05,
        collision_risk=rng.uniform(0.0, 0.12),
        nearest_obstacle_m=rng.uniform(0.5, 3.0),
        occluded=rng.random() < 0.08,
        scene_stable=rng.random() > 0.08,
    )
    world.entities = [_random_entity(rng, i) for i in range(rng.randint(3, 8))]
    if rng.random() < 0.45:
        world.user_pointing_target_id = rng.choice(world.entities).id
    return world


def _random_character(rng: random.Random) -> Character:
    affinity = rng.uniform(25.0, 90.0)
    if affinity < 40:
        tier = "acquaintance"
    elif affinity < 60:
        tier = "friend"
    elif affinity < 78:
        tier = "close_friend"
    else:
        tier = "intimate"
    valence = rng.uniform(-0.8, 0.9)
    arousal = rng.uniform(0.05, 0.95)
    label = (
        "happy" if valence > 0.45 else
        "sad" if valence < -0.45 else
        "curious" if arousal > 0.65 and valence >= -0.2 else
        "tired" if arousal < 0.2 else
        "neutral"
    )
    return Character(
        energy=rng.uniform(0.08, 1.0),
        patience=rng.uniform(0.12, 1.0),
        curiosity=rng.uniform(0.1, 1.0),
        social_battery=rng.uniform(0.1, 1.0),
        stress=rng.uniform(0.0, 0.7),
        emotion_label=label,
        emotion_intensity=rng.uniform(0.1, 0.9),
        emotion_valence=valence,
        emotion_arousal=arousal,
        affinity=affinity,
        trust=rng.uniform(30.0, 92.0),
        familiarity=rng.uniform(5.0, 95.0),
        relationship_tier=tier,
        speech_state=rng.choice(["idle", "idle", "listening", "thinking", "speaking"]),
        active_behavior=rng.choice(BEHAVIOR_NAMES[:24]),
        active_target_id="",
        current_behavior_age_s=rng.uniform(0.2, 12.0),
        recent_switch_count=rng.randint(0, 7),
        last_interaction_age_s=rng.uniform(0.0, 180.0),
        salient_memory_count=rng.randint(0, 5),
        has_unfinished_topic=rng.random() < 0.25,
    )


def _random_intent(rng: random.Random, world: World, step: int) -> Intent:
    goals = [
        "idle", "observe_user", "listen_user", "speak", "think",
        "observe_object", "approach_user", "maintain_distance", "retreat",
        "follow_user", "go_to_object", "point_at_object", "inspect_object",
        "invite_to_object", "sit", "wave", "nod", "shake_head", "laugh",
        "sigh", "surprised", "comfort_user", "reposition",
    ]
    goal = rng.choice(goals)
    target = ""
    if goal in ("observe_object", "go_to_object", "point_at_object",
                "inspect_object", "invite_to_object", "sit"):
        entity = rng.choice(world.entities) if world.entities else None
        if entity is not None and rng.random() > 0.05:
            target = entity.id
    if goal in ("observe_user", "listen_user", "speak", "approach_user",
                "maintain_distance", "retreat", "follow_user", "wave",
                "nod", "shake_head", "laugh", "surprised", "comfort_user"):
        target = "user"
    return Intent(
        goal=goal,
        target=target,
        attention=target,
        emotion=rng.choice(["neutral", "happy", "calm", "curious", "shy",
                            "excited", "sad", "tired", "surprised"]),
        emotion_intensity=rng.uniform(0.1, 0.9),
        behavior_style=rng.choice(["neutral", "casual", "warm", "shy",
                                   "playful", "serious", "tired", "excited"]),
        urgency=rng.uniform(0.0, 1.0),
        social_priority=rng.uniform(0.1, 1.0),
        speaking=goal == "speak" or rng.random() < 0.18,
        age_s=rng.uniform(0.0, 18.0) if step else 0.0,
        spatial_target_id=target,
        desired_distance_m=rng.uniform(0.55, 2.0),
    )


def generate_dataset(seed: int = 20260909, episodes: int = 500,
                     steps_per_episode: int = 12) -> Dict[str, object]:
    """生成训练数据。返回 numpy-free 的 Python 结构，调用方可直接写 npz。"""
    rng = random.Random(seed)
    features: List[List[float]] = []
    labels: List[float] = []
    soft_targets: List[float] = []
    params: List[List[float]] = []
    hard_negatives: List[int] = []
    candidate_behaviors: List[str] = []
    candidate_targets: List[str] = []
    candidate_utilities: List[float] = []
    groups: List[int] = []
    group_meta: List[Dict[str, object]] = []

    for episode in range(episodes):
        world = _random_world(rng)
        state = _random_character(rng)
        intent = _random_intent(rng, world, 0)
        scenario = _scenario_for(episode, rng)
        for step in range(steps_per_episode):
            _advance_episode(world, state, intent, rng, scenario, step)
            candidates = build_candidates(state, world, intent)
            scores = [expert_score(state, world, intent, c, rng) for c in candidates]
            soft = _softmax(scores)
            best_index = max(range(len(candidates)), key=lambda i: scores[i])
            best = candidates[best_index]
            best_params = _params_for(best)
            for i, candidate in enumerate(candidates):
                features.append(encode_features(state, world, intent, candidate))
                labels.append(1.0 if i == best_index else 0.0)
                soft_targets.append(soft[i])
                params.append(best_params if i == best_index else [0.0] * len(PARAM_NAMES))
                hard_negatives.append(1 if candidate.hard_negative else 0)
                candidate_behaviors.append(candidate.behavior)
                candidate_targets.append(candidate.target_id)
                candidate_utilities.append(scores[i])
                groups.append(len(group_meta))
            group_meta.append({
                "episode": episode,
                "step": step,
                "scenario": scenario,
                "intent_goal": intent.goal,
                "intent_target": intent.target,
                "best_behavior": best.behavior,
                "best_target": best.target_id,
                "user_distance": _dist(world.user_position, (0, 0, 0)),
                "user_speaking": world.user_speaking,
                "user_visible": world.user_visible,
            })
            state.current_behavior_age_s += 0.1
            state.recent_switch_count = max(0, state.recent_switch_count - 1)
    return {
        "features": features,
        "labels": labels,
        "soft_targets": soft_targets,
        "params": params,
        "hard_negatives": hard_negatives,
        "candidate_behaviors": candidate_behaviors,
        "candidate_targets": candidate_targets,
        "candidate_utilities": candidate_utilities,
        "groups": groups,
        "group_meta": group_meta,
        "feature_names": FEATURE_NAMES,
        "behavior_names": BEHAVIOR_NAMES,
        "param_names": PARAM_NAMES,
    }


def _scenario_for(index: int, rng: random.Random) -> str:
    scenarios = [
        "call_character", "user_approach", "user_leave", "user_return",
        "user_silence", "point_object", "look_object", "follow_me",
        "sit_here", "dont_come", "interrupt", "emotion_shift",
        "two_targets", "target_missing", "network_stale",
    ]
    return scenarios[index % len(scenarios)]


def _advance_episode(world: World, state: Character, intent: Intent,
                     rng: random.Random, scenario: str, step: int) -> None:
    """推进仿真状态；用脚本化场景覆盖关键行为。"""
    world.scene_version += 1 if rng.random() < 0.03 else 0
    world.world_age_s = rng.uniform(0.0, 2.5)
    intent.age_s += 0.1

    if scenario == "user_approach":
        world.user_position = (
            world.user_position[0] * 0.96,
            1.6,
            world.user_position[2] * 0.96,
        )
        world.user_velocity = (-0.45, 0.0, 0.0)
    elif scenario == "user_leave":
        world.user_position = (world.user_position[0] + 0.7, 1.6,
                               world.user_position[2] + 0.7)
        world.user_visible = step < 6
        world.user_velocity = (0.8, 0.0, 0.8)
    elif scenario == "user_return":
        world.user_visible = step >= 2
        if world.user_visible:
            world.user_position = (rng.uniform(-0.3, 0.3), 1.6,
                                   rng.uniform(-0.3, 0.3))
    elif scenario == "user_silence":
        world.user_speaking = False
        world.user_idle_s += 1.0
        intent.age_s += 0.25
    elif scenario == "point_object":
        world.user_pointing_target_id = (
            rng.choice(world.entities).id if world.entities else "")
        world.user_speaking = step % 3 == 0
    elif scenario == "look_object":
        target = rng.choice(world.entities) if world.entities else None
        world.user_pointing_target_id = target.id if target else ""
        world.user_speaking = False
    elif scenario == "follow_me":
        world.user_velocity = (0.7, 0.0, 0.7)
        world.user_position = (world.user_position[0] + 0.18, 1.6,
                               world.user_position[2] + 0.18)
    elif scenario == "sit_here":
        seats = [e for e in world.entities if e.is_seat]
        intent.goal = "sit"
        intent.target = seats[0].id if seats else ""
    elif scenario == "dont_come":
        intent.goal = "maintain_distance"
        intent.target = "user"
        world.user_velocity = (0.0, 0.0, 0.0)
    elif scenario == "interrupt":
        world.user_speaking = step % 4 != 0
        state.speech_state = "speaking" if step % 4 == 0 else "listening"
    elif scenario == "emotion_shift":
        state.emotion_valence = math.sin(step * 0.8) * 0.8
        state.emotion_arousal = 0.3 + abs(math.cos(step * 0.5)) * 0.6
        state.emotion_label = (
            "happy" if state.emotion_valence > 0.3 else
            "sad" if state.emotion_valence < -0.3 else "neutral")
    elif scenario == "two_targets":
        intent.goal = rng.choice(["observe_object", "point_at_object"])
        if world.entities:
            intent.target = rng.choice(world.entities).id
    elif scenario == "target_missing":
        intent.goal = "observe_object"
        intent.target = "missing_object"
    elif scenario == "network_stale":
        world.world_age_s = 8.0 + step
        world.navmesh_reachable = False
    elif scenario == "call_character":
        world.user_speaking = step < 2
        world.user_looking_at_avatar = True
        intent.goal = "listen_user" if world.user_speaking else "observe_user"
        intent.target = "user"

    # 连续状态自然变化，避免每步独立随机造成不真实跳变。
    state.energy = _clamp(state.energy + rng.uniform(-0.015, 0.008), 0.0, 1.0)
    state.patience = _clamp(state.patience + rng.uniform(-0.01, 0.012), 0.0, 1.0)
    state.social_battery = _clamp(
        state.social_battery + rng.uniform(-0.012, 0.01), 0.0, 1.0)
    state.stress = _clamp(state.stress + rng.uniform(-0.01, 0.012), 0.0, 1.0)
    state.current_behavior_age_s += 0.1
    state.recent_switch_count = max(0, state.recent_switch_count + (1 if rng.random() < 0.04 else 0))
    for entity in world.entities:
        if rng.random() < 0.08:
            entity.position = (
                entity.position[0] + rng.uniform(-0.05, 0.05),
                entity.position[1],
                entity.position[2] + rng.uniform(-0.05, 0.05),
            )


__all__ = [
    "Candidate",
    "Character",
    "Entity",
    "Intent",
    "World",
    "build_candidates",
    "encode_features",
    "expert_score",
    "generate_dataset",
]
