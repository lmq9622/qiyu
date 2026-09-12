# -*- coding: utf-8 -*-
"""媒体轨道：可发送/接收的音频与视频 track。

设计要点
--------
- **mute 不等于停轨道**：静音时继续按节奏发 0 能量帧（浏览器同款做法），
  这样对端时钟不抖、也不触发重协商。视频关摄像头时发黑帧。
- 队列轨道（``QueueAudioTrack``）给本地麦克风/远端音频用：
  有数据就发数据，没数据就发静音，永不阻塞。
- 视频轨道（``SyntheticVideoTrack``）的帧来源是**回调**，
  既可以是测试图样，也可以是 Quest/摄像头的「选帧」结果。
"""

from __future__ import annotations

import asyncio
import fractions
import time
from typing import Callable, Optional

import numpy as np

import av
from aiortc import AudioStreamTrack, VideoStreamTrack


# --------------------------------------------------------------------------
# 音频
# --------------------------------------------------------------------------


class ToneAudioTrack(AudioStreamTrack):
    """按采样率生成固定音调（或静音）的音频轨道。测试与自检用。"""

    kind = "audio"

    def __init__(self, sample_rate: int = 48000, freq: float = 440.0,
                 amplitude: float = 0.2, frame_ms: float = 20.0):
        super().__init__()
        self.sample_rate = int(sample_rate)
        self.freq = float(freq)
        self.amplitude = float(amplitude)
        self.samples_per_frame = int(self.sample_rate * frame_ms / 1000.0)
        self.enabled = True            # False = 静音（mute）
        self.frames_sent = 0
        self._samples = 0

    async def recv(self) -> av.AudioFrame:
        self._samples += self.samples_per_frame
        target = self._samples / self.sample_rate
        delay = target - (time.perf_counter() - _T0)
        if delay > 0:
            await asyncio.sleep(delay)
        n = self.samples_per_frame
        if self.enabled and self.amplitude > 0:
            t = (np.arange(n, dtype=np.float64) + self._samples - n) / self.sample_rate
            wave = self.amplitude * np.sin(2 * np.pi * self.freq * t)
        else:
            wave = np.zeros(n, dtype=np.float64)
        arr = np.clip(wave * 32767.0, -32768, 32767).astype("<i2").reshape(1, n)
        frame = av.AudioFrame.from_ndarray(arr, format="s16", layout="mono")
        frame.sample_rate = self.sample_rate
        frame.pts = self._samples
        frame.time_base = fractions.Fraction(1, self.sample_rate)
        self.frames_sent += 1
        return frame


class QueueAudioTrack(AudioStreamTrack):
    """从队列取 PCM（float32，范围 -1~1）发送；队列空时发静音。"""

    kind = "audio"

    def __init__(self, sample_rate: int = 16000, frame_ms: float = 20.0,
                 max_queue: int = 50):
        super().__init__()
        self.sample_rate = int(sample_rate)
        self.samples_per_frame = int(self.sample_rate * frame_ms / 1000.0)
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue)
        self.enabled = True
        self.frames_sent = 0
        self.dropped_chunks = 0
        self._buf = np.zeros(0, dtype=np.float32)
        self._samples = 0

    def push(self, pcm: np.ndarray) -> None:
        """推入 float32 PCM。队列满则丢最旧的一块（低延迟优先）。"""
        arr = np.asarray(pcm, dtype=np.float32).reshape(-1)
        try:
            self.queue.put_nowait(arr)
        except asyncio.QueueFull:
            try:
                self.queue.get_nowait()
                self.dropped_chunks += 1
            except asyncio.QueueEmpty:
                pass
            try:
                self.queue.put_nowait(arr)
            except asyncio.QueueFull:
                self.dropped_chunks += 1

    async def recv(self) -> av.AudioFrame:
        n = self.samples_per_frame
        need = n - len(self._buf)
        while need > 0:
            try:
                self._buf = np.concatenate([self._buf, self.queue.get_nowait()])
            except asyncio.QueueEmpty:
                break
            need = n - len(self._buf)
        if len(self._buf) >= n:
            chunk = self._buf[:n]
            self._buf = self._buf[n:]
        else:
            chunk = np.zeros(n, dtype=np.float32)
            self._buf = np.zeros(0, dtype=np.float32)
        if not self.enabled:
            chunk = np.zeros(n, dtype=np.float32)
        self._samples += n
        target = self._samples / self.sample_rate
        delay = target - (time.perf_counter() - _T0)
        if delay > 0:
            await asyncio.sleep(delay)
        arr = np.clip(chunk * 32767.0, -32768, 32767).astype("<i2").reshape(1, n)
        frame = av.AudioFrame.from_ndarray(arr, format="s16", layout="mono")
        frame.sample_rate = self.sample_rate
        frame.pts = self._samples
        frame.time_base = fractions.Fraction(1, self.sample_rate)
        self.frames_sent += 1
        return frame


