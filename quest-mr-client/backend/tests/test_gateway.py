"""P0 Gateway 真实 WebSocket 测试（不依赖 Unity / Quest 设备）。"""
from __future__ import annotations

import asyncio
import io
import json
import wave

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qiyu_quest_gateway import audio as quest_audio
from qiyu_quest_gateway import gateway as gateway_module
from qiyu_quest_gateway.binary_frame import (
    KIND_AUDIO_IN_PCM16,
    KIND_TTS_OUT_PCM16,
    pack_frame,
    unpack_frame,
)
from qiyu_quest_gateway.gateway import QuestWebSocketGateway
from qiyu_quest_gateway.planner import QuestResponsePlanner
from qiyu_quest_gateway.vision_detector import _extract_json, _normalize_bbox
from qiyu_quest_gateway.world_state import (
    WorldStateStore,
    render_world_state_for_llm,
)


def _hello(user_id: str = "quest_user", char_id: str = "xiaoban") -> dict:
    return {
        "v": "1.0.0",
        "id": "hello-1",
        "type": "client.hello",
        "ts": 1000,
        "payload": {
            "user_id": user_id,
            "char_id": char_id,
            "device": "meta-quest-3",
            "client_version": "0.0.1",
            "capabilities": ["world_state_v1"],
        },
    }


def _make_client() -> tuple[FastAPI, QuestWebSocketGateway, TestClient]:
    app = FastAPI()
    gateway = QuestWebSocketGateway()
    app.add_api_websocket_route("/v1/quest/ws", gateway.handle_ws)
    return app, gateway, TestClient(app)


def test_hello_heartbeat_echo_and_bye() -> None:
    app, gateway, client = _make_client()
    with client.websocket_connect("/v1/quest/ws") as ws:
        ws.send_text(json.dumps(_hello()))
        ack = json.loads(ws.receive_text())
        assert ack["type"] == "server.hello_ack"
        assert ack["payload"]["protocol_version"] == "1.0.0"
        session_id = ack["session"]
        assert session_id
        assert gateway.registry.count() == 1

        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "hb-1", "type": "client.heartbeat",
            "ts": 1100, "session": session_id, "payload": {},
        }))
        hb = json.loads(ws.receive_text())
        assert hb["type"] == "server.heartbeat"
        assert hb["reply_to"] == "hb-1"

        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "echo-1", "type": "client.echo",
            "ts": 1200, "session": session_id,
            "payload": {"message": "你好 Quest"},
        }))
        echo = json.loads(ws.receive_text())
        assert echo["type"] == "server.echo"
        assert echo["payload"]["message"] == "你好 Quest"

        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "bye-1", "type": "client.bye",
            "ts": 1300, "session": session_id, "payload": {},
        }))
        bye = json.loads(ws.receive_text())
        assert bye["type"] == "server.ack"

    assert gateway.registry.count() == 0


def test_world_state_is_stored_and_acked() -> None:
    app, gateway, client = _make_client()
    with client.websocket_connect("/v1/quest/ws") as ws:
        ws.send_text(json.dumps(_hello()))
        ack = json.loads(ws.receive_text())
        session_id = ack["session"]
        state = {
            "protocol_version": "1.0.0",
            "ts": 1400,
            "room_id": "room-1",
            "scene_version": 7,
            "status": "ready",
            "anchors": [],
            "user": {},
            "avatar": {},
        }
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "ws-1", "type": "client.world_state",
            "ts": 1400, "session": session_id, "payload": state,
        }))
        result = json.loads(ws.receive_text())
        assert result["type"] == "server.ack"
        assert result["payload"]["scene_version"] == 7
        stored = gateway.registry.get(session_id)
        assert stored is not None
        assert stored.world_state["room_id"] == "room-1"


