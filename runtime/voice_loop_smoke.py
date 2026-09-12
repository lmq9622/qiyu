# -*- coding: utf-8 -*-
"""真实闭环冒烟：TTS 播放文本→STT 识别→MiniMind(D6) 回复→TTS chunk。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _P:
    def __init__(self, b): self._b = b
    async def quick_reply(self, *a, **kw): return await self._b.quick_reply(*a, **kw)


async def main():
    from runtime.tts import WindowsSapiNativeTTSProvider
    from runtime.stt import stt_provider
    from runtime.realtime import MiniMindOOmniBackend
    from runtime.brain.pipeline import BrainPipeline
    from runtime.voice_pipeline import VoicePipeline, VoiceProfile

    tts = WindowsSapiNativeTTSProvider()
    out = await tts.synthesize("在吗", speed=1.0)
    assert out and Path(out["path"]).exists()
    audio_bytes = Path(out["path"]).read_bytes()
    text = await stt_provider.transcribe(audio_bytes)
    backend = MiniMindOOmniBackend()
    await backend.load()
    pipeline = BrainPipeline(provider_getter=lambda: _P(backend))
    res = await pipeline.run([text or "在吗"], {
        "role_context": "【状态】普通朋友，耐心70。", "max_tokens": 12, "timeout_s": 8.0})
    reply = res.get("reply_text") or ""
    vp = VoicePipeline(profile=VoiceProfile())
    chunks = []
    async for c in vp.synthesize_stream(reply, provider=tts):
        chunks.append(c)
        break
    print(json.dumps({"asr": text, "reply": reply, "mode": res.get("mode"),
                      "tts_reply_ok": bool(chunks and chunks[0].path)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
