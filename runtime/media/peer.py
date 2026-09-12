# -*- coding: utf-8 -*-
"""Peer Connection 抽象（aiortc 实现）。

这一层只做「一条 WebRTC 连接」的事：SDP、ICE、轨道、状态、统计。
它不知道 Quest、不知道 Omni、也不知道信令是走 WebSocket 还是进程内。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

from .types import ConnectionState, IceServerConfig, MediaQualitySample


@dataclass
class PeerConfig:
    role: str = "offerer"                      # offerer / answerer
    ice_servers: list = field(default_factory=list)   # list[IceServerConfig]
    ice_transport_policy: str = "all"          # all / relay（relay 需要 TURN）

    def to_rtc(self) -> RTCConfiguration:
        servers = []
        for item in self.ice_servers:
            cfg = item if isinstance(item, IceServerConfig) else IceServerConfig.from_env_like([item])[0]
            if not cfg.urls:
                continue
            kwargs = {"urls": list(cfg.urls)}
            if cfg.username:
                kwargs["username"] = cfg.username
                kwargs["credential"] = cfg.credential
                kwargs["credentialType"] = cfg.credential_type
            try:
                servers.append(RTCIceServer(**kwargs))
            except Exception:
                servers.append(RTCIceServer(urls=list(cfg.urls)))
        # 不同 aiortc 版本对 iceTransportPolicy 的支持不一致：支持就带上，
        # 不支持就退回默认（媒体层不因此报错，策略差异记在 config 里）。
        try:
            return RTCConfiguration(iceServers=servers,
                                    iceTransportPolicy=self.ice_transport_policy)
        except TypeError:
            return RTCConfiguration(iceServers=servers)


class PeerLink:
    """一条 RTCPeerConnection 的薄封装。"""

    def __init__(self, config: Optional[PeerConfig] = None):
        self.config = config or PeerConfig()
        self.pc = RTCPeerConnection(configuration=self.config.to_rtc())
        self.remote_tracks: dict = {}
        self._connected = asyncio.Event()
        self._gathered = asyncio.Event()
        self._closed = False
        self._on_track_cb: Optional[Callable] = None
        self._state_history: list = []
        self.created_at = time.time()
        self.connected_at = 0.0

        @self.pc.on("track")
        def _on_track(*args):
            track = args[0]
            self.remote_tracks[track.kind] = track
            if self._on_track_cb is not None:
                try:
                    self._on_track_cb(track)
                except Exception:
                    pass

        @self.pc.on("connectionstatechange")
        def _on_state():
            state = self.pc.connectionState
            self._state_history.append((time.time(), state))
            if state == "connected":
                self.connected_at = time.time()
                self._connected.set()
            elif state in ("failed", "closed", "disconnected"):
                self._connected.clear()

        @self.pc.on("icegatheringstatechange")
        def _on_gather():
            if self.pc.iceGatheringState == "complete":
                self._gathered.set()

    # ---------- 轨道 ----------
    def add_track(self, track):
        return self.pc.addTrack(track)

    def on_track(self, cb: Callable) -> None:
        self._on_track_cb = cb

    # ---------- 协商 ----------
    async def create_offer(self) -> str:
        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        return self.pc.localDescription.sdp

    async def create_answer(self) -> str:
        answer = await self.pc.createAnswer()
        await self.pc.setLocalDescription(answer)
        return self.pc.localDescription.sdp

    async def set_remote(self, sdp_type: str, sdp: str) -> None:
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=sdp_type))

    async def wait_ice_gathering(self, timeout: float = 5.0) -> bool:
        try:
            await asyncio.wait_for(self._gathered.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_connected(self, timeout: float = 15.0) -> bool:
        if self.pc.connectionState == "connected":
            return True
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ---------- 状态 ----------
    @property
    def connection_state(self) -> str:
        return self.pc.connectionState

    @property
    def ice_state(self) -> str:
        return self.pc.iceConnectionState

    def state_history(self) -> list:
        return [{"ts": ts, "state": s} for ts, s in self._state_history]

    # ---------- 统计 ----------
    async def stats(self) -> MediaQualitySample:
        sample = MediaQualitySample()
        try:
            report = await self.pc.getStats()
        except Exception:
            return sample
        items = report.values() if isinstance(report, dict) else report
        for st in items:
            t = getattr(st, "type", "")
            if t == "candidate-pair" and (getattr(st, "state", "") == "succeeded"
                                          or getattr(st, "nominated", False)):
                rtt = getattr(st, "currentRoundTripTime", None)
                if rtt:
                    sample.rtt_ms = float(rtt) * 1000.0
            elif t in ("inbound-rtp", "outbound-rtp"):
                sample.packets_lost += int(getattr(st, "packetsLost", 0) or 0)
                sample.packets_received += int(getattr(st, "packetsReceived", 0) or 0)
                jitter = getattr(st, "jitter", None)
                if jitter:
                    # aiortc 的 jitter 是 RTP 时间戳单位，不是秒：必须除以时钟频率。
                    # （不除会得到几十万毫秒的假抖动，把带宽自适应一路打到 CRITICAL。）
                    clock = getattr(st, "clockRate", None) or 0
                    if not clock:
                        kind = getattr(st, "kind", "") or getattr(st, "mediaType", "")
                        clock = 48000 if kind == "audio" else 90000
                    sample.jitter_ms = max(sample.jitter_ms,
                                           float(jitter) / float(clock) * 1000.0)
                fps = getattr(st, "framesPerSecond", None)
                if fps:
                    sample.frames_per_second = max(sample.frames_per_second, float(fps))
        if sample.packets_received > 0:
            sample.loss_ratio = sample.packets_lost / float(sample.packets_received + sample.packets_lost)
        return sample

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.pc.close()
        except Exception:
            pass
