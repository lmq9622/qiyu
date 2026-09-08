"""Qiyu Quest WebSocket Gateway。

只新增 Quest 入口，不替代 Qiyu 现有 MessageGateway / BrainPipeline。
"""
from qiyu_quest_gateway.gateway import QuestWebSocketGateway
from qiyu_quest_gateway.audio import (
    AudioError,
    AudioTurnBuffer,
    synthesize_pcm16,
    transcribe_pcm16,
)
from qiyu_quest_gateway.binary_frame import (
    BinaryFrame,
    KIND_AUDIO_IN_PCM16,
    KIND_TTS_OUT_PCM16,
    KIND_VISION_JPEG,
    pack_frame,
    unpack_frame,
)
from qiyu_quest_gateway.planner import QuestResponsePlanner
from qiyu_quest_gateway.protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    Envelope,
    build_envelope,
)
from qiyu_quest_gateway.world_state import (
    WorldStateStore,
    render_world_state_for_llm,
)

__all__ = [
    "PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "Envelope",
    "QuestWebSocketGateway",
    "QuestResponsePlanner",
    "AudioError",
    "AudioTurnBuffer",
    "BinaryFrame",
    "KIND_AUDIO_IN_PCM16",
    "KIND_TTS_OUT_PCM16",
    "KIND_VISION_JPEG",
    "WorldStateStore",
    "pack_frame",
    "render_world_state_for_llm",
    "synthesize_pcm16",
    "transcribe_pcm16",
    "unpack_frame",
    "build_envelope",
]
