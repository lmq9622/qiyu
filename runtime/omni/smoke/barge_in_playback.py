# -*- coding: utf-8 -*-
"""真实「播放侧」barge-in（真模型 + 真扬声器 + WASAPI 回环实测，无 Mock）。

与 `ws_barge_in.py` 的区别
--------------------------
`ws_barge_in.py` 只测到「打断控制路径」：VAD → force_listen → 服务端停止 →
新输入 → 新 TTFT/TTFA。它的 `playback_flush_ms` 恒为 0，是**模拟值**。

本脚本补上真正的播放侧：

    模型输出 audio delta
      → AudioPlayer 真实写进扬声器（soundcard/WASAPI）
      → LoopbackMonitor 对同一台扬声器回环采集，确认「确实在响」
      → 用户插话（真实 wav 按 32ms 帧实时过 RMS-VAD）
      → 打断：force_listen + flush 本地播放队列 + 取消 Avatar 说话动画
      → 回环实测「确实停了」（**可听见的**停止时刻）
      → 新输入继续同一 session，新回复再次被真实播放出来（确认恢复）

有效性判据（缺一不算有效样本，且全部留在报告里）：
  1. 插话素材里真的检出了语音（不是静音片段）；
  2. **打断那一刻扬声器确实在响**（回环在最近 250ms 内有能量）；
  3. 服务端给出 LISTEN 停止确认；
  4. 打断后回环实测到了静音；
  5. 同一 session 拿到新回复的音频（并且再次被听见）。

用法：
    python -m runtime.omni.smoke.barge_in_playback --target-valid 20 --max-iters 36
    python -m runtime.omni.smoke.barge_in_playback --target-valid 20 --dump-audio

报告：runtime/omni/out/barge_in_playback.json
"""

from __future__ import annotations

import argparse
import array
import asyncio
import base64
import ctypes
import json
import math
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import websockets  # noqa: E402

