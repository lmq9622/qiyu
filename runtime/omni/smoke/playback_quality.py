# -*- coding: utf-8 -*-
"""播放质量诊断：模型原始音频 vs 真实扬声器回环录音。

要回答的问题
------------
「听到的音节是碎的」到底是：
  A. 模型/TTS 输出本身就是碎的（上游问题），还是
  B. 我们的播放链路（分块写设备 / 抖动缓冲 / 采样率）把声音切碎了。

做法：同一段时间里
  1. 把 `response.output.delta kind=audio` 的 PCM 按到达顺序拼成模型原始音频（理想信号）；
  2. 同时用 AudioPlayer 真实播出去，用 LoopbackMonitor 录回来（实际听到的信号）；
  3. 对两个信号分别算 20ms RMS 包络、语音段、以及**语音段内部的静音缺口**，
     并画成 PNG 供人工比对。

指标里最关键的是 `gaps_in_speech`：语音段内部的短静音个数。
理想信号里这个数应该接近「模型自己的换气/停顿」，实际信号里如果显著更多，
就是播放链路（抖动缓冲不足 / 分块过大 / 设备欠载）切碎的。

用法：
    python -m runtime.omni.smoke.playback_quality --seconds 30 \
        --device "扬声器 (ToDesk Virtual Audio)"        # 虚拟设备，不吵人
    python -m runtime.omni.smoke.playback_quality --seconds 30   # 用系统默认扬声器

产出：
    runtime/omni/out/debug_model_raw.wav     模型原始（拼接后）
    runtime/omni/out/debug_loopback.wav      扬声器回环实录
    runtime/omni/out/playback_quality.png    两条包络对比图
    runtime/omni/out/playback_quality.json   指标
"""

from __future__ import annotations

import argparse
import array
import asyncio
import base64
import ctypes
import json
import struct
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import websockets  # noqa: E402

from runtime.omni.playback import build_monitor, build_player  # noqa: E402

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


