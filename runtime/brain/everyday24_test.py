# -*- coding: utf-8 -*-
"""日常聊天回归（Stage 1 Personality Base）。

24 条 everyday 消息走真实 BrainPipeline（非 mock）：
- 覆盖闲聊/状态报备/情绪/吐槽/碎句/无意义输入；
- 检查直答率、空回、重复碎句、客服腔；
- 用于验证「路由放宽 + Personality Base」后的真实聊天效果。

运行：python -m runtime.brain.everyday24_test
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.brain.quality import hard_fail  # noqa: E402

EVERYDAY = [
    "周末干嘛", "最近怎么样", "今天加班", "感冒了", "在减肥", "刚下班",
    "堵车了", "准备睡了", "我困了", "今天好累", "想你了", "你是不是傻",
    "无聊", "你干嘛呢", "吃饭没", "在忙吗", "同事好烦", "心里堵得慌",
    "我今天其实想跟你说", "？？？", "。。。", "在打游戏", "看了个电影", "明天要早起",
]

SERVICE_RE = re.compile(r"作为(AI|人工智能|助手)|我是AI|有什么可以帮|请问还有什么|"
                        r"当然可以|很高兴为您|我可以帮你")


def _ctx(text: str) -> dict:
    return {
        "user_id": "everyday24", "char_id": "xiaoban",
        "char_hint": "小办，普通朋友 · 有空就聊",
        "role_context": "【状态】你和对方现在是普通朋友（好感50/100，耐心70/100）。",
        "max_tokens": 16, "timeout_s": 10.0, "web_enabled": True, "images": [],
        "topic": "", "topic_transition": "continue",
        "emotion_state": {"mood": "neutral", "patience": 70, "affection": 50},
        "memory_hint": "",
    }


async def main():
    from runtime.realtime import MiniMindOOmniBackend
    from runtime.brain.pipeline import BrainPipeline
    backend = MiniMindOOmniBackend()
    r = await backend.load()
    if not r.get("ok"):
        raise SystemExit(f"MiniMind 加载失败: {r.get('reason')}")
    pipe = BrainPipeline(provider_getter=lambda: backend, main_brain=None)
    rows, direct, esc, empty, hard, service = [], 0, 0, 0, 0, 0
    for t in EVERYDAY:
        t0 = time.time()
        try:
            res = await asyncio.wait_for(pipe.run([t], _ctx(t)), timeout=60)
        except Exception as e:
            res = {"reply_text": "", "decision": {"mini_ran": False}, "error": str(e)}
        reply = (res.get("reply_text") or "").strip()
        mode = res.get("mode")
        d = res.get("decision") or {}
        is_direct = bool(d.get("mini_ran")) and mode == "direct"
        if is_direct:
            direct += 1
        else:
            esc += 1
        if not reply:
            empty += 1
        if reply and hard_fail(reply):
            hard += 1
        if reply and SERVICE_RE.search(reply):
            service += 1
        rows.append({"user": t, "reply": reply, "mode": mode, "direct": is_direct,
                     "took_ms": res.get("took_ms"), "error": res.get("error", "")})
        print(f"[{'direct' if is_direct else 'escalate':>8}] {t} -> {reply[:40]}")
    summary = {"total": len(EVERYDAY), "direct": direct, "escalated": esc,
               "direct_rate": round(direct / len(EVERYDAY), 3), "empty": empty,
               "hard_fail": hard, "service_tone": service}
    print("EVERYDAY24_SUMMARY", json.dumps(summary, ensure_ascii=False))
    out = ROOT / "runtime" / "brain" / "everyday24_report.json"
    out.write_text(json.dumps({"summary": summary, "results": rows},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT_SAVED", out)


if __name__ == "__main__":
    asyncio.run(main())
