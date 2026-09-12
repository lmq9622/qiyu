# -*- coding: utf-8 -*-
"""AI Media Adapter：媒体面 → 认知面 的**单向**桥。

这是整个架构里唯一允许同时认识 WebRTC 和 Omni 的地方：

    MediaSession(远端 audio/video)  ─┐
    本地 Mic                        ─┼→ 本适配器 → OmniSession（只走公开 API）
    事件（Point/Gaze…）             ─┘

规则：
1. **不每帧复制**：远端视频只交给 ``VideoScheduler``，被选中的帧才进 Omni；
2. **不碰 Omni 内部**：只用 ``IRealtimeOmni`` 的公开方法；
3. 音频带 ``speaker_id``，远端与本地可分辨（多人场景前置条件）；
4. 适配器可以整体停掉，媒体照常通话（AI 面掉线不影响通话）。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .tracks import audio_frame_to_f32, frame_energy, video_frame_to_rgb


@dataclass
class AIMediaStats:
    audio_chunks_to_omni: int = 0
    audio_seconds_to_omni: float = 0.0
    video_frames_seen: int = 0
    video_frames_to_omni: int = 0
    video_frames_dropped: int = 0
    last_audio_ts: float = 0.0
    last_video_ts: float = 0.0
    last_rms: float = 0.0
    max_rms: float = 0.0
    silent_chunks: int = 0
    errors: list = field(default_factory=list)

    @property
    def video_reduction(self) -> float:
        if self.video_frames_seen == 0:
            return 0.0
        return 1.0 - self.video_frames_to_omni / float(self.video_frames_seen)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["video_reduction"] = round(self.video_reduction, 3)
        return d


class AIMediaAdapter:
    """把一个或多个 MediaSession 的音频/视频接进一个 OmniSession。"""

    # 连续视频进 Omni 的最小间隔（毫秒）。实测：MiniCPM-o 双工在
    # 「音频 2 次/秒 + 视频 10 帧/秒」时**完全不出话**；只喂音频（0.5s/块）就正常出话。
    # 事件帧（snapshot / roi / burst）不受这个间隔限制，永远放行。
    VIDEO_INTERVAL_MS = 2000.0

    def __init__(self, omni, scheduler=None, target_rate: int = 16000,
                 chunk_ms: float = 200.0, send_video_with_audio: bool = False,
                 video_interval_ms: float = 0.0):
        from runtime.omni.types import AudioChunk, FrameKind, VideoFrame
        self._AudioChunk = AudioChunk
        self._VideoFrame = VideoFrame
        self._FrameKind = FrameKind
        self.omni = omni
        self.scheduler = scheduler
        self.target_rate = int(target_rate)
        # 聚合后再送：WebRTC 每 20ms 来一帧，若逐帧转发，Omni 侧会变成每秒几十次
        # input.append（实测 64 次/秒时模型来不及消化，反而不出话）。默认攒 200ms 发一次。
        self.chunk_ms = float(chunk_ms)
        self.send_video_with_audio = bool(send_video_with_audio)
        self.video_interval_ms = float(video_interval_ms or self.VIDEO_INTERVAL_MS)
        self._last_video_ts = 0.0
        self.video_throttled = 0
        self._pending_audio: list = []
        self._pending_samples = 0
        self.stats = AIMediaStats()
        self._tasks: list = []
        self._stopped = False
        self._seq = 0
        self._frame_id = 0

    # ---------- 本地麦克风 ----------
    async def send_local_audio(self, pcm, sample_rate: int = 16000,
                               is_speech: Optional[bool] = None) -> None:
        """本地 Mic → Omni（离线/网关侧直接调用，无需 WebRTC）。"""
        self._seq += 1
        chunk = self._AudioChunk(pcm=np.asarray(pcm, dtype=np.float32),
                                 sample_rate=sample_rate,
                                 speaker_id="local_user", seq=self._seq,
                                 is_speech=is_speech)
        await self.omni.send_audio_chunk(chunk)
        self.stats.audio_chunks_to_omni += 1
        self.stats.audio_seconds_to_omni += len(np.asarray(pcm).reshape(-1)) / float(sample_rate)
        self.stats.last_audio_ts = time.time()

    # ---------- 远端媒体 ----------
    def attach_remote(self, session, *, audio: bool = True, video: bool = True,
                      speaker_id: str = "remote_user") -> None:
        """把远端会话的轨道挂上（视频只走调度器选帧）。"""
        if audio and session.remote_audio is not None:
            self._tasks.append(asyncio.create_task(
                self._audio_pump(session.remote_audio, speaker_id)))
        if video and session.remote_video is not None:
            self._tasks.append(asyncio.create_task(
                self._video_pump(session.remote_video, speaker_id)))

    async def _audio_pump(self, track, speaker_id: str) -> None:
        while not self._stopped:
            try:
                frame = await track.recv()
            except Exception as e:
                if not self._stopped:
                    self.stats.errors.append(f"audio:{type(e).__name__}")
                return
            try:
                pcm = audio_frame_to_f32(frame, self.target_rate)
                self._pending_audio.append(pcm)
                self._pending_samples += len(pcm)
                need = int(self.target_rate * self.chunk_ms / 1000.0)
                if self._pending_samples < need:
                    continue
                merged = np.concatenate(self._pending_audio) if \
                    len(self._pending_audio) > 1 else self._pending_audio[0]
                self._pending_audio = []
                self._pending_samples = 0
                rms = float(np.sqrt(np.mean(merged * merged))) if len(merged) else 0.0
                self.stats.last_rms = round(rms, 5)
                self.stats.max_rms = round(max(self.stats.max_rms, rms), 5)
                if rms < 0.005:
                    self.stats.silent_chunks += 1
                self._seq += 1
                await self.omni.send_audio_chunk(self._AudioChunk(
                    pcm=merged, sample_rate=self.target_rate, speaker_id=speaker_id,
                    seq=self._seq, is_speech=None))
                self.stats.audio_chunks_to_omni += 1
                self.stats.audio_seconds_to_omni += len(merged) / float(self.target_rate)
                self.stats.last_audio_ts = time.time()
            except Exception as e:
                self.stats.errors.append(f"audio_send:{type(e).__name__}")

    async def _video_pump(self, track, speaker_id: str) -> None:
        while not self._stopped:
            try:
                frame = await track.recv()
            except Exception as e:
                if not self._stopped:
                    self.stats.errors.append(f"video:{type(e).__name__}")
                return
            self.stats.video_frames_seen += 1
            try:
                rgb = video_frame_to_rgb(frame)
                h, w = rgb.shape[:2]
                self._frame_id += 1
                vf = self._VideoFrame(data=rgb, frame_id=self._frame_id,
                                      kind=self._FrameKind.KEYFRAME.value,
                                      width=w, height=h, source="remote_peer",
                                      speaker_id=speaker_id,
                                      meta={"energy": round(frame_energy(rgb), 4)})
                if self.scheduler is not None:
                    picked = self.scheduler.offer(vf)
                    if picked is None:
                        self.stats.video_frames_dropped += 1
                        continue
                    vf = picked
                # 连续关键帧限速（事件帧 snapshot/roi/burst 不受限，始终放行）
                if vf.kind == self._FrameKind.KEYFRAME.value and self.video_interval_ms > 0:
                    now = time.time()
                    if (now - self._last_video_ts) * 1000.0 < self.video_interval_ms:
                        self.stats.video_frames_dropped += 1
                        self.video_throttled += 1
                        continue
                    self._last_video_ts = now
                await self.omni.send_video_frame(vf)
                self.stats.video_frames_to_omni += 1
                self.stats.last_video_ts = time.time()
            except Exception as e:
                self.stats.errors.append(f"video_send:{type(e).__name__}")

    # ---------- 生命周期 ----------
    async def stop(self) -> None:
        self._stopped = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks.clear()

    def stats_dict(self) -> dict:
        d = self.stats.to_dict()
        d["scheduler"] = self.scheduler.snapshot() if self.scheduler is not None else None
        return d
