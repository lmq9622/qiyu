# -*- coding: utf-8 -*-
"""动捕聚合器：本地高频进，Omni 只拿到「事件 + 摘要」。

这是规格 E 的闸门：

    Quest 30~60Hz HumanMotionState --(本地)--> GestureRecognizer
                                    --(降采样)--> MotionSummary
                                    ------> 事件队列 --> Omni（只收这两个）

原始骨骼 / 每帧 transform 不会出现在 to_omni_payload() 的结果里。
"""

from __future__ import annotations

import math
import time
from typing import Optional

from .recognizer import GestureRecognizer, RecognizerConfig
from .types import HumanMotionState, MotionSummary


class HumanMotionAggregator:
    def __init__(self, config: Optional[RecognizerConfig] = None,
                 summary_hz: float = 1.0, event_queue_max: int = 32):
        self.recognizer = GestureRecognizer(config)
        self.summary_hz = float(summary_hz)
        self._events: list = []
        self._event_max = int(event_queue_max)
        self._summary: Optional[MotionSummary] = None
        self._last_summary_ts = 0.0
        self._fps_window: list = []
        self.stats = {"frames_in": 0, "events_out": 0, "summaries_out": 0,
                      "events_dropped": 0, "effective_hz": 0.0,
                      "gesture_counts": {}}

    def ingest(self, state: HumanMotionState) -> list:
        """喂一帧（30~60Hz）。返回本帧新识别出的事件。"""
        self.stats["frames_in"] += 1
        now = state.timestamp or time.time()
        self._fps_window.append(now)
        if len(self._fps_window) > 120:
            self._fps_window.pop(0)
        if len(self._fps_window) >= 2:
            span = self._fps_window[-1] - self._fps_window[0]
            if span > 0:
                self.stats["effective_hz"] = round((len(self._fps_window) - 1) / span, 1)

        new_events = self.recognizer.observe(state)
        for ev in new_events:
            name = ev["name"]
            self.stats["gesture_counts"][name] = \
                self.stats["gesture_counts"].get(name, 0) + 1
            if len(self._events) >= self._event_max:
                self._events.pop(0)
                self.stats["events_dropped"] += 1
            self._events.append(ev)
            self.stats["events_out"] += 1

        self._update_summary(state, new_events)
        return new_events

    def _update_summary(self, state: HumanMotionState, new_events: list) -> None:
        now = state.timestamp or time.time()
        due = (now - self._last_summary_ts) >= (1.0 / max(0.01, self.summary_hz))
        if self._summary is None:
            due = True
        if not due:
            if new_events and self._summary is not None:
                self._summary.events_in_window = (
                    self._summary.events_in_window + [e["name"] for e in new_events])[-8:]
            return

        hand = state.dominant_hand()
        hand_zone = "unknown"
        if hand is not None:
            y = hand.position[1]
            hand_zone = "high" if y >= 1.4 else ("mid" if y >= 0.9 else "low")
        speed = math.sqrt(sum(v * v for v in state.velocity))
        if state.capabilities.get("body"):
            posture = "sitting" if state.head_height < 1.25 else "standing"
        else:
            posture = "standing" if state.head_height >= 1.25 else "unknown"
        denom = -state.facing_direction[2]
        facing_deg = math.degrees(math.atan2(state.facing_direction[0],
                                             denom if abs(denom) > 1e-6 else 1e-6))
        prev_events = self._summary.events_in_window if self._summary else []
        self._summary = MotionSummary(
            timestamp=now,
            head_height=round(state.head_height, 3),
            posture=posture,
            facing_deg=round(facing_deg, 1),
            gaze_target=self._summary.gaze_target if self._summary else "",
            left_hand_zone=hand_zone if hand is state.left_hand else "unknown",
            right_hand_zone=hand_zone if hand is state.right_hand else "unknown",
            motion_energy=round(min(1.0, speed / 1.5), 3),
            moving=speed >= 0.2,
            events_in_window=([e["name"] for e in new_events] + prev_events)[-8:],
            capabilities=dict(state.capabilities),
            confidence=round(state.confidence, 3),
        )
        self._last_summary_ts = now
        self.stats["summaries_out"] += 1

    def pending_events(self, drain: bool = True) -> list:
        ev = list(self._events)
        if drain:
            self._events.clear()
        return ev

    def latest_summary(self) -> Optional[dict]:
        return self._summary.to_dict() if self._summary is not None else None

    def to_omni_payload(self, drain: bool = True) -> dict:
        """进 Omni 的载荷：只有事件 + 摘要，没有任何骨骼/每帧数据。"""
        return {"events": self.pending_events(drain=drain),
                "summary": self.latest_summary(),
                "stats": {"frames_in": self.stats["frames_in"],
                          "effective_hz": self.stats["effective_hz"]}}

    def set_gaze_target(self, target: str) -> None:
        if self._summary is not None:
            self._summary.gaze_target = target

    def stats_dict(self) -> dict:
        return dict(self.stats)
