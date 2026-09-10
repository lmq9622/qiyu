"""行为策略固定 schema。

必须与 Unity `BehaviorFeatureEncoder.cs` / `CharacterTypes.cs` 完全一致。
任何顺序变化都必须同时升级模型版本并重新训练。
"""
from __future__ import annotations

SCHEMA_VERSION = "1.0"
MODEL_TYPE = "mlp_candidate_scorer"
MODEL_VERSION = "behavior-policy-v1"

BEHAVIOR_NAMES = [
    "idle",
    "listen_user",
    "think",
    "speak",
    "observe_user",
    "observe_object",
    "approach_user",
    "maintain_distance",
    "retreat",
    "follow_user",
    "go_to_object",
    "point_at_object",
    "inspect_object",
    "invite_to_object",
    "sit",
    "stand",
    "reposition",
    "wave",
    "nod",
    "shake_head",
    "laugh",
    "sigh",
    "surprised",
    "comfort_user",
    "reflex_stop",
    "reflex_step_back",
    "reflex_dodge",
    "reflex_freeze",
    "reflex_look_at_threat",
]

PARAM_NAMES = [
    "desired_distance",
    "speed_scale",
    "gaze_weight",
    "gesture_probability",
    "look_away_rate",
    "speech_urge",
]

PARAM_SCALE = [1.65, 1.0, 1.0, 1.0, 1.0, 1.0]
PARAM_OFFSET = [0.55, 0.0, 0.0, 0.0, 0.0, 0.0]

STATE_FEATURES = [
    "energy",
    "patience",
    "curiosity",
    "social_battery",
    "stress",
    "emotion_valence",
    "emotion_arousal",
    "emotion_intensity",
    "affinity_norm",
    "trust_norm",
    "familiarity_norm",
    "intent_urgency",
    "intent_social_priority",
    "intent_age_norm",
    "user_visible",
    "user_distance_norm",
    "user_angle_norm",
    "user_approach_norm",
    "user_retreat_norm",
    "user_speaking",
    "user_looking_at_avatar",
    "user_pointing",
    "user_idle_norm",
    "avatar_speaking",
    "avatar_listening",
    "avatar_thinking",
    "current_behavior_age_norm",
    "recent_switch_norm",
    "collision_risk",
    "obstacle_distance_norm",
    "navmesh_ok",
    "target_present",
    "target_distance_norm",
    "target_angle_norm",
    "target_visible",
    "target_age_norm",
    "target_is_seat",
    "target_is_surface",
    "target_is_small",
    "target_interest",
    "object_count_norm",
    "nearest_interest_distance_norm",
    "scene_stable",
    "world_age_norm",
    "intent_stale",
    "memory_salient_norm",
    "relationship_tier_norm",
    "last_interaction_age_norm",
    "autonomy_available",
    "repetition_penalty",
    "distance_pref_error",
    "candidate_energy_cost_state",
]

GOAL_FEATURES = [f"goal_{i}" for i in range(8)]
BEHAVIOR_FEATURES = [f"behavior_{i}" for i in range(len(BEHAVIOR_NAMES))]
TARGET_TYPE_FEATURES = [f"target_type_{i}" for i in range(6)]
CANDIDATE_FEATURES = [
    "candidate_affordance_match",
    "candidate_distance_fit",
    "candidate_social_fit",
    "candidate_energy_cost",
    "candidate_interruptibility",
    "candidate_motion_cost",
    "candidate_novelty",
    "candidate_emotion_match",
    "candidate_goal_match",
]

FEATURE_NAMES = (
    STATE_FEATURES + GOAL_FEATURES + BEHAVIOR_FEATURES +
    TARGET_TYPE_FEATURES + CANDIDATE_FEATURES
)

STATE_FEATURE_COUNT = len(STATE_FEATURES)
GOAL_FEATURE_COUNT = len(GOAL_FEATURES)
BEHAVIOR_FEATURE_COUNT = len(BEHAVIOR_FEATURES)
TARGET_TYPE_FEATURE_COUNT = len(TARGET_TYPE_FEATURES)
CANDIDATE_FEATURE_COUNT = len(CANDIDATE_FEATURES)
INPUT_DIM = len(FEATURE_NAMES)

GOAL_GROUPS = {
    "idle": 0,
    "observe_user": 1,
    "observe_object": 1,
    "listen_user": 2,
    "speak": 2,
    "think": 2,
    "approach_user": 3,
    "maintain_distance": 3,
    "retreat": 3,
    "follow_user": 3,
    "go_to_object": 4,
    "inspect_object": 4,
    "invite_to_object": 4,
    "sit": 4,
    "stand": 4,
    "reposition": 4,
    "wave": 5,
    "nod": 5,
    "shake_head": 5,
    "laugh": 5,
    "sigh": 5,
    "surprised": 5,
    "point_at_object": 6,
    "comfort_user": 7,
}

MOTION_COST = {
    "idle": 0.05,
    "listen_user": 0.05,
    "think": 0.05,
    "speak": 0.05,
    "observe_user": 0.05,
    "observe_object": 0.05,
    "approach_user": 0.8,
    "maintain_distance": 0.6,
    "retreat": 0.6,
    "follow_user": 0.8,
    "go_to_object": 0.8,
    "point_at_object": 0.35,
    "inspect_object": 0.45,
    "invite_to_object": 0.55,
    "sit": 0.6,
    "stand": 0.6,
    "reposition": 0.8,
    "wave": 0.35,
    "nod": 0.05,
    "shake_head": 0.05,
    "laugh": 0.05,
    "sigh": 0.05,
    "surprised": 0.05,
    "comfort_user": 0.3,
    "reflex_stop": 0.05,
    "reflex_step_back": 0.6,
    "reflex_dodge": 0.7,
    "reflex_freeze": 0.05,
    "reflex_look_at_threat": 0.05,
}


def assert_schema() -> None:
    if INPUT_DIM != 104:
        raise AssertionError(f"INPUT_DIM 必须为 104，当前 {INPUT_DIM}")
    if len(BEHAVIOR_NAMES) != 29:
        raise AssertionError(f"行为数必须为 29，当前 {len(BEHAVIOR_NAMES)}")


assert_schema()

__all__ = [
    "BEHAVIOR_NAMES",
    "CANDIDATE_FEATURE_COUNT",
    "FEATURE_NAMES",
    "GOAL_FEATURES",
    "GOAL_FEATURE_COUNT",
    "GOAL_GROUPS",
    "INPUT_DIM",
    "MODEL_TYPE",
    "MODEL_VERSION",
    "MOTION_COST",
    "PARAM_NAMES",
    "PARAM_OFFSET",
    "PARAM_SCALE",
    "SCHEMA_VERSION",
    "STATE_FEATURES",
    "STATE_FEATURE_COUNT",
    "TARGET_TYPE_FEATURES",
    "TARGET_TYPE_FEATURE_COUNT",
]