from runtime.omni.playback import (  # noqa: E402
    SRC_RATE_OUTPUT, build_monitor, build_player,
)

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
    ap.add_argument("--target-valid", type=int, default=20)
    ap.add_argument("--max-iters", type=int, default=36)
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--speak-timeout", type=float, default=25.0)
    ap.add_argument("--frame-ms", type=int, default=32)
    ap.add_argument("--vad-thr", type=float, default=0.02)
    ap.add_argument("--pacing", type=float, default=0.5)
    ap.add_argument("--stop-ack-timeout", type=float, default=6.0)
    ap.add_argument("--audio-device", default="", help="留空=系统默认扬声器")
    ap.add_argument("--out-rate", type=int, default=SRC_RATE_OUTPUT)
    ap.add_argument("--silence-hold-ms", type=float, default=60.0)
    ap.add_argument("--audible-window-ms", type=float, default=250.0,
                    help="打断前多久内有回环能量才算「正在响」")
    ap.add_argument("--max-pending-kb", type=float, default=256.0,
                    help="WS 发送缓冲超过该值就不再灌 ambient 音频（防背压污染打断延迟）")
    ap.add_argument("--dump-audio", action="store_true",
                    help="把前 3 次有效采样的回环录音存成 wav（人工可听证据）")
    args = ap.parse_args()

    ctypes.windll.ole32.CoInitializeEx(None, 0x2)   # 主线程 COM

    wavs = sorted(DUP.glob("*.wav"))
    jpgs = sorted(DUP.glob("*.jpg"))
    prompts = [load_wav_f32(w) for w in wavs[:8]]
    users = [load_wav_f32(w) for w in wavs[8:]]

    player = build_player(device=args.audio_device, samplerate=48000, channels=2,
                          blocksize=480, allow_null=True)
    monitor = build_monitor(speaker_name=args.audio_device, samplerate=48000,
                            blocksize=480, allow_null=True)
    print(f"[播放] backend={player.stats.backend} device={player.stats.device!r} "
          f"err={player.stats.error!r}")
    print(f"[回环] {monitor.snapshot()}")
    real_playback = player.stats.backend == "soundcard"
    real_loopback = monitor.backend == "soundcard-loopback"
    label = "REAL LOCAL" if (real_playback and real_loopback) else "SIMULATED"
    print(f"[标签] 播放侧 = {label}"
          + ("" if label == "REAL LOCAL" else "  ← 设备不可用，本次结果不能算播放侧实测"))

    from runtime.avatar import AvatarEvent, GenericAvatarController
    avatar = GenericAvatarController()
    avatar_events = {"cancel": 0, "speaking": 0}

    t0 = time.time()
    def rel() -> float:
        return round(time.time() - t0, 4)

    q: asyncio.Queue = asyncio.Queue()
    ambient_on = asyncio.Event()
    ambient_on.set()
    send_lock = asyncio.Lock()
    counts = {"listen": 0, "text": 0, "audio": 0, "done": 0, "sent": 0,
              "ambient_dropped": 0}
    accept_audio = {"on": False}
    dropped_after_flush = {"n": 0}
    send_timing = {"lock_wait_ms": 0.0, "ws_send_ms": 0.0, "pending_kb": 0.0}
    send_inflight = {"on": False}

    async with websockets.connect(args.url, max_size=None,
                                  ping_interval=None, open_timeout=60) as ws:
        def pending_kb() -> float:
            try:
                return len(ws.transport.get_write_buffer()) / 1024.0
            except Exception:
                try:
                    return ws.transport.get_write_buffer_size() / 1024.0
                except Exception:
                    return 0.0

        async def send_input(pcm, sr, force_listen=False, video=None):
            body: dict = {"audio": b64_f32(pcm)}
            if force_listen:
                body["force_listen"] = True
            if video is not None:
                body["video_frames"] = [base64.b64encode(video).decode()]
            ta = time.perf_counter()
            async with send_lock:
                tb = time.perf_counter()
                send_inflight["on"] = True
                await ws.send(json.dumps({"type": "input.append", "input": body}))
                tc = time.perf_counter()
                send_inflight["on"] = False
                counts["sent"] += 1
            send_timing["lock_wait_ms"] = round((tb - ta) * 1000.0, 1)
            send_timing["ws_send_ms"] = round((tc - tb) * 1000.0, 1)
            send_timing["pending_kb"] = round(pending_kb(), 1)

        await ws.send(json.dumps({"type": "session.init", "payload": {
            "mode": "full_duplex", "use_tts": True, "voice": {"ref_audio": ref_b64()}}}))
        first = await asyncio.wait_for(ws.recv(), timeout=120)
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
                    if k == "audio":
                        if accept_audio["on"]:
                            if real_playback:
                                player.enqueue_b64(ev.get("audio") or "",
                                                   src_rate=args.out_rate)
                            avatar_events["speaking"] += 1
                            try:
                                await avatar.emit_event(
                                    AvatarEvent(emotion="neutral", intensity=0.4,
                                                action="speak", speaking=True, mouth=0.5),
                                    avatar_type="json")
                            except Exception:
                                pass
                        else:
                            dropped_after_flush["n"] += 1
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
                    if pending_kb() > args.max_pending_kb:
                        counts["ambient_dropped"] += 1      # 服务端吃不下就丢，别堆在管道里
                        await asyncio.sleep(0.05)
                        continue
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
            n = int(sr * frame_ms / 1000)
            for i in range(0, len(pcm) - n + 1, n):
                seg = pcm[i:i + n]
                rms = math.sqrt(sum(v * v for v in seg) / n)
                if rms > thr:
                    return i / float(sr)
                await asyncio.sleep(frame_ms / 1000.0)
            return None

        await asyncio.sleep(0.5)
        floor = await asyncio.to_thread(monitor.noise_floor)
        thr_audio = max(0.004, floor * 6.0)
        print(f"[回环] 底噪={floor:.6f} 出声阈值={thr_audio:.6f}")

        accept_audio["on"] = True
        warm = await wait_kind({"audio", "text"}, args.speak_timeout)
        print(f"[预热] 模型开始输出 {'kind=' + warm[1] if warm else '未出话'}")
        if real_loopback:
            p0 = time.perf_counter()
            loud = await asyncio.to_thread(monitor.wait_above, thr_audio, 25.0, None)
            print(f"[预热] 扬声器确实出声: +{round((loud - p0), 3) if loud else '未检测到'} s")

        samples = []
        valid = 0
        it = 0
        while it < args.max_iters and valid < args.target_valid:
            it += 1
            accept_audio["on"] = True
            ambient_on.set()
            got = await wait_kind({"audio"}, args.speak_timeout)
            if got is None:
                samples.append({"iter": it, "skipped": "model_not_speaking"})
                print(f"[{rel():8.4f}] #{it} 跳过：模型未出声（有效 {valid}/{args.target_valid}）")
                continue
            p_audio_delta = time.perf_counter()
            if real_loopback:
                peak = await asyncio.to_thread(monitor.peak_rms, p_audio_delta - 2.0)
                thr_speak = max(thr_audio, peak * 0.15)
                loud_ts = await asyncio.to_thread(monitor.wait_above, thr_speak, 10.0,
                                                  p_audio_delta - 0.5)
                if loud_ts is None:
                    samples.append({"iter": it, "skipped": "not_audible"})
                    print(f"[{rel():8.4f}] #{it} 跳过：扬声器没有可听见输出"
                          f"（有效 {valid}/{args.target_valid}）")
                    continue

            # 用户插话：ambient 保持开启（真实场景是「Avatar 还在说，用户打断」），
            # 这样打断那一刻扬声器确实在响。
            upcm, usr = users[(it - 1) % len(users)]
            # 注意：这里**不**提前暂停 ambient —— 必须让打断发生在「Avatar 真的还在说」的时刻，
            # 否则播放在打断前就已经自然结束，测不到播放侧停止。
            t_play_p = time.perf_counter()
            onset = await feed_vad(upcm, usr, args.frame_ms, args.vad_thr)
            t_vad_p = time.perf_counter()
            vad_ms = round((t_vad_p - t_play_p) * 1000.0, 1)
            onset_ms = round((onset or 0.0) * 1000.0, 1)
            vad_proc_ms = round(vad_ms - onset_ms, 1)
            if onset is None:
                samples.append({"iter": it, "skipped": "no_local_speech",
                                "vad_detect_ms": vad_ms})
                print(f"[{rel():8.4f}] #{it} 跳过：插话素材没有检出语音"
                      f"（有效 {valid}/{args.target_valid}）")
                continue

            audible_peak = await asyncio.to_thread(
                monitor.peak_rms, t_vad_p - args.audible_window_ms / 1000.0)
            audible_at_interrupt = audible_peak >= max(thr_audio, 0.004)
            t_vad = time.time()
            ambient_on.clear()          # 用户开口 → 停止灌 ambient（插话后不再灌）

            await send_input(upcm, usr, force_listen=True)
            t_int = time.time()
            t_int_p = time.perf_counter()
            int_ms = round((t_int - t_vad) * 1000.0, 1)
            if int_ms > 300:
                print(f"    [诊断] 打断发送慢：lock_wait={send_timing['lock_wait_ms']}ms "
                      f"ws_send={send_timing['ws_send_ms']}ms "
                      f"pending={send_timing['pending_kb']}KB")

            t_flush1 = time.perf_counter()
            flush_ms = player.flush("barge_in") if real_playback else 0.0
            accept_audio["on"] = False

            t_av0 = time.perf_counter()
            try:
                await avatar.interrupt()
                await avatar.emit_event(
                    AvatarEvent(emotion="neutral", intensity=0.0, action="speech_cancel",
                                speaking=False, mouth=0.0, gesture=""),
                    avatar_type="json")
                avatar_events["cancel"] += 1
            except Exception:
                pass
            t_av1 = time.perf_counter()
            avatar_ms = round((t_av1 - t_av0) * 1000.0, 2)

            stop_acoustic_ms = None
            stop_from_onset_ms = None
            stop_after_flush_ms = None
            if real_loopback:
                peak2 = await asyncio.to_thread(monitor.peak_rms, p_audio_delta - 2.0)
                thr_sil = max(thr_audio, peak2 * 0.15)
                silent = await asyncio.to_thread(monitor.wait_below, thr_sil,
                                                 args.silence_hold_ms, 6.0, t_flush1)
                if silent is not None:
                    stop_acoustic_ms = round((silent - t_vad_p) * 1000.0, 1)
                    stop_from_onset_ms = round(
                        (silent - (t_play_p + (onset or 0.0))) * 1000.0, 1)
                    stop_after_flush_ms = round((silent - t_flush1) * 1000.0, 1)

            stop_ack = None
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
                if ev.get("kind") == "listen":
                    stop_ack = round((t - t_int) * 1000.0, 1)
                    break
            clean = stop_ack is not None

            await send_input(upcm, usr)
            t_new = time.time()
            t_new_p = time.perf_counter()
            new_ms = round((t_new - t_int) * 1000.0, 1)
            accept_audio["on"] = True

            ttft = ttfa = None
            resume_audible = None
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
                elif k == "audio" and ttfa is None:
                    ttfa = round((t - t_new) * 1000.0, 1)
                    if real_loopback:
                        peak3 = await asyncio.to_thread(monitor.peak_rms, t_new_p - 0.5)
                        thr_res = max(thr_audio, peak3 * 0.15)
                        back = await asyncio.to_thread(monitor.wait_above, thr_res, 10.0,
                                                       t_new_p)
                        if back is not None:
                            resume_audible = round((back - t_new_p) * 1000.0, 1)
                    break
            ambient_on.set()

            if not audible_at_interrupt:
                reason = "playback_not_active_at_interrupt"
            elif int_ms > 2000.0:
                reason = "interrupt_send_slow"
            elif not clean:
                reason = "no_stop_ack"
            elif ttfa is None:
                reason = "no_new_audio"
            elif real_loopback and stop_acoustic_ms is None:
                reason = "playback_stop_not_observed"
            else:
                reason = None
                valid += 1
            samples.append({
                "iter": it, "vad_detect_ms": vad_ms, "vad_clip_onset_ms": onset_ms,
                "vad_processing_ms": vad_proc_ms, "interrupt_send_ms": int_ms,
                "interrupt_queue_wait_ms": send_timing["lock_wait_ms"],
                "interrupt_ws_send_ms": send_timing["ws_send_ms"],
                "audio_flush_ms": round(flush_ms, 2),
                "playback_stop_ms": stop_acoustic_ms,
                "playback_stop_from_onset_ms": stop_from_onset_ms,
                "playback_stop_after_flush_ms": stop_after_flush_ms,
                "avatar_cancel_ms": avatar_ms,
                "avatar_cancel_from_vad_ms": round((t_av1 - t_vad_p) * 1000.0, 2),
                "stop_ack_ms": stop_ack, "clean_stop_ack": clean,
                "audible_at_interrupt": audible_at_interrupt,
                "audible_peak_before": round(audible_peak, 5),
                "skip_reason": reason, "new_input_ms": new_ms,
                "new_ttft_ms": ttft, "new_ttfa_ms": ttfa,
                "resume_audible_ms": resume_audible,
                "dropped_after_flush_total": dropped_after_flush["n"],
            })
            print(f"[{rel():8.4f}] #{it} vad={vad_ms}(onset={onset_ms}+proc={vad_proc_ms}) "
                  f"int={int_ms} flush={round(flush_ms,2)} "
                  f"stop_ac={stop_acoustic_ms} stop_flush={stop_after_flush_ms} "
                  f"avatar={avatar_ms} ack={stop_ack} clean={clean} "
                  f"audible={audible_at_interrupt} new_in={new_ms} "
                  f"TTFT={ttft} TTFA={ttfa} resume_aud={resume_audible} "
                  f"[有效 {valid}/{args.target_valid}]")

            if args.dump_audio and reason is None and valid <= 3:
                OUT.mkdir(parents=True, exist_ok=True)
                p = OUT / f"barge_in_playback_trial{valid}.wav"
                if monitor.dump_wav(p):
                    print(f"    回环录音: {p}")
                try:
                    monitor.used.clear()
                except Exception:
                    pass

        for t in (at, rt):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    player.close()
    monitor.close()

    ok = [s for s in samples
          if s.get("new_ttfa_ms") is not None and s.get("clean_stop_ack")
          and s.get("audible_at_interrupt")
          and (not real_loopback or s.get("playback_stop_ms") is not None)]
    keys = ["vad_detect_ms", "vad_clip_onset_ms", "vad_processing_ms",
            "interrupt_send_ms", "interrupt_queue_wait_ms", "interrupt_ws_send_ms",
            "audio_flush_ms", "playback_stop_ms",
            "playback_stop_from_onset_ms", "playback_stop_after_flush_ms",
            "avatar_cancel_ms", "avatar_cancel_from_vad_ms", "stop_ack_ms",
            "new_input_ms", "new_ttft_ms", "new_ttfa_ms", "resume_audible_ms"]
    summary = {
        "target_valid": args.target_valid, "max_iters": args.max_iters,
        "attempts": len(samples), "valid": len(ok),
        "playback_backend": player.stats.backend, "playback_device": player.stats.device,
        "loopback_backend": monitor.backend, "loopback_device": monitor.device,
        "loopback_error": monitor.error, "label": label,
        "skipped": {
            "model_not_speaking": len([s for s in samples
                                       if s.get("skipped") == "model_not_speaking"]),
            "not_audible": len([s for s in samples if s.get("skipped") == "not_audible"]),
            "no_local_speech": len([s for s in samples
                                    if s.get("skipped") == "no_local_speech"]),
            "playback_not_active_at_interrupt": len(
                [s for s in samples
                 if s.get("skip_reason") == "playback_not_active_at_interrupt"]),
            "no_stop_ack": len([s for s in samples
                                if s.get("skip_reason") == "no_stop_ack"]),
            "no_new_audio": len([s for s in samples
                                 if s.get("skip_reason") == "no_new_audio"]),
            "playback_stop_not_observed": len(
                [s for s in samples
                 if s.get("skip_reason") == "playback_stop_not_observed"]),
        },
        "counts": counts, "avatar_events": avatar_events,
        "dropped_after_flush": dropped_after_flush["n"],
        "player_stats": player.stats.to_dict(),
    }
    for k in keys:
        vals = [s.get(k) for s in ok]
        summary[k] = {"p50": pct(vals, 50), "p90": pct(vals, 90),
                      "p95": pct(vals, 95), "p99": pct(vals, 99)}
    print("=" * 70)
    print("BARGE_IN_PLAYBACK_SUMMARY:", json.dumps(summary, ensure_ascii=False))
    verdict = "PASS" if len(ok) >= args.target_valid else "FAIL"
    print(f"BARGE_IN_PLAYBACK = {verdict}  (有效 {len(ok)}/{args.target_valid}，"
          f"尝试 {len(samples)} 次，播放侧={label})")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "barge_in_playback.json").write_text(
        json.dumps({"summary": summary, "samples": samples},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT / "barge_in_playback.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