def write_wav(path: Path, pcm: np.ndarray, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.clip(np.asarray(pcm, dtype=np.float32), -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((x * 32767.0).astype("<i2").tobytes())


def envelope(x: np.ndarray, sr: int, win_ms: float = 20.0) -> tuple:
    """返回 (时间轴, RMS 包络)。"""
    n = max(1, int(sr * win_ms / 1000.0))
    frames = len(x) // n
    if frames == 0:
        return np.zeros(0), np.zeros(0)
    y = x[:frames * n].reshape(frames, n)
    rms = np.sqrt((y * y).mean(axis=1))
    t = np.arange(frames) * (win_ms / 1000.0)
    return t, rms


def analyze(x: np.ndarray, sr: int, thr: float, label: str) -> dict:
    t, rms = envelope(x, sr)
    if len(rms) == 0:
        return {"label": label, "duration_s": 0.0, "frames": 0, "speech_s": 0.0,
                "speech_segments": 0, "gaps_in_speech": 0, "gap_ms_total": 0.0,
                "longest_gap_ms": 0.0, "rms_peak": 0.0, "rms_p95": 0.0}
    loud = rms > thr
    segments = []
    i = 0
    n = len(loud)
    while i < n:
        if loud[i]:
            j = i
            while j + 1 < n and loud[j + 1]:
                j += 1
            segments.append((i, j))
            i = j + 1
        else:
            i += 1
    # 语音段内部缺口：把间隔 < gap_join_ms 的两个语音段视为「同一句被切开」
    win_ms = 20.0
    gap_join_frames = int(2000.0 / win_ms)      # 2s 内的静音算「同一句内部被切」
    gaps = []
    for (a1, b1), (a2, b2) in zip(segments, segments[1:]):
        gap_frames = a2 - b1 - 1
        if 0 < gap_frames <= gap_join_frames:
            gaps.append((b1 + 1, a2 - 1, gap_frames * win_ms))
    speech_frames = sum(b - a + 1 for a, b in segments)
    return {
        "label": label,
        "duration_s": round(len(x) / sr, 3),
        "frames": int(len(rms)),
        "threshold": round(float(thr), 5),
        "speech_s": round(speech_frames * win_ms / 1000.0, 3),
        "speech_segments": len(segments),
        "gaps_in_speech": len(gaps),
        "gap_ms_total": round(sum(g[2] for g in gaps), 1),
        "longest_gap_ms": round(max([g[2] for g in gaps], default=0.0), 1),
        "rms_peak": round(float(rms.max()), 5),
        "rms_p95": round(float(np.percentile(rms, 95)), 5),
        "_t": t, "_rms": rms, "_thr": thr,
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:19080/backend")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--device", default="", help="留空=系统默认扬声器")
    ap.add_argument("--out-rate", type=int, default=24000)
    ap.add_argument("--pacing", type=float, default=0.5)
    ap.add_argument("--dump", action="store_true", default=True)
    args = ap.parse_args()

    ctypes.windll.ole32.CoInitializeEx(None, 0x2)
    wavs = sorted(DUP.glob("*.wav"))
    jpgs = sorted(DUP.glob("*.jpg"))
    prompts = [load_wav_f32(w) for w in wavs[:8]]

    player = build_player(device=args.device, samplerate=48000, channels=2,
                          blocksize=2400, allow_null=False)
    monitor = build_monitor(speaker_name=args.device, samplerate=48000,
                            blocksize=2400, allow_null=False, dump=True)
    print(f"[播放] {player.stats.device!r} backend={player.stats.backend} "
          f"blocksize={player.bs} prebuffer={player.prebuffer_ms}ms")
    print(f"[回环] {monitor.snapshot()}")

    raw_chunks = []
    counts = {"audio": 0, "text": 0, "listen": 0}
    send_lock = asyncio.Lock()
    stop_ambient = asyncio.Event()

    async with websockets.connect(args.url, max_size=None, ping_interval=None,
                                  open_timeout=120) as ws:
        async def send_input(pcm, sr, video=None):
            body = {"audio": b64_f32(pcm)}
            if video is not None:
                body["video_frames"] = [base64.b64encode(video).decode()]
            async with send_lock:
                await ws.send(json.dumps({"type": "input.append", "input": body}))

        await ws.send(json.dumps({"type": "session.init", "payload": {
            "mode": "full_duplex", "use_tts": True, "voice": {"ref_audio": ref_b64()}}}))
        print("[会话]", str(await asyncio.wait_for(ws.recv(), timeout=120))[:120])

        async def reader():
            while True:
                try:
                    raw = await ws.recv()
                except Exception:
                    return
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                if ev.get("type") != "response.output.delta":
                    continue
                k = ev.get("kind")
                if k in counts:
                    counts[k] += 1
                if k == "audio":
                    b64 = ev.get("audio") or ""
                    if b64:
                        pcm = np.frombuffer(base64.b64decode(b64), dtype="<f4")
                        raw_chunks.append(pcm.astype(np.float32, copy=True))
                        player.enqueue_pcm(pcm, src_rate=args.out_rate)

        async def ambient():
            ai = 0
            while not stop_ambient.is_set():
                pcm, sr = prompts[ai % len(prompts)]
                step = int(sr * 0.5)
                for ci in range(0, len(pcm), step):
                    if stop_ambient.is_set():
                        return
                    vid = jpgs[ai % len(jpgs)].read_bytes() if ci == 0 else None
                    try:
                        await send_input(pcm[ci:ci + step], sr, video=vid)
                    except Exception:
                        return
                    await asyncio.sleep(args.pacing)
                ai += 1

        rt = asyncio.create_task(reader())
        at = asyncio.create_task(ambient())
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < args.seconds:
            await asyncio.sleep(1.0)
            print(f"  [{time.perf_counter()-t0:5.1f}s] audio={counts['audio']} "
                  f"text={counts['text']} listen={counts['listen']} "
                  f"queued={player.queued_ms:.0f}ms "
                  f"underrun={player.stats.underrun_blocks} idle={player.stats.idle_silence_blocks}")
        stop_ambient.set()
        for t in (at, rt):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    await asyncio.sleep(0.5)
    raw = np.concatenate(raw_chunks) if raw_chunks else np.zeros(1, dtype=np.float32)
    loop, sr_loop = [], 48000
    try:
        loop = np.concatenate(list(monitor.used)) if monitor.used else np.zeros(1, np.float32)
    except Exception:
        loop = np.zeros(1, np.float32)
    player.close()
    monitor.close()

    if args.dump:
        write_wav(OUT / "debug_model_raw.wav", raw, args.out_rate)
        write_wav(OUT / "debug_loopback.wav", loop, sr_loop)

    a_raw = analyze(raw, args.out_rate, 0.01, "模型原始(拼接)")
    a_loop = analyze(loop, sr_loop, 0.01, "扬声器回环实录")

    # 画图
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2, 1, figsize=(14, 6), sharex=False)
        for ax, a in zip(axes, (a_raw, a_loop)):
            t, rms = a["_t"], a["_rms"]
            ax.plot(t, rms, lw=0.7)
            ax.axhline(a["threshold"], color="orange", ls="--", lw=0.8)
            ax.set_title(f'{a["label"]}  语音段={a["speech_segments"]}  '
                         f'段内缺口={a["gaps_in_speech"]}  缺口总时长={a["gap_ms_total"]}ms')
            ax.set_xlabel("秒")
            ax.set_ylabel("RMS")
        fig.tight_layout()
        fig.savefig(OUT / "playback_quality.png", dpi=110)
        print("图:", OUT / "playback_quality.png")
    except Exception as e:
        print("画图失败:", e)

    report = {"device": player.stats.device, "blocksize": player.bs,
              "prebuffer_ms": player.prebuffer_ms, "out_rate": args.out_rate,
              "player_stats": player.stats.to_dict(),
              "counts": counts,
              "raw": {k: v for k, v in a_raw.items() if not k.startswith("_")},
              "loopback": {k: v for k, v in a_loop.items() if not k.startswith("_")}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "playback_quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("报告:", OUT / "playback_quality.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
