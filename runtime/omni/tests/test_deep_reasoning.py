# -*- coding: utf-8 -*-
"""深推理后端（MainBrain）接线验证：真实 LLM 端点，无 mock。

验证：
  1. 复杂度闸门（闲聊不触发、复杂请求触发）
  2. 真实 OpenAI 兼容端点可用性
  3. 真实调用返回非空文本（记录模型与延迟）
  4. 接到 OmniMainChain 上：maybe_deep_reason 只在复杂请求时调用
  5. 端点不可达时如实返回 available=False（不伪造）
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from runtime.omni.deep_reasoning import DeepReasoningConfig, MainBrainDeepReasoning
from runtime.omni.mainchain import OmniMainChain

OUT = Path("runtime/omni/out")
RESULTS = {}


def _record(name, ok, detail=None, blocked=False):
    RESULTS[name] = {"ok": bool(ok), "blocked": bool(blocked), **(detail or {})}
    tag = "BLOCKED" if blocked else ("PASS" if ok else "FAIL")
    print("  [%s] %s %s" % (tag, name, json.dumps(detail or {}, ensure_ascii=False)))
    return bool(ok)


async def main():
    print("=" * 70)
    print("深推理后端（MainBrain）接线验证")
    print("=" * 70)
    cfg = DeepReasoningConfig.from_env()
    backend = MainBrainDeepReasoning(cfg)
    print("  端点:", cfg.base_url, "模型:", cfg.model)

    _record("complexity_gate",
            backend.is_complex("嗯") is False
            and backend.is_complex("帮我做一个三步学习计划") is True
            and backend.is_complex("随便说点什么" * 8) is True,
            {"short_chat": backend.is_complex("嗯"),
             "keyword": backend.is_complex("帮我做一个三步学习计划"),
             "long": backend.is_complex("随便说点什么" * 8)})

    ok = await backend.available()
    _record("endpoint_available", ok, {"base_url": cfg.base_url, "model": cfg.model})
    if not ok:
        summary = {"label": "BLOCKED（LLM 端点不可达）", "results": RESULTS,
                   "passed": 0, "total": len(RESULTS), "verdict": "BLOCKED"}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "deep_reasoning_tests.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("DEEP_REASONING = BLOCKED")
        return 0

    t0 = asyncio.get_event_loop().time()
    out = await backend("用一句话说明什么是实时全双工语音对话。",
                        {"system_prompt": "用一句中文回答，不要寒暄。"})
    _record("real_llm_call", out.get("ok") and len(out.get("text", "")) > 0,
            {"text": (out.get("text") or "")[:80], "model": out.get("model"),
             "latency_ms": out.get("latency_ms"), "usage": out.get("usage")})

    chain = OmniMainChain(omni=None, deep_reasoning=backend)
    simple = await chain.maybe_deep_reason("嗯")
    _record("chain_skips_simple", simple.get("invoked") is False
            and chain.stats.deep_reasoning_calls == 0,
            {"result": simple, "calls": chain.stats.deep_reasoning_calls})
    complex_res = await chain.maybe_deep_reason("给我一个三步走的计划：怎么安排每周的学习时间？")
    _record("chain_invokes_on_complex",
            complex_res.get("invoked") is True
            and chain.stats.deep_reasoning_calls == 1,
            {"calls": chain.stats.deep_reasoning_calls,
             "text": ((complex_res.get("result") or {}).get("text") or "")[:80]})

    summary = {"label": "REAL LOCAL（真实 LLM 端点）",
               "endpoint": cfg.base_url, "model": cfg.model,
               "results": RESULTS,
               "backend_stats": backend.stats(),
               "passed": sum(1 for v in RESULTS.values() if v.get("ok")),
               "total": len(RESULTS)}
    verdict = all(v.get("ok") for v in RESULTS.values())
    summary["verdict"] = "PASS" if verdict else "FAIL"
    print("=" * 70)
    print("DEEP_REASONING =", summary["verdict"],
          "(%d/%d)" % (summary["passed"], summary["total"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "deep_reasoning_tests.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("报告:", OUT / "deep_reasoning_tests.json")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
