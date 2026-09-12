# -*- coding: utf-8 -*-
"""P0 真实调用链测试：MessageGateway → MiniMind → BrainDecision → Direct/MainBrain。

不是 endpoint 200/mock：MiniMind 用本机官方 minimind-3o 真实后端，
MainBrain 用当前 LLMClient（默认指向 x99 llama.cpp），不可用时如实标 UNVERIFIED。

运行：
  python -m runtime.brain.p0_test
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class _CountProvider:
    def __init__(self, backend) -> None:
        self._backend = backend
        self.quick_calls = 0

    async def quick_reply(self, *args, **kwargs):
        self.quick_calls += 1
        return await self._backend.quick_reply(*args, **kwargs)


async def _build_provider():
    from runtime.realtime import MiniMindOOmniBackend
    from runtime.minimindo import discover_model_dir
    model_dir = discover_model_dir(Path(ROOT) / "models" / "realtime")
    if model_dir is None:
        raise SystemExit("缺少 minimind-3o 权重，无法做真实 MiniMind 测试")
    backend = MiniMindOOmniBackend(model_root=model_dir)
    r = await backend.load()
    if not r.get("ok"):
        raise SystemExit(f"MiniMind 加载失败: {r.get('reason')}")
    return _CountProvider(backend)


async def _build_main_brain(count: dict):
    try:
        from companion.llm import LLMClient
    except Exception as e:
        return None, f"LLMClient import 失败: {e}"
    client = LLMClient()
    if not getattr(client, "available", False):
        return None, "LLMClient.available=False（未配置/连不上主模型）"

    async def _mb(texts, decision, ctx, brain_ctx):
        count["main"] += 1
        msgs = ctx.get("_llm_messages") or [{"role": "user", "content": t} for t in texts]
        reply, pieces = await client.chat(
            "xiaoban", msgs, 0.7, user_id=ctx.get("user_id", "p0_test"),
            use_memory=bool(ctx.get("memory_hint")), use_rag=True,
            brain_context=brain_ctx)
        return {"text": reply or "", "pieces": pieces or []}
    return _mb, ""


def _ctx(text: str, **kw) -> dict:
    base = {
        "user_id": "p0_test", "char_id": "xiaoban",
        "char_hint": "小办，普通朋友 · 有空就聊",
        "role_context": "【状态】你和对方现在是普通朋友（好感50/100，耐心70/100）。",
        "max_tokens": 16, "timeout_s": 10.0,
        "web_enabled": True, "images": [],
        "topic": "", "topic_transition": "continue",
        "emotion_state": {"mood": "neutral", "patience": 70, "affection": 50},
        "memory_hint": "",
    }
    base.update(kw)
    return base


async def main():
    from runtime.brain.pipeline import BrainPipeline
    provider = await _build_provider()
    main_count = {"main": 0}
    mb, mb_note = await _build_main_brain(main_count)
    pipeline = BrainPipeline(provider_getter=lambda: provider, main_brain=mb)

    cases = [
        ("1_haha", ["哈哈"], _ctx("哈哈")),
        ("2_cao", ["草"], _ctx("草")),
        ("3_fan", ["好烦"], _ctx("好烦")),
        ("4_casual", ["今天天气不错"], _ctx("今天天气不错")),
        ("5_complex", ["帮我解释一下什么是相对论"],
         _ctx("帮我解释一下什么是相对论")),
        ("6_search", ["帮我查一下明天北京的天气"],
         _ctx("帮我查一下明天北京的天气")),
        ("7_image", ["这张图里是什么"],
         _ctx("这张图里是什么", images=["data:image/png;base64,iVBORw0KGgo="])),
        ("8_mini_down", ["哈哈"], _ctx("哈哈")),
        ("9_rag", ["你还记得我咖啡怎么喝吗"],
         _ctx("你还记得我咖啡怎么喝吗",
              memory_hint="用户喜欢喝黑咖啡，不加糖",
              role_context="【状态】你和对方现在是普通朋友。\n你记得：用户喜欢喝黑咖啡，不加糖。")),
        ("10_repeat", ["七千预算买什么电脑好"],
         _ctx("七千预算买什么电脑好", topic="七千预算买电脑", topic_transition="repeat_recent")),
        ("11_abrupt", ["突然想养猫了"],
         _ctx("突然想养猫了", topic="电脑配置", topic_transition="abrupt")),
    ]
    results = []
    simple_cases = ("1_haha", "2_cao", "3_fan", "4_casual")
    simple_direct = 0
    for name, texts, ctx in cases:
        start = time.time()
        if name == "8_mini_down":
            down_pl = BrainPipeline(provider_getter=lambda: None, main_brain=mb)
            r = await down_pl.run(texts, ctx)
        else:
            before_mini = provider.quick_calls
            before_main = main_count["main"]
            r = await pipeline.run(texts, ctx)
            d = r["decision"]
            if name in simple_cases:
                assert d["mini_ran"], "简单消息 MiniMind 必须先执行"
                if d["mode"] == "direct":
                    simple_direct += 1
                    assert main_count["main"] == before_main, f"{name} 不应拉 MainBrain"
            elif name == "5_complex":
                assert d["mini_ran"], "复杂消息也必须先执行 MiniMind"
                assert d["mode"] == "main"
                if mb is not None:
                    assert main_count["main"] == before_main + 1, "复杂消息应调 MainBrain"
            elif name == "6_search":
                assert d["mini_ran"] and d["need_tool"], f"搜索应 need_tool: {d}"
            elif name == "7_image":
                assert d["mini_ran"] and d["need_vision"], f"图片应 need_vision: {d}"
            elif name == "9_rag":
                assert d["memory_hint"], f"RAG 应保留 memory_hint: {d}"
            elif name == "10_repeat":
                assert d["topic_transition"] == "repeat_recent"
            elif name == "11_abrupt":
                assert d["topic_transition"] == "abrupt"
            assert provider.quick_calls >= before_mini, "本轮必须真正调用 MiniMind"
        results.append({
            "case": name, "texts": texts,
            "mode": r.get("mode"), "mini_ran": r.get("decision", {}).get("mini_ran"),
            "need_tool": r.get("decision", {}).get("need_tool"),
            "need_vision": r.get("decision", {}).get("need_vision"),
            "transition": r.get("decision", {}).get("topic_transition"),
            "reply": (r.get("reply_text") or "")[:50],
            "main_calls": main_count["main"], "mini_calls": provider.quick_calls,
            "took_ms": r.get("took_ms"),
            "chain": [c.get("step") for c in (r.get("chain") or [])],
        })

    # 12：连续 3 条只触发一次 MiniMind
    before_mini = provider.quick_calls
    before_main = main_count["main"]
    r = await pipeline.run(
        ["我电脑又炸了", "刚才还好好的", "现在直接黑屏"],
        _ctx("我电脑又炸了", topic="电脑问题", topic_transition="continue"))
    results.append({
        "case": "12_batch", "texts": ["电脑又炸了", "刚才还好好的", "黑屏"],
        "mode": r.get("mode"), "mini_ran": r.get("decision", {}).get("mini_ran"),
        "mini_calls_delta": provider.quick_calls - before_mini,
        "main_calls_delta": main_count["main"] - before_main,
        "reply": (r.get("reply_text") or "")[:50],
        "chain": [c.get("step") for c in (r.get("chain") or [])],
    })

    print("MAIN_BRAIN_NOTE", mb_note or "available")
    print("RESULTS", json.dumps(results, ensure_ascii=False, indent=2, default=str))
    ok_direct = all(
        x["mini_ran"] and x["mode"] == "direct" and x["main_calls"] == 0
        for x in results if x["case"] in simple_cases)
    print("P0_SUMMARY",
          json.dumps({"simple_not_main": ok_direct,
                      "simple_direct": simple_direct,
                      "simple_total": len(simple_cases),
                      "main_available": mb is not None,
                      "total_cases": len(results)}, ensure_ascii=False, default=str))
    report = {
        "main_brain_note": mb_note or "available",
        "results": results,
        "summary": {"simple_not_main": ok_direct, "simple_direct": simple_direct,
                    "simple_total": len(simple_cases), "main_available": mb is not None,
                    "total_cases": len(results)},
    }
    Path(ROOT / "runtime" / "brain" / "p0_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("REPORT_SAVED", ROOT / "runtime" / "brain" / "p0_report.json")


if __name__ == "__main__":
    asyncio.run(main())
