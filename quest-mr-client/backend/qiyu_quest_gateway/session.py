"""Quest session 注册表。"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from qiyu_quest_gateway.audio import AudioTurnBuffer


@dataclass
class QuestSession:
    session_id: str
    user_id: str
    char_id: str
    device: str = ""
    client_version: str = ""
    protocol_version: str = ""
    capabilities: dict = field(default_factory=dict)
    connected_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    remote: str = ""
    world_state: Optional[dict] = None
    world_state_updates: int = 0
    behavior_state: Optional[dict] = None
    character_state: Optional[dict] = None
    last_interaction_event: Optional[dict] = None
    interaction_events: int = 0
    human_motion_state: Optional[dict] = None
    human_motion_updates: int = 0
    user_body: Optional[dict] = None
    user_body_updates: int = 0
    last_client_seq: int = 0
    last_server_seq: int = 0
    client_ack: int = 0
    dropped_client_events: int = 0
    duplicate_client_events: int = 0
    recent_event_ids: list[str] = field(default_factory=list)
    recent_event_id_set: set[str] = field(default_factory=set)
    last_autonomy_at: float = 0.0
    # 并发回合控制：同一 session 同时只跑一轮对话，新一轮/打断会取消旧轮。
    turn_task: Optional[asyncio.Task] = None
    autonomy_task: Optional[asyncio.Task] = None
    barge_in_epoch: int = 0
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    audio_buffer: AudioTurnBuffer = field(default_factory=AudioTurnBuffer)
    latest_vision_frame: Optional[bytes] = None
    vision_meta: dict = field(default_factory=dict)
    pending_vision_text: str = ""
    pending_vision_request: Optional[object] = None
    tts_enabled: bool = True
    # Behavior 层：会话级行为桥与 8Hz 调度心跳（由网关创建/回收）
    behavior_bridge: Optional[object] = None
    behavior_task: Optional[asyncio.Task] = None

    def to_public_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "char_id": self.char_id,
            "device": self.device,
            "client_version": self.client_version,
            "protocol_version": self.protocol_version,
            "capabilities": self.capabilities,
            "connected_at": round(self.connected_at, 3),
            "last_seen_at": round(self.last_seen_at, 3),
            "world_state_revision": (self.world_state or {}).get("scene_version", 0),
            "behavior_revision": (self.behavior_state or {}).get("since_ms", 0),
            "last_client_seq": self.last_client_seq,
            "last_server_seq": self.last_server_seq,
            "client_ack": self.client_ack,
            "dropped_client_events": self.dropped_client_events,
            "duplicate_client_events": self.duplicate_client_events,
        }


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, QuestSession] = {}

    def create(
        self,
        *,
        user_id: str,
        char_id: str,
        device: str = "",
        client_version: str = "",
        protocol_version: str = "",
        capabilities: Optional[dict] = None,
        remote: str = "",
    ) -> QuestSession:
        session = QuestSession(
            session_id=uuid.uuid4().hex,
            user_id=user_id,
            char_id=char_id,
            device=device,
            client_version=client_version,
            protocol_version=protocol_version,
            capabilities=dict(capabilities or {}),
            remote=remote,
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> Optional[QuestSession]:
        return self._sessions.get(session_id)

    def touch(self, session_id: str) -> Optional[QuestSession]:
        s = self._sessions.get(session_id)
        if s is not None:
            s.last_seen_at = time.time()
        return s

    def update_world_state(self, session_id: str, world_state: dict) -> Optional[QuestSession]:
        s = self._sessions.get(session_id)
        if s is not None:
            s.world_state = dict(world_state)
            s.last_seen_at = time.time()
        return s

    def update_behavior_state(self, session_id: str, behavior_state: dict) -> Optional[QuestSession]:
        s = self._sessions.get(session_id)
        if s is not None:
            s.behavior_state = dict(behavior_state or {})
            s.last_seen_at = time.time()
        return s

    def update_character_state(self, session_id: str, character_state: dict) -> Optional[QuestSession]:
        s = self._sessions.get(session_id)
        if s is not None:
            s.character_state = dict(character_state or {})
            s.last_seen_at = time.time()
        return s

    def drop(self, session_id: str) -> Optional[QuestSession]:
        return self._sessions.pop(session_id, None)

    def list(self) -> list[dict]:
        return [s.to_public_dict() for s in self._sessions.values()]

    def count(self) -> int:
        return len(self._sessions)

