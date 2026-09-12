# -*- coding: utf-8 -*-
"""栖语 · 本地动捕层（Quest 本地高频）。

职责：
- 30~60Hz 的本地人体状态（``HumanMotionState``）**只留在本地**；
- 识别出的交互事件（``HumanInteractionEvent``）与**降采样摘要**才允许进 Omni；
- 共享注意力（``SharedAttention``）在本地算，Omni 只收结论。

**不 import WebRTC，也不 import Omni 内部实现**：事件用 ``runtime.omni.types``
里的同名数据类（那是跨层契约），除此之外没有任何依赖。
"""

from .types import (  # noqa: F401
    GestureName, HumanJoint, HumanMotionState, MotionSummary, Vec3,
)
from .recognizer import GestureRecognizer, RecognizerConfig  # noqa: F401
from .aggregator import HumanMotionAggregator  # noqa: F401
from .shared_attention import (  # noqa: F401
    AreaOfInterest, SharedAttention, SharedAttentionTracker,
)

__all__ = [
    "GestureName", "HumanJoint", "HumanMotionState", "MotionSummary", "Vec3",
    "GestureRecognizer", "RecognizerConfig",
    "HumanMotionAggregator",
    "AreaOfInterest", "SharedAttention", "SharedAttentionTracker",
]
