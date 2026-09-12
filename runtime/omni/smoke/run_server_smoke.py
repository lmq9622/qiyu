# -*- coding: utf-8 -*-
"""llama-omni-server HTTP 会话链路 smoke（真模型）。

链路：``omni_init`` → ``prefill`` → ``decode``(SSE) → 可选 ``break``

这正是 ``MiniCPMOBackend`` 需要对接的真实 API：

| 端点 | 作用 | 对应 OmniSession 动作 |
|---|---|---|
| `POST /v1/stream/omni_init` | 建会话、加载 LLM/VPM/APM/TTS/T2W | `start_session()` |
| `POST /v1/stream/prefill` | 喂一轮输入（音频/图像按**文件路径前缀**） | `send_audio_chunk()` / `send_video_frame()` |
| `POST /v1/stream/decode` | SSE 流式出文本 | `receive_text_delta()` |
| `POST /v1/stream/break` | 打断 | `interrupt()` |

```bash
python -m runtime.omni.smoke.run_server_smoke --port 19080
```
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


def post_json(url: str, body: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def decode_sse(url: str, body: dict, timeout: int = 900) -> dict:
    """读 SSE，返回 {text, events, ttft_ms, total_ms}。"""
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    out = {"text": "", "events": [], "ttft_ms": None, "total_ms": None,
           "is_listen": 0, "end_of_turn": 0}
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                ev = json.loads(payload)
            except Exception:
                continue
            content = ev.get("content") or ""
            if content and out["ttft_ms"] is None:
                out["ttft_ms"] = round((time.time() - t0) * 1000, 1)
            out["text"] += content
            if ev.get("is_listen"):
                out["is_listen"] += 1
            if ev.get("end_of_turn"):
                out["end_of_turn"] += 1
            if len(out["events"]) < 40:
                out["events"].append({k: ev.get(k) for k in ("content", "stop", "is_listen", "end_of_turn")})
    out["total_ms"] = round((time.time() - t0) * 1000, 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="llama-omni-server HTTP smoke")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=19080)
    ap.add_argument("--prefix", default="",
                    help="测试用例前缀；缺省用仓库自带 omni_test_case_")
    ap.add_argument("--frames", type=int, default=1)
    ap.add_argument("--no-cancel", action="store_true", help="解码过程不测 break")
    args = ap.parse_args()

    base = f"http://{args.host}:{args.port}"
    prefix = args.prefix or ("D:/qiyu-omni-build/src/llama.cpp-omni-master/"
                             "tools/omni/assets/test_case/omni_test_case/omni_test_case_")
    rep: dict = {"prefix": prefix, "steps": {}}

    print("=" * 64)
    print("  llama-omni-server HTTP 会话 smoke（真模型）")
    print("=" * 64)

    # 1) omni_init
    t0 = time.time()
    try:
        r = post_json(f"{base}/v1/stream/omni_init", {
            "msg_type": 2, "use_tts": True, "duplex_mode": False,
            "tts_gpu_layers": 100, "token2wav_device": "gpu:0",
            "output_dir": "D:/qiyu-omni-build/smoke_out",
        })
    except urllib.error.HTTPError as e:
        print("omni_init 失败:", e.code, e.read().decode("utf-8", "ignore")[:300])
        return 1
    init_ms = round((time.time() - t0) * 1000, 1)
    rep["steps"]["omni_init"] = {"ok": bool(r.get("success")), "ms": init_ms}
    print(f"[1/4] omni_init   ok={r.get('success')}  {init_ms} ms")

    # 2) prefill（音频 + 图像，按路径前缀）
    # 注意：服务端把 audio_path_prefix / img_path_prefix 当作**完整文件名**使用，
    # 而 cnt 是 index（不是数量）。Comni demo 的 worker 也是写临时文件后传全路径。
    idx = 0
    aud_path = f"{prefix}{idx:04d}.wav"
    img_path = f"{prefix}{idx:04d}.jpg"
    t0 = time.time()
    r = post_json(f"{base}/v1/stream/prefill", {
        "audio_path_prefix": aud_path, "cnt": idx,
        "img_path_prefix": img_path if args.frames > 0 else "", "round_idx": 0,
    })
    prefill_ms = round((time.time() - t0) * 1000, 1)
    rep["steps"]["prefill"] = {"ok": bool(r.get("success")), "ms": prefill_ms,
                               "audio": aud_path, "image": img_path}
    print(f"[2/4] prefill     ok={r.get('success')}  {prefill_ms} ms  audio={Path(aud_path).name}")

    # 3) decode（SSE 流式）
    dec = decode_sse(f"{base}/v1/stream/decode", {
        "stream": True, "round_idx": 0, "debug_dir": "D:/qiyu-omni-build/smoke_out/debug",
    })
    rep["steps"]["decode"] = {
        "text": dec["text"], "ttft_ms": dec["ttft_ms"], "total_ms": dec["total_ms"],
        "is_listen": dec["is_listen"], "end_of_turn": dec["end_of_turn"],
        "events": dec["events"][:12],
    }
    print(f"[3/4] decode      TTFT={dec['ttft_ms']} ms  总={dec['total_ms']} ms  "
          f"listen={dec['is_listen']} end={dec['end_of_turn']}")
    print(f"      文本: {dec['text'][:160]!r}")

    # 4) break（打断端点是否可用）
    if not args.no_cancel:
        try:
            rb = post_json(f"{base}/v1/stream/break", {"reason": "smoke"})
            rep["steps"]["break"] = {"ok": True, "resp": rb}
            print(f"[4/4] break       ok  {str(rb)[:80]}")
        except urllib.error.HTTPError as e:
            rep["steps"]["break"] = {"ok": False, "code": e.code,
                                     "body": e.read().decode("utf-8", "ignore")[:200]}
            print(f"[4/4] break       HTTP {e.code}")

    Path("runtime/omni/out").mkdir(parents=True, exist_ok=True)
    out = Path("runtime/omni/out/server_smoke.json")
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("-" * 64)
    print("报告:", out)
    ok = bool(rep["steps"].get("omni_init", {}).get("ok")) and bool(rep["steps"].get("decode", {}).get("text"))
    print("结果:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
