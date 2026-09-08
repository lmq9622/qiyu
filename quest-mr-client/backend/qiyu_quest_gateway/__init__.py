"""Qiyu Quest WebSocket Gateway（P0）。

只新增 Quest 入口，不替代 Qiyu 现有 MessageGateway / BrainPipeline。
"""
from qiyu_quest_gateway.gateway import QuestWebSocketGateway
from qiyu_quest_gateway.protocol import (
    PROTOCOL_VERSION,
    SUPPORTED_PROTOCOL_VERSIONS,
    Envelope,
    build_envelope,
)

__all__ = [
    "PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "Envelope",
    "QuestWebSocketGateway",
    "build_envelope",
]
