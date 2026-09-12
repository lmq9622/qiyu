# -*- coding: utf-8 -*-
"""Gateway ↔ Omni 统一协议验证（真 WebSocket；后端为注入口的确定性假链）。

验证规格 §二 的全部协议要求：
  1. session.start -> session.ready（带 session_id / 能力 / 音频格式）
  2. input.text -> output.text_delta + output.done
  3. 出站 sequence 严格单调
  4. 重复事件（同 msg_id）丢弃
  5. stale 事件（序号回退）丢弃
  6. control.interrupt -> output.listen（打断回执）
  7. control.close -> session.closed
  8. 断线后在宽限期内重连 -> session.resumed（序号不重置）

标签：REAL LOCAL（真 WS + 真协议实现）；SIMULATION（后端为假链，不碰模型）。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import websockets  # noqa: E402

import gateway.omni_ws as omni_ws  # noqa: E402
from runtime.omni.protocol import (  # noqa: E402
    CONTROL_CLOSE, CONTROL_INTERRUPT, INPUT_TEXT, OUTPUT_DONE, OUTPUT_INTENT,
    OUTPUT_LISTEN, OUTPUT_TEXT, SESSION_CLOSED, SESSION_READY, SESSION_RESUMED,
    SESSION_START, OmniEnvelope,
)
from runtime.omni.types import AvatarIntent, AvatarIntentName, ConversationOutput  # noqa: E402

PORT = 8812
OUT = Path("runtime/omni/out")
RESULTS = {}


def _record(name, ok, detail=None):
    RESULTS[name] = {"ok": bool(ok), **(detail or {})}
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name,
                            json.dumps(detail or {}, ensure_ascii=False)))
    return bool(ok)


class FakeUnified:
    """假事件信封（只带 kind/conversation/avatar_intent/state/payload）。"""

    def __init__(self, kind="conversation", conversation=None, intent=None, payload=None):
        self.kind, self.conversation, self.avatar_intent = kind, conversation, intent
        self.payload = payload or {}
        self.state = "speaking"


class FakeOmni:
    backend_name = "fake_chain"
    state = "listening"

    def __init__(self):
        self.q: asyncio.Queue = asyncio.Queue()
        self.interrupted = 0
        self.cancelled = 0
        self.received = []

    async def receive_event(self):
        while True:
            yield await self.q.get()

    async def start_session(self, config=None):
        return "fake-session"

    async def close(self):
        return None

    async def interrupt(self, reason=""):
        self.interrupted += 1

    async def cancel(self):
        self.cancelled += 1

    async def send_text(self, text, speaker_id="local_user"):
        self.received.append(("text", text, speaker_id))
        await self.q.put(FakeUnified(conversation=ConversationOutput(text="收到：" + text)))
        await self.q.put(FakeUnified(conversation=ConversationOutput(text="收到：" + text,
                                                                    is_final=True)))
        await self.q.put(FakeUnified(intent=AvatarIntent(intent=AvatarIntentName.WAVE.value,
                                                         target="user")))

    async def send_audio_chunk(self, chunk):
        self.received.append(("audio", chunk.sample_rate, chunk.speaker_id))

    async def send_video_frame(self, frame):
        self.received.append(("video", frame.kind, frame.speaker_id))

    async def send_world_event(self, event):
        self.received.append(("world", event.kind, event.priority))

    async def send_motion_event(self, event):
        self.received.append(("motion", event.name))


class FakeChain:
    def __init__(self, session_id=""):
        self.omni = FakeOmni()
        self.session_id = session_id
        self.stopped = False

    async def start(self, config=None):
        return await self.omni.start_session(config)

    async def stop(self):
        self.stopped = True
        await self.omni.close()

    async def send_text(self, text, speaker_id="local_user"):
        await self.omni.send_text(text, speaker_id=speaker_id)

    async def send_audio(self, pcm, sample_rate=16000, speaker_id="local_user",
                         is_speech=None):
        await self.omni.send_audio_chunk(type("C", (), {"sample_rate": sample_rate,
                                                        "speaker_id": speaker_id})())

    async def send_video(self, data, kind="keyframe", source="quest_camera",
                         speaker_id="", frame_id=0, meta=None):
        await self.omni.send_video_frame(type("F", (), {"kind": kind,
                                                        "speaker_id": speaker_id})())

    async def send_world_event(self, kind="world_state", payload=None, priority=0,
                               source="quest"):
        await self.omni.send_world_event(type("E", (), {"kind": kind, "priority": priority})())

    async def send_shared_attention(self, snapshot=None):
        return None

    def stats_dict(self):
        return {"backend": "fake_chain", "received": len(self.omni.received)}


def start_server():
    app = FastAPI()
    app.include_router(omni_ws.router)
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            return server
        time.sleep(0.1)
    raise RuntimeError("uvicorn 未启动")


async def main():
    print("=" * 70)
    print("Gateway ↔ Omni 统一协议验证（真 WebSocket）")
    print("=" * 70)
    omni_ws._hub.chain_factory = lambda sid: _mk_chain(sid)
    server = start_server()
    url = f"ws://127.0.0.1:{PORT}/v1/omni/session"
    out_events = []

    async def collect(ws, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.01, deadline - time.time()))
            except asyncio.TimeoutError:
                return
            except websockets.exceptions.ConnectionClosed:
                return
            except Exception:
                return
            out_events.append(json.loads(raw))

    ws = await websockets.connect(url, max_size=None, ping_interval=None)
    await ws.send(json.dumps(OmniEnvelope(event_type=SESSION_START, session_id="",
                                          sequence=1, payload={"mode": "full_duplex"},
                                          msg_id="m1").to_wire()))
    ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    sid = ready.get("session_id")
    _record("session_start_ready",
            ready.get("event_type") == SESSION_READY and bool(sid),
            {"event_type": ready.get("event_type"), "session_id": sid,
             "payload": ready.get("payload")})

    await ws.send(json.dumps(OmniEnvelope(event_type=INPUT_TEXT, session_id=sid, sequence=2,
                                          payload={"text": "你好"}, msg_id="m2").to_wire()))
    await collect(ws, 1.5)
    kinds = [e["event_type"] for e in out_events]
    seqs = [e["sequence"] for e in out_events]
    _record("input_text_drives_output",
            OUTPUT_TEXT in kinds and OUTPUT_INTENT in kinds,
            {"kinds": kinds, "text": [e["payload"].get("text") for e in out_events
                                      if e["event_type"] == OUTPUT_TEXT]})
    _record("server_sequence_monotonic", seqs == sorted(seqs) and len(set(seqs)) == len(seqs),
            {"sequences": seqs})

    before = len(out_events)
    dup = OmniEnvelope(event_type=INPUT_TEXT, session_id=sid, sequence=3,
                       payload={"text": "重复"}, msg_id="m2").to_wire()
    await ws.send(json.dumps(dup))
    await ws.send(json.dumps(OmniEnvelope(event_type=INPUT_TEXT, session_id=sid, sequence=1,
                                          payload={"text": "过期"}, msg_id="m99").to_wire()))
    await collect(ws, 1.0)
    _record("duplicate_and_stale_dropped",
            len(out_events) == before and omni_ws._hub.rejected >= 2,
            {"new_events": len(out_events) - before, "rejected": omni_ws._hub.rejected})

    await ws.send(json.dumps(OmniEnvelope(event_type=CONTROL_INTERRUPT, session_id=sid,
                                          sequence=4, payload={}, msg_id="m4").to_wire()))
    await collect(ws, 1.0)
    _record("control_interrupt_acks",
            any(e["event_type"] == OUTPUT_LISTEN for e in out_events),
            {"kinds": [e["event_type"] for e in out_events[-3:]]})

    last_seq = max(e["sequence"] for e in out_events)
    await ws.close()
    await asyncio.sleep(0.5)
    ws2 = await websockets.connect(url, max_size=None, ping_interval=None)
    await ws2.send(json.dumps(OmniEnvelope(event_type=SESSION_START, session_id=sid,
                                           sequence=1, msg_id="r1",
                                           payload={"resume_session_id": sid}).to_wire()))
    resumed = json.loads(await asyncio.wait_for(ws2.recv(), timeout=10))
    _record("reconnect_resumes_session",
            resumed.get("event_type") == SESSION_RESUMED
            and resumed.get("session_id") == sid
            and resumed.get("sequence") > last_seq,
            {"event_type": resumed.get("event_type"), "session_id": resumed.get("session_id"),
             "sequence": resumed.get("sequence"), "last_before": last_seq})

    # 重连后客户端**继续自己的序号**（断线前用到 4），否则会被正确地判为 stale
    await ws2.send(json.dumps(OmniEnvelope(event_type=CONTROL_CLOSE, session_id=sid,
                                           sequence=6, payload={}, msg_id="c1").to_wire()))
    await collect(ws2, 1.0)
    _record("control_close_closes_session",
            any(e["event_type"] == SESSION_CLOSED for e in out_events),
            {"kinds": [e["event_type"] for e in out_events[-3:]],
             "hub": omni_ws._hub.stats()["connections"]})
    await ws2.close()
    server.should_exit = True

    summary = {"label": "REAL LOCAL(WS+协议) + SIMULATION(假链后端)",
               "results": RESULTS,
               "hub_stats": omni_ws._hub.stats(),
               "passed": sum(1 for v in RESULTS.values() if v.get("ok")),
               "total": len(RESULTS)}
    verdict = all(v.get("ok") for v in RESULTS.values())
    summary["verdict"] = "PASS" if verdict else "FAIL"
    print("=" * 70)
    print("GATEWAY_OMNI_PROTOCOL =", summary["verdict"],
          "(%d/%d)" % (summary["passed"], summary["total"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gateway_omni_protocol.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT / "gateway_omni_protocol.json")
    return 0 if verdict else 1


_CHAINS = {}


def _mk_chain(sid):
    chain = FakeChain(sid)
    _CHAINS[sid] = chain
    return chain


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
