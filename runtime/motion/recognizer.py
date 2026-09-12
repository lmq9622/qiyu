# -*- coding: utf-8 -*-
"""手势识别（规则版，本地实时）。

启发式识别器：靠关节轨迹 + 时间窗判定，不用模型、不联网、可解释。
阈值集中在 :class:`RecognizerConfig`，方便按真机标定。

原则：
- 只在置信度足够且满足时间模式时输出事件，避免抖动误触发；
- 每个手势有冷却时间，防止连发；
- 识别不出来就不报（宁缺勿滥）。
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .types import GestureName, HumanMotionState


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v):
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def _unit(v):
    n = _norm(v)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-6 else (0.0, 0.0, 0.0)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


@dataclass
class RecognizerConfig:
    min_confidence: float = 0.35
    window_s: float = 1.6
    cooldown_s: float = 1.2
    wave_min_y: float = 1.15
    wave_amplitude_m: float = 0.10
    wave_min_reversals: int = 3
    point_min_forward_m: float = 0.30
    point_hold_s: float = 0.35
    stop_min_y: float = 1.25
    stop_hold_s: float = 0.5
    come_here_y_range: tuple = (0.9, 1.5)
    head_min_reversals: int = 3
    head_pitch_deg: float = 6.0
    head_yaw_deg: float = 8.0
    reach_speed_mps: float = 0.25
    high_five_dist_m: float = 0.75
    high_five_min_y: float = 1.1
    sit_drop_m: float = 0.35
    follow_min_speed_mps: float = 0.2


@dataclass
class _Window:
    ts: list = field(default_factory=list)
    hand: list = field(default_factory=list)
    gaze: list = field(default_factory=list)
    speed: list = field(default_factory=list)
    height: list = field(default_factory=list)

    def push(self, st: HumanMotionState) -> None:
        self.ts.append(st.timestamp)
        h = st.dominant_hand()
        self.hand.append(h.position if h is not None else None)
        self.gaze.append(st.gaze_direction)
        self.speed.append(_norm(st.velocity))
        self.height.append(st.head_height)

    def trim(self, window_s: float) -> None:
        if not self.ts:
            return
        cutoff = self.ts[-1] - window_s
        while self.ts and self.ts[0] < cutoff:
            self.ts.pop(0)
            self.hand.pop(0)
            self.gaze.pop(0)
            self.speed.pop(0)
            self.height.pop(0)


class GestureRecognizer:
    """从 HumanMotionState 流里识别交互手势。"""

    def __init__(self, config: Optional[RecognizerConfig] = None):
        self.config = config or RecognizerConfig()
        self.window = _Window()
        self._last_fire: dict = {}
        self._hold_start: dict = {}
        self._head_hist = deque(maxlen=60)
        self.stats: dict = {}

    def _can_fire(self, name: str, now: float) -> bool:
        return (now - self._last_fire.get(name, 0.0)) >= self.config.cooldown_s

    def _fire(self, name: str, now: float, confidence: float,
              target: str = "avatar", **payload) -> dict:
        self._last_fire[name] = now
        self.stats[name] = self.stats.get(name, 0) + 1
        return {"name": name, "confidence": round(min(1.0, max(0.0, confidence)), 3),
                "target": target, "payload": payload, "timestamp": now}

    @staticmethod
    def _reversals(values: list, min_delta: float) -> int:
        rev, last_sign, last_val = 0, 0, None
        for v in values:
            if v is None:
                continue
            if last_val is None:
                last_val = v
                continue
            d = v - last_val
            if abs(d) < min_delta:
                continue
            sign = 1 if d > 0 else -1
            if last_sign != 0 and sign != last_sign:
                rev += 1
            last_sign = sign
            last_val = v
        return rev

    def _hold_ok(self, key: str, now: float, need_s: float) -> bool:
        start = self._hold_start.get(key)
        if start is None:
            self._hold_start[key] = now
            return False
        return (now - start) >= need_s

    def _hold_reset(self, key: str) -> None:
        self._hold_start.pop(key, None)

    def observe(self, st: HumanMotionState) -> list:
        events: list = []
        if st.confidence < self.config.min_confidence:
            return events
        self.window.push(st)
        self.window.trim(self.config.window_s)
        now = st.timestamp
        cfg = self.config
        hand = st.dominant_hand()
        hand_pos = hand.position if hand else None
        head = st.head

        if hand_pos and hand_pos[1] >= cfg.wave_min_y:
            xs = [p[0] for p in self.window.hand if p is not None]
            rev = self._reversals(xs, cfg.wave_amplitude_m)
            if rev >= cfg.wave_min_reversals:
                moving = max(self.window.speed or [0.0]) >= cfg.follow_min_speed_mps
                if moving:
                    if self._can_fire(GestureName.FOLLOW_ME.value, now):
                        events.append(self._fire(GestureName.FOLLOW_ME.value, now,
                                                 0.5 + 0.1 * rev, reversals=rev))
                elif self._can_fire(GestureName.WAVE.value, now):
                    events.append(self._fire(GestureName.WAVE.value, now,
                                             0.5 + 0.1 * rev, reversals=rev,
                                             hand_y=round(hand_pos[1], 3)))
                self._hold_reset("point")

        if hand_pos and hand_pos[1] >= cfg.stop_min_y:
            vel = _norm(hand.velocity) if hand else 0.0
            if vel < 0.15:
                if self._hold_ok("stop", now, cfg.stop_hold_s) and \
                        self._can_fire(GestureName.STOP.value, now):
                    events.append(self._fire(GestureName.STOP.value, now, 0.8,
                                             hand_y=round(hand_pos[1], 3)))
            else:
                self._hold_reset("stop")
        else:
            self._hold_reset("stop")

        if hand_pos:
            origin = st.head.position if head else (0.0, 1.6, 0.0)
            fwd = _unit(st.facing_direction)
            to_hand = _sub(hand_pos, origin)
            forward_m = _dot(to_hand, fwd)
            if forward_m >= cfg.point_min_forward_m:
                if self._hold_ok("point", now, cfg.point_hold_s):
                    dist = _norm(to_hand)
                    if hand_pos[1] >= cfg.high_five_min_y and dist <= cfg.high_five_dist_m \
                            and self._can_fire(GestureName.HIGH_FIVE.value, now):
                        events.append(self._fire(GestureName.HIGH_FIVE.value, now, 0.75,
                                                 distance=round(dist, 3)))
                    elif self._can_fire(GestureName.POINT.value, now):
                        direction = _unit(to_hand)
                        events.append(self._fire(
                            GestureName.POINT.value, now, 0.7,
                            ray_origin=[round(v, 4) for v in origin],
                            ray_dir=[round(v, 4) for v in direction],
                            distance=round(dist, 3)))
            else:
                self._hold_reset("point")
            if hand and _norm(hand.velocity) >= cfg.reach_speed_mps:
                if _dot(hand.velocity, fwd) > 0 and self._can_fire(GestureName.REACH.value, now):
                    events.append(self._fire(GestureName.REACH.value, now, 0.55,
                                             speed=round(_norm(hand.velocity), 3)))

        if hand_pos and cfg.come_here_y_range[0] <= hand_pos[1] <= cfg.come_here_y_range[1]:
            zs = [p[2] for p in self.window.hand if p is not None]
            if self._reversals(zs, cfg.wave_amplitude_m) >= cfg.wave_min_reversals \
                    and self._can_fire(GestureName.COME_HERE.value, now):
                events.append(self._fire(GestureName.COME_HERE.value, now, 0.6))

        if head is not None and head.rotation is not None:
            pitch, yaw, _roll = head.rotation
            self._head_hist.append((now, math.degrees(pitch), math.degrees(yaw)))
            recent = [(t, p, y) for (t, p, y) in self._head_hist if now - t <= cfg.window_s]
            if len(recent) >= 5:
                pv = [p for _, p, _ in recent]
                yv = [y for _, _, y in recent]
                if max(pv) - min(pv) >= cfg.head_pitch_deg and \
                        self._reversals(pv, cfg.head_pitch_deg / 3.0) >= cfg.head_min_reversals:
                    if self._can_fire(GestureName.NOD.value, now):
                        events.append(self._fire(GestureName.NOD.value, now, 0.7))
                elif max(yv) - min(yv) >= cfg.head_yaw_deg and \
                        self._reversals(yv, cfg.head_yaw_deg / 3.0) >= cfg.head_min_reversals:
                    if self._can_fire(GestureName.SHAKE_HEAD.value, now):
                        events.append(self._fire(GestureName.SHAKE_HEAD.value, now, 0.7))

        heights = [h for h in self.window.height if h is not None]
        if len(heights) >= 3:
            drop = max(heights) - min(heights)
            if drop >= cfg.sit_drop_m:
                rising = heights[-1] > heights[0]
                name = GestureName.STAND.value if rising else GestureName.SIT.value
                if self._can_fire(name, now):
                    events.append(self._fire(name, now, 0.7, drop=round(drop, 3)))

        gazes = [g for g in self.window.gaze if g is not None]
        if len(gazes) >= 4:
            base = gazes[0]
            turned = any(_dot(_unit(base), _unit(g)) < 0.9 for g in gazes[1:])
            if turned and self._can_fire(GestureName.LOOK.value, now):
                events.append(self._fire(GestureName.LOOK.value, now, 0.5,
                                         gaze=[round(v, 4) for v in st.gaze_direction]))
        return events
