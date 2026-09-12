# -*- coding: utf-8 -*-
"""栖语 · VideoScheduler（规格 §5）。

核心决定：**不把 30/60FPS 的摄像头帧全部推给 Omni。**

- 常态：``base_fps``（默认 8，落在规格要求的 5~10 区间）
- 事件触发提速：用户指向 / 新物体 / 拿起物体 / 主动要看 / 远端明显动作 /
  场景变化 / Omni 主动要视觉信息
- 高频的 Head / Hands / Gaze / Spatial tracking **全部留在 Quest 本地**，
  这里只处理降采样后的相机帧

调度器只做「这一帧该不该发」的判断，不碰编码、不碰网络。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from runtime.omni.types import FrameKind, VideoFrame

# 触发提速的事件 → 提速目标（fps, 持续毫秒）
DEFAULT_BOOST_POLICY: dict = {
    "point":            (24.0, 2000, "用户指向"),
    "gaze_target":      (16.0, 1500, "用户注视目标"),
    "object_appeared":  (24.0, 1500, "新物体出现"),
    "object_picked":    (24.0, 2000, "用户拿起物体"),
    "user_look_request": (24.0, 3000, "用户主动要求看"),
    "remote_motion":    (24.0, 2000, "远端视频明显动作"),
    "scene_change":     (20.0, 2500, "场景变化"),
    "omni_vision_request": (24.0, 3000, "Omni 请求视觉信息"),
    "hand_raise":       (20.0, 1500, "用户举手"),
    "reach":            (20.0, 1500, "用户伸手"),
}


@dataclass
class BoostState:
    until_ts: float = 0.0
    fps: float = 0.0
    reason: str = ""
    event: str = ""


@dataclass
class SchedulerStats:
    offered: int = 0
    sent: int = 0
    dropped: int = 0
    boosts: int = 0
    forced: int = 0
    last_send_ts: float = 0.0
    effective_fps: float = 0.0


@dataclass
class VideoScheduler:
    """按「常态低频 + 事件提速」决定视频帧的去留。"""

    base_fps: float = 8.0
    max_fps: float = 24.0
    min_interval_ms: float = 0.0        # 硬下限，0 表示由 fps 反推
    keyframe_interval_ms: float = 2000.0
    policy: dict = field(default_factory=lambda: dict(DEFAULT_BOOST_POLICY))

    boost: BoostState = field(default_factory=BoostState)
    stats: SchedulerStats = field(default_factory=SchedulerStats)
    _last_keyframe_ts: float = 0.0
    _window: list = field(default_factory=list)   # 用于估算有效 fps
    _now_fn: object = None                        # 便于测试注入时钟

    # ---------- 时间 ----------

    def _now(self) -> float:
        return self._now_fn() if callable(self._now_fn) else time.time()

    def _interval_ms(self) -> float:
        now = self._now()
        fps = self.base_fps
        if self.boost.until_ts > now and self.boost.fps > 0:
            fps = self.boost.fps
        fps = max(0.5, min(fps, self.max_fps))
        base = 1000.0 / fps
        return max(base, self.min_interval_ms) if self.min_interval_ms else base

    # ---------- 事件 ----------

    def on_event(self, event: str, *, fps: Optional[float] = None,
                 duration_ms: Optional[float] = None) -> BoostState:
        """世界事件触发采样提速。未知事件按策略表缺省忽略。"""
        spec = self.policy.get(event)
        if spec:
            target_fps, dur, label = spec
        else:
            target_fps, dur, label = self.max_fps, 1500.0, event
        if fps is not None:
            target_fps = fps
        if duration_ms is not None:
            dur = duration_ms
        now = self._now()
        self.boost = BoostState(until_ts=now + dur / 1000.0,
                                fps=min(target_fps, self.max_fps),
                                reason=label, event=event)
        self.stats.boosts += 1
        return self.boost

    def request_boost(self, event: str = "omni_vision_request", reason: str = "",
                      fps: Optional[float] = None, duration_ms: Optional[float] = None) -> BoostState:
        st = self.on_event(event, fps=fps, duration_ms=duration_ms)
        if reason:
            st.reason = reason
        return st

    # ---------- 帧去留 ----------

    def offer(self, frame: VideoFrame) -> Optional[VideoFrame]:
        """普通帧入口：该发就返回帧，不该发返回 None。

        强制帧（``kind`` 是 SNAPSHOT / ROI / BURST）**永远放行** —— 它们是事件产物，
        不受采样率限制。
        """
        self.stats.offered += 1
        now = self._now()

        if frame.kind in (FrameKind.SNAPSHOT.value, FrameKind.ROI.value, FrameKind.BURST.value):
            self.stats.forced += 1
            self._record_send(now)
            return frame

        if not self._last_send_ts_ref():
            self._set_last_send(now)
            if frame.kind == FrameKind.KEYFRAME.value:
                self._last_keyframe_ts = now
            self._record_send(now)
            return frame

        elapsed_ms = (now - self._last_send_ts_ref()) * 1000.0
        want_ms = self._interval_ms()

        # 定期 keyframe：即使没到采样间隔，也保证视觉上下文不丢
        need_keyframe = (now - self._last_keyframe_ts) * 1000.0 >= self.keyframe_interval_ms
        if need_keyframe:
            self._last_keyframe_ts = now
            self._set_last_send(now)
            self._record_send(now)
            frame.kind = FrameKind.KEYFRAME.value
            return frame

        if elapsed_ms >= want_ms:
            self._set_last_send(now)
            self._record_send(now)
            return frame

        self.stats.dropped += 1
        return None

    def force(self, frame: VideoFrame, kind: str = FrameKind.SNAPSHOT.value) -> VideoFrame:
        """强制发一帧（事件产物）。"""
        frame.kind = kind
        self.stats.forced += 1
        now = self._now()
        self._set_last_send(now)
        self._record_send(now)
        return frame

    # ---------- 内部 ----------

    def _last_send_ts_ref(self) -> float:
        return self.stats.last_send_ts

    def _set_last_send(self, ts: float) -> None:
        self.stats.last_send_ts = ts

    def _record_send(self, now: float) -> None:
        self.stats.sent += 1
        self._window.append(now)
        cutoff = now - 2.0
        self._window = [t for t in self._window if t >= cutoff]
        if len(self._window) >= 2:
            span = self._window[-1] - self._window[0]
            if span > 0:
                self.stats.effective_fps = round((len(self._window) - 1) / span, 2)

    def snapshot(self) -> dict:
        return {
            "base_fps": self.base_fps,
            "max_fps": self.max_fps,
            "offered": self.stats.offered,
            "sent": self.stats.sent,
            "dropped": self.stats.dropped,
            "forced": self.stats.forced,
            "boosts": self.stats.boosts,
            "effective_fps": self.stats.effective_fps,
            "boost_active": self.boost.until_ts > self._now(),
            "boost_event": self.boost.event,
        }


__all__ = ["DEFAULT_BOOST_POLICY", "BoostState", "SchedulerStats", "VideoScheduler"]
