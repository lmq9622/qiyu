# -*- coding: utf-8 -*-
"""动捕数据模型。

坐标约定：右手系、米、Quest 空间（Y 向上）。角度用弧度。
凡是设备不支持的部位（例如没有 body tracking 时），字段保持 ``None`` 并在
``capabilities`` 里如实标 False —— **不允许假造**。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

Vec3 = tuple


class GestureName(str, Enum):
    """本地可识别的交互手势（规格 §E）。"""

    WAVE = "wave"
    POINT = "point"
    COME_HERE = "come_here"
    STOP = "stop"
    NOD = "nod"
    SHAKE_HEAD = "shake_head"
    REACH = "reach"
    GIVE = "give"
    SIT = "sit"
    STAND = "stand"
    LOOK = "look"
    HIGH_FIVE = "high_five"
    FOLLOW_ME = "follow_me"


@dataclass
class HumanJoint:
    """单个关节/部位。``position`` 米，(x, y, z)。"""

    position: Vec3 = (0.0, 0.0, 0.0)
    rotation: Optional[Vec3] = None      # (pitch, yaw, roll)，没有就 None
    velocity: Vec3 = (0.0, 0.0, 0.0)     # m/s
    confidence: float = 0.0
    tracked: bool = False

    def to_dict(self) -> dict:
        return {"pos": [round(float(v), 4) for v in self.position],
                "rot": ([round(float(v), 4) for v in self.rotation]
                        if self.rotation else None),
                "vel": [round(float(v), 4) for v in self.velocity],
                "conf": round(float(self.confidence), 3),
                "tracked": bool(self.tracked)}


@dataclass
class HumanMotionState:
    """本地 30~60Hz 的人体状态。**不上传**，只在本地用于识别与驱动。"""

    timestamp: float = field(default_factory=time.time)
    sequence: int = 0
    head: Optional[HumanJoint] = None
    left_hand: Optional[HumanJoint] = None
    right_hand: Optional[HumanJoint] = None
    body: Optional[HumanJoint] = None            # 设备支持时才有
    gaze_origin: Vec3 = (0.0, 1.6, 0.0)
    gaze_direction: Vec3 = (0.0, 0.0, -1.0)      # 单位向量
    facing_direction: Vec3 = (0.0, 0.0, -1.0)
    head_height: float = 1.6
    velocity: Vec3 = (0.0, 0.0, 0.0)             # 人体移动速度
    confidence: float = 0.0
    capabilities: dict = field(default_factory=lambda: {
        "head": True, "hands": True, "body": False, "gaze": True, "body_velocity": False})
    source: str = "quest"

    @property
    def hands(self) -> dict:
        out = {}
        if self.left_hand is not None:
            out["left"] = self.left_hand
        if self.right_hand is not None:
            out["right"] = self.right_hand
        return out

    def dominant_hand(self) -> Optional[HumanJoint]:
        """取置信度更高的那只手。"""
        cands = [h for h in (self.left_hand, self.right_hand) if h is not None]
        if not cands:
            return None
        return max(cands, key=lambda h: h.confidence)

    def to_dict(self) -> dict:
        d = {
            "ts": self.timestamp, "seq": self.sequence,
            "gaze_origin": list(self.gaze_origin),
            "gaze_dir": list(self.gaze_direction),
            "facing": list(self.facing_direction),
            "head_height": self.head_height,
            "velocity": list(self.velocity),
            "confidence": round(float(self.confidence), 3),
            "capabilities": dict(self.capabilities),
            "source": self.source,
        }
        for name in ("head", "left_hand", "right_hand", "body"):
            v = getattr(self, name)
            d[name] = v.to_dict() if v is not None else None
        return d


@dataclass
class MotionSummary:
    """允许进 Omni 的**降采样摘要**（不含骨骼、不含每帧数据）。"""

    timestamp: float = field(default_factory=time.time)
    head_height: float = 1.6
    posture: str = "standing"          # standing / sitting / unknown
    facing_deg: float = 0.0
    gaze_target: str = ""
    left_hand_zone: str = "low"        # low / mid / high / unknown
    right_hand_zone: str = "low"
    motion_energy: float = 0.0         # 0~1
    moving: bool = False
    events_in_window: list = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["motion_energy"] = round(float(self.motion_energy), 3)
        d["confidence"] = round(float(self.confidence), 3)
        return d
