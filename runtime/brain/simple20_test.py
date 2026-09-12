# -*- coding: utf-8 -*-
"""P0 runtime 直答回归：20 条 simple 消息走真实链路（非 mock）。

链路：MiniMind quick_reply（_sanitize_quick_text 门槛）→ BrainDecision → Direct/MainBrain，
与 Web /v1/chat/completions 主链路相同（BrainPipeline.run）。

判定（runtime/brain/quality.py 硬规则）：
- 空回复 → empty（FAIL）
- 重复碎句/无意义循环 → hard_fail:<reason>（FAIL）
- 「我看看/等下」类敷衍 → deferred（单独计数，不算 PASS）
- simple 应 direct 直答；被升级 MainBrain → escalated（单独计数）

运行（用 env 指定 base + adapter）：
  $env:QIYU_REALTIME_MODEL_DIR="...\\models\\realtime\\minimind-tag-D-local"
  $env:QIYU_REALTIME_ADAPTER="...\\training\\minimind_realtime\\runs\\exp-tag-D2\\adapter"
  python -m runtime.brain.simple20_test
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

SIMPLE20 = [
    "哈哈", "草", "好烦", "好困", "嘿嘿",
    "笑死", "真的假的", "服了", "无聊", "你睡了吗",
    "晚安", "饿", "下班了", "好呀", "啊？",
    "你干嘛呢", "吃饭没", "在忙吗", "今天好热", "想你了",
]

DEFER_RE = re.compile(r"^(我看看|等下|等会|等一下|稍等|我看一下|我看看哈|回头|晚点)")


def _ctx(text: str) -> dict:
    return {
        "user_id": "simple20", "char_id": "xiaoban",
        "char_hint": "小办，普通朋友 · 有空就聊",
        "role_context": "【状态】你和对方现在是普通朋友（好感50/100，耐心70/100）。",
        "max_tokens": 16, "timeout_s": 10.0,
        "web_enabled": True, "images": [],
        "topic": "", "topic_transition": "continue",
        "emotion_state": {"mood": "neutral", "patience": 70, "affection": 50},
        "memory_hint": "",
    }


async def _build_provider():
    from runtime.realtime import MiniMindOOmniBackend
    backend = MiniMindOOmniBackend()
    r = await backend.load()
    if not r.get("ok"):
        raise SystemExit(f"MiniMind 加载失败: {r.get('reason')}")
    return backend


def _verdict(text: str, r: dict) -> str:
    d = r.get("decision", {})
    reply = (r.get("reply_text") or "").strip()
    if not d.get("mini_ran"):
        return "mini_not_ran"
    hard = hard_fail(reply)
    if hard:
        return f"hard_fail:{hard}"
    if not reply:
        return "empty"
    if d.get("mode") == "direct":
        if DEFER_RE.match(reply):
            return "deferred"
        return "pass"
    return "escalated"


async def main():
    from runtime.brain.pipeline import BrainPipeline
    provider = await _build_provider()
    pipeline = BrainPipeline(provider_getter=lambda: provider, main_brain=None)
    results = []
    for text in SIMPLE20:
        start = time.time()
        try:
            r = await asyncio.wait_for(pipeline.run([text], _ctx(text)), timeout=60)
        except Exception as e:
            r = {"reply_text": "", "decision": {"mini_ran": False}, "error": str(e)}
        verdict = _verdict(text, r)
        results.append({
            "user": text,
            "reply": (r.get("reply_text") or "")[:60],
            "mode": r.get("mode"),
            "verdict": verdict,
            "took_ms": r.get("took_ms"),
            "error": r.get("error", ""),
        })
    counts = {}
    for x in results:
        key = x["verdict"].split(":", 1)[0]
        counts[key] = counts.get(key, 0) + 1
    summary = {
        "total": len(results),
        "counts": counts,
        "pass": counts.get("pass", 0),
        "fail": counts.get("hard_fail", 0) + counts.get("empty", 0) + counts.get("mini_not_ran", 0),
        "pass_rate": round(counts.get("pass", 0) / len(results), 3),
    }
    print("SIMPLE20_SUMMARY", json.dumps(summary, ensure_ascii=False))
    for x in results:
        print(f"[{x['verdict']:>22}] {x['user']} -> {x['reply']}")
    report = {"summary": summary, "results": results,
              "model_env": "QIYU_REALTIME_MODEL_DIR/QIYU_REALTIME_ADAPTER"}
    out = ROOT / "runtime" / "brain" / "simple20_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("REPORT_SAVED", str(out))


if __name__ == "__main__":
    asyncio.run(main())
