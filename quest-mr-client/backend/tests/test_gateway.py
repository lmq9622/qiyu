"""P0 Gateway 真实 WebSocket 测试（不依赖 Unity / Quest 设备）。"""
from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qiyu_quest_gateway.gateway import QuestWebSocketGateway


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
