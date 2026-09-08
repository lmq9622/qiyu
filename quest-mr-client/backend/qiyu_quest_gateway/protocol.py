"""Envelope 编解码与版本常量。"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

PROTOCOL_VERSION = "1.0.0"
SUPPORTED_PROTOCOL_VERSIONS = {"1.0.0"}


class EnvelopeError(ValueError):
    pass


class Envelope:
    """轻量 Envelope 对象，不强制依赖 Pydantic 才能收发。"""

    __slots__ = ("v", "id", "type", "ts", "session", "reply_to", "payload")

    def __init__(
        self,
        type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        id: Optional[str] = None,
        ts: Optional[int] = None,
        session: Optional[str] = None,
        reply_to: Optional[str] = None,
        v: str = PROTOCOL_VERSION,
    ) -> None:
        self.v = v
        self.id = id or uuid.uuid4().hex
        self.type = type
        self.ts = int(ts if ts is not None else time.time() * 1000)
        self.session = session
        self.reply_to = reply_to
        self.payload = dict(payload or {})

    def to_dict(self) -> dict[str, Any]:
        out = {
            "v": self.v,
            "id": self.id,
            "type": self.type,
            "ts": self.ts,
            "payload": self.payload,
        }
        if self.session:
            out["session"] = self.session
        if self.reply_to:
            out["reply_to"] = self.reply_to
        return out

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    def reply(
        self,
        type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        session: Optional[str] = None,
    ) -> "Envelope":
        return Envelope(
            type=type,
            payload=payload or {},
            reply_to=self.id,
            session=session if session is not None else self.session,
        )

    @classmethod
    def from_text(cls, raw: str) -> "Envelope":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise EnvelopeError(f"invalid_json: {e}") from e
        if not isinstance(data, dict):
            raise EnvelopeError("envelope_must_be_object")
        v = str(data.get("v") or "")
        if v not in SUPPORTED_PROTOCOL_VERSIONS:
            raise EnvelopeError(f"unsupported_protocol_version:{v}")
        typ = str(data.get("type") or "")
        msg_id = str(data.get("id") or "")
        if not typ or not msg_id:
            raise EnvelopeError("missing_type_or_id")
        ts = data.get("ts")
        if not isinstance(ts, int):
            raise EnvelopeError("invalid_ts")
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise EnvelopeError("payload_must_be_object")
        return cls(
            type=typ,
            payload=payload,
            id=msg_id,
            ts=ts,
            session=str(data["session"]) if data.get("session") else None,
            reply_to=str(data["reply_to"]) if data.get("reply_to") else None,
            v=v,
        )


def build_envelope(
    type: str,
    payload: Optional[dict[str, Any]] = None,
    *,
    session: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> Envelope:
    return Envelope(type=type, payload=payload, session=session, reply_to=reply_to)
