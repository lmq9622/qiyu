# -*- coding: utf-8 -*-
"""运行时：真实音频播放 + WASAPI 回环（loopback）校验。

为什么需要这个模块
------------------
`runtime/avatar.py` 里的 ``AudioOutput`` 只是占位（``play`` / ``interrupt`` 都抛
``NotImplementedError``）。但「播放侧 barge-in」要验证的是**扬声器真的在响、真的停了**，
不是「``interrupt()`` 被调用过」。所以这里补上真正的设备能力：

- ``AudioPlayer``：soundcard（Windows WASAPI 共享模式）真实输出。写线程 + 有界队列，
  ``flush()`` 立刻清空队列并停止后续写入。注意：**已经进了端点缓冲的那几十毫秒还会放完**，
  所以「可听见的停止」必须实测，不能拿 ``flush()`` 的返回时间冒充。
- ``LoopbackMonitor``：对同一台扬声器做 WASAPI **回环采集**，实时算 RMS。用它判定
  「确实在响」和「确实停了」，给出**可听见的**停止时刻。

后端不可用时退化为 ``NullPlayer`` / ``NullMonitor``，报告里标 ``SIMULATED``，
绝不冒充真机。
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

SRC_RATE_INPUT = 16000     # 送进模型的音频
SRC_RATE_OUTPUT = 24000    # 模型 TTS 出来的音频（omni.cpp: audio_output_cb(..., 24000, ...)）


def _co_init() -> None:
    """soundcard 每个线程都要自己初始化 COM，否则报 0x800401f0。"""
    try:
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)
    except Exception:
        pass


def _resample(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or pcm.size == 0:
        return pcm.astype(np.float32, copy=False)
    n_dst = max(1, int(round(len(pcm) * dst_rate / float(src_rate))))
    x_src = np.linspace(0.0, 1.0, len(pcm), endpoint=False)
    x_dst = np.linspace(0.0, 1.0, n_dst, endpoint=False)
    return np.interp(x_dst, x_src, pcm).astype(np.float32)


def _b64_to_f32(b64: str) -> np.ndarray:
    import base64
    raw = base64.b64decode(b64)
    return np.frombuffer(raw, dtype="<f4").astype(np.float32, copy=True)


@dataclass
class PlaybackStats:
    backend: str = "null"
    device: str = ""
    samplerate: int = 0
    channels: int = 0
    enqueued_frames: int = 0      # 设备采样率下的帧
    rendered_frames: int = 0
    underrun_blocks: int = 0      # 说话中途断粮（真正会让音节被切）
    idle_silence_blocks: int = 0  # 空闲时的静音写
    flush_count: int = 0
    flush_ms_last: float = 0.0
    dropped_frames_last: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class AudioPlayer:
    """soundcard(WASAPI) 真实播放器：写线程 + 有界队列 + flush。"""

    def __init__(self, device: str = "", samplerate: int = 48000, channels: int = 2,
                 blocksize: int = 2400, queue_ms: int = 4000,
                 prebuffer_ms: float = 400.0, label: str = ""):
        self.device = device
        self.sr = int(samplerate)
        self.ch = int(channels)
        self.bs = int(blocksize)
        # 抖动缓冲：模型给的是「一阵一阵」的音频（一段一段发，段与段之间还有间隔），
        # 边到边播会把每个音节切碎。先攒够 prebuffer_ms 再开始消耗，缺口明显减少。
        self.prebuffer_ms = float(prebuffer_ms)
        self.max_blocks = max(4, int(queue_ms / max(1.0, 1000.0 * self.bs / self.sr)))
        self.label = label
        self.stats = PlaybackStats(samplerate=self.sr, channels=self.ch)
        self._q: deque = deque()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_write_ts = 0.0
        self._active_ms = 0.0
        self._draining = False

    # ---------- 生命周期 ----------
    def start(self, timeout: float = 5.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="qiyu-audio-player", daemon=True)
        self._thread.start()
        return self._ready.wait(timeout)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        _co_init()
        try:
            import soundcard as sc
            spk = sc.get_speaker(self.device) if self.device else sc.default_speaker()
            self.stats.device = str(spk.name)
            self.stats.backend = "soundcard"
            with spk.player(samplerate=self.sr, channels=self.ch, blocksize=self.bs) as p:
                self._ready.set()
                while not self._stop.is_set():
                    if not self._draining and self.queued_ms >= self.prebuffer_ms:
                        self._draining = True
                    blk = self._take(self.bs)
                    p.play(blk)
                    with self._lock:
                        self.stats.rendered_frames += self.bs
                        self._last_write_ts = time.perf_counter()
        except Exception as e:  # 设备被占用/不存在等
            self.stats.backend = "null"
            self.stats.error = f"{type(e).__name__}: {e}"
            self._ready.set()

    # ---------- 数据 ----------
    def enqueue_pcm(self, pcm: np.ndarray, src_rate: int = SRC_RATE_OUTPUT) -> int:
        """把模型输出（f32 单声道）转成设备格式入队；返回入队帧数。"""
        if self.stats.backend != "soundcard":
            return 0
        pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if pcm.size == 0:
            return 0
        up = _resample(pcm, src_rate, self.sr)
        if self.ch > 1:
            up = np.repeat(up[:, None], self.ch, axis=1)
        with self._lock:
            if len(self._q) >= self.max_blocks * 4:
                self._q.popleft()          # 丢最旧的，避免无限堆积
            self._q.append(up)
            self.stats.enqueued_frames += len(up)
        return len(up)

    def enqueue_b64(self, b64: str, src_rate: int = SRC_RATE_OUTPUT) -> int:
        return self.enqueue_pcm(_b64_to_f32(b64), src_rate=src_rate)

    def _take(self, n: int) -> np.ndarray:
        out = np.zeros((n, self.ch), dtype=np.float32)
        got = 0
        with self._lock:
            while got < n and self._q:
                blk = self._q[0]
                need = n - got
                if len(blk) <= need:
                    out[got:got + len(blk)] = blk
                    got += len(blk)
                    self._q.popleft()
                else:
                    out[got:got + need] = blk[:need]
                    self._q[0] = blk[need:]
                    got += need
            if got < n:
                if self._draining:
                    self.stats.underrun_blocks += 1      # 说话中途断粮 → 声音被切开
                    if len(self._q) == 0:
                        self._draining = False           # 这段放完，等下一段攒够再放
                else:
                    self.stats.idle_silence_blocks += 1  # 本来就没人说话
        return out

    # ---------- 打断 ----------
    def flush(self, reason: str = "barge_in") -> float:
        """清空待播队列并停止写入；返回本地清空耗时(ms)。

        ⚠️ 返回的是**本地**耗时，不含端点缓冲残余。可听见的停止时刻由
        ``LoopbackMonitor`` 实测（见 smoke/barge_in_playback.py）。
        """
        t0 = time.perf_counter()
        with self._lock:
            dropped = sum(len(b) for b in self._q)
            self._q.clear()
        self.stats.flush_count += 1
        self.stats.dropped_frames_last = dropped
        ms = (time.perf_counter() - t0) * 1000.0
        self.stats.flush_ms_last = round(ms, 3)
        return ms

    # ---------- 状态 ----------
    @property
    def queued_ms(self) -> float:
        with self._lock:
            frames = sum(len(b) for b in self._q)
        return frames * 1000.0 / self.sr

    @property
    def playing(self) -> bool:
        return self.queued_ms > 0.0


class LoopbackMonitor:
    """对同一台扬声器做 WASAPI 回环采集，判定「真的在响 / 真的停了」。"""

    def __init__(self, speaker_name: str = "", samplerate: int = 48000,
                 blocksize: int = 480, keep_sec: float = 60.0):
        self.speaker_name = speaker_name
        self.sr = int(samplerate)
        self.bs = int(blocksize)
        self.keep = float(keep_sec)
        self.samples: deque = deque()          # (perf_ts, rms, peak)
        self.used: deque = deque()             # 原始波形（仅 dump 用）
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.backend = "null"
        self.error = ""
        self.device = ""
        self._dump = False

    def start(self, timeout: float = 5.0, dump: bool = False) -> bool:
        self._dump = dump
        self._thread = threading.Thread(target=self._run, name="qiyu-loopback", daemon=True)
        self._thread.start()
        return self._ready.wait(timeout)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        _co_init()
        try:
            import soundcard as sc
            name = self.speaker_name or str(sc.default_speaker().name)
            mic = sc.get_microphone(name, include_loopback=True)
            self.device = str(mic.name)
            if not getattr(mic, "isloopback", False):
                raise RuntimeError("取到的不是 loopback 设备")
            with mic.recorder(samplerate=self.sr, channels=1, blocksize=self.bs) as r:
                self.backend = "soundcard-loopback"
                self._ready.set()
                while not self._stop.is_set():
                    blk = np.asarray(r.record(numframes=self.bs), dtype=np.float32).reshape(-1)
                    ts = time.perf_counter()
                    rms = float(np.sqrt(np.mean(blk * blk))) if blk.size else 0.0
                    peak = float(np.max(np.abs(blk))) if blk.size else 0.0
                    self.samples.append((ts, rms, peak))
                    if self._dump:
                        self.used.append(blk.copy())
                    while len(self.samples) > self.keep * self.sr / self.bs:
                        self.samples.popleft()
        except Exception as e:
            self.backend = "null"
            self.error = f"{type(e).__name__}: {e}"
            self._ready.set()

    # ---------- 判定 ----------
    def noise_floor(self, since: Optional[float] = None) -> float:
        vals = [r for ts, r, _ in self.samples if since is None or ts >= since]
        return float(np.median(vals)) if vals else 0.0

    def peak_rms(self, since: Optional[float] = None) -> float:
        vals = [r for ts, r, _ in self.samples if since is None or ts >= since]
        return float(np.max(vals)) if vals else 0.0

    def wait_above(self, thr: float, timeout: float = 10.0,
                   since: Optional[float] = None) -> Optional[float]:
        """等第一个 RMS > thr 的块，返回 perf 时间戳。"""
        deadline = time.perf_counter() + timeout
        idx = 0
        while time.perf_counter() < deadline:
            snap = list(self.samples)
            while idx < len(snap):
                ts, rms, _ = snap[idx]
                idx += 1
                if (since is None or ts >= since) and rms > thr:
                    return ts
            time.sleep(0.002)
        return None

    def wait_below(self, thr: float, hold_ms: float = 60.0, timeout: float = 5.0,
                   since: Optional[float] = None) -> Optional[float]:
        """等连续 hold_ms 都低于 thr，返回**第一个低于阈值的那一块**的时间戳。"""
        deadline = time.perf_counter() + timeout
        idx = 0
        hold = hold_ms / 1000.0
        start_low: Optional[float] = None
        while time.perf_counter() < deadline:
            snap = list(self.samples)
            while idx < len(snap):
                ts, rms, _ = snap[idx]
                idx += 1
                if since is not None and ts < since:
                    continue
                if rms <= thr:
                    if start_low is None:
                        start_low = ts
                    if ts - start_low >= hold:
                        return start_low
                else:
                    start_low = None
            time.sleep(0.002)
        return None

    def dump_wav(self, path) -> bool:
        if not self.used:
            return False
        import wave
        data = np.concatenate(list(self.used))
        pcm16 = np.clip(data, -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype("<i2")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sr)
            w.writeframes(pcm16.tobytes())
        return True

    def snapshot(self) -> dict:
        return {"backend": self.backend, "device": self.device, "error": self.error,
                "samplerate": self.sr, "blocks": len(self.samples)}


class NullPlayer:
    """没有设备时的占位：行为一致但不出声，报告里标 SIMULATED。"""

    stats = PlaybackStats(backend="null")

    def start(self, timeout: float = 0.0) -> bool:
        return False

    def close(self) -> None:
        return None

    def enqueue_pcm(self, pcm, src_rate: int = SRC_RATE_OUTPUT) -> int:
        return 0

    def enqueue_b64(self, b64: str, src_rate: int = SRC_RATE_OUTPUT) -> int:
        return 0

    def flush(self, reason: str = "barge_in") -> float:
        return 0.0

    @property
    def queued_ms(self) -> float:
        return 0.0

    @property
    def playing(self) -> bool:
        return False


class NullMonitor:
    backend = "null"
    error = ""
    device = ""

    def start(self, timeout: float = 0.0, dump: bool = False) -> bool:
        return False

    def close(self) -> None:
        return None

    def noise_floor(self, since=None) -> float:
        return 0.0

    def peak_rms(self, since=None) -> float:
        return 0.0

    def wait_above(self, thr, timeout=0.0, since=None):
        return None

    def wait_below(self, thr, hold_ms=60.0, timeout=0.0, since=None):
        return None

    def dump_wav(self, path) -> bool:
        return False

    def snapshot(self) -> dict:
        return {"backend": "null", "device": "", "error": "", "blocks": 0}


def build_player(device: str = "", samplerate: int = 48000, channels: int = 2,
                 blocksize: int = 480, allow_null: bool = True):
    p = AudioPlayer(device=device, samplerate=samplerate, channels=channels, blocksize=blocksize)
    ok = p.start()
    if ok and p.stats.backend == "soundcard":
        return p
    if not allow_null:
        raise RuntimeError(f"音频输出不可用：{p.stats.error}")
    p.close()
    return NullPlayer()


def build_monitor(speaker_name: str = "", samplerate: int = 48000,
                  blocksize: int = 480, allow_null: bool = True, dump: bool = False):
    m = LoopbackMonitor(speaker_name=speaker_name, samplerate=samplerate, blocksize=blocksize)
    ok = m.start(dump=dump)
    if ok and m.backend == "soundcard-loopback":
        return m
    if not allow_null:
        raise RuntimeError(f"回环采集不可用：{m.error}")
    m.close()
    return NullMonitor()


__all__ = [
    "AudioPlayer", "LoopbackMonitor", "NullPlayer", "NullMonitor",
    "PlaybackStats", "build_player", "build_monitor",
    "SRC_RATE_INPUT", "SRC_RATE_OUTPUT",
]
