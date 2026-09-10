"""Protocol v1/v1.1 Pydantic 模型。

v1.1 只做向后兼容扩展：
- 旧 AvatarIntent.action / SpatialAction 继续可用；
- 新客户端优先消费 goal/target/attention 等高层字段；
- LLM 永远不产出骨骼、路径点或逐帧控制量。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "1.0.0"
CHARACTER_SCHEMA_VERSION = "1.1"


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Quat(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    w: float = 1.0


class Pose(BaseModel):
    position: Vec3 = Field(default_factory=Vec3)
    rotation: Quat = Field(default_factory=Quat)
    scale: Optional[Vec3] = None


class Bounds(BaseModel):
    min: Vec3
    max: Vec3


class SceneAnchor(BaseModel):
    id: str
    label: Literal[
        "room", "floor", "wall", "ceiling", "table", "chair", "sofa",
        "door", "window", "storage", "plant", "screen", "other", "unknown"
    ] = "unknown"
    parent_id: Optional[str] = None
    pose: Pose = Field(default_factory=Pose)
    extents: Optional[Vec3] = None
    bounds: Optional[Bounds] = None
    mesh_available: bool = False
    updated_at_ms: int = 0


class TrackedObject(BaseModel):
    id: str
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox_2d: Optional[list[float]] = None
    position: Optional[Vec3] = None
    velocity: Optional[Vec3] = None
    anchor_id: Optional[str] = None
    source: Literal["scene_api", "local_detector", "cloud_vision", "user_placed"] = "local_detector"
    last_seen_at_ms: int = 0
    affordances: list[str] = Field(default_factory=list)
    state: Literal["visible", "occluded", "moving", "lost", "unknown"] = "visible"


class UserPose(BaseModel):
    head: Optional[Pose] = None
    left_hand: Optional[Pose] = None
    right_hand: Optional[Pose] = None
    gaze_direction: Optional[Vec3] = None
    velocity: Optional[Vec3] = None
    source: Literal["headset", "body_tracking", "estimated"] = "headset"
    is_speaking: bool = False
    gaze_target_id: str = ""
    pointing_target_id: str = ""
    last_spoke_at_ms: int = 0


class AvatarPose(BaseModel):
    id: str = ""
    pose: Pose = Field(default_factory=Pose)
    visible: bool = True
    state: Literal[
        "idle", "moving", "speaking", "listening", "thinking", "busy", "hidden"
    ] = "idle"


class NavmeshInfo(BaseModel):
    generated: bool = False
    version: int = 0
    bounds: Optional[Bounds] = None
    walkable_area_m2: float = 0.0


class WorldInteraction(BaseModel):
    """Quest 本地计算的交互级特征，避免后端重复做几何计算。"""

    user_distance_m: float = 0.0
    user_approach_speed_mps: float = 0.0
    user_relative_angle_deg: float = 0.0
    occluded: bool = False
    collision_risk: float = 0.0
    nearest_obstacle_m: float = 0.0
    navmesh_reachable: bool = True


class WorldState(BaseModel):
    """WorldState：Quest 真实空间状态。

    旧客户端只填 v1 字段仍然合法；新客户端追加 schema_version/world_epoch/
    interaction 等字段。
    """

    model_config = ConfigDict(extra="ignore")
    protocol_version: Literal["1.0.0"] = PROTOCOL_VERSION
    schema_version: str = "1.0"
    ts: int = 0
    room_id: str = ""
    world_epoch: int = 0
    scene_version: int = 1
    status: Literal["scanning", "ready", "stale", "lost"] = "scanning"
    anchors: list[SceneAnchor] = Field(default_factory=list)
    objects: list[TrackedObject] = Field(default_factory=list)
    user: UserPose = Field(default_factory=UserPose)
    avatar: AvatarPose = Field(default_factory=AvatarPose)
    navmesh: NavmeshInfo = Field(default_factory=NavmeshInfo)
    interaction: WorldInteraction = Field(default_factory=WorldInteraction)


AvatarGoalLiteral = Literal[
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
]

BehaviorStyleLiteral = Literal[
    "neutral", "casual", "warm", "shy", "playful",
    "serious", "tired", "excited", "guarded",
]

EmotionLiteral = Literal[
    "neutral", "happy", "calm", "sad", "annoyed", "angry",
    "excited", "shy", "confused", "tired", "surprised",
    "curious", "embarrassed",
]


class SpatialHint(BaseModel):
    """高层空间提示；禁止路径点、坐标序列和关节角度。"""

    model_config = ConfigDict(extra="forbid")
    target_id: str = ""
    desired_distance_m: float = Field(default=0.9, ge=0.2, le=5.0)
    face_target: bool = True


class AvatarIntent(BaseModel):
    """LLM/Qiyu 后端 → Quest Avatar Runtime。

    `goal/target/attention` 是新版唯一应消费的高层意图。
    旧 `action/gesture` 字段只用于 v1.0 客户端兼容，不参与新运行时决策。
    """

    model_config = ConfigDict(extra="ignore")
    schema_version: str = CHARACTER_SCHEMA_VERSION
    id: str = ""
    intent_id: str = ""
    ts: int = 0
    goal: AvatarGoalLiteral = "idle"
    target: str = ""
    attention: str = ""
    behavior_style: BehaviorStyleLiteral = "neutral"
    urgency: float = Field(default=0.0, ge=0.0, le=1.0)
    social_priority: float = Field(default=0.5, ge=0.0, le=1.0)
    duration_hint_ms: int = Field(default=0, ge=0, le=600000)
    speech_act: str = ""
    priority: int = Field(default=1, ge=0, le=5)
    interrupt_policy: Literal[
        "never", "on_higher_priority", "on_barge_in", "always"
    ] = "on_higher_priority"
    emotion: EmotionLiteral = "neutral"
    intensity: float = Field(default=0.0, ge=0.0, le=1.0)
    emotion_intensity: float = Field(default=0.0, ge=0.0, le=1.0)
    expression: str = ""
    gesture: str = ""
    action: Literal[
        "idle", "look_at_user", "look_away", "look_at_object", "nod",
        "shake", "wave", "lean_in", "sigh", "laugh", "blush"
    ] = "idle"
    speaking: bool = False
    prosody: Optional[dict] = None
    text: str = ""
    duration_ms: int = 0
    cancel_on_barge_in: bool = True
    spatial_hint: Optional[SpatialHint] = None


class EmotionState(BaseModel):
    label: EmotionLiteral = "neutral"
    intensity: float = Field(default=0.0, ge=0.0, le=1.0)
    valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    arousal: float = Field(default=0.0, ge=0.0, le=1.0)


class RelationshipState(BaseModel):
    tier: str = "acquaintance"
    affinity: float = Field(default=50.0, ge=0.0, le=100.0)
    trust: float = Field(default=50.0, ge=0.0, le=100.0)
    familiarity: float = Field(default=0.0, ge=0.0, le=100.0)


class DrivesState(BaseModel):
    patience: float = Field(default=0.7, ge=0.0, le=1.0)
    energy: float = Field(default=0.8, ge=0.0, le=1.0)
    curiosity: float = Field(default=0.6, ge=0.0, le=1.0)
    social_battery: float = Field(default=0.75, ge=0.0, le=1.0)
    stress: float = Field(default=0.1, ge=0.0, le=1.0)


class MemoryContext(BaseModel):
    salient_count: int = 0
    last_interaction_age_s: float = 0.0
    has_unfinished_topic: bool = False
    relationship_notes: list[str] = Field(default_factory=list)


class AttentionState(BaseModel):
    target_id: str = ""
    focus: float = Field(default=0.5, ge=0.0, le=1.0)
    gaze_weight: float = Field(default=0.7, ge=0.0, le=1.0)


class SpeechState(BaseModel):
    state: Literal[
        "idle", "listening", "thinking", "speaking", "interrupted"
    ] = "idle"
    response_id: str = ""
    cancel_on_barge_in: bool = True


class CharacterState(BaseModel):
    """角色内部状态；由 Quest 本地维护，后端可同步快照用于推理与日志。"""

    model_config = ConfigDict(extra="ignore")
    schema_version: str = CHARACTER_SCHEMA_VERSION
    character_id: str = "qiyu"
    ts: int = 0
    emotion: EmotionState = Field(default_factory=EmotionState)
    relationship: RelationshipState = Field(default_factory=RelationshipState)
    drives: DrivesState = Field(default_factory=DrivesState)
    memory_context: MemoryContext = Field(default_factory=MemoryContext)
    attention: AttentionState = Field(default_factory=AttentionState)
    speech: SpeechState = Field(default_factory=SpeechState)
    active_behavior: str = "idle"
    active_goal: str = "idle"
    active_target_id: str = ""


class BehaviorState(BaseModel):
    """Quest 本地行为运行时遥测。"""

    model_config = ConfigDict(extra="ignore")
    schema_version: str = CHARACTER_SCHEMA_VERSION
    ts: int = 0
    active_behavior: str = "idle"
    goal: str = "idle"
    target_id: str = ""
    priority: int = Field(default=0, ge=0, le=5)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    policy_source: str = "utility"
    since_ms: int = 0
    interruptible: bool = True
    locomotion: dict = Field(default_factory=dict)
    attention: dict = Field(default_factory=dict)
    motion: dict = Field(default_factory=dict)
    reflex: dict = Field(default_factory=dict)
    latency_ms: dict = Field(default_factory=dict)


class InteractionEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str = CHARACTER_SCHEMA_VERSION
    ts: int = 0
    event_type: Literal[
        "user_near", "user_far", "user_left", "user_returned",
        "user_speech_start", "user_speech_end", "barge_in",
        "gaze_target", "point_target", "object_appeared", "object_lost",
        "collision", "danger", "occlusion", "stuck", "gesture",
    ]
    target_id: str = ""
    value: float = 0.0
    data: dict = Field(default_factory=dict)
    gesture: str = ""
    intent: str = ""
    direction: Optional[Vec3] = None
    distance_m: float = 0.0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    emotion_hint: str = ""
    source: str = ""


class AutonomyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: str = CHARACTER_SCHEMA_VERSION
    reason: str = ""
    urgency: float = Field(default=0.0, ge=0.0, le=1.0)
    social_priority: float = Field(default=0.5, ge=0.0, le=1.0)
    cooldown_s: int = Field(default=90, ge=5, le=3600)
    world_scene_version: int = 0


class HumanMotionSnapshot(BaseModel):
    """压缩后的本地 Human Motion State，5–15Hz 同步，不包含完整骨骼。"""

    model_config = ConfigDict(extra="ignore")
    schema_version: str = CHARACTER_SCHEMA_VERSION
    ts: int = 0
    sequence: int = 0
    head_pose: Optional[Pose] = None
    left_hand_position: Optional[Vec3] = None
    right_hand_position: Optional[Vec3] = None
    left_hand_tracked: bool = False
    right_hand_tracked: bool = False
    body_tracked: bool = False
    body_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    gaze_direction: Optional[Vec3] = None
    gaze_target_id: str = ""
    gesture: str = ""
    facing_direction: Optional[Vec3] = None
    velocity: Optional[Vec3] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = "meta_xr"


class SpatialAction(BaseModel):
    """LLM/Qiyu 后端 → Quest Spatial Action Runtime。"""

    model_config = ConfigDict(extra="ignore")
    id: str = ""
    ts: int = 0
    action: Literal[
        "move_to", "approach", "move_away", "face_user", "face_object",
        "look_at", "play_animation", "interact", "stop"
    ]
    target_id: str = ""
    target_position: Optional[Vec3] = None
    anchor: Literal["world", "head", "left_hand", "right_hand", "surface", "object"] = "world"
    speed: float = 1.0
    stop_distance_m: float = 0.5
    min_distance_m: float = 0.0
    face_target: bool = True
    avoid_obstacles: bool = True
    cancel_on_barge_in: bool = True
    duration_ms: int = 0
    animation: str = ""
    priority: Literal[0, 1, 2, 3] = 1


__all__ = [
    "AttentionState",
    "AutonomyRequest",
    "AvatarGoalLiteral",
    "AvatarIntent",
    "AvatarPose",
    "BehaviorState",
    "BehaviorStyleLiteral",
    "Bounds",
    "CHARACTER_SCHEMA_VERSION",
    "CharacterState",
    "DrivesState",
    "EmotionLiteral",
    "EmotionState",
    "HumanMotionSnapshot",
    "InteractionEvent",
    "MemoryContext",
    "NavmeshInfo",
    "PROTOCOL_VERSION",
    "Pose",
    "Quat",
    "RelationshipState",
    "SceneAnchor",
    "SpatialAction",
    "SpatialHint",
    "SpeechState",
    "TrackedObject",
    "UserPose",
    "Vec3",
    "WorldInteraction",
    "WorldState",
]