# --------------------------------------------------------------------------
# 视频
# --------------------------------------------------------------------------


def _bars(width: int, height: int, phase: float) -> np.ndarray:
    """生成一帧可见的测试图样（带移动竖条，方便肉眼确认「真的在动」）。"""
    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)[:, None]
    stripe = 0.5 + 0.5 * np.sin((x[None, :] / max(1, width) * 8 + phase) * np.pi)
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[..., 0] = (stripe * 255).astype(np.uint8)
    frame[..., 1] = (np.clip((y - 0) / max(1, height), 0, 1) * 255).astype(np.uint8)
    frame[..., 2] = 64
    return frame


class SyntheticVideoTrack(VideoStreamTrack):
    """按 fps 产出视频帧；帧来源可以是回调（相机/选帧器），默认测试图样。

    ``enabled=False``（摄像头关闭）时发纯黑帧 —— 轨道保持存活，
    等价于浏览器里关摄像头的行为，不触发重协商。
    """

    kind = "video"

    def __init__(self, fps: float = 10.0, width: int = 320, height: int = 240,
                 provider: Optional[Callable[[], Optional[np.ndarray]]] = None):
        super().__init__()
        self.fps = float(fps)
        self.width = int(width)
        self.height = int(height)
        self.provider = provider
        self.enabled = True
        self.frames_sent = 0
        self.frames_blacked = 0
        self.black_frames_when_disabled = True
        self._phase = 0.0

    def _next_frame(self) -> np.ndarray:
        if not self.enabled:
            self.frames_blacked += 1
            return np.zeros((self.height, self.width, 3), dtype=np.uint8)
        if self.provider is not None:
            got = self.provider()
            if got is not None:
                arr = np.asarray(got)
                if arr.dtype != np.uint8:
                    arr = np.clip(arr, 0, 255).astype(np.uint8)
                if arr.ndim == 2:
                    arr = np.stack([arr] * 3, axis=-1)
                return arr
        self._phase += 0.1
        return _bars(self.width, self.height, self._phase)

    async def recv(self) -> av.VideoFrame:
        pts, time_base = await self.next_timestamp()
        arr = self._next_frame()
        frame = av.VideoFrame.from_ndarray(arr, format="rgb24")
        frame.pts = pts
        frame.time_base = time_base
        self.frames_sent += 1
        return frame


_T0 = time.perf_counter()


# --------------------------------------------------------------------------
# 转换工具
# --------------------------------------------------------------------------


def audio_frame_to_f32(frame: av.AudioFrame, target_rate: int = 16000) -> np.ndarray:
    """把收到的音频帧转成单声道 float32（必要时重采样到 target_rate）。"""
    arr = frame.to_ndarray()
    if arr.dtype == np.int16:
        data = arr.astype(np.float32) / 32768.0
    elif arr.dtype == np.int32:
        data = arr.astype(np.float32) / 2147483648.0
    else:
        data = arr.astype(np.float32)
    if data.ndim > 1:
        data = data.mean(axis=0)
    src_rate = int(frame.sample_rate or target_rate)
    if src_rate != target_rate and data.size > 1:
        n_dst = max(1, int(round(len(data) * target_rate / float(src_rate))))
        x_src = np.linspace(0.0, 1.0, len(data), endpoint=False)
        x_dst = np.linspace(0.0, 1.0, n_dst, endpoint=False)
        data = np.interp(x_dst, x_src, data).astype(np.float32)
    return np.ascontiguousarray(data, dtype=np.float32)


def video_frame_to_rgb(frame: av.VideoFrame) -> np.ndarray:
    """把收到的视频帧转成 RGB ndarray（uint8）。"""
    arr = frame.to_ndarray(format="rgb24")
    return np.ascontiguousarray(arr)


def frame_energy(rgb: np.ndarray) -> float:
    """帧的平均亮度（0~1），用来判定「黑帧 / 有画面」。"""
    if rgb is None or rgb.size == 0:
        return 0.0
    return float(np.asarray(rgb, dtype=np.float32).mean() / 255.0)
