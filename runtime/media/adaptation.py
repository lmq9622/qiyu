# -*- coding: utf-8 -*-
"""带宽自适应（bandwidth adaptation）。

输入是 ``MediaQualitySample``（RTT / 抖动 / 丢包 / fps），输出是**视频采样目标**：

    EXCELLENT 10fps -> GOOD 8 -> FAIR 5 -> POOR 3 -> CRITICAL 2（可关摄像头）

设计要点：
- **滞回**：等级必须连续 ``hold_samples`` 次一致才切换，避免抖动式来回跳；
- **冷却**：切换后 ``cooldown_s`` 内不再切（防止抖动放大）；
- **只动视频**：音频永不降级（说话断了比画面糊严重得多）；
- ``apply()`` 只改本地视频轨的 fps / 开关，不碰 Omni 与推理链。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .types import MediaQualitySample


class QualityLevel(str, Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


@dataclass
class AdaptationConfig:
    fps_by_level: dict = field(default_factory=lambda: {
        QualityLevel.EXCELLENT.value: 10.0,
        QualityLevel.GOOD.value: 8.0,
        QualityLevel.FAIR.value: 5.0,
        QualityLevel.POOR.value: 3.0,
        QualityLevel.CRITICAL.value: 2.0,
    })
    rtt_ms_thresholds: tuple = (80.0, 150.0, 250.0, 400.0)      # -> good/fair/poor/critical
    loss_thresholds: tuple = (0.005, 0.02, 0.05, 0.10)
    jitter_ms_thresholds: tuple = (30.0, 60.0, 120.0, 200.0)
    hold_samples: int = 2
    cooldown_s: float = 5.0
    pause_camera_at: str = QualityLevel.CRITICAL.value


@dataclass
class AdaptationDecision:
    level: str = QualityLevel.EXCELLENT.value
    target_fps: float = 10.0
    previous_fps: float = 10.0
    camera_enabled: bool = True
    changed: bool = False
    reason: str = ""
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"level": self.level, "target_fps": self.target_fps,
                "previous_fps": self.previous_fps,
                "camera_enabled": self.camera_enabled,
                "changed": self.changed, "reason": self.reason, "ts": self.ts}


def _level_of(sample: MediaQualitySample, cfg: AdaptationConfig) -> tuple:
    """按最差指标定级，返回 (level, reason)。"""
    worst = QualityLevel.EXCELLENT.value
    reason = "ok"
    order = [QualityLevel.GOOD.value, QualityLevel.FAIR.value,
             QualityLevel.POOR.value, QualityLevel.CRITICAL.value]
    for idx, (rtt_t, loss_t, jit_t) in enumerate(zip(cfg.rtt_ms_thresholds,
                                                     cfg.loss_thresholds,
                                                     cfg.jitter_ms_thresholds)):
        hit = []
        if sample.rtt_ms > rtt_t:
            hit.append(f"rtt={sample.rtt_ms:.0f}ms")
        if sample.loss_ratio > loss_t:
            hit.append(f"loss={sample.loss_ratio:.3f}")
        if sample.jitter_ms > jit_t:
            hit.append(f"jitter={sample.jitter_ms:.0f}ms")
        if hit:
            worst = order[idx]
            reason = ",".join(hit)
    return worst, reason


class BandwidthAdapter:
    def __init__(self, config: Optional[AdaptationConfig] = None, current_fps: float = 10.0):
        self.config = config or AdaptationConfig()
        self.level = QualityLevel.EXCELLENT.value
        self.current_fps = float(current_fps)
        self._pending: Optional[str] = None
        self._pending_count = 0
        self._last_change_ts = 0.0
        self.history: list = []

    def decide(self, sample: MediaQualitySample) -> AdaptationDecision:
        cfg = self.config
        level, reason = _level_of(sample, cfg)
        now = time.time()
        changed = False
        if level != self.level:
            if self._pending == level:
                self._pending_count += 1
            else:
                self._pending = level
                self._pending_count = 1
            if self._pending_count >= cfg.hold_samples and \
                    (now - self._last_change_ts) >= cfg.cooldown_s:
                self.level = level
                self._last_change_ts = now
                changed = True
                self._pending = None
                self._pending_count = 0
        else:
            self._pending = None
            self._pending_count = 0

        target = float(cfg.fps_by_level.get(self.level, self.current_fps))
        decision = AdaptationDecision(
            level=self.level, target_fps=target, previous_fps=self.current_fps,
            camera_enabled=(self.level != cfg.pause_camera_at),
            changed=changed, reason=reason)
        if changed:
            self.history.append(decision.to_dict())
            self.current_fps = target
        return decision

    def apply(self, session, decision: AdaptationDecision) -> dict:
        """把决策落到本地视频轨（不碰音频、不碰认知层）。"""
        applied = {"level": decision.level, "target_fps": decision.target_fps}
        try:
            if session.local_video is not None:
                session.local_video.fps = float(decision.target_fps)
                session.local_video.enabled = bool(decision.camera_enabled)
                applied["camera_enabled"] = decision.camera_enabled
            applied["changed"] = decision.changed
        except Exception as e:
            applied["error"] = f"{type(e).__name__}: {e}"
        return applied

    def stats(self) -> dict:
        return {"level": self.level, "current_fps": self.current_fps,
                "changes": len(self.history), "history": self.history[-5:]}