def test_first_message_must_be_hello() -> None:
    app, gateway, client = _make_client()
    with client.websocket_connect("/v1/quest/ws") as ws:
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "bad-1", "type": "client.echo",
            "ts": 1000, "payload": {"x": 1},
        }))
        err = json.loads(ws.receive_text())
        assert err["type"] == "server.error"
        assert err["payload"]["code"] == "handshake_required"
    assert gateway.registry.count() == 0


def test_user_text_without_brain_returns_honest_error() -> None:
    app, gateway, client = _make_client()
    with client.websocket_connect("/v1/quest/ws") as ws:
        ws.send_text(json.dumps(_hello()))
        ack = json.loads(ws.receive_text())
        session_id = ack["session"]
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "u-1", "type": "user.text",
            "ts": 1500, "session": session_id, "payload": {"text": "你好"},
        }))
        err = json.loads(ws.receive_text())
        assert err["type"] == "server.error"
        assert err["payload"]["code"] == "brain_not_attached"


def test_user_text_with_brain_emits_speech_and_intents() -> None:
    app, gateway, client = _make_client()

    async def _handler(session, text, meta):
        assert session.user_id == "quest_user"
        assert text == "帮我看看桌子上有什么"
        assert meta["source"] == "user.text"
        return {
            "response_id": "resp-1",
            "text": "桌上有杯子。",
            "pieces": [{"text": "桌上有杯子。", "type": "statement", "delay": 0}],
            "avatar_intent": {
                "emotion": "happy", "intensity": 0.6,
                "action": "look_at_object", "speaking": True,
            },
            "spatial_action": {
                "action": "look_at", "target_id": "table-1",
                "anchor": "object", "speed": 1.0,
            },
        }

    gateway.on_user_text = _handler
    with client.websocket_connect("/v1/quest/ws") as ws:
        ws.send_text(json.dumps(_hello()))
        ack = json.loads(ws.receive_text())
        session_id = ack["session"]
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "u-2", "type": "user.text",
            "ts": 1600, "session": session_id,
            "payload": {"text": "帮我看看桌子上有什么"},
        }))
        speech = json.loads(ws.receive_text())
        assert speech["type"] == "agent.speech"
        assert speech["payload"]["text"] == "桌上有杯子。"
        assert speech["reply_to"] == "u-2"
        intent = json.loads(ws.receive_text())
        assert intent["type"] == "avatar.intent"
        assert intent["payload"]["emotion"] == "happy"
        action = json.loads(ws.receive_text())
        assert action["type"] == "spatial.action"
        assert action["payload"]["target_id"] == "table-1"


def test_barge_in_is_acked_and_does_not_drop_session() -> None:
    app, gateway, client = _make_client()
    with client.websocket_connect("/v1/quest/ws") as ws:
        ws.send_text(json.dumps(_hello()))
        ack = json.loads(ws.receive_text())
        session_id = ack["session"]
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "bi-1", "type": "client.barge_in",
            "ts": 1700, "session": session_id, "payload": {},
        }))
        result = json.loads(ws.receive_text())
        assert result["type"] == "server.ack"
        assert result["payload"]["barge_in"] is True
        assert gateway.registry.get(session_id) is not None


def test_world_state_store_and_llm_renderer() -> None:
    store = WorldStateStore()
    state = {
        "room_id": "living-room",
        "scene_version": 3,
        "status": "ready",
        "anchors": [
            {"id": "floor-1", "label": "floor",
             "pose": {"position": {"x": 0, "y": 0, "z": 0}}},
            {"id": "table-1", "label": "table",
             "pose": {"position": {"x": 1.5, "y": 0.7, "z": 2.0}},
             "extents": {"x": 1.2, "y": 0.7, "z": 0.8}, "mesh_available": True},
            {"id": "chair-1", "label": "chair",
             "pose": {"position": {"x": -0.8, "y": 0.5, "z": 1.2}}},
        ],
        "objects": [
            {"id": "cup-1", "label": "cup", "confidence": 0.91,
             "position": {"x": 1.4, "y": 0.9, "z": 2.0}, "anchor_id": "table-1"},
        ],
        "user": {"head": {
            "position": {"x": 0, "y": 1.6, "z": 0},
            "rotation": {"x": 0, "y": 0, "z": 0, "w": 1},
        }},
        "navmesh": {"generated": True, "version": 2, "walkable_area_m2": 12.5},
    }
    store.update("s1", state)
    assert store.get("s1")["room_id"] == "living-room"
    assert store.latest()["scene_version"] == 3
    text = render_world_state_for_llm(state)
    assert "living-room" in text
    assert "桌子" in text and "椅子" in text
    assert "距用户" in text
    assert "cup" in text
    assert "可导航区域：已生成" in text
    store.drop("s1")
    assert store.get("s1") is None


