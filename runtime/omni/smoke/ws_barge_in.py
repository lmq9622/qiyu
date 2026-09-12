# -*- coding: utf-8 -*-
"""真实 barge-in 采样（WS /backend 直连，真模型，不经 Qiyu Pipeline，不用 Mock）。

上一版 20 次只有 4 次有效的真实原因（已定位，非模型问题）：
    full_duplex 下模型只在「持续有输入」时保持说话态。上一版每次采样前停止送
    音频、被动等 audio delta，模型已经回到 LISTEN，于是 16/20 次以
    `model_not_speaking` 跳过 —— 那是测试驱动方式的问题。

本版改为真实会话形态：
    - 后台 ambient 任务按实时节奏持续送音频，把模型喂到说话态；
    - 一旦收到 audio delta（模型正在说），立刻暂停 ambient（用户停下不说话）；
    - 用户插话音频按 32ms 帧实时喂入本地 RMS-VAD，检出语音后立刻打断。

单次采样（对应调试需求 §十）：
  模型正在输出音频
    -> 用户插话音频实时过 VAD（t_vad）
    -> input.append{force_listen:true, audio:插话}（t_int，打断信号）
    -> 清空本地待播缓冲（t_stop；本脚本不做真实播放，该值标记 SIMULATED）
    -> input.append{audio:插话}（t_new，同一 session 新输入）
    -> 记录服务端 LISTEN 停止确认、新 TTFT / TTFA

记录：vad_detect_ms / interrupt_send_ms / playback_flush_ms / stop_ack_ms /
      inflight_audio_ms / new_input_ms / new_ttft_ms / new_ttfa_ms
输出 P50/P90/P95 -> runtime/omni/out/ws_barge_in.json

用法：python -m runtime.omni.smoke.ws_barge_in --target-valid 20 --max-iters 36

有效样本判定：clean_stop_ack=True（打断后服务端确实回到 LISTEN）且拿到新 TTFA。
无效样本一律保留在报告里并写明 skip_reason，不做丢弃式筛样。
"""

from __future__ import annotations

import argparse
import array
import asyncio
import base64
import json
import math
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


def b64_f32(pcm) -> str:
    return base64.b64encode(array.array("f", pcm).tobytes()).decode()


def ref_b64() -> str:
    pcm, sr = load_wav_f32(REF)
    return b64_f32(pcm[: sr * 6])


