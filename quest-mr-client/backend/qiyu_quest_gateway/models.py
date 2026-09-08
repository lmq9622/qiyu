"""Protocol v1 Pydantic 模型。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = "1.0.0"


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
    anchor_id: Optional[str] = None
    source: Literal["scene_api", "local_detector", "cloud_vision", "user_placed"] = "local_detector"


class UserPose(BaseModel):
    head: Optional[Pose] = None
    left_hand: Optional[Pose] = None
    right_hand: Optional[Pose] = None
    gaze_direction: Optional[Vec3] = None
    source: Literal["headset", "body_tracking", "estimated"] = "headset"


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


class WorldState(BaseModel):
    """v1 WorldState：Quest 真实空间状态。"""

    model_config = ConfigDict(extra="ignore")
    protocol_version: Literal["1.0.0"] = PROTOCOL_VERSION
    ts: int = 0
    room_id: str = ""
    scene_version: int = 1
    status: Literal["scanning", "ready", "stale", "lost"] = "scanning"
    anchors: list[SceneAnchor] = Field(default_factory=list)
    objects: list[TrackedObject] = Field(default_factory=list)
    user: UserPose = Field(default_factory=UserPose)
    avatar: AvatarPose = Field(default_factory=AvatarPose)
    navmesh: NavmeshInfo = Field(default_factory=NavmeshInfo)


class AvatarIntent(BaseModel):
    """LLM/Qiyu 后端 → Quest Avatar Runtime。"""

    model_config = ConfigDict(extra="ignore")
    id: str = ""
    ts: int = 0
    emotion: Literal[
        "neutral", "happy", "calm", "sad", "annoyed", "angry",
        "excited", "shy", "confused", "tired", "surprised"
    ] = "neutral"
    intensity: float = Field(default=0.0, ge=0.0, le=1.0)
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
