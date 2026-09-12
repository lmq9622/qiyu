# -*- coding: utf-8 -*-
"""full_duplex 长稳测试（真模型 / WS /backend 直连 / 不经 Qiyu Pipeline / 不用 Mock）。

对应调试需求 §八（长稳）：
    持续 audio + 低频 video + 连续输出 + 随机 interruption，至少 30 分钟。
    监控：VRAM / RSS / GPU / CPU / 客户端队列堆积 / stale events / deadlock /
          stream disconnect / output freeze。

启动前显存闸门（需求 §九）：
    整卡专用显存已用超过 --gpu-limit-mb 就直接明确退出，
    不让「显存不够」表现成代码异常。

用法：
    python -m runtime.omni.smoke.ws_duplex_soak --minutes 30

长稳客户端的 keepalive 说明（第一轮 FAIL 的教训）：
    websockets 库默认 ping_interval=20 / ping_timeout=20；服务端在 full_duplex
    长时间解码时来不及回 pong，客户端就自己发 1011 关流，跑不满 30 分钟。
    默认改为 --ping-interval 0（关闭客户端 ping），并加了一个独立的 HTTP
    /health 探针，用来证明「是客户端 keepalive 误判，而不是服务端卡死」。
"""

from __future__ import annotations

import argparse
import array
import asyncio
import base64
import json
import random
import struct
import sys
import time
import urllib.request
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import websockets  # noqa: E402

from runtime.omni.smoke.vram_probe import read_gpu_dedicated_mb  # noqa: E402

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


