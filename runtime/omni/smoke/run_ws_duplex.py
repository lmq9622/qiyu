# -*- coding: utf-8 -*-
"""真实 WS 双工 / barge-in smoke（真模型，不用 Mock）。

用法：
  python -m runtime.omni.smoke.run_ws_duplex --turns 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from pathlib import Path

from runtime.omni import build_omni
from runtime.omni.types import AudioChunk, SessionConfig, VideoFrame


def _tone(ms: float, freq: float = 220.0, sr: int = 16000, amp: float = 0.12) -> AudioChunk:
    n = max(1, int(sr * ms / 1000.0))
    pcm = [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)]
    return AudioChunk(pcm=pcm, sample_rate=sr)


async def collect(sess, seconds: float) -> dict:
    out = {"text": "", "audio": 0, "events": [], "first_text_ms": None, "first_audio_ms": None}
    t0 = time.time()

    async def _rd():
        async for ev in sess.receive_event():
            dt = (time.time() - t0) * 1000
            c = ev.conversation
            if c is not None:
                if c.text:
                    out["text"] += c.text
                    if out["first_text_ms"] is None:
                        out["first_text_ms"] = round(dt, 1)
                if c.audio is not None:
                    out["audio"] += 1
                    if out["first_audio_ms"] is None:
                        out["first_audio_ms"] = round(dt, 1)
            if ev.payload:
                out["events"].append(ev.payload.get("event", ""))
            if time.time() > t0 + seconds:
                return

    try:
        await asyncio.wait_for(_rd(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=3)
    ap.add_argument("--port", type=int, default=19080)
    args = ap.parse_args()

    import os
    os.environ["QIYU_OMNI_PORT"] = str(args.port)

    rep: dict = {"backend": "", "turns": [], "duplex": {}, "barge_in": {}}
    sess = build_omni(allow_mock=False)
    await sess.start_session(SessionConfig(personality="栖语：说话自然、简短、像真人朋友",
                                          full_duplex=True, allow_barge_in=True))
    rep["backend"] = sess.backend_name
    print(f"backend={sess.backend_name}  state={sess.state}")

    # ---- T1 多轮文本 ----
    for i, text in enumerate(["在吗", "你在干嘛", "我今天有点烦"], start=1):
        if i > args.turns:
            break
        t0 = time.time()
        await sess.send_text(text)
        got = await collect(sess, 12.0)
        rep["turns"].append({"input": text, "text": got["text"],
                             "audio_chunks": got["audio"],
                             "ttft_ms": got["first_text_ms"], "ttfa_ms": got["first_audio_ms"],
                             "wall_ms": round((time.time() - t0) * 1000, 1),
                             "events": got["events"][:6]})
        print(f"[turn {i}] {text!r} -> {got['text'][:50]!r}  "
              f"ttft={got['first_text_ms']}ms ttfa={got['first_audio_ms']}ms audio={got['audio']}")

    # ---- T2 全双工：模型说话时持续送音频，输出不得被阻塞 ----
    await sess.send_text("给我讲一句长一点的话")
    t0 = time.time()
    task = asyncio.create_task(collect(sess, 8.0))
    for _ in range(10):
        await sess.send_audio_chunk(_tone(200))
        await asyncio.sleep(0.2)
        await sess.send_video_frame(VideoFrame(data=b"\xff\xd8\xff\xd9", frame_id=int(time.time()*1000) % 100000))
    got = await task
    rep["duplex"] = {"audio_in_while_speaking": 10,
                     "output_text": got["text"][:80], "audio_out_chunks": got["audio"],
                     "output_not_blocked": got["audio"] > 0 or bool(got["text"]),
                     "wall_ms": round((time.time() - t0) * 1000, 1)}
    print(f"[duplex] 边送音频边收输出 -> text={got['text'][:40]!r} audio={got['audio']}")

    # ---- T3 真实 barge-in ----
    await sess.send_text("继续说，别停")
    await asyncio.sleep(0.6)
    t_int = time.time()
    await sess.interrupt(reason="user_barge_in")
    int_ms = round((time.time() - t_int) * 1000, 1)
    after = await collect(sess, 1.5)
    # 打断后新输入必须还能被接受（不重建 session）
    await sess.send_text("我说的是另一件事")
    nxt = await collect(sess, 12.0)
    rep["barge_in"] = {
        "interrupt_signal_ms": int_ms,
        "dropped_audio_chunks": sess.stream.dropped_on_interrupt if hasattr(sess, "stream") else None,
        "audio_after_interrupt": after["audio"],
        "next_input_accepted": bool(nxt["text"]),
        "next_text": nxt["text"][:60],
        "next_ttft_ms": nxt["first_text_ms"],
        "next_ttfa_ms": nxt["first_audio_ms"],
        "session_alive": sess.state not in ("closed", "error"),
    }
    print(f"[barge-in] signal={int_ms}ms  打断后新输入: {nxt['text'][:40]!r} "
          f"ttft={nxt['first_text_ms']}ms  session={sess.state}")

    rep["health"] = {"counters": dict(sess.counters), "state": sess.state,
                     "video": sess.video.snapshot()}
    out = Path("runtime/omni/out/ws_duplex.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", out)
    await sess.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
