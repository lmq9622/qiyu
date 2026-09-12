# -*- coding: utf-8 -*-
"""最小 WS /backend 测试客户端（**不经 Qiyu 封装**）。

用途：证据链定位。直接打印服务端发来的每一条消息，带 T5(收到) 时间戳。
排除 OmniSession / MiniCPMOWsBackend 的干扰。

```bash
python -m runtime.omni.smoke.ws_min_client --mode full_duplex --turns 10
python -m runtime.omni.smoke.ws_min_client --mode turn_based  --turns 3
```
"""

from __future__ import annotations

import argparse
import array
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import websockets  # noqa: E402

DUP = Path(r"D:\qiyu-omni-build\src\llama.cpp-omni-master\tools\omni\assets"
           r"\test_case\duplex_omni_test_case")


def load_wav_f32(path: Path):
    import struct
    b = path.read_bytes()
    pos, sr, bits, data = 12, 16000, 16, None
    while pos + 8 <= len(b):
        cid = b[pos:pos + 4]
        size = struct.unpack_from("<I", b, pos + 4)[0]
        body = b[pos + 8: pos + 8 + size]
        if cid == b"fmt ":
            _, _, sr, _, _, bits = struct.unpack_from("<HHIIHH", body, 0)
        elif cid == b"data":
            data = body
        pos += 8 + size + (size & 1)
    arr = array.array("h")
    arr.frombytes(data[: len(data) // 2 * 2])
    return [v / 32768.0 for v in arr], sr


def b64_f32(pcm) -> str:
    return base64.b64encode(array.array("f", pcm).tobytes()).decode()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:19080/backend")
    ap.add_argument("--mode", default="full_duplex", choices=["full_duplex", "turn_based"])
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--settle", type=float, default=2.0)
    args = ap.parse_args()

    wavs = sorted(DUP.glob("*.wav"))
    jpgs = sorted(DUP.glob("*.jpg"))
    print(f"素材: {len(wavs)} wav / {len(jpgs)} jpg   模式={args.mode}  轮数={args.turns}")

    stats = {"created": 0, "listen": 0, "text": 0, "audio": 0, "done": 0, "closed": 0, "other": 0}
    t0 = time.time()

    async with websockets.connect(args.url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "session.init",
                                  "payload": {"mode": args.mode, "use_tts": True}}))
        # 等服务端把管线建好
        first = await ws.recv()
        print(f"[{time.time()-t0:6.2f}s] << {first[:180]}")
        await asyncio.sleep(args.settle)

        async def reader():
            while True:
                raw = await ws.recv()
                dt = time.time() - t0
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                ty = ev.get("type", "?")
                kind = ev.get("kind", "-")
                if ty == "session.created":
                    stats["created"] += 1
                elif ty == "response.output.delta":
                    if kind == "listen":
                        stats["listen"] += 1
                    elif kind == "text":
                        stats["text"] += 1
                    elif kind == "audio":
                        stats["audio"] += 1
                    else:
                        stats["other"] += 1
                elif ty == "response.done":
                    stats["done"] += 1
                elif ty == "session.closed":
                    stats["closed"] += 1
                extra = ""
                if kind == "text":
                    extra = repr(ev.get("text", ""))[:60]
                elif kind == "audio":
                    extra = f"audio_b64_len={len(ev.get('audio') or '')}"
                elif ty == "response.done":
                    extra = repr(ev.get("text", ""))[:60]
                print(f"[{dt:6.2f}s] << {ty} kind={kind} {extra}")

        rt = asyncio.create_task(reader())
        for i in range(args.turns):
            pcm, sr = load_wav_f32(wavs[i % len(wavs)])
            img = jpgs[i % len(jpgs)].read_bytes()
            if args.mode == "full_duplex":
                body = {"audio": b64_f32(pcm),
                        "video_frames": [base64.b64encode(img).decode()]}
            else:
                body = {"messages": [{"role": "user", "content": [
                    {"type": "text", "text": f"第{i+1}轮"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," +
                                                        base64.b64encode(img).decode()}},
                    {"type": "audio", "audio": b64_f32(pcm)}]}],
                    "streaming": True, "use_tts_template": True}
            await ws.send(json.dumps({"type": "input.append", "input": body}))
            print(f"[{time.time()-t0:6.2f}s] >> turn {i+1} ({args.mode})")
            await asyncio.sleep(4.0)
        await asyncio.sleep(8)
        rt.cancel()
        try:
            await rt
        except asyncio.CancelledError:
            pass

    print("-" * 62)
    print("统计:", json.dumps(stats, ensure_ascii=False))
    ok = stats["text"] > 0 or stats["audio"] > 0 or stats["listen"] > 0
    print("RESULT:", "RECEIVED" if ok else "NOTHING_RECEIVED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