def find_server_pid() -> int:
    try:
        import psutil
    except Exception:
        return 0
    for p in psutil.process_iter(["name"]):
        try:
            if (p.info.get("name") or "").lower().startswith("llama-omni-server"):
                return p.pid
        except Exception:
            continue
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:19080/backend")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--settle", type=float, default=2.5)
    ap.add_argument("--pacing", type=float, default=0.5, help="audio chunk 发送间隔")
    ap.add_argument("--video-every", type=int, default=8,
                    help="每 N 个 audio chunk 附一帧图（默认 8 -> 约 4s 一帧）")
    ap.add_argument("--interrupt-min", type=float, default=45.0)
    ap.add_argument("--interrupt-max", type=float, default=90.0)
    ap.add_argument("--sample-sec", type=float, default=15.0)
    ap.add_argument("--freeze-sec", type=float, default=90.0,
                    help="持续输入下超过该时长没有任何输出即判定 output freeze")
    ap.add_argument("--warmup-sec", type=float, default=60.0)
    ap.add_argument("--gpu-limit-mb", type=float, default=11600.0)
    # 客户端 keepalive：默认关闭。
    # websockets 库默认 ping_interval=20s / ping_timeout=20s，客户端会在服务端
    # 长时间忙于解码、来不及回 pong 时自己发 1011 主动关流，容易被误读成
    # 「模型不稳定」。这里默认关闭客户端 ping，改由 --health-url 独立 HTTP 探针
    # 加 output freeze 检测来证明服务端到底有没有真的卡死。
    ap.add_argument("--ping-interval", type=float, default=0.0,
                    help="客户端 keepalive ping 间隔秒；0=禁用（默认）")
    ap.add_argument("--ping-timeout", type=float, default=60.0,
                    help="客户端 pong 超时秒，仅 --ping-interval > 0 时生效")
    ap.add_argument("--health-url", default="http://127.0.0.1:19080/health",
                    help="独立 HTTP 探针，区分「服务端卡死」与「客户端 keepalive 误判」")
    ap.add_argument("--out-name", default="ws_duplex_soak.json",
                    help="runtime/omni/out 下的报告文件名")
    args = ap.parse_args()

    gpu0 = await asyncio.to_thread(read_gpu_dedicated_mb)
    pid = find_server_pid()
    print(f"[闸门] 整卡专用显存已用 {gpu0} MB / 上限 {args.gpu_limit_mb} MB；"
          f"llama-omni-server pid={pid}")
    if gpu0 > args.gpu_limit_mb:
        print(f"[闸门] 显存不足，明确退出（不启动长稳，避免把显存问题伪装成代码异常）")
        return 2

    import psutil
    proc = psutil.Process(pid) if pid else None
    if proc:
        proc.cpu_percent(None)

    wavs = sorted(DUP.glob("*.wav"))
    jpgs = sorted(DUP.glob("*.jpg"))
    chunks = [load_wav_f32(w) for w in wavs]
    users = [load_wav_f32(w) for w in wavs[8:]]
    t0 = time.time()

    def rel() -> float:
        return round(time.time() - t0, 3)

    counts = {"listen": 0, "text": 0, "audio": 0, "done": 0, "other": 0}
    sent = {"audio": 0, "video": 0, "interrupt": 0}
    state = {"last_output": None, "last_any": None, "max_queue": 0,
             "freezes": 0, "disconnected": False, "errors": [],
             "stale_events": 0, "done_ids": set(), "audio_bytes": 0,
             "health_ms": [], "health_fails": 0, "health_fail_times": []}
    samples: list = []
    queue: asyncio.Queue = asyncio.Queue()
    send_lock = asyncio.Lock()
    running = asyncio.Event()
    running.set()

    ping_kwargs = ({"ping_interval": None} if args.ping_interval <= 0 else
                   {"ping_interval": args.ping_interval,
                    "ping_timeout": args.ping_timeout})
    print(f"[配置] 客户端 keepalive: {ping_kwargs}；HTTP 健康探针: {args.health_url}")

    async with websockets.connect(args.url, max_size=None, open_timeout=60,
                                  close_timeout=10, **ping_kwargs) as ws:
        async def send_input(body: dict):
            async with send_lock:
                await ws.send(json.dumps({"type": "input.append", "input": body}))

        async def reader():
            try:
                while True:
                    raw = await ws.recv()
                    t = time.time()
                    try:
                        ev = json.loads(raw)
                    except Exception:
                        continue
                    ty = ev.get("type")
                    if ty == "response.output.delta":
                        k = ev.get("kind")
                        if k in counts:
                            counts[k] += 1
                        else:
                            counts["other"] += 1
                        if k == "audio":
                            state["audio_bytes"] += len(ev.get("audio") or "")
                        state["last_output"] = t
                        rid = ev.get("response_id")
                        if rid and rid in state["done_ids"]:
                            state["stale_events"] += 1
                    elif ty == "response.done":
                        counts["done"] += 1
                        rid = ev.get("response_id")
                        if rid:
                            state["done_ids"].add(rid)
                        state["last_output"] = t
                    state["last_any"] = t
                    try:
                        queue.put_nowait((t, ev))
                    except asyncio.QueueFull:
                        pass
            except asyncio.CancelledError:
                raise
            except Exception as e:  # 断流 / 协议错误
                state["disconnected"] = True
                state["errors"].append(f"reader: {type(e).__name__}: {e}")

        async def drainer():
            """消费队列，模拟上层消费者；队列深度用于观测 audio backlog。"""
            while True:
                await queue.get()
                state["max_queue"] = max(state["max_queue"], queue.qsize())

        async def sender():
            i = 0
            while running.is_set():
                pcm, sr = chunks[i % len(chunks)]
                step = int(sr * args.pacing)
                for ci in range(0, len(pcm), step):
                    if not running.is_set():
                        return
                    body: dict = {"audio": b64_f32(pcm[ci:ci + step])}
                    if i % args.video_every == 0 and ci == 0:
                        body["video_frames"] = [base64.b64encode(
                            jpgs[i % len(jpgs)].read_bytes()).decode()]
                        sent["video"] += 1
                    try:
                        await send_input(body)
                        sent["audio"] += 1
                    except Exception as e:
                        state["disconnected"] = True
                        state["errors"].append(f"sender: {type(e).__name__}: {e}")
                        return
                    await asyncio.sleep(args.pacing)
                i += 1

        async def interrupter():
            k = 0
            while running.is_set():
                await asyncio.sleep(random.uniform(args.interrupt_min, args.interrupt_max))
                if not running.is_set():
                    return
                pcm, sr = users[k % len(users)]
                try:
                    await send_input({"audio": b64_f32(pcm), "force_listen": True})
                    await asyncio.sleep(0.1)
                    await send_input({"audio": b64_f32(pcm)})
                    sent["interrupt"] += 1
                except Exception as e:
                    state["errors"].append(f"interrupter: {type(e).__name__}: {e}")
                    return
                k += 1

        def probe_health():
            """独立 HTTP 探针：服务端事件循环若被解码阻塞，这里会先暴露出来。"""
            t = time.time()
            try:
                with urllib.request.urlopen(args.health_url, timeout=10) as r:
                    r.read()
                return round((time.time() - t) * 1000, 1), True
            except Exception:
                return round((time.time() - t) * 1000, 1), False

        async def monitor():
            nonlocal gpu0
            while running.is_set():
                await asyncio.sleep(args.sample_sec)
                if not running.is_set():
                    return
                gpu = await asyncio.to_thread(read_gpu_dedicated_mb)
                hms, hok = await asyncio.to_thread(probe_health)
                state["health_ms"].append(hms)
                if not hok:
                    state["health_fails"] += 1
                    state["health_fail_times"].append(rel())
                rss = cpu = 0.0
                alive = True
                if proc:
                    try:
                        rss = round(proc.memory_info().rss / 1048576.0, 1)
                        cpu = round(proc.cpu_percent(None), 1)
                    except Exception:
                        alive = False
                pgpu = 0.0
                try:
                    from runtime.omni.smoke.vram_probe import read_proc_gpu_mb
                    pgpu = await asyncio.to_thread(read_proc_gpu_mb, pid)
                except Exception:
                    pass
                idle = (time.time() - state["last_output"]) if state["last_output"] else None
                if (idle is not None and idle > args.freeze_sec
                        and rel() > args.warmup_sec):
                    state["freezes"] += 1
                    state["last_output"] = time.time()  # 避免同一段冻结被重复计数
                rec = {"t": rel(), "gpu_mb": gpu, "proc_gpu_mb": pgpu, "rss_mb": rss,
                       "cpu_pct": cpu, "alive": alive, "queue": queue.qsize(),
                       "health_ms": hms, "health_ok": hok,
                       "sent_audio": sent["audio"], "video": sent["video"],
                       "interrupts": sent["interrupt"], "listen": counts["listen"],
                       "text": counts["text"], "audio": counts["audio"],
                       "done": counts["done"], "idle_out_sec": round(idle, 1) if idle else None}
                samples.append(rec)
                print(f"[{rec['t']:8.1f}s] gpu={gpu:.0f}MB proc={pgpu:.0f}MB "
                      f"rss={rss:.0f}MB cpu={cpu:.1f}% q={rec['queue']} "
                      f"health={hms:.0f}ms{'' if hok else '!!'} "
                      f"sent={sent['audio']} vid={sent['video']} int={sent['interrupt']} "
                      f"| out: L{counts['listen']} T{counts['text']} A{counts['audio']} "
                      f"D{counts['done']} idle={rec['idle_out_sec']}")

        await ws.send(json.dumps({"type": "session.init", "payload": {
            "mode": "full_duplex", "use_tts": True, "voice": {"ref_audio": ref_b64()}}}))
        first = await asyncio.wait_for(ws.recv(), timeout=90)
        print(f"[{rel():8.3f}s] << {str(first)[:160]}")
        await asyncio.sleep(args.settle)

        tasks = [asyncio.create_task(x()) for x in (reader, drainer, sender, interrupter, monitor)]
        deadline = time.time() + args.minutes * 60
        try:
            while time.time() < deadline and not state["disconnected"]:
                await asyncio.sleep(1.0)
        finally:
            running.clear()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    dur = rel()
    def mean_tail(key, n=3):
        vals = [s[key] for s in samples[-n:] if s.get(key)]
        return round(sum(vals) / len(vals), 1) if vals else None
    def mean_head(key, n=3):
        vals = [s[key] for s in samples[:n] if s.get(key)]
        return round(sum(vals) / len(vals), 1) if vals else None

    gpu_peak = max([s["gpu_mb"] for s in samples], default=gpu0)
    pgpu_peak = max([s["proc_gpu_mb"] for s in samples], default=0.0)
    rss_peak = max([s["rss_mb"] for s in samples], default=0.0)
    rss_head, rss_tail = mean_head("rss_mb"), mean_tail("rss_mb")
    gpu_head, gpu_tail = mean_head("gpu_mb"), mean_tail("gpu_mb")
    rss_growth = round((rss_tail or 0) - (rss_head or 0), 1)
    gpu_growth = round((gpu_tail or 0) - (gpu_head or 0), 1)

    def pct(vals, q):
        if not vals:
            return None
        s = sorted(vals)
        k = min(len(s) - 1, max(0, int(round(q / 100.0 * (len(s) - 1)))))
        return s[k]

    hvals = state["health_ms"]

    summary = {
        "duration_sec": dur, "requested_min": args.minutes,
        "completed": dur >= args.minutes * 60 * 0.95,
        "client_ping_interval": args.ping_interval,
        "client_ping_timeout": args.ping_timeout,
        "health_url": args.health_url,
        "health_probes": len(hvals),
        "health_fails": state["health_fails"],
        "health_fail_times": state["health_fail_times"][:10],
        "health_p50_ms": pct(hvals, 50), "health_p95_ms": pct(hvals, 95),
        "health_max_ms": pct(hvals, 100),
        "gpu_start_mb": gpu0, "gpu_peak_mb": gpu_peak, "gpu_end_mb": mean_tail("gpu_mb"),
        "proc_gpu_peak_mb": pgpu_peak, "rss_peak_mb": rss_peak,
        "rss_head_mb": rss_head, "rss_tail_mb": rss_tail, "rss_growth_mb": rss_growth,
        "gpu_growth_mb": gpu_growth,
        "max_client_queue": state["max_queue"],
        "stale_events": state["stale_events"],
        "freezes": state["freezes"], "disconnected": state["disconnected"],
        "errors": state["errors"][:10],
        "sent": sent, "received": counts,
        "audio_mb_received": round(state["audio_bytes"] * 0.75 / 1048576.0, 2),
        "samples": len(samples),
    }
    print("=" * 70)
    print("SOAK_SUMMARY:", json.dumps(summary, ensure_ascii=False))
    verdict = "PASS"
    reasons = []
    if not summary["completed"]:
        verdict = "FAIL"; reasons.append("未跑满时长")
    if state["disconnected"]:
        verdict = "FAIL"; reasons.append("断流")
    if state["freezes"] > 0:
        verdict = "FAIL"; reasons.append("output freeze")
    if rss_growth > 500:
        verdict = "FAIL"; reasons.append(f"RSS 增长 {rss_growth} MB")
    if gpu_peak > 11900:
        verdict = "FAIL"; reasons.append("显存触顶")
    if counts["audio"] == 0 and counts["text"] == 0:
        verdict = "FAIL"; reasons.append("全程无输出")
    if counts["other"] > 0:
        reasons.append(f"未知事件类型 {counts['other']} 个（记录，不判 FAIL）")
    if state["health_fails"] >= 3:
        verdict = "FAIL"; reasons.append(
            f"HTTP 健康探针连续失败 {state['health_fails']} 次（服务端可能真的卡死）")
    print(f"LONG_STABILITY = {verdict}" + (f"  ({'; '.join(reasons)})" if reasons else ""))

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / args.out_name).write_text(
        json.dumps({"summary": summary, "samples": samples}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print("报告:", OUT / args.out_name)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
