# -*- coding: utf-8 -*-
"""VoicePipeline + AvatarEvent 真实验证（SAPI / JSON Bridge）。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    from runtime.tts import WindowsSapiTTSProvider
    from runtime.voice_pipeline import SentenceSegmenter, VoicePipeline, VoiceProfile
    from runtime.avatar import AvatarEvent, avatar_controller

    text = "嗯，那我想想。这个其实挺有意思的，你等一下。说完我就告诉你。"
    seg = SentenceSegmenter()
    parts = seg.split(text)
    assert parts and len(parts) >= 2, parts

    provider = WindowsSapiTTSProvider()
    vp = VoicePipeline(profile=VoiceProfile(voice_id="", pitch=1.0, speed=1.0, energy=1.0))
    chunks = []
    async for chunk in vp.synthesize_stream(text, emotion_state={"mood": "happy", "intensity": 0.7},
                                            provider=provider):
        chunks.append(chunk)
        if len(chunks) == 1 and len(parts) > 1:
            await vp.interrupt()
    assert chunks, "没有产生任何音频 chunk"
    assert chunks[0].path and Path(chunks[0].path).exists(), "首个 chunk 未生成音频"
    assert chunks[-1].interrupted or len(chunks) <= 2, "打断没有生效"

    q: asyncio.Queue = asyncio.Queue()
    assert avatar_controller.subscribe_json(q)
    ev = AvatarEvent(emotion="happy", intensity=0.65, action="small_smile",
                     mouth=0.7, blink=True, breathing=0.5, speaking=True,
                     prosody={"speed": 1.1, "pitch": 1.05})
    r = await avatar_controller.emit_event(ev, "json")
    assert r.get("delivered", 0) >= 1
    got_event = await asyncio.wait_for(q.get(), timeout=3)
    assert got_event.get("emotion") == "happy"

    print(json.dumps({
        "sentence_chunks": parts,
        "audio_chunks": len(chunks),
        "first_audio_ok": True,
        "interrupted": bool(chunks[-1].interrupted),
        "avatar_delivered": r.get("delivered"),
        "avatar_event": got_event,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
