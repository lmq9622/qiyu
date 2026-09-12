# -*- coding: utf-8 -*-
"""栖语 · WebRTC 媒体层（Media Plane）。

**与 AI 认知层完全解耦**：本包不 import ``runtime.omni``，
Omni 也不 import 本包。两边只通过 ``runtime/media/ai_adapter.py`` 单向桥接。

分层：

    Quest  ↔  MediaSession  ↔  Remote Peer          （媒体面，WebRTC）
                 │
                 └─(按需、已降采样)→ AI Media Adapter → OmniSession   （AI 面）
"""

from .types import (  # noqa: F401
    ConnectionState, MediaSessionState, TrackKind, IceServerConfig,
    MediaSessionStats, MediaQualitySample,
)
from .signaling import (  # noqa: F401
    SignalKind, SignalMessage, SignalingTransport, InProcessSignaling,
)
from .tracks import ToneAudioTrack, SyntheticVideoTrack, QueueAudioTrack  # noqa: F401
from .peer import PeerLink, PeerConfig  # noqa: F401
from .session import MediaSession, MediaSessionConfig  # noqa: F401
from .service import VideoCallService  # noqa: F401

__all__ = [
    "ConnectionState", "MediaSessionState", "TrackKind", "IceServerConfig",
    "MediaSessionStats", "MediaQualitySample",
    "SignalKind", "SignalMessage", "SignalingTransport", "InProcessSignaling",
    "ToneAudioTrack", "SyntheticVideoTrack", "QueueAudioTrack",
    "PeerLink", "PeerConfig",
    "MediaSession", "MediaSessionConfig",
    "VideoCallService",
]
