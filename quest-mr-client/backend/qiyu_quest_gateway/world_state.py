"""WorldState 存储与面向 LLM 的空间语义渲染。

设计原则：
- Quest 端负责实时空间计算（MRUK/Scene API/几何），后端只做状态缓存与
  “把真实坐标翻译成人类/LLM 可读的空间关系”；
- 渲染只使用 Quest 上报的真实数据，不编造房间、物体或位置；
- 坐标沿用 Protocol v1：右手系、米、Y 轴向上，与 Unity 一致。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

_LABEL_CN = {
    "room": "房间",
    "floor": "地面",
    "wall": "墙",
    "ceiling": "天花板",
    "table": "桌子",
    "chair": "椅子",
    "sofa": "沙发",
    "door": "门",
    "window": "窗",
    "storage": "柜子/收纳",
    "plant": "植物",
    "screen": "屏幕",
    "other": "其他家具",
    "unknown": "未分类物体",
}


def _vec(value: Any) -> Optional[tuple[float, float, float]]:
    if not isinstance(value, dict):
        return None
    try:
        return (float(value.get("x", 0.0)),
                float(value.get("y", 0.0)),
                float(value.get("z", 0.0)))
    except (TypeError, ValueError):
        return None


def _pose_position(pose: Any) -> Optional[tuple[float, float, float]]:
    if not isinstance(pose, dict):
        return None
    return _vec(pose.get("position"))


def _yaw_deg(rotation: Any) -> float:
    """Unity 四元数 → 绕 Y 轴偏航角（度）。"""
    if not isinstance(rotation, dict):
        return 0.0
    try:
        x = float(rotation.get("x", 0.0))
        y = float(rotation.get("y", 0.0))
        z = float(rotation.get("z", 0.0))
        w = float(rotation.get("w", 1.0))
    except (TypeError, ValueError):
        return 0.0
    return math.degrees(math.atan2(2.0 * (w * y + x * z),
                                   1.0 - 2.0 * (y * y + x * x)))


def _relative(origin: tuple[float, float, float], yaw_deg: float,
              target: tuple[float, float, float]) -> tuple[float, float]:
    """返回 (水平距离米, 相对朝向角；正=右 负=左)。"""
    dx = target[0] - origin[0]
    dz = target[2] - origin[2]
    distance = math.hypot(dx, dz)
    yaw = math.radians(yaw_deg)
    forward = (math.sin(yaw), math.cos(yaw))
    right = (math.cos(yaw), -math.sin(yaw))
    dot_forward = dx * forward[0] + dz * forward[1]
    dot_right = dx * right[0] + dz * right[1]
    angle = math.degrees(math.atan2(dot_right, dot_forward))
    return distance, angle


def _direction_cn(angle_deg: float) -> str:
    a = ((angle_deg + 180.0) % 360.0) - 180.0
    if abs(a) <= 20.0:
        return "正前方"
    if abs(a) >= 160.0:
        return "正后方"
    side = "右" if a > 0 else "左"
    if abs(a) <= 60.0:
        return f"前方偏{side}"
    if abs(a) <= 120.0:
        return f"{side}侧"
    return f"后方偏{side}"


def _fmt(v: float) -> str:
    return f"{v:.2f}"


@dataclass
class _AnchorView:
    anchor_id: str
    label: str
    position: Optional[tuple[float, float, float]]
    extents: Optional[tuple[float, float, float]]
    mesh_available: bool
    distance: Optional[float] = None
    direction: str = ""


class WorldStateStore:
    """按 session 缓存 Quest 上报的 WorldState，供 Gateway/LLM 读取。"""

    def __init__(self) -> None:
        self._by_session: dict[str, dict] = {}
        self._updated_at: dict[str, float] = {}

    def update(self, session_id: str, world_state: dict) -> None:
        self._by_session[session_id] = dict(world_state or {})
        self._updated_at[session_id] = time.time()

    def get(self, session_id: str) -> Optional[dict]:
        return self._by_session.get(session_id)

    def age_s(self, session_id: str) -> float:
        ts = self._updated_at.get(session_id)
        return float("inf") if ts is None else max(0.0, time.time() - ts)

    def drop(self, session_id: str) -> None:
        self._by_session.pop(session_id, None)
        self._updated_at.pop(session_id, None)

    def latest(self) -> Optional[dict]:
        if not self._by_session:
            return None
        session_id = max(self._updated_at, key=lambda k: self._updated_at[k])
        return self._by_session.get(session_id)


def render_world_state_for_llm(world_state: Optional[dict], *,
                               max_anchors: int = 48,
                               max_objects: int = 32) -> str:
    """把 WorldState 渲染成紧凑中文空间描述，供 MainBrain 注入上下文。"""
    if not isinstance(world_state, dict) or not world_state:
        return ""

    status = str(world_state.get("status") or "unknown")
    room_id = str(world_state.get("room_id") or "未知房间")
    scene_version = world_state.get("scene_version", 0)
    anchors = world_state.get("anchors") or []
    objects = world_state.get("objects") or []
    user = world_state.get("user") or {}
    navmesh = world_state.get("navmesh") or {}

    head_pose = user.get("head") if isinstance(user, dict) else None
    head_pos = _pose_position(head_pose)
    head_yaw = _yaw_deg((head_pose or {}).get("rotation")) if isinstance(head_pose, dict) else 0.0

    views: list[_AnchorView] = []
    for raw in anchors:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "unknown")
        pos = _pose_position(raw.get("pose"))
        extents = _vec(raw.get("extents"))
        view = _AnchorView(
            anchor_id=str(raw.get("id") or ""),
            label=label,
            position=pos,
            extents=extents,
            mesh_available=bool(raw.get("mesh_available")),
        )
        if pos and head_pos:
            view.distance, angle = _relative(head_pos, head_yaw, pos)
            view.direction = _direction_cn(angle)
        views.append(view)

    # 与用户相关的家具优先，其次按距离；无距离的放最后。
    def _sort_key(v: _AnchorView) -> tuple[int, float]:
        if v.label in ("floor", "ceiling", "room"):
            return (2, 0.0)
        if v.distance is None:
            return (1, 999.0)
        return (0, v.distance)

    views.sort(key=_sort_key)

    lines: list[str] = []
    lines.append(
        f"【真实房间空间状态（Quest MRUK 实时上报，scene_version={scene_version}，"
        f"status={status}，房间={room_id}）】"
    )
    if head_pos:
        lines.append(
            f"- 用户头部位置：({_fmt(head_pos[0])}, {_fmt(head_pos[1])}, {_fmt(head_pos[2])})，"
            f"朝向偏航 {head_yaw:.0f}°；以下方位均以用户当前朝向为基准。"
        )
    else:
        lines.append("- 用户头部位置：本轮未上报。")

    grouped: dict[str, list[_AnchorView]] = {}
    for view in views:
        grouped.setdefault(view.label, []).append(view)

    for label in ("floor", "ceiling", "wall", "table", "chair", "sofa",
                  "door", "window", "storage", "plant", "screen",
                  "other", "unknown", "room"):
        items = grouped.pop(label, None)
        if not items:
            continue
        cn = _LABEL_CN.get(label, label)
        if label in ("floor", "ceiling", "room"):
            for item in items[:2]:
                extra = ""
                if item.position:
                    extra = (f"，位置({_fmt(item.position[0])}, {_fmt(item.position[1])}, "
                             f"{_fmt(item.position[2])})")
                lines.append(f"- {cn}：已建模{extra}")
            continue
        lines.append(f"- {cn} 共 {len(items)} 个：")
        for item in items[:max_anchors]:
            detail = f"  · {item.anchor_id or cn}"
            if item.position:
                detail += (f" 位置({_fmt(item.position[0])}, {_fmt(item.position[1])}, "
                           f"{_fmt(item.position[2])})")
            if item.distance is not None:
                detail += f"，距用户 {_fmt(item.distance)}m，位于{item.direction}"
            if item.extents:
                detail += (f"，尺寸 {_fmt(item.extents[0])}×{_fmt(item.extents[1])}"
                           f"×{_fmt(item.extents[2])}m")
            if item.mesh_available:
                detail += "，有网格"
            lines.append(detail)
            if len(lines) > max_anchors + 20:
                break
        if len(lines) > max_anchors + 20:
            lines.append("- （锚点过多，已截断）")
            break

    for label, items in grouped.items():
        cn = _LABEL_CN.get(label, label)
        lines.append(f"- {cn} 共 {len(items)} 个（未逐项展开）")

    if objects:
        lines.append(f"- 已识别物体 {len(objects)} 个：")
        for raw in objects[:max_objects]:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or "物体")
            conf = raw.get("confidence")
            pos = _vec(raw.get("position"))
            detail = f"  · {label}"
            if isinstance(conf, (int, float)):
                detail += f"（置信度 {float(conf):.2f}）"
            if pos and head_pos:
                distance, angle = _relative(head_pos, head_yaw, pos)
                detail += f" 距用户 {_fmt(distance)}m，位于{_direction_cn(angle)}"
            elif pos:
                detail += f" 位置({_fmt(pos[0])}, {_fmt(pos[1])}, {_fmt(pos[2])})"
            anchor_id = str(raw.get("anchor_id") or "")
            if anchor_id:
                detail += f"，依附锚点 {anchor_id}"
            lines.append(detail)
    else:
        lines.append("- 尚未识别 Scene API 之外的物体（杯子/手机等由 P4 视觉检测补充）。")

    if isinstance(navmesh, dict) and navmesh.get("generated"):
        lines.append(
            f"- 可导航区域：已生成（版本 {navmesh.get('version', 0)}，"
            f"可行走面积约 {float(navmesh.get('walkable_area_m2') or 0.0):.2f} 平方米）。"
        )
    else:
        lines.append("- 可导航区域：尚未生成。")

    lines.append(
        "使用规则：这些是角色当前所在真实房间的实时空间事实。"
        "回答涉及“这里/房间/桌子/椅子/周围/过去那边”等问题时必须以此为准；"
        "不确定的位置不要编造。角色只能通过高层 SpatialAction 请求移动，禁止直接指定骨骼坐标。"
    )
    return "\n".join(lines)


__all__ = ["WorldStateStore", "render_world_state_for_llm"]
