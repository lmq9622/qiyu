# -*- coding: utf-8 -*-
"""诊断：OmniSession -> MiniCPMOWsStream 为什么不出话（对照裸 WS 能出话）。

分两阶段喂同一个真模型会话：
  A) 只喂音频（0.5s/块、每 0.5s 一块，和能出话的 smoke 完全一致）
  B) 音频 + 视频（10fps，和我们 E2E 的高频喂法一致）

判据：哪个阶段开始产出 text/audio，就说明差别在「视频频率/批处理」还是「session 初始化」。
"""

from __future__ import annotations

import array
import asyncio
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from runtime.omni.backends.minicpm_ws import MiniCPMOWsBackend
from runtime.omni.session import OmniSession
from runtime.omni.types import AudioChunk, SessionConfig, VideoFrame

DUP = Path(r"D:\qiyu-omni-build\src\llama.cpp-omni-master\tools\omni\assets"
           r"\test_case\duplex_omni_test_case")
OUT = Path("runtime/omni/out")


def load_wav_f32(path: Path):
    b = path.read_bytes()
    pos, sr, data = 12, 16000, None
    while pos + 8 <= len(b):
        cid = b[pos:pos + 4]
        size = struct.unpack_from("<I", b, pos + 4)[0]
        body = b[pos + 8: pos + 8 + size]
        if cid == b"fmt ":
            sr = struct.unpack_from("<I", body, 4)[0]
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)
    arr = array.array("h")
    arr.frombytes(data[: len(data) // 2 * 2])
    return [v / 32768.0 for v in arr], sr


async def main() -> int:
    wavs = sorted(DUP.glob("*.wav"))
    jpgs = sorted(DUP.glob("*.jpg"))
    prompts = [load_wav_f32(w) for w in wavs[:6]]
    clips = []
    for pcm, sr in prompts:
        for i in range(0, len(pcm) - int(sr * 0.5) + 1, int(sr * 0.5)):
            clips.append(pcm[i:i + int(sr * 0.5)])

    report = {"phases": []}
    for phase, with_video in (("audio_only", False), ("audio_plus_video_10fps", True)):
        print("=" * 66)
        print(f"[阶段] {phase}  (video={with_video})")
        omni = OmniSession(backend=MiniCPMOWsBackend())
        cfg = SessionConfig(meta={"mode": "full_duplex"})
        t0 = time.time()
        try:
            sid = await omni.start_session(cfg)
        except Exception as e:
            print("  启动失败:", type(e).__name__, e)
            report["phases"].append({"phase": phase, "error": f"{type(e).__name__}: {e}"})
            continue
        print(f"  会话已建: {sid} state={omni.state} "
              f"metrics={getattr(omni.stream, 'last_metrics', {})}")
        events = {"text": 0, "audio": 0, "listen": 0, "other": 0}
        texts = []

        async def consume():
            async for ev in omni.receive_event():
                k = getattr(ev, "kind", "")
                conv = getattr(ev, "conversation", None)
                if conv is not None and conv.text:
                    events["text"] += 1
                    texts.append(conv.text)
                elif conv is not None and conv.audio is not None:
                    events["audio"] += 1
                elif k == "event":
                    events["other"] += 1
                else:
                    events["listen"] += 1

        task = asyncio.create_task(consume())
        vi = 0
        deadline = time.time() + 40
        ci = 0
        while time.time() < deadline and ci < 40:
            pcm = clips[ci % len(clips)]
            await omni.send_audio_chunk(AudioChunk(pcm=pcm, sample_rate=16000,
                                                   speaker_id="remote_user", seq=ci))
            if with_video:
                for _ in range(5):
                    jpg = jpgs[vi % len(jpgs)].read_bytes()
                    vi += 1
                    await omni.send_video_frame(VideoFrame(
                        data=jpg, kind="keyframe", source="remote_peer",
                        speaker_id="remote_user", frame_id=vi, meta={}))
                    await asyncio.sleep(0.02)
            ci += 1
            await asyncio.sleep(0.5)
            if events["text"] or events["audio"]:
                break
        await asyncio.sleep(2.0)
        task.cancel()
        counters = dict(omni.counters)
        print(f"  喂了 {ci} 个音频块 / {vi} 帧视频；事件={events}")
        print(f"  counters={counters}")
        if texts:
            print("  文本样例:", " | ".join(t[:20] for t in texts[:5]))
        report["phases"].append({"phase": phase, "audio_blocks": ci, "video_frames": vi,
                                 "events": events, "counters": counters,
                                 "texts": texts[:5], "elapsed_s": round(time.time() - t0, 1)})
        try:
            await omni.close()
        except Exception:
            pass
        await asyncio.sleep(2.0)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "diag_session_stream.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = any(p.get("events", {}).get("text") or p.get("events", {}).get("audio")
             for p in report["phases"])
    print("=" * 66)
    print("DIAG =", "PRODUCED_OUTPUT" if ok else "NO_OUTPUT")
    print("报告:", OUT / "diag_session_stream.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