def test_planner_fallback_without_llm_is_honest() -> None:
    planner = QuestResponsePlanner()
    result = asyncio.run(planner.plan(
        reply_text="我在这儿。",
        world_state={"user": {"head": {"position": {"x": 0, "y": 1.6, "z": 0}}}},
        emotion_state={"joy": 70, "excitement": 20, "sadness": 5,
                       "anxiety": 8, "fear": 5},
        user_visible=True,
    ))
    assert result["source"] == "fallback"
    assert result["avatar_intent"].emotion == "happy"
    assert result["avatar_intent"].action == "look_at_user"
    assert result["spatial_action"] is None


def test_planner_llm_rejects_unknown_spatial_target() -> None:
    async def _fake_llm(system_prompt, user_prompt, temperature):
        return json.dumps({
            "avatar_intent": {
                "emotion": "happy", "intensity": 0.5,
                "action": "look_at_object", "speaking": True,
            },
            "spatial_action": {
                "action": "look_at", "target_id": "不存在的东西",
            },
        })

    planner = QuestResponsePlanner(llm_complete=_fake_llm)
    result = asyncio.run(planner.plan(
        reply_text="我看向那边。",
        world_state={
            "anchors": [{"id": "table-1", "label": "table",
                         "pose": {"position": {"x": 1, "y": 0.7, "z": 2}}}],
            "user": {"head": {"position": {"x": 0, "y": 1.6, "z": 0}}},
        },
    ))
    assert result["source"] == "llm"
    assert result["avatar_intent"].action == "look_at_object"
    assert result["spatial_action"] is None


def test_binary_frame_roundtrip() -> None:
    frame = pack_frame(KIND_AUDIO_IN_PCM16, 42, b"\x01\x02\x03")
    parsed = unpack_frame(frame)
    assert parsed.kind == KIND_AUDIO_IN_PCM16
    assert parsed.seq == 42
    assert parsed.payload == b"\x01\x02\x03"
    try:
        unpack_frame(b"bad")
    except Exception as e:
        assert "frame_too_short" in str(e)
    else:
        raise AssertionError("非法帧必须抛错")


def test_pcm16_wav_roundtrip_and_resample() -> None:
    pcm = b"".join(int(1000).to_bytes(2, "little", signed=True) for _ in range(1600))
    wav_bytes = quest_audio.pcm16_to_wav(pcm, 16000, 1)
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        assert w.getframerate() == 16000
        assert w.getnchannels() == 1
    out, rate, channels = quest_audio.wav_bytes_to_pcm16(wav_bytes)
    assert rate == 16000 and channels == 1
    assert len(out) == len(pcm)

    # 48k → 16k 重采样
    pcm48 = b"".join(int(500).to_bytes(2, "little", signed=True) for _ in range(4800))
    wav48 = quest_audio.pcm16_to_wav(pcm48, 48000, 1)
    out48, rate48, _ = quest_audio.wav_bytes_to_pcm16(wav48)
    assert rate48 == 16000
    assert 1500 <= len(out48) // 2 <= 1700


