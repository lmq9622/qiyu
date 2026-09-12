# -*- coding: utf-8 -*-
"""真实 full_duplex 时间重叠验证（WS /backend 直连，不经 Qiyu Pipeline，不用 Mock）。

对应调试需求 §九：输入持续进行时，A 输出尚未结束，B 已经继续进入 pipeline。

流程：
  1. session.init(full_duplex) → 等服务端建好双工管线；
  2. 以 real-time 节奏连续送音频 A（每 0.5s 一个 chunk，持续不停）；
  3. 收到 **第一个输出增量**（listen/text/audio）时记录 t_A_out_start；
  4. 不等待 A 结束，立刻把后续输入切到音频 B，继续按同一节奏送；
  5. 记录 A/B 输入起点、输出起点、最后一个输出增量的时间；
  6. 计算 overlap = t_last_output - t_B_in_start。

判定：t_B_in_start < t_last_output 且 B 输入之后仍收到输出 → FULL_DUPLEX = PASS。

用法：
  python -m runtime.omni.smoke.ws_duplex_overlap
  python -m runtime.omni.smoke.ws_duplex_overlap --a-wavs 6 --b-wavs 8 --pacing 0.5
"""

from __future__ import annotations

import argparse
import array
import asyncio
import base64
import json
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import websockets  # noqa: E402

DUP = Path(r"D:\qiyu-omni-build\src\llama.cpp-omni-master\tools\omni\assets"
           r"\test_case\duplex_omni_test_case")
REF = Path(r"D:\qiyu-omni-build\src\llama.cpp-omni-master\tools\omni\assets"
           r"\default_ref_audio\default_ref_audio.wav")
OUT = Path("runtime/omni/out")


def load_wav_f32(path: Path):
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


