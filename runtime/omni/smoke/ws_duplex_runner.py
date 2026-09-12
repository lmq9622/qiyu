# -*- coding: utf-8 -*-
"""真实 WS 双工 / barge-in smoke（真模型 + 真实语音，不用 Mock）。

修正了此前三个错误：
  1. 用仓库自带**真实语音 wav**，不再用正弦波（正弦波模型会正确判定为无人说话）；
  2. 文本轮次走 `turn_based`，音频连续流走 `full_duplex`；
  3. **会话串行化**：服务端同一时刻只允许一个活动会话，关闭后需等释放。

用法：
  python -m runtime.omni.smoke.run_ws_duplex [--port 19080] [--mode all|duplex|text|barge]
"""

from __future__ import annotations

import argparse
import asyncio
import array
import json
import os
import struct
import time
from pathlib import Path

ASSET = Path(r"D:\qiyu-omni-build\src\llama.cpp-omni-master\tools\omni\assets"
              r"\test_case\audio_test_case\audio_test_case_0000.wav")
OUT = Path("runtime/omni/out")


def load_wav_f32(path: Path) -> tuple[list, int]:
    """解析 WAV（正确跳过 LIST 等附加块），返回 (float 列表, 采样率)。"""
    b = path.read_bytes()
    if b[:4] != b"RIFF":
        raise ValueError("not RIFF")
    pos, sr, ch, bits, data = 12, 16000, 1, 16, None
    while pos + 8 <= len(b):
        cid = b[pos:pos + 4]
        size = struct.unpack_from("<I", b, pos + 4)[0]
        body = b[pos + 8: pos + 8 + size]
        if cid == b"fmt ":
            fmt, ch, sr, _, _, bits = struct.unpack_from("<HHIIHH", body, 0)
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)
    if data is None:
        raise ValueError("no data chunk")
    if bits == 16:
        arr = array.array("h")
        arr.frombytes(data[: len(data) // 2 * 2])
        return [v / 32768.0 for v in arr], sr
    if bits == 32:
        arr = array.array("f")
        arr.frombytes(data[: len(data) // 4 * 4])
        return list(arr), sr
    raise ValueError(f"unsupported bits={bits}")


async def pump(sess, seconds: float, sink: dict) -> None:
    """收事件，写进 sink（供并发观察输出是否被输入阻塞）。"""
    t0 = sink["t0"]

    async def _rd():
        async for ev in sess.receive_event():
            dt = round((time.time() - t0) * 1000, 1)
            c = ev.conversation
            if c is not None:
                if c.text:
                    sink["text"] += c.text
                    if sink["ttft"] is None:
                        sink["ttft"] = dt
                if c.audio is not None:
                    sink["audio"] += 1
                    if sink["ttfa"] is None:
                        sink["ttfa"] = dt
            if ev.payload:
                sink["events"].append(ev.payload.get("event", ""))
            if time.time() > t0 + seconds:
                return

    try:
        await asyncio.wait_for(_rd(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    return sink


def new_sink() -> dict:
    return {"t0": time.time(), "text": "", "audio": 0, "ttft": None, "ttfa": None, "events": []}


async def one_session(mode: str, action, seconds: float) -> dict:
    """建会话 → 执行 action（可并发喂输入）→ 收输出 → 关闭并等待释放。"""
    from runtime.omni import build_omni
    from runtime.omni.types import SessionConfig

    sess = build_omni(allow_mock=False)
    await sess.start_session(SessionConfig(
        personality="栖语：说话自然、简短、像真人朋友",
        meta={"mode": mode}, full_duplex=(mode == "full_duplex")))
    sink = new_sink()
    task = asyncio.create_task(pump(sess, seconds, sink))
    await action(sess)
    got = await task
    got["state"] = sess.state
    got["counters"] = dict(sess.counters)
    got["interrupts"] = getattr(sess.stream, "interrupts", 0)
    got["dropped"] = getattr(sess.stream, "dropped_on_interrupt", 0)
    await sess.close()
    await asyncio.sleep(3.0)          # 等服务端释放会话/管线
    return got


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=19080)
    ap.add_argument("--mode", default="all",
                    choices=["all", "duplex", "text", "barge"])
    args = ap.parse_args()
    os.environ["QIYU_OMNI_PORT"] = str(args.port)

    pcm, sr = load_wav_f32(ASSET)
    dur = len(pcm) / sr
    print(f"语音素材: {ASSET.name}  {dur:.2f}s @ {sr}Hz")
    rep: dict = {"asset": str(ASSET), "asset_sec": round(dur, 2)}

    from runtime.omni.types import AudioChunk

    def slice_chunks(step_s: float = 0.5):
        n = int(sr * step_s)
        return [AudioChunk(pcm=pcm[i:i + n], sample_rate=sr) for i in range(0, len(pcm), n)]

    # ---------- 1) full_duplex：真实语音 → 流式文本 + 流式音频 ----------
    if args.mode in ("all", "duplex"):
        async def feed(sess):
            for ch in slice_chunks(0.5):
                await sess.send_audio_chunk(ch)
                await asyncio.sleep(0.05)
        got = await one_session("full_duplex", feed, 25.0)
        rep["duplex"] = got
        print(f"[duplex] text={got['text'][:70]!r} ttft={got['ttft']}ms ttfa={got['ttfa']}ms "
              f"audio={got['audio']} events={got['events'][:5]}")

    # ---------- 2) turn_based：文本多轮 ----------
    if args.mode in ("all", "text"):
        turns = []
        for text in ["在吗", "我今天有点烦"]:
            async def send(sess, t=text):
                await sess.send_text(t)
            got = await one_session("turn_based", send, 25.0)
            got["input"] = text
            turns.append(got)
            print(f"[text] {text!r} -> {got['text'][:60]!r} ttft={got['ttft']}ms "
                  f"ttfa={got['ttfa']}ms audio={got['audio']}")
        rep["text_turns"] = turns

    # ---------- 3) barge-in：输出中继续送语音 + interrupt ----------
    if args.mode in ("all", "barge"):
        state: dict = {}

        async def barge(sess):
            for ch in slice_chunks(0.5):
                await sess.send_audio_chunk(ch)
                await asyncio.sleep(0.05)
            await asyncio.sleep(1.2)               # 等模型开始输出
            state["t_int"] = time.time()
            await sess.interrupt(reason="user_barge_in")
            state["int_ms"] = round((time.time() - state["t_int"]) * 1000, 1)
            before_audio = None
            await asyncio.sleep(1.0)
            # 打断后继续送新语音（同一 session，不重建）
            for ch in slice_chunks(0.5):
                await sess.send_audio_chunk(ch)
                await asyncio.sleep(0.05)

        got = await one_session("full_duplex", barge, 35.0)
        got["interrupt_signal_ms"] = state.get("int_ms")
        rep["barge_in"] = got
        print(f"[barge] signal={state.get('int_ms')}ms dropped={got['dropped']} "
              f"interrupts={got['interrupts']} text={got['text'][:60]!r} "
              f"ttfa={got['ttfa']}ms audio={got['audio']}")

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "ws_duplex.json"
    p.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
