# -*- coding: utf-8 -*-
"""语音聊天链真实冒烟：文本/STT 文本 → MiniMind(D6) → BrainDecision → 分句 TTS。
打印首字/首句/首音频耗时，供“1 秒内”优化验证；可打断。"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _BackendProvider:
    def __init__(self, backend) -> None:
        self._b = backend

    async def quick_reply(self, *a, **kw):
        return await self._b.quick_reply(*a, **kw)


async def run(text: str, rounds: int = 1):
    from runtime.realtime import MiniMindOOmniBackend
    from runtime.brain.pipeline import BrainPipeline
    from runtime.tts import WindowsSapiNativeTTSProvider
    from runtime.voice_pipeline import VoicePipeline, VoiceProfile

    backend = MiniMindOOmniBackend()
    r = await backend.load()
    if not r.get("ok"):
        raise SystemExit(f"MiniMind load fail: {r}")
    pipeline = BrainPipeline(provider_getter=lambda: _BackendProvider(backend))
    provider = WindowsSapiNativeTTSProvider()
    vp = VoicePipeline(profile=VoiceProfile(speed=1.0, pitch=1.0))
    await provider.synthesize("嗯", speed=1.0)  # 预热 System.Speech，避免首包计入装配耗时

    rows = []
    for _ in range(rounds):
        t0 = time.time()
        pres = await pipeline.run([text], {
            "char_hint": "小办，普通朋友",
            "role_context": "【状态】普通朋友，耐心70。",
            "emotion_state": {"mood": "neutral", "intensity": 0.5},
            "max_tokens": 12, "timeout_s": 8.0,
        })
        decision_ms = (time.time() - t0) * 1000
        reply = pres.get("reply_text") or ""
        if pres.get("mode") != "direct" or not reply:
            rows.append({"mode": pres.get("mode"), "error": "not_direct_or_empty",
                         "decision_ms": round(decision_ms, 1)})
            continue
        t1 = time.time()
        chunks = []
        async for chunk in vp.synthesize_stream(reply, emotion_state={"mood": "neutral"},
                                                provider=provider):
            chunks.append(chunk)
            if len(chunks) == 1:
                break  # 只测首包
        first_audio_ms = (time.time() - t1) * 1000
        rows.append({"mode": "direct", "reply": reply, "decision_ms": round(decision_ms, 1),
                     "first_audio_ms": round(first_audio_ms, 1),
                     "chunks": len(chunks),
                     "audio_ok": bool(chunks and chunks[0].path)})
    print(json.dumps({"text": text, "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    txt = sys.argv[1] if len(sys.argv) > 1 else "在吗"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    asyncio.run(run(txt, n))
