# -*- coding: utf-8 -*-
"""共享注意力（Shared Attention）。

    human_focus / avatar_focus / shared_target / gaze_alignment / attention_confidence

要点：
- 本地算：射线求交（raycast）在 Quest 本地做，Omni 只收「指向了谁」；
- 不每帧调用 Omni：只有焦点变化或事件触发时才把结论发过去；
- gaze_alignment = 用户看向 Avatar 焦点方向的单位向量夹角余弦。
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


def _norm(v):
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _unit(v):
    n = _norm(v)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-6 else (0.0, 0.0, 0.0)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


@dataclass
class AreaOfInterest:
    """场景里可被关注的对象（物体 / 人 / 位置）。"""

    id: str
    label: str = ""
    position: tuple = (0.0, 0.0, 0.0)
    radius: float = 0.3
    kind: str = "object"


@dataclass
class SharedAttention:
    timestamp: float = field(default_factory=time.time)
    human_focus: str = ""
    avatar_focus: str = ""
    shared_target: str = ""
    gaze_alignment: float = 0.0
    attention_confidence: float = 0.0
    human_ray: dict = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict:
        return {"ts": self.timestamp, "human_focus": self.human_focus,
                "avatar_focus": self.avatar_focus, "shared_target": self.shared_target,
                "gaze_alignment": round(self.gaze_alignment, 3),
                "attention_confidence": round(self.attention_confidence, 3),
                "human_ray": self.human_ray, "reason": self.reason}


class SharedAttentionTracker:
    def __init__(self, raycast: Optional[Callable[[tuple, tuple], Optional[str]]] = None):
        """raycast(origin, direction) -> area_id | None 由 Quest 侧注入；
        没注入时退化为本地球体求交。"""
        self.raycast = raycast
        self.aois: Dict[str, AreaOfInterest] = {}
        self.human_origin = (0.0, 1.6, 0.0)
        self.human_dir = (0.0, 0.0, -1.0)
        self.human_focus = ""
        self.human_conf = 0.0
        self.avatar_focus = ""
        self.avatar_point: Optional[tuple] = None
        self.last = SharedAttention()
        self.stats = {"rays": 0, "hits": 0, "shared": 0, "updates": 0}

    def register(self, aoi: AreaOfInterest) -> None:
        self.aois[aoi.id] = aoi

    def update_human(self, origin: tuple, direction: tuple, confidence: float = 0.8) -> None:
        self.human_origin = origin
        self.human_dir = _unit(direction)
        self.human_conf = float(confidence)
        self.stats["rays"] += 1
        hit = None
        if self.raycast is not None:
            try:
                hit = self.raycast(self.human_origin, self.human_dir)
            except Exception:
                hit = None
        if hit is None:
            hit = self._raycast_local(self.human_origin, self.human_dir)
        if hit:
            self.stats["hits"] += 1
            self.human_focus = hit
        elif not self.human_focus:
            self.human_focus = "unknown"

    def update_avatar(self, target: str, point: Optional[tuple] = None) -> None:
        self.avatar_focus = target
        self.avatar_point = point

    def _raycast_local(self, origin: tuple, direction: tuple) -> Optional[str]:
        best, best_t = None, 1e9
        for aoi in self.aois.values():
            to_c = _sub(aoi.position, origin)
            t = _dot(to_c, direction)
            if t <= 0:
                continue
            closest = (origin[0] + direction[0] * t,
                       origin[1] + direction[1] * t,
                       origin[2] + direction[2] * t)
            if _norm(_sub(aoi.position, closest)) <= aoi.radius and t < best_t:
                best, best_t = aoi.id, t
        return best

    def snapshot(self) -> SharedAttention:
        shared = ""
        if self.human_focus and self.human_focus == self.avatar_focus:
            shared = self.human_focus
            self.stats["shared"] += 1
        align = 0.0
        if self.avatar_point is not None:
            align = _dot(self.human_dir, _unit(_sub(self.avatar_point, self.human_origin)))
        known = bool(self.human_focus and self.human_focus != "unknown")
        conf = self.human_conf * (1.0 if known else 0.4)
        self.last = SharedAttention(
            human_focus=self.human_focus, avatar_focus=self.avatar_focus,
            shared_target=shared, gaze_alignment=align,
            attention_confidence=conf,
            human_ray={"origin": [round(v, 4) for v in self.human_origin],
                       "dir": [round(v, 4) for v in self.human_dir]},
            reason="shared_target" if shared else ("human_only" if known else "none"))
        self.stats["updates"] += 1
        return self.last

    def resolve_point(self, origin: tuple, direction: tuple) -> str:
        """用户指着某处 -> 返回目标 id（object:<id> / unknown）。"""
        d = _unit(direction)
        hit = None
        if self.raycast is not None:
            try:
                hit = self.raycast(origin, d)
            except Exception:
                hit = None
        if hit is None:
            hit = self._raycast_local(origin, d)
        return f"object:{hit}" if hit else "unknown"

    def stats_dict(self) -> dict:
        return dict(self.stats)
