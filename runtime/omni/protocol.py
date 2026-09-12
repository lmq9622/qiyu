# -*- coding: utf-8 -*-
"""Gateway ↔ App/Quest 统一协议（规格 §二）。

所有事件共用同一个信封：

    {"session_id": "...", "sequence": 12, "timestamp": 1789..., "event_type": "input.text",
     "payload": {...}, "speaker_id": "local_user", "msg_id": "..."}

事件类型（封闭集合）：
    session.start / session.ready / session.resumed / session.closed
    input.audio / input.video / input.text / input.motion / input.world_event
    output.text_delta / output.audio_chunk / output.avatar_intent / output.listen /
    output.done / output.error
    control.interrupt / control.cancel / control.resume / control.close

必须处理：**乱序、重复、stale、断线、重连**。
这里的 :class:`SequenceTracker` 就是干这个的：按 session 记录已见序号与 msg_id，
重复/过期一律丢弃并计数，缺口记 gap（不丢，交上层决定）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

SESSION_START = "session.start"
SESSION_READY = "session.ready"
SESSION_RESUMED = "session.resumed"
SESSION_CLOSED = "session.closed"

INPUT_AUDIO = "input.audio"
INPUT_VIDEO = "input.video"
INPUT_TEXT = "input.text"
INPUT_MOTION = "input.motion"
INPUT_WORLD = "input.world_event"

OUTPUT_TEXT = "output.text_delta"
OUTPUT_AUDIO = "output.audio_chunk"
OUTPUT_INTENT = "output.avatar_intent"
OUTPUT_LISTEN = "output.listen"
OUTPUT_DONE = "output.done"
OUTPUT_ERROR = "output.error"

CONTROL_INTERRUPT = "control.interrupt"
CONTROL_CANCEL = "control.cancel"
CONTROL_RESUME = "control.resume"
CONTROL_CLOSE = "control.close"

INPUT_TYPES = {INPUT_AUDIO, INPUT_VIDEO, INPUT_TEXT, INPUT_MOTION, INPUT_WORLD}
OUTPUT_TYPES = {OUTPUT_TEXT, OUTPUT_AUDIO, OUTPUT_INTENT, OUTPUT_LISTEN, OUTPUT_DONE, OUTPUT_ERROR}
CONTROL_TYPES = {CONTROL_INTERRUPT, CONTROL_CANCEL, CONTROL_RESUME, CONTROL_CLOSE}
SESSION_TYPES = {SESSION_START, SESSION_READY, SESSION_RESUMED, SESSION_CLOSED}
ALL_TYPES = INPUT_TYPES | OUTPUT_TYPES | CONTROL_TYPES | SESSION_TYPES


@dataclass
class OmniEnvelope:
    event_type: str = ""
    session_id: str = ""
    sequence: int = 0
    timestamp: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)
    speaker_id: str = "local_user"
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_wire(self) -> dict:
        return {"event_type": self.event_type, "session_id": self.session_id,
                "sequence": int(self.sequence), "timestamp": self.timestamp,
                "payload": self.payload, "speaker_id": self.speaker_id,
                "msg_id": self.msg_id}

    @staticmethod
    def from_wire(raw) -> "OmniEnvelope":
        d = dict(raw or {})
        et = str(d.get("event_type") or d.get("type") or "")
        return OmniEnvelope(
            event_type=et,
            session_id=str(d.get("session_id") or ""),
            sequence=int(d.get("sequence") or 0),
            timestamp=float(d.get("timestamp") or time.time()),
            payload=dict(d.get("payload") or {}),
            speaker_id=str(d.get("speaker_id") or "local_user"),
            msg_id=str(d.get("msg_id") or uuid.uuid4().hex[:12]))

    def valid(self) -> tuple:
        if self.event_type not in ALL_TYPES:
            return False, "unknown_event_type"
        if not self.session_id and self.event_type != SESSION_START:
            return False, "missing_session_id"
        return True, "ok"


@dataclass
class SequenceReport:
    accepted: bool = False
    reason: str = "ok"
    gap: int = 0


class SequenceTracker:
    """单会话的序号/去重/过期判定。"""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        # 入站与出站序号是两套计数器：客户端序号只用于去重/过期判定，
        # 服务端出站序号用于保证 output.* 单调。混用会把合法输入误判成 stale。
        self.last_in_seq = 0
        self.out_seq = 0
        self.seen_ids: dict = {}
        self.stats = {"accepted": 0, "duplicate": 0, "stale": 0, "gaps": 0,
                      "invalid": 0, "gap_total": 0}

    def accept(self, env: OmniEnvelope, keep_ids: int = 512) -> SequenceReport:
        ok, reason = env.valid()
        if not ok:
            self.stats["invalid"] += 1
            return SequenceReport(False, reason)
        if env.msg_id in self.seen_ids:
            self.stats["duplicate"] += 1
            return SequenceReport(False, "duplicate")
        if env.sequence and env.sequence <= self.last_in_seq:
            self.stats["stale"] += 1
            return SequenceReport(False, "stale")
        gap = 0
        if env.sequence and self.last_in_seq and env.sequence > self.last_in_seq + 1:
            gap = env.sequence - self.last_in_seq - 1
            self.stats["gaps"] += 1
            self.stats["gap_total"] += gap
        if env.sequence:
            self.last_in_seq = env.sequence
        self.seen_ids[env.msg_id] = env.sequence
        if len(self.seen_ids) > keep_ids:
            for k in list(self.seen_ids.keys())[: len(self.seen_ids) - keep_ids]:
                self.seen_ids.pop(k, None)
        self.stats["accepted"] += 1
        return SequenceReport(True, "ok", gap)

    def note_outbound(self) -> int:
        """服务端出站序号（全局单调，跨重连不重置）。"""
        self.out_seq += 1
        return self.out_seq

    def snapshot(self) -> dict:
        return {"session_id": self.session_id, "last_in_seq": self.last_in_seq,
                "out_seq": self.out_seq, **self.stats}