def load_ref_b64() -> str:
    pcm, sr = load_wav_f32(REF)
    max_n = sr * 6
    return b64_f32(pcm[:max_n])


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:19080/backend")
    ap.add_argument("--a-wavs", type=int, default=8, help="A 阶段音频 wav 个数（约 1s/个）")
    ap.add_argument("--b-wavs", type=int, default=8, help="B 阶段音频 wav 个数")
    ap.add_argument("--pacing", type=float, default=0.5, help="每个 chunk 的发送间隔（秒）")
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--tail", type=float, default=14.0, help="喂完后继续收尾时长")
    ap.add_argument("--switch-on", default="any", choices=["any", "audio"],
                    help="切到 B 的触发点：any=任意输出增量；audio=首条音频增量（A 音频仍在流）")
    args = ap.parse_args()

    wavs = sorted(DUP.glob("*.wav"))
    jpgs = sorted(DUP.glob("*.jpg"))
    t0 = time.time()

    def rel() -> float:
        return round(time.time() - t0, 3)

    tl: dict = {"sends": [], "events": [], "A_in_start": None, "B_in_start": None,
                "A_out_start": None, "A_audio_start": None, "A_audio_last": None,
                "B_out_start": None, "last_out": None,
                "audio_deltas": 0, "text_deltas": 0, "listen_deltas": 0, "done": 0}
    out_started = asyncio.Event()
    audio_started = asyncio.Event()

    async with websockets.connect(args.url, max_size=None) as ws:
        await ws.send(json.dumps({"type": "session.init", "payload": {
            "mode": "full_duplex", "use_tts": True,
            "voice": {"ref_audio": load_ref_b64()}}}))
        first = await asyncio.wait_for(ws.recv(), timeout=90)
        print(f"[{rel():7.3f}s] << {str(first)[:160]}")
        await asyncio.sleep(args.settle)

        async def reader():
            while True:
                raw = await ws.recv()
                t = rel()
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                ty = ev.get("type", "?")
                kind = ev.get("kind", "-")
                rec = {"t": t, "type": ty, "kind": kind}
                if ty == "response.output.delta":
                    rec["text"] = (ev.get("text") or "")[:40]
                    rec["audio_len"] = len(ev.get("audio") or "")
                    if kind == "listen":
                        tl["listen_deltas"] += 1
                    elif kind == "text":
                        tl["text_deltas"] += 1
                    elif kind == "audio":
                        tl["audio_deltas"] += 1
                    if tl["A_out_start"] is None:
                        tl["A_out_start"] = t
                        out_started.set()
                    if kind == "audio":
                        if tl["A_audio_start"] is None:
                            tl["A_audio_start"] = t
                            audio_started.set()
                        tl["A_audio_last"] = t
                    if (tl["B_in_start"] is not None and tl["B_out_start"] is None
                            and t >= tl["B_in_start"]):
                        tl["B_out_start"] = t
                    tl["last_out"] = t
                elif ty == "response.done":
                    tl["done"] += 1
                elif ty == "session.closed":
                    pass
                tl["events"].append(rec)
                extra = ""
                if kind == "text":
                    extra = repr(rec.get("text", ""))
                elif kind == "audio":
                    extra = f"audio_b64={rec.get('audio_len')}"
                print(f"[{t:7.3f}s] << {ty} kind={kind} {extra}")

        rt = asyncio.create_task(reader())

        # ---- 连续送 A，首个输出到达后切换为 B（不停止输入）----
        def chunks_for(wav_idx: int):
            pcm, sr = load_wav_f32(wavs[wav_idx % len(wavs)])
            n = int(sr * 0.5)
            return [pcm[i:i + n] for i in range(0, len(pcm), n)]

        tl["A_in_start"] = rel()
        phase = "A"
        phase_idx = 0
        trigger = audio_started if args.switch_on == "audio" else out_started
        while phase in ("A", "B"):
            limit = args.a_wavs if phase == "A" else args.b_wavs
            if phase_idx >= limit:
                break
            for ci, ch in enumerate(chunks_for(phase_idx)):
                body: dict = {"audio": b64_f32(ch)}
                if ci == 0:
                    body["video_frames"] = [base64.b64encode(
                        jpgs[phase_idx % len(jpgs)].read_bytes()).decode()]
                await ws.send(json.dumps({"type": "input.append", "input": body}))
                tl["sends"].append({"t": rel(), "phase": phase, "wav": phase_idx, "ci": ci})
                await asyncio.sleep(args.pacing)
                # A 阶段：一旦模型已开始输出，立刻切 B（输入不中断）
                if phase == "A" and trigger.is_set():
                    tl["B_in_start"] = rel()
                    phase = "B"
                    phase_idx = 0
                    print(f"[{tl['B_in_start']:7.3f}s] >> 触发({args.switch_on})已到，"
                          f"切换 B 输入（不断流）")
                    break
            else:
                phase_idx += 1
                continue
            if phase == "A":
                break

        print(f"[{rel():7.3f}s] 输入结束，收尾 {args.tail}s")
        await asyncio.sleep(args.tail)
        rt.cancel()
        try:
            await rt
        except asyncio.CancelledError:
            pass

    sends = tl["sends"]
    after_start = [s for s in sends if tl["A_out_start"] is not None
                   and s["t"] >= tl["A_out_start"]]
    after_b = [s for s in sends if tl["B_in_start"] is not None
               and s["t"] >= tl["B_in_start"]]
    overlap = None
    if tl["B_in_start"] is not None and tl["last_out"] is not None:
        overlap = round(tl["last_out"] - tl["B_in_start"], 3)

    summary = {
        "A_in_start": tl["A_in_start"], "A_out_start": tl["A_out_start"],
        "A_audio_start": tl["A_audio_start"], "A_audio_last": tl["A_audio_last"],
        "B_in_start": tl["B_in_start"], "B_out_start": tl["B_out_start"],
        "last_out": tl["last_out"], "overlap_sec": overlap,
        "sends_total": len(sends), "sends_after_A_out": len(after_start),
        "sends_after_B_in": len(after_b),
        "listen": tl["listen_deltas"], "text": tl["text_deltas"],
        "audio": tl["audio_deltas"], "done": tl["done"],
    }
    print("=" * 62)
    print("SUMMARY:", json.dumps(summary, ensure_ascii=False))
    verdict = "FAIL"
    if (tl["A_out_start"] is not None and tl["B_in_start"] is not None
            and tl["B_out_start"] is not None and overlap is not None and overlap > 0
            and len(after_b) > 0):
        verdict = "PASS"
    # 严格版：要求 B 输入发生在 A 音频仍在流式输出期间（barge-in 场景）
    if args.switch_on == "audio":
        strict = (tl["A_audio_start"] is not None and tl["B_in_start"] is not None
                  and tl["B_out_start"] is not None and tl["A_audio_last"] is not None
                  and tl["B_out_start"] <= tl["A_audio_last"])
        print(f"STRICT(A 音频流未结束即收到 B 输出) = {'PASS' if strict else 'FAIL'}"
              f"  B_out_start={tl['B_out_start']}  A_audio_last={tl['A_audio_last']}")
        if not strict:
            verdict = "FAIL"
    print(f"FULL_DUPLEX_OVERLAP = {verdict}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ws_duplex_overlap.json").write_text(
        json.dumps({"summary": summary, "timeline": tl}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("报告:", OUT / "ws_duplex_overlap.json")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