def test_gateway_audio_end_uses_stt_and_runs_turn() -> None:
    app, gateway, client = _make_client()
    called = {}

    async def _fake_transcribe(pcm, sample_rate):
        called["bytes"] = len(pcm)
        called["rate"] = sample_rate
        return "你好，栖语"

    async def _handler(session, text, meta):
        called["text"] = text
        return {
            "response_id": "resp-audio",
            "text": "我在。",
            "pieces": [{"text": "我在。", "type": "statement", "delay": 0}],
            "avatar_intent": {"emotion": "calm", "speaking": True, "action": "look_at_user"},
            "spatial_action": None,
        }

    original = gateway_module.transcribe_pcm16
    gateway_module.transcribe_pcm16 = _fake_transcribe
    gateway.on_user_text = _handler
    try:
        with client.websocket_connect("/v1/quest/ws") as ws:
            ws.send_text(json.dumps(_hello()))
            ack = json.loads(ws.receive_text())
            session_id = ack["session"]
            ws.send_text(json.dumps({
                "v": "1.0.0", "id": "tts-cfg", "type": "client.tts_config",
                "ts": 1750, "session": session_id, "payload": {"enabled": False},
            }))
            assert json.loads(ws.receive_text())["type"] == "server.ack"
            pcm = b"\x00\x00" * 1600
            ws.send_bytes(pack_frame(KIND_AUDIO_IN_PCM16, 1, pcm))
            ws.send_text(json.dumps({
                "v": "1.0.0", "id": "ae-1", "type": "user.audio_end",
                "ts": 1800, "session": session_id,
                "payload": {"sample_rate": 16000},
            }))
            transcript = json.loads(ws.receive_text())
            assert transcript["type"] == "server.voice_transcript"
            assert transcript["payload"]["text"] == "你好，栖语"
            speech = json.loads(ws.receive_text())
            assert speech["type"] == "agent.speech"
            assert called["text"] == "你好，栖语"
            assert called["bytes"] == len(pcm)
    finally:
        gateway_module.transcribe_pcm16 = original


def test_gateway_streams_real_tts_binary_frames() -> None:
    """真实调用 Qiyu TTSProvider（System.Speech）验证 PCM 二进制下行。"""
    app, gateway, client = _make_client()

    async def _handler(session, text, meta):
        return {
            "response_id": "resp-tts",
            "text": "你好。",
            "pieces": [{"text": "你好。", "type": "statement", "delay": 0}],
            "avatar_intent": {"emotion": "happy", "speaking": True},
            "spatial_action": None,
        }

    gateway.on_user_text = _handler
    with client.websocket_connect("/v1/quest/ws") as ws:
        ws.send_text(json.dumps(_hello()))
        ack = json.loads(ws.receive_text())
        session_id = ack["session"]
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "u-tts", "type": "user.text",
            "ts": 1900, "session": session_id, "payload": {"text": "你好"},
        }))
        start = None
        audio_bytes = b""
        while True:
            message = ws.receive()
            if message.get("type") != "websocket.send":
                break
            if message.get("bytes") is not None:
                frame = unpack_frame(message["bytes"])
                assert frame.kind == KIND_TTS_OUT_PCM16
                audio_bytes += frame.payload
                continue
            envelope = json.loads(message["text"])
            if envelope["type"] == "audio.tts_start":
                start = envelope
                assert start["payload"]["sample_rate"] == 16000
                continue
            if envelope["type"] == "audio.tts_end":
                break
        assert start is not None
        assert len(audio_bytes) > 1000


def test_real_tts_to_stt_roundtrip() -> None:
    """真实 TTS → PCM → 真实 STT，验证语音通道不是占位实现。"""
    synth = asyncio.run(quest_audio.synthesize_pcm16("你好，我是栖语。"))
    assert synth["sample_rate"] == 16000
    assert len(synth["pcm"]) > 2000
    text = asyncio.run(quest_audio.transcribe_pcm16(synth["pcm"], 16000))
    assert text, "真实 STT 必须返回文本"
    assert any(ch in text for ch in "你好栖语我是")


