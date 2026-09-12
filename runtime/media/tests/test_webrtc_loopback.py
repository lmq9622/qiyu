# -*- coding: utf-8 -*-
"""真实的 WebRTC 本机回环验证（真 ICE / DTLS / SRTP，不是假 peer）。

验证项（对应规格 C / J 的第 6 步 WebRTC local loopback）：
  1. 两个真 WebRTC peer 完成协商并 connected
  2. 视频轨道真的传过去（收到帧、非黑、有帧率）
  3. 音频轨道真的传过去（收到非静音）
  4. mute 生效（对端收到静音）
  5. 摄像头开关生效（对端收到黑帧）
  6. 连接状态 / 统计可取（RTT、包数）
  7. reconnect 后仍能继续收帧
  8. close 后状态正确

标签：REAL WEBRTC（本机回环、进程内信令）。
NOT VERIFIED：跨机 / 跨 NAT / TURN / 真 Quest 端点。

用法：python -m runtime.media.tests.test_webrtc_loopback
报告：runtime/omni/out/webrtc_loopback.json
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from runtime.media.service import VideoCallService  # noqa: E402
from runtime.media.tracks import (  # noqa: E402
    audio_frame_to_f32, frame_energy, video_frame_to_rgb,
)

OUT = Path("runtime/omni/out")
RESULTS: dict = {}


def _record(name: str, ok: bool, detail: dict | None = None) -> bool:
    RESULTS[name] = {"ok": bool(ok), **(detail or {})}
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name} " + json.dumps(detail or {}, ensure_ascii=False))
    return bool(ok)


async def collect_video(track, seconds: float) -> dict:
    frames, energies, ts = 0, [], []
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline and frames < 200:
        try:
            frame = await asyncio.wait_for(track.recv(), timeout=2.0)
        except Exception:
            break
        rgb = video_frame_to_rgb(frame)
        frames += 1
        energies.append(frame_energy(rgb))
        ts.append(time.perf_counter())
    fps = 0.0
    if len(ts) >= 2:
        fps = (len(ts) - 1) / max(1e-6, ts[-1] - ts[0])
    return {
        "frames": frames,
        "mean_energy": round(float(np.mean(energies)) if energies else 0.0, 4),
        "max_energy": round(float(np.max(energies)) if energies else 0.0, 4),
        "fps": round(fps, 2),
    }


async def collect_audio(track, seconds: float) -> dict:
    chunks, ts = [], []
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            frame = await asyncio.wait_for(track.recv(), timeout=2.0)
        except Exception:
            break
        chunks.append(audio_frame_to_f32(frame, 16000))
        ts.append(time.perf_counter())
    if not chunks:
        return {"frames": 0, "rms": 0.0, "seconds": 0.0}
    data = np.concatenate(chunks)
    rms = float(np.sqrt(np.mean(data * data))) if data.size else 0.0
    return {
        "frames": len(chunks),
        "rms": round(rms, 5),
        "seconds": round(len(data) / 16000.0, 3),
        "peak": round(float(np.max(np.abs(data))) if data.size else 0.0, 4),
    }


def make_tone(seconds: float, rate: int = 48000, freq: float = 440.0,
              amp: float = 0.25, chunk_ms: float = 20.0) -> list:
    n = int(rate * chunk_ms / 1000.0)
    total = int(seconds * rate)
    t = np.arange(total, dtype=np.float64) / rate
    wave = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return [wave[i:i + n] for i in range(0, len(wave) - n + 1, n)]


async def drain(track, seconds: float) -> int:
    """把轨道里积压的帧丢掉（发送端刚切换状态时，接收端还有旧帧在管道里）。"""
    n = 0
    deadline = time.perf_counter() + seconds
    while time.perf_counter() < deadline:
        try:
            await asyncio.wait_for(track.recv(), timeout=0.5)
            n += 1
        except Exception:
            break
    return n


async def push_tone(session, seconds: float, chunk_ms: float = 20.0) -> None:
    for chunk in make_tone(seconds, chunk_ms=chunk_ms):
        session.push_local_audio(chunk)
        await asyncio.sleep(chunk_ms / 1000.0 / 5.0)


async def main() -> int:
    print("=" * 70)
    print("WebRTC 本机回环验证（真 ICE / DTLS / SRTP）")
    print("=" * 70)
    service = VideoCallService(ice_servers=[])
    t0 = time.perf_counter()
    a, b = await service.connect_loopback(video_fps=10.0, audio_sample_rate=48000)
    connect_s = round(time.perf_counter() - t0, 2)

    _record("peer_connected",
            a.link is not None and b.link is not None
            and a.link.connection_state == "connected"
            and b.link.connection_state == "connected",
            {"connect_seconds": connect_s,
             "a_state": a.link.connection_state, "b_state": b.link.connection_state,
             "a_ice": a.link.ice_state, "b_ice": b.link.ice_state})
    _record("remote_tracks_negotiated",
            a.remote_audio is not None and a.remote_video is not None
            and b.remote_audio is not None and b.remote_video is not None,
            {"a_tracks": list(a.link.remote_tracks), "b_tracks": list(b.link.remote_tracks)})

    got = await collect_video(a.remote_video, 2.0)
    _record("video_track_flows", got["frames"] >= 3 and got["max_energy"] > 0.02, got)

    send_task = asyncio.create_task(push_tone(b, 1.5))
    audio_rx = await collect_audio(a.remote_audio, 1.5)
    await send_task
    _record("audio_track_flows", audio_rx["frames"] >= 5 and audio_rx["rms"] > 0.01, audio_rx)

    b.set_muted(True)
    await asyncio.sleep(0.4)
    await drain(a.remote_audio, 0.8)
    send_task = asyncio.create_task(push_tone(b, 1.0))
    muted_rx = await collect_audio(a.remote_audio, 1.2)
    await send_task
    _record("mute_silences_remote", muted_rx["rms"] < 0.005, muted_rx)

    b.set_muted(False)
    await asyncio.sleep(0.4)
    await drain(a.remote_audio, 0.5)
    send_task = asyncio.create_task(push_tone(b, 1.0))
    unmuted_rx = await collect_audio(a.remote_audio, 1.2)
    await send_task
    _record("unmute_restores_audio", unmuted_rx["rms"] > 0.01, unmuted_rx)

    b.set_camera_enabled(False)
    await asyncio.sleep(0.5)
    await drain(a.remote_video, 1.0)
    cam_off = await collect_video(a.remote_video, 1.5)
    _record("camera_off_sends_black",
            cam_off["frames"] >= 3 and cam_off["max_energy"] < 0.02, cam_off)

    b.set_camera_enabled(True)
    await asyncio.sleep(0.5)
    await drain(a.remote_video, 1.0)
    cam_on = await collect_video(a.remote_video, 1.5)
    _record("camera_on_restores_video",
            cam_on["frames"] >= 3 and cam_on["max_energy"] > 0.02, cam_on)

    q_a, q_b = await a.sample_quality(), await b.sample_quality()
    _record("quality_stats_available", bool(q_a) and bool(q_b),
            {"offerer": q_a, "answerer": q_b})

    # 重连：由 offerer 主动重建并发新 offer，answerer 就地重建并应答
    ok_a = await a.reconnect(timeout=15.0)
    await asyncio.sleep(0.8)
    ok_b = await b.wait_live(15.0)
    await drain(a.remote_video, 0.8)
    after = await collect_video(a.remote_video, 2.0)
    _record("reconnect_resumes_media", ok_a and ok_b and after["frames"] >= 3,
            {"answerer_reconnected": ok_b, "offerer_live": ok_a, **after})

    stats_before_close = {"a": a.stats().to_dict(), "b": b.stats().to_dict()}
    await service.close_all()
    await asyncio.sleep(0.5)
    _record("close_works", a.state == "closed" and b.state == "closed",
            {"a_state": a.state, "b_state": b.state})

    summary = {
        "label": "REAL WEBRTC (loopback)",
        "not_verified": ["跨机/跨 NAT", "TURN 中继", "真实 Quest 端点", "带宽自适应策略"],
        "connect_seconds": connect_s,
        "results": RESULTS,
        "stats_before_close": stats_before_close,
        "passed": sum(1 for v in RESULTS.values() if v.get("ok")),
        "total": len(RESULTS),
    }
    verdict = all(v.get("ok") for v in RESULTS.values())
    summary["verdict"] = "PASS" if verdict else "FAIL"
    print("=" * 70)
    print("WEBRTC_LOOPBACK =", summary["verdict"],
          f"({summary['passed']}/{summary['total']})")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "webrtc_loopback.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT / "webrtc_loopback.json")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