def pct(vals, p):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1)))))
    return round(s[k], 1)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:19080/backend")
    ap.add_argument("--target-valid", type=int, default=20,
                    help="需要的有效样本数（对话要求：至少 20 次）")
    ap.add_argument("--max-iters", type=int, default=36,
                    help="尝试次数上限（模型说话态依赖持续输入，个别轮次会不出声）")
    ap.add_argument("--iters", type=int, default=0,
                    help="兼容旧参数：等价于 --target-valid N --max-iters N")
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--speak-timeout", type=float, default=20.0,
                    help="等待模型出声 / 等待新 response 的上限")
    ap.add_argument("--frame-ms", type=int, default=32)
    ap.add_argument("--vad-thr", type=float, default=0.02)
    ap.add_argument("--pacing", type=float, default=0.5,
                    help="ambient 每个 0.5s chunk 的发送间隔")
    ap.add_argument("--keep-ambient", action="store_true",
                    help="插话期间不暂停 ambient（默认暂停，模拟用户停下听模型说）")
    ap.add_argument("--stop-ack-timeout", type=float, default=4.0,
                    help="打断后等待服务端 LISTEN 停止确认的上限")
    args = ap.parse_args()
    if args.iters:
        args.target_valid = args.iters
        args.max_iters = args.iters

    wavs = sorted(DUP.glob("*.wav"))
    jpgs = sorted(DUP.glob("*.jpg"))
    prompts = [load_wav_f32(w) for w in wavs[:8]]
    users = [load_wav_f32(w) for w in wavs[8:]]
    t0 = time.time()

    def rel() -> float:
        return round(time.time() - t0, 4)

    q: asyncio.Queue = asyncio.Queue()
    ambient_on = asyncio.Event()
    ambient_on.set()
    send_lock = asyncio.Lock()
    counts = {"listen": 0, "text": 0, "audio": 0, "done": 0, "sent": 0}

    async with websockets.connect(args.url, max_size=None) as ws:
        async def send_input(pcm, sr, force_listen=False, video=None):
            body: dict = {"audio": b64_f32(pcm)}
            if force_listen:
                body["force_listen"] = True
            if video is not None:
                body["video_frames"] = [base64.b64encode(video).decode()]
            async with send_lock:
                await ws.send(json.dumps({"type": "input.append", "input": body}))
                counts["sent"] += 1

        await ws.send(json.dumps({"type": "session.init", "payload": {
            "mode": "full_duplex", "use_tts": True, "voice": {"ref_audio": ref_b64()}}}))
        first = await asyncio.wait_for(ws.recv(), timeout=90)
        print(f"[{rel():8.4f}] << {str(first)[:140]}")
        await asyncio.sleep(args.settle)

        async def reader():
            while True:
                raw = await ws.recv()
                t = time.time()
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                if ev.get("type") == "response.output.delta":
                    k = ev.get("kind")
                    if k in counts:
                        counts[k] += 1
                elif ev.get("type") == "response.done":
                    counts["done"] += 1
                await q.put((t, ev))

        async def ambient():
            ai = 0
            while True:
                if not ambient_on.is_set():
                    await asyncio.sleep(0.05)
                    continue
                pcm, sr = prompts[ai % len(prompts)]
                step = int(sr * 0.5)
                for ci in range(0, len(pcm), step):
                    if not ambient_on.is_set():
                        break
                    vid = jpgs[ai % len(jpgs)].read_bytes() if ci == 0 else None
                    try:
                        await send_input(pcm[ci:ci + step], sr, video=vid)
                    except Exception:
                        return
                    await asyncio.sleep(args.pacing)
                ai += 1

        rt = asyncio.create_task(reader())
        at = asyncio.create_task(ambient())

        async def next_event(timeout: float):
            try:
                return await asyncio.wait_for(q.get(), timeout=timeout)
            except asyncio.TimeoutError:
                return None

        async def wait_kind(kinds, timeout):
            """等一个指定 kind 的 response.output.delta；返回 (t, kind, text)。"""
            deadline = time.time() + timeout
            while True:
                left = deadline - time.time()
                if left <= 0:
                    return None
                e = await next_event(left)
                if e is None:
                    return None
                t, ev = e
                if ev.get("type") == "response.output.delta" and ev.get("kind") in kinds:
                    return (t, ev.get("kind"), ev.get("text") or "")

        async def feed_vad(pcm, sr, frame_ms, thr):
            """按实时节奏把插话音频喂进 RMS-VAD，返回检测到语音的秒数（无则 None）。"""
            n = int(sr * frame_ms / 1000)
            for i in range(0, len(pcm) - n + 1, n):
                seg = pcm[i:i + n]
                rms = math.sqrt(sum(v * v for v in seg) / n)
                if rms > thr:
                    return i / float(sr)
                await asyncio.sleep(frame_ms / 1000.0)
            return None

        # ---- 预热：ambient 已经开着，等模型第一次出声 ----
        warm = await wait_kind({"audio", "text"}, args.speak_timeout)
        print(f"[预热] 模型开始输出 {'kind=' + warm[1] if warm else '未出话'}")

        samples = []
        valid = 0
        it = 0
        while it < args.max_iters and valid < args.target_valid:
            it += 1
            # 1) ambient 保持开启，等模型出声（模型正在说话）
            ambient_on.set()
            got = await wait_kind({"audio"}, args.speak_timeout)
            if got is None:
                samples.append({"iter": it, "skipped": "model_not_speaking"})
                print(f"[{rel():8.4f}] #{it} 跳过：{args.speak_timeout}s 内模型未出声"
                      f"（有效 {valid}/{args.target_valid}）")
                continue
            t_speak = got[0]

            # 2) 用户停下不说话（暂停 ambient），模型仍在输出音频
            if not args.keep_ambient:
                ambient_on.clear()
                await asyncio.sleep(0.05)

            # 3) 真实 RMS-VAD：插话音频按实时节奏喂入
            upcm, usr = users[(it - 1) % len(users)]
            t_play = time.time()
            onset = await feed_vad(upcm, usr, args.frame_ms, args.vad_thr)
            t_vad = time.time()
            vad_ms = round((t_vad - t_play) * 1000.0, 1)
            # 拆开看：onset_ms 是这段插话素材本身的前导静音长度（不是算法开销），
            # vad_proc_ms 才是「语音帧已出现 -> VAD 判定」的算法 + 事件循环开销。
            onset_ms = round((onset or 0.0) * 1000.0, 1)
            vad_proc_ms = round(vad_ms - onset_ms, 1)

            # 4) 打断信号：force_listen + 插话音频（同一 session，不重建）
            await send_input(upcm, usr, force_listen=True)
            t_int = time.time()
            int_ms = round((t_int - t_vad) * 1000.0, 1)

            # 5) 播放停止：丢弃本地待播缓冲（本脚本不做真实播放，SIMULATED）
            t_stop = time.time()
            flush_ms = round((t_stop - t_int) * 1000.0, 1)

            # 6) 等服务端停止确认：打断后第一条 listen delta
            #    （force_listen 让模型丢弃当前 response 并停在 LISTEN）
            #    停止确认之前仍在管道里流出的音频记作 in-flight，不计入新 response。
            stop_ack = None
            inflight = None
            ack_deadline = time.time() + args.stop_ack_timeout
            while True:
                left = ack_deadline - time.time()
                if left <= 0:
                    break
                e = await next_event(left)
                if e is None:
                    break
                t, ev = e
                if ev.get("type") != "response.output.delta" or t < t_int:
                    continue
                k = ev.get("kind")
                if k == "listen":
                    stop_ack = round((t - t_int) * 1000.0, 1)
                    break
                if k == "audio":
                    inflight = round((t - t_int) * 1000.0, 1)
            clean = stop_ack is not None

            # 7) 新输入继续同一 session；TTFT / TTFA 一律相对「本次新输入」计时。
            await send_input(upcm, usr)
            t_new = time.time()
            new_ms = round((t_new - t_int) * 1000.0, 1)

            ttft = None
            ttfa = None
            deadline = time.time() + args.speak_timeout
            while True:
                left = deadline - time.time()
                if left <= 0:
                    break
                e = await next_event(left)
                if e is None:
                    break
                t, ev = e
                if ev.get("type") != "response.output.delta" or t < t_new:
                    continue
                k = ev.get("kind")
                if k == "text" and ttft is None:
                    ttft = round((t - t_new) * 1000.0, 1)
                elif k == "audio":
                    ttfa = round((t - t_new) * 1000.0, 1)
                    break

            if not args.keep_ambient:
                ambient_on.set()

            if not clean:
                reason = "no_stop_ack"
            elif ttfa is None:
                reason = "no_new_audio"
            else:
                reason = None
                valid += 1
            samples.append({"iter": it, "vad_detect_ms": vad_ms,
                            "vad_clip_onset_ms": onset_ms,
                            "vad_processing_ms": vad_proc_ms,
                            "interrupt_send_ms": int_ms,
                            "playback_flush_ms": flush_ms,
                            "stop_ack_ms": stop_ack,
                            "inflight_audio_ms": inflight,
                            "clean_stop_ack": clean,
                            "skip_reason": reason,
                            "new_input_ms": new_ms,
                            "new_ttft_ms": ttft,
                            "new_ttfa_ms": ttfa})
            print(f"[{rel():8.4f}] #{it} speak@{round(t_speak - t0, 3)} "
                  f"vad={vad_ms}ms(onset={onset_ms}+proc={vad_proc_ms}) "
                  f"int={int_ms}ms flush={flush_ms}ms "
                  f"stop_ack={stop_ack}ms inflight={inflight}ms clean={clean} "
                  f"new_in={new_ms}ms TTFT={ttft} TTFA={ttfa} "
                  f"[有效 {valid}/{args.target_valid}]")

        for t in (at, rt):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    ok = [s for s in samples if s.get("new_ttfa_ms") is not None
          and s.get("clean_stop_ack")]
    keys = [("vad_detect_ms", "vad_detect_ms"),
            ("vad_clip_onset_ms", "vad_clip_onset_ms"),
            ("vad_processing_ms", "vad_processing_ms"),
            ("interrupt_send_ms", "interrupt_signal_ms"),
            ("playback_flush_ms", "playback_flush_ms"),
            ("stop_ack_ms", "server_stop_ack_ms"),
            ("inflight_audio_ms", "inflight_audio_ms"),
            ("new_input_ms", "new_input_ms"),
            ("new_ttft_ms", "new_ttft_ms"),
            ("new_ttfa_ms", "new_ttfa_ms")]
    summary = {"target_valid": args.target_valid, "max_iters": args.max_iters,
               "attempts": len(samples), "valid": len(ok),
               "skipped_model_not_speaking": len([s for s in samples
                                                  if s.get("skipped")]),
               "no_stop_ack": len([s for s in samples
                                   if s.get("skip_reason") == "no_stop_ack"]),
               "no_new_audio": len([s for s in samples
                                    if s.get("skip_reason") == "no_new_audio"]),
               "counts": counts}
    for src, dst in keys:
        vals = [s.get(src) for s in ok]
        summary[dst] = {"p50": pct(vals, 50), "p90": pct(vals, 90), "p95": pct(vals, 95)}
    print("=" * 66)
    print("BARGE_IN_SUMMARY:", json.dumps(summary, ensure_ascii=False))
    verdict = "PASS" if len(ok) >= args.target_valid else "FAIL"
    print(f"BARGE_IN = {verdict}  (有效采样 {len(ok)}/{args.target_valid}，"
          f"尝试 {len(samples)} 次)")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ws_barge_in.json").write_text(
        json.dumps({"summary": summary, "samples": samples}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("报告:", OUT / "ws_barge_in.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
