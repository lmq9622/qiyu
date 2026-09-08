"""真实进程级联调：启动 quest_server.py，用 websockets 客户端跑协议链路。

用法：
    python tests/smoke_live_gateway.py

覆盖：
- 真实 uvicorn 进程 + 现有 Qiyu app
- client.hello → server.hello_ack
- client.world_state → server.ack
- user.text → agent.speech（或诚实的 server.error）
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PORT = int(os.getenv("QIYU_QUEST_SMOKE_PORT", "8767"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _wait_port(host: str, port: int, timeout_s: float = 90.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.5)
    raise TimeoutError(f"端口 {host}:{port} 未在 {timeout_s}s 内监听")


async def _run_client() -> dict:
    import websockets

    url = f"ws://127.0.0.1:{PORT}/v1/quest/ws"
    result = {"hello": False, "world_state": False, "turn": None}
    async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "v": "1.0.0", "id": "smoke-hello", "type": "client.hello", "ts": 1,
            "payload": {"user_id": "smoke_user", "char_id": "xiaoban",
                        "device": "smoke-test", "client_version": "0.0.1"},
        }))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        assert ack["type"] == "server.hello_ack", ack
        session = ack["session"]
        result["hello"] = True

        async def _heartbeat() -> None:
            counter = 0
            while True:
                await asyncio.sleep(5)
                counter += 1
                await ws.send(json.dumps({
                    "v": "1.0.0", "id": f"smoke-hb-{counter}",
                    "type": "client.heartbeat", "ts": counter, "session": session,
                    "payload": {},
                }))

        heartbeat_task = asyncio.create_task(_heartbeat())

        await ws.send(json.dumps({
            "v": "1.0.0", "id": "smoke-ws", "type": "client.world_state",
            "ts": 2, "session": session,
            "payload": {
                "protocol_version": "1.0.0", "ts": 2, "room_id": "smoke-room",
                "scene_version": 1, "status": "ready",
                "anchors": [{
                    "id": "table-1", "label": "table",
                    "pose": {"position": {"x": 1, "y": 0.7, "z": 2}},
                }],
                "user": {"head": {"position": {"x": 0, "y": 1.6, "z": 0}}},
                "avatar": {}, "navmesh": {},
            },
        }))
        ws_ack = None
        while ws_ack is None:
            candidate = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if candidate["type"] != "server.heartbeat":
                ws_ack = candidate
        assert ws_ack["type"] == "server.ack", ws_ack
        result["world_state"] = True

        await ws.send(json.dumps({
            "v": "1.0.0", "id": "smoke-text", "type": "user.text",
            "ts": 3, "session": session, "payload": {"text": "你好，你在吗？"},
        }))
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1, deadline - time.time()))
            except asyncio.TimeoutError:
                break
            message = json.loads(raw)
            if message["type"] == "server.heartbeat":
                continue
            if message["type"] in ("agent.speech", "server.error"):
                result["turn"] = message
                break
        heartbeat_task.cancel()
        return result


def main() -> int:
    env = dict(os.environ)
    env["QIYU_QUEST_PORT"] = str(PORT)
    env["QIYU_QUEST_HOST"] = "127.0.0.1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_file = tempfile.NamedTemporaryFile(
        prefix="qiyu_quest_smoke_", suffix=".log", delete=False)
    log_path = log_file.name
    process = subprocess.Popen(
        [sys.executable, "quest_server.py"],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    log_file.close()
    try:
        _wait_port("127.0.0.1", PORT)
        result = asyncio.run(_run_client())
        print("hello_ack:", result["hello"])
        print("world_state_ack:", result["world_state"])
        turn = result["turn"] or {}
        print("turn_type:", turn.get("type"))
        if turn.get("type") == "agent.speech":
            print("turn_text:", (turn.get("payload") or {}).get("text", "")[:120])
        elif turn.get("type") == "server.error":
            print("turn_error:", (turn.get("payload") or {}).get("code"),
                  (turn.get("payload") or {}).get("message", "")[:160])
        ok = result["hello"] and result["world_state"] and result["turn"] is not None
        print("SMOKE", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        try:
            output = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            output = ""
        tail = "\n".join(output.splitlines()[-15:])
        if tail:
            print("--- server tail ---")
            print(tail)
        try:
            Path(log_path).unlink()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
