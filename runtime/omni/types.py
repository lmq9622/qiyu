# -*- coding: utf-8 -*-
"""栖语 · Realtime Omni 数据模型（版本体系 v2，产品主线 0.1.x）。

这个模块定义了新架构里所有的「跨层契约」。设计约束（来自架构规格）：

1. **Omni 只出两条**：``ConversationOutput``（话）+ ``AvatarIntent``（想做什么）。
   Omni 绝不允许输出骨骼 / IK / 每帧 transform / Animator 参数 / 脚步轨迹。
2. **音频事件必须带 ``speaker_id``**（``local_user`` / ``remote_user`` / ``qiyu``），
   为多人场景预留。
3. **视频帧必须带 ``timestamp`` 与 ``frame_id``**，并区分
   ``keyframe`` / ``roi`` / ``snapshot`` / ``burst``。
4. 高频的身体执行（30~60Hz 动捕、Reflex、IK、Animator）**全部留在 Quest 本地**，
   这里只承载降采样的 ``WorldState`` 摘要与事件。

单位约定：``timestamp`` 一律为 Unix 秒（float）；音频为 PCM float32
（-1.0~1.0），采样率默认 16000；``delay`` / 时延单位为毫秒。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class SpeakerId(str, Enum):
    """音频来源。为多人场景预留，新事件必须带这个字段。"""

    LOCAL_USER = "local_user"
    REMOTE_USER = "remote_user"
    QIYU = "qiyu"
    SYSTEM = "system"


class FrameKind(str, Enum):
    """视频帧类型。默认只按调度器发 keyframe/snapshot，不做 30/60FPS 直推。"""

    KEYFRAME = "keyframe"
    ROI = "roi"              # 用户指向/关注的局部区域
    SNAPSHOT = "snapshot"    # 事件触发的单帧
    BURST = "burst"          # 短促连拍（用户拿起物体、远端动作）


class EventKind(str, Enum):
    """统一进 Omni 的事件类别（规格 §3：输入统一进 OmniSession）。"""

    USER_TEXT = "user_text"
    HUMAN_INTERACTION = "human_interaction"
    WORLD_STATE = "world_state"
    SHARED_ATTENTION = "shared_attention"
    AVATAR_STATE = "avatar_state"
    MEMORY_HINT = "memory_hint"
    REMOTE_MEDIA = "remote_media"
    MOTION = "motion"
    SYSTEM = "system"


class OmniOutputKind(str, Enum):
    """Omni 的两条输出 + 一条内部事件。"""

    CONVERSATION = "conversation"
    AVATAR_INTENT = "avatar_intent"
    EVENT = "event"          # 会话生命周期/错误/打断等内部事件


class SessionState(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    CLOSED = "closed"
    ERROR = "error"


class AvatarIntentName(str, Enum):
    """AvatarIntent 允许的行为名（规格 §7-B）。

    这个集合是**封闭**的：Omni 只能从这里挑，具体怎么做交给 Behavior Policy。
    """

    LOOK_AT = "look_at"
    APPROACH = "approach"
    FOLLOW = "follow"
    RETREAT = "retreat"
    WAVE = "wave"
    POINT = "point"
    GESTURE = "gesture"
    WAIT = "wait"
    SIT = "sit"
    STAND = "stand"
    HIGH_FIVE = "high_five"
    OBSERVE = "observe"
    COOPERATE = "cooperate"
    NOD = "nod"
    SHAKE_HEAD = "shake_head"
    IDLE = "idle"


# ---------------------------------------------------------------------------
# 输入侧
# ---------------------------------------------------------------------------


@dataclass
class AudioChunk:
    """一路音频分片。流式输入的最小单位，不等整句。

    - ``pcm``：float32 PCM，范围 -1.0~1.0（也允许 int16 的 bytes，由后端归一化）
    - ``sample_rate``：采样率
    - ``speaker_id``：**必填语义**，默认本地用户
    - ``is_speech``：VAD 结论；None 表示还没判
    - ``seq``：同一路音频的单调序号，用于丢包/乱序检测
    """

    pcm: Any
    sample_rate: int = 16000
    speaker_id: str = SpeakerId.LOCAL_USER.value
    timestamp: float = field(default_factory=time.time)
    is_speech: Optional[bool] = None
    seq: int = 0
    channels: int = 1
    meta: dict = field(default_factory=dict)

    def duration_ms(self) -> float:
        try:
            n = len(self.pcm)
        except TypeError:
            n = 0
        return 1000.0 * n / max(1, self.sample_rate)


@dataclass
class VideoFrame:
    """一帧视频。必须带 timestamp 与 frame_id（规格 §5）。

    ``data`` 可以是 numpy 数组、JPEG bytes 或任何后端能吃的对象。
    """

    data: Any
    timestamp: float = field(default_factory=time.time)
    frame_id: int = 0
    kind: str = FrameKind.KEYFRAME.value
    width: int = 0
    height: int = 0
    source: str = "quest_camera"       # quest_camera / remote_peer / screenshot
    roi: Optional[tuple] = None        # (x, y, w, h) 归一化或像素
    speaker_id: str = ""               # 远端视频时标明属于谁
    meta: dict = field(default_factory=dict)


@dataclass
class WorldEvent:
    """来自 Quest / 远端的结构化事件（已降采样，不是每帧）。"""

    kind: str = EventKind.WORLD_STATE.value
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    priority: int = 0                  # 越大越优先；>=80 视为高优先，可打断当前输出
    source: str = "quest"


@dataclass
class HumanInteractionEvent:
    """本地动捕 → 事件（规格 §9）。原始骨骼不上传，只上传事件。"""

    name: str = ""                     # wave / point / stop / come_here / reach / give / sit / stand / look / nod / shake_head / high_five
    confidence: float = 0.0
    target: str = ""                   # user / avatar / object:<id>
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AvatarIntent:
    """Omni → Behavior Policy 的唯一行为输出（规格 §7-B / §8）。

    **禁止**在这里出现骨骼 / IK / transform / 脚步轨迹 / Animator 参数。
    这里只回答「想做什么、对谁、带什么情绪」，怎么做由 Behavior Policy 决定。
    """

    intent: str = AvatarIntentName.IDLE.value
    target: str = ""                   # user / avatar / object:<id> / location:<id>
    emotion: str = ""
    urgency: float = 0.0               # 0~1
    attention: str = ""                # 注意力焦点描述
    style: str = ""                    # behavior_style 提示（不是 animator 参数）
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    meta: dict = field(default_factory=dict)

    def to_wire(self) -> dict:
        """转 Quest 协议（v1.1 兼容字段）。"""
        return {
            "type": "avatar_intent",
            "intent": self.intent,
            "target": self.target,
            "emotion": self.emotion,
            "urgency": round(float(self.urgency), 3),
            "attention": self.attention,
            "behavior_style": self.style,
            "reason": self.reason,
            "ts": self.timestamp,
        }


@dataclass
class ConversationOutput:
    """Omni 的「话」：流式文本 + 流式音频 + 情绪表达。"""

    text: str = ""
    is_final: bool = False
    audio: Any = None                  # 原生 speech output 的 audio chunk
    audio_format: str = ""             # pcm_f32 / pcm_s16 / mp3 / opus
    sample_rate: int = 24000
    emotion: str = ""
    emotion_intensity: float = 0.0
    viseme_hint: Any = None            # phoneme/viseme/timing，供口型同步
    speaker_id: str = SpeakerId.QIYU.value
    timestamp: float = field(default_factory=time.time)
    latency_ms: dict = field(default_factory=dict)


@dataclass
class UnifiedBrainEvent:
    """Omni 输出的统一事件信封。

    上层业务（UI / Quest 网关 / 日志 / REAL_CONVERSATION_TEST）只消费这个，
    不去碰具体 backend。
    """

    kind: str = OmniOutputKind.EVENT.value
    session_id: str = ""
    conversation: Optional[ConversationOutput] = None
    avatar_intent: Optional[AvatarIntent] = None
    payload: dict = field(default_factory=dict)
    state: str = SessionState.IDLE.value
    seq: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_wire(self) -> dict:
        out: dict = {
            "type": "unified_brain_event",
            "kind": self.kind,
            "session_id": self.session_id,
            "state": self.state,
            "seq": self.seq,
            "ts": self.timestamp,
        }
        if self.conversation is not None:
            out["conversation"] = {
                "text": self.conversation.text,
                "final": self.conversation.is_final,
                "emotion": self.conversation.emotion,
                "has_audio": self.conversation.audio is not None,
                "sample_rate": self.conversation.sample_rate,
                "latency_ms": self.conversation.latency_ms,
            }
        if self.avatar_intent is not None:
            out["avatar_intent"] = self.avatar_intent.to_wire()
        if self.payload:
            out["payload"] = self.payload
        return out


# ---------------------------------------------------------------------------
# WorldState（规格 §6）：只发事件/状态摘要，不是每帧
# ---------------------------------------------------------------------------


def empty_world_state() -> dict:
    """WorldState 的规范骨架（与 Quest 侧 MRUK 发布器对齐）。"""
    return {
        "user": {},
        "avatar": {},
        "objects": [],
        "room": {},
        "attention": {},
        "interaction": {},
        "ts": time.time(),
    }


def normalize_world_state(raw: Optional[dict]) -> dict:
    """把外部 WorldState 归一化到规范骨架（缺字段补空，不丢原字段）。"""
    base = empty_world_state()
    if not raw:
        return base
    for key, val in raw.items():
        base[key] = val
    base["ts"] = raw.get("ts") or time.time()
    return base


# ---------------------------------------------------------------------------
# 会话配置（人格 / 说话风格 / 关系 / 情绪 / 耐心 / 精力 / 话题 / 记忆提示）
# ---------------------------------------------------------------------------


@dataclass
class SessionConfig:
    """Omni session 的 system conditioning（规格 §16）。

    这些量**直接进 Omni session**，不再经过任何小脑 personality adapter。
    """

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    character_id: str = ""
    personality: str = ""
    speaking_style: str = ""
    relationship: str = ""
    emotion_state: dict = field(default_factory=dict)
    patience: float = 0.6
    energy: float = 0.6
    topic_state: str = ""
    memory_hint: str = ""
    modality: tuple = ("audio", "video", "text")
    full_duplex: bool = True
    allow_barge_in: bool = True
    system_prompt: str = ""
    meta: dict = field(default_factory=dict)

    def to_conditioning(self) -> dict:
        """转成后端可注入的条件字典。"""
        return {
            "session_id": self.session_id,
            "character_id": self.character_id,
            "personality": self.personality,
            "speaking_style": self.speaking_style,
            "relationship": self.relationship,
            "emotion_state": dict(self.emotion_state or {}),
            "patience": float(self.patience),
            "energy": float(self.energy),
            "topic_state": self.topic_state,
            "memory_hint": self.memory_hint,
            "full_duplex": bool(self.full_duplex),
            "system_prompt": self.system_prompt,
        }


@dataclass
class BackendCapabilities:
    """后端能力声明。上层据此决定降级策略。"""

    audio_in: bool = False
    audio_out: bool = False
    video_in: bool = False
    text_in: bool = True
    text_out: bool = True
    streaming: bool = False
    full_duplex: bool = False
    barge_in: bool = False
    native_speech: bool = False        # 原生语音输出（不是 text→TTS）
    languages: tuple = ("zh",)
    backends: tuple = ("cpu",)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "audio_in": self.audio_in,
            "audio_out": self.audio_out,
            "video_in": self.video_in,
            "text_in": self.text_in,
            "text_out": self.text_out,
            "streaming": self.streaming,
            "full_duplex": self.full_duplex,
            "barge_in": self.barge_in,
            "native_speech": self.native_speech,
            "languages": list(self.languages),
            "backends": list(self.backends),
            "notes": self.notes,
        }


__all__ = [
    "AudioChunk",
    "AvatarIntent",
    "AvatarIntentName",
    "BackendCapabilities",
    "ConversationOutput",
    "EventKind",
    "FrameKind",
    "HumanInteractionEvent",
    "OmniOutputKind",
    "SessionConfig",
    "SessionState",
    "SpeakerId",
    "UnifiedBrainEvent",
    "VideoFrame",
    "WorldEvent",
    "empty_world_state",
    "normalize_world_state",
]
