# -*- coding: utf-8 -*-
"""媒体层数据模型（WebRTC 面）。

这里只描述**媒体**：连接状态、轨道类型、ICE 配置、统计。
不含任何「认知」概念（那是 ``runtime/omni/types.py`` 的事）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class TrackKind(str, Enum):
    AUDIO = "audio"
    VIDEO = "video"


class ConnectionState(str, Enum):
    """与 RTCPeerConnection.connectionState 对齐，另加我们自己的 idle/recovering。"""

    IDLE = "idle"
    NEW = "new"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    RECOVERING = "recovering"
    CLOSED = "closed"


class MediaSessionState(str, Enum):
    IDLE = "idle"
    OFFERING = "offering"
    ANSWERING = "answering"
    LIVE = "live"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"
    ERROR = "error"


@dataclass
class IceServerConfig:
    """STUN/TURN 抽象。空列表 = 只走局域网候选（本机回环验证用）。"""

    urls: list = field(default_factory=list)
    username: str = ""
    credential: str = ""
    credential_type: str = "password"

    def to_dict(self) -> dict:
        out = {"urls": list(self.urls)}
        if self.username:
            out["username"] = self.username
            out["credential"] = self.credential
        return out

    @staticmethod
    def from_env_like(raw: list) -> list:
        """接受 ["stun:host:port", {"urls": [...], "username":..., "credential":...}]。"""
        out = []
        for item in raw or []:
            if isinstance(item, str):
                out.append(IceServerConfig(urls=[item]))
            elif isinstance(item, dict):
                out.append(IceServerConfig(
                    urls=list(item.get("urls") or []),
                    username=item.get("username", ""),
                    credential=item.get("credential", ""),
                ))
        return out


@dataclass
class MediaQualitySample:
    """一次网络质量采样（来自 RTCPeerConnection.getStats）。"""

    timestamp: float = field(default_factory=time.time)
    rtt_ms: float = 0.0
    jitter_ms: float = 0.0
    packets_lost: int = 0
    packets_received: int = 0
    bitrate_kbps: float = 0.0
    loss_ratio: float = 0.0
    frames_per_second: float = 0.0

    def to_dict(self) -> dict:
        return {
            "ts": self.timestamp,
            "rtt_ms": round(self.rtt_ms, 2),
            "jitter_ms": round(self.jitter_ms, 2),
            "packets_lost": self.packets_lost,
            "packets_received": self.packets_received,
            "bitrate_kbps": round(self.bitrate_kbps, 1),
            "loss_ratio": round(self.loss_ratio, 4),
            "fps": round(self.frames_per_second, 1),
        }


@dataclass
class MediaSessionStats:
    session_id: str = ""
    state: str = MediaSessionState.IDLE.value
    connection: str = ConnectionState.IDLE.value
    peer_role: str = ""                  # offerer / answerer
    audio_track_out: bool = False
    video_track_out: bool = False
    audio_track_in: bool = False
    video_track_in: bool = False
    muted: bool = False
    camera_enabled: bool = True
    created_at: float = field(default_factory=time.time)
    connected_at: float = 0.0
    reconnects: int = 0
    closed_at: float = 0.0
    error: str = ""
    last_quality: dict = field(default_factory=dict)
    audio_frames_sent: int = 0
    audio_frames_received: int = 0
    video_frames_sent: int = 0
    video_frames_received: int = 0

    def to_dict(self) -> dict:
        return dict(self.__dict__)
