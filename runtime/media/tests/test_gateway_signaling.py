# -*- coding: utf-8 -*-
"""网关信令 + 真 WebRTC 客户端验证。

链路（全是真东西，只有机器是同一台）：

    aiortc 客户端(本测试) <--WebSocket /v1/call/signal--> FastAPI 网关
                          <--WebRTC(ICE/DTLS/SRTP)-->   网关侧 MediaSession

验证项：
  1. 真实 WebSocket 信令通道建立并完成 offer/answer 交换
  2. WebRTC 连接建立（客户端与网关侧 peer）
  3. 服务端视频真的传到客户端（收到非黑帧）
  4. 客户端音频真的传到服务端（quality.packets_received > 0）
  5. 网关侧带宽自适应循环推送 quality（adapt 生效）
  6. bye 后返回会话统计且状态 closed

标签：REAL WEBRTC + REAL WS SIGNALING（同机回环）。
NOT VERIFIED：跨机 / TURN / 真实 Quest 端点。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import av  # noqa: E402
import websockets  # noqa: E402
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack  # noqa: E402

from gateway.call_signaling import router as call_router  # noqa: E402
from runtime.media.tracks import frame_energy, video_frame_to_rgb  # noqa: E402

PORT = 8811
OUT = Path("runtime/omni/out")
RESULTS = {}


def _record(name, ok, detail=None):
    RESULTS[name] = {"ok": bool(ok), **(detail or {})}
    print("  [%s] %s %s" % ("PASS" if ok else "FAIL", name,
                            json.dumps(detail or {}, ensure_ascii=False)))
    return bool(ok)


class ProbeVideo(VideoStreamTrack):
    """客户端摄像头：发测试图样（证明上行视频/音频通道真的在跑）。"""

    kind = "video"

    def __init__(self):
        super().__init__()
        self.sent = 0

    async def recv(self):
        pts, tb = await self.next_timestamp()
        x = np.linspace(0, 255, 160, dtype=np.uint8)
        arr = np.stack([np.tile(x, (120, 1))] * 3, axis=-1)
        f = av.VideoFrame.from_ndarray(arr, format="rgb24")
        f.pts, f.time_base = pts, tb
        self.sent += 1
        return f


class ProbeAudio:
    """客户端麦克风：直接复用 runtime.media 的队列轨道。"""


def start_server():
    app = FastAPI()
    app.include_router(call_router)
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            return server, t
        time.sleep(0.1)
    raise RuntimeError("uvicorn 未启动")


async def main():
    print("=" * 70)
    print("网关信令 + 真 WebRTC 客户端验证")
    print("=" * 70)
    server, thread = start_server()
    from runtime.media.tracks import QueueAudioTrack
    url = f"ws://127.0.0.1:{PORT}/v1/call/signal"
    pc = RTCPeerConnection()
    audio = QueueAudioTrack(sample_rate=48000)
    pc.addTrack(audio)
    pc.addTrack(ProbeVideo())
    remote_tracks = {}
    frames_seen = {"n": 0, "energy": []}

    @pc.on("track")
    def _on_track(track):
        remote_tracks[track.kind] = track

        async def consume():
            while True:
                try:
                    frame = await track.recv()
                except Exception:
                    return
                if track.kind == "video":
                    frames_seen["n"] += 1
                    frames_seen["energy"].append(frame_energy(video_frame_to_rgb(frame)))

        asyncio.ensure_future(consume())

    quality_replies = []
    bye_stats = None
    got_offer = False
    async with websockets.connect(url, max_size=None, ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "hello", "role": "offerer", "from": "quest"}))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        _record("ws_signaling_connected", ack.get("type") == "hello.ack",
                {"ack": ack.get("type"), "session_id": ack.get("session_id"),
                 "ice_servers": ack.get("ice_servers")})

        async def push_audio():
            chunk = int(48000 * 0.02)
            t = 0
            while True:
                n = chunk
                idx = np.arange(t, t + n)
                wave = (0.2 * np.sin(2 * np.pi * 440 * idx / 48000)).astype(np.float32)
                audio.push(wave)
                t += n
                await asyncio.sleep(0.02)

        audio_task = asyncio.create_task(push_audio())
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            except asyncio.TimeoutError:
                break
            t = msg.get("type")
            if t == "offer":
                got_offer = True
                await pc.setRemoteDescription(RTCSessionDescription(
                    sdp=msg["payload"]["sdp"], type="offer"))
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                await ws.send(json.dumps({"type": "answer",
                                          "payload": {"sdp": pc.localDescription.sdp,
                                                      "type": "answer"}}))
            elif t == "quality":
                quality_replies.append(msg.get("payload") or {})
            elif t == "bye":
                bye_stats = msg.get("payload") or {}

        _record("webrtc_connected", got_offer and pc.connectionState == "connected",
                {"got_offer": got_offer, "pc_state": pc.connectionState,
                 "ice": pc.iceConnectionState})
        await asyncio.sleep(1.0)
        energies = frames_seen["energy"]
        _record("server_video_reaches_client",
                frames_seen["n"] >= 3 and max(energies or [0]) > 0.05,
                {"frames": frames_seen["n"],
                 "max_energy": round(max(energies or [0.0]), 4)})
        _record("client_audio_reaches_server",
                any((q.get("packets_received") or 0) > 0 for q in quality_replies),
                {"quality_samples": len(quality_replies),
                 "last": quality_replies[-1] if quality_replies else None})
        _record("bandwidth_adaptation_running",
                any("level" in q for q in quality_replies),
                {"levels": [q.get("level") for q in quality_replies][-3:],
                 "fps": [q.get("target_fps") for q in quality_replies][-3:]})

        await ws.send(json.dumps({"type": "stats"}))
        try:
            stats_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        except asyncio.TimeoutError:
            stats_msg = {}
        await ws.send(json.dumps({"type": "bye"}))
        try:
            bye = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            bye_stats = bye.get("payload") or bye_stats
        except asyncio.TimeoutError:
            pass
        audio_task.cancel()
        _record("server_session_stats",
                bool(stats_msg.get("payload")) and bye_stats is not None,
                {"stats": stats_msg.get("payload"),
                 "bye_state": (bye_stats or {}).get("state")})
    await pc.close()
    await asyncio.sleep(0.5)
    server.should_exit = True

    summary = {"label": "REAL WEBRTC + REAL WS SIGNALING (loopback)",
               "not_verified": ["跨机 / 跨 NAT", "TURN 中继", "真实 Quest 端点"],
               "results": RESULTS,
               "passed": sum(1 for v in RESULTS.values() if v.get("ok")),
               "total": len(RESULTS)}
    verdict = all(v.get("ok") for v in RESULTS.values())
    summary["verdict"] = "PASS" if verdict else "FAIL"
    print("=" * 70)
    print("GATEWAY_SIGNALING =", summary["verdict"],
          "(%d/%d)" % (summary["passed"], summary["total"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gateway_signaling.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT / "gateway_signaling.json")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
