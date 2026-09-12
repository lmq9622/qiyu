# -*- coding: utf-8 -*-
"""栖语 · Realtime Omni 架构（产品主线 0.1.x）。

新核心架构（规格 §26）：

```text
Message / Audio / Video / WorldEvent
              ↓
        Realtime Omni          ← runtime.omni.session.OmniSession
              ↓
       Unified Brain Event      ← runtime.omni.types.UnifiedBrainEvent
     ┌────────┴─────────┐
     ↓                  ↓
 Conversation       AvatarIntent
     ↓                  ↓
Streaming Audio    Behavior Policy
     ↓                  ↓
 Quest Audio      Motion / IK / Animator（全部在 Quest 本地）
```

对外只有一个入口::

    from runtime.omni import build_omni
    session = build_omni()                 # 选后端（本地 → 云端 → mock）
    await session.start_session(cfg)
"""

from runtime.omni.interface import (
    BackendUnavailable,
    IRealtimeOmni,
    IRealtimeOmniBackend,
    IRealtimeOmniStream,
)
from runtime.omni.registry import OmniBackendRegistry, get_registry
from runtime.omni.session import OmniSession
from runtime.omni.types import (
    AudioChunk,
    AvatarIntent,
    AvatarIntentName,
    BackendCapabilities,
    ConversationOutput,
    EventKind,
    FrameKind,
    HumanInteractionEvent,
    OmniOutputKind,
    SessionConfig,
    SessionState,
    SpeakerId,
    UnifiedBrainEvent,
    VideoFrame,
    WorldEvent,
    empty_world_state,
    normalize_world_state,
)
from runtime.omni.video_scheduler import VideoScheduler

__all__ = [
    "AudioChunk",
    "AvatarIntent",
    "AvatarIntentName",
    "BackendCapabilities",
    "BackendUnavailable",
    "ConversationOutput",
    "EventKind",
    "FrameKind",
    "HumanInteractionEvent",
    "IRealtimeOmni",
    "IRealtimeOmniBackend",
    "IRealtimeOmniStream",
    "OmniBackendRegistry",
    "OmniOutputKind",
    "OmniSession",
    "SessionConfig",
    "SessionState",
    "SpeakerId",
    "UnifiedBrainEvent",
    "VideoFrame",
    "VideoScheduler",
    "WorldEvent",
    "build_omni",
    "build_omni_session",
    "empty_world_state",
    "get_registry",
    "normalize_world_state",
]


def build_omni(prefer: str = "", allow_mock: bool = True, **kwargs) -> OmniSession:
    """构建一个 OmniSession（唯一对外入口）。

    ``allow_mock=True`` 时，本地/云端都不可用会退回 MockOmniBackend，
    保证链路可测；生产环境应保持默认的 ``QIYU_OMNI_ALLOW_MOCK`` 未设置状态，
    使 mock 不被选中。
    """
    from runtime.omni.registry import OmniBackendRegistry

    registry = OmniBackendRegistry(allow_mock=allow_mock)
    backend = registry.select(prefer=prefer)
    if backend is None:
        raise BackendUnavailable(
            "没有可用的 Realtime Omni 后端：" + str(registry.report())
        )
    session = OmniSession(backend, **kwargs)
    session.registry_report = registry.report()  # type: ignore[attr-defined]
    return session


def build_omni_session(*args, **kwargs) -> OmniSession:
    """``build_omni`` 的别名，语义更直白。"""
    return build_omni(*args, **kwargs)