def test_vision_detector_json_and_bbox_normalization() -> None:
    parsed = _extract_json('```json\n{"objects":[{"label":"cup","bbox_2d":[0.1,0.2,0.3,0.4]}]}\n```')
    assert parsed["objects"][0]["label"] == "cup"
    bbox = _normalize_bbox([0.1, 0.2, 0.3, 0.4], 640, 480)
    assert bbox == [64.0, 96.0, 192.0, 192.0]
    assert _normalize_bbox([1, 2, 3], 640, 480) is None


def test_vision_request_closed_loop_reruns_same_question() -> None:
    """BrainDecision 需要视觉 → server.vision_request → 检测结果 → 自动重跑同一问题。"""
    app, gateway, client = _make_client()
    calls = []

    async def _turn_handler(session, text, meta):
        calls.append(meta)
        if meta.get("vision_objects"):
            return {
                "response_id": "resp-vision-2",
                "text": "我看到桌上有杯子。",
                "pieces": [{"text": "我看到桌上有杯子。", "type": "statement", "delay": 0}],
                "avatar_intent": {"emotion": "happy", "speaking": True},
                "spatial_action": None,
                "need_vision": False,
            }
        return {
            "response_id": "resp-vision-1",
            "text": "我看看。",
            "pieces": [{"text": "我看看。", "type": "statement", "delay": 0}],
            "avatar_intent": {"emotion": "neutral", "speaking": True},
            "spatial_action": None,
            "need_vision": True,
            "vision_query": "桌子上有什么",
        }

    async def _vision_handler(session, frame, meta, prompt):
        assert frame == b"jpeg-bytes"
        return {
            "objects": [{"id": "cup-1", "label": "cup", "confidence": 0.9,
                         "bbox_2d": [10, 20, 30, 40]}],
            "image_width": 640,
            "image_height": 480,
        }

    gateway.on_user_text = _turn_handler
    gateway.on_vision_query = _vision_handler
    with client.websocket_connect("/v1/quest/ws") as ws:
        ws.send_text(json.dumps(_hello()))
        session_id = json.loads(ws.receive_text())["session"]
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "tts-cfg-v", "type": "client.tts_config",
            "ts": 1999, "session": session_id, "payload": {"enabled": False},
        }))
        assert json.loads(ws.receive_text())["type"] == "server.ack"
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "vq-1", "type": "user.text",
            "ts": 2000, "session": session_id, "payload": {"text": "桌子上有什么"},
        }))
        speech = json.loads(ws.receive_text())
        assert speech["type"] == "agent.speech"
        vision_request = None
        while vision_request is None:
            candidate = json.loads(ws.receive_text())
            if candidate["type"] == "server.vision_request":
                vision_request = candidate
        assert vision_request["type"] == "server.vision_request"
        assert vision_request["payload"]["prompt"] == "桌子上有什么"

        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "vm-1", "type": "client.vision_frame_meta",
            "ts": 2001, "session": session_id,
            "payload": {"width": 640, "height": 480},
        }))
        assert json.loads(ws.receive_text())["type"] == "server.ack"
        ws.send_bytes(pack_frame(3, 1, b"jpeg-bytes"))
        ws.send_text(json.dumps({
            "v": "1.0.0", "id": "vq-2", "type": "client.vision_query",
            "ts": 2002, "session": session_id, "payload": {"prompt": "桌子上有什么"},
        }))
        detection = json.loads(ws.receive_text())
        assert detection["type"] == "server.object_detection"
        assert detection["payload"]["objects"][0]["label"] == "cup"
        final_speech = json.loads(ws.receive_text())
        assert final_speech["type"] == "agent.speech"
        assert final_speech["payload"]["text"] == "我看到桌上有杯子。"
        assert calls[-1].get("vision_objects")
