# -*- coding: utf-8 -*-
"""Qiyu Runtime · BrainPipeline（P0：唯一大小脑主链路）。

原则：
- MiniMind 是每批消息的第一入口；即使 Decision=main，MiniMind 也必须先执行，
  并把压缩理解传给 MainBrain；
- classifier 只在 MiniMind 不可用/超时时作为 fallback，不做前置并行路由；
- Pipeline 不面向 UI，业务层只消费 PipelineResult；BrainDecision 严禁外发。

P0 接通范围：Web /v1/chat/completions 的非流式主链路。微信/主动/队列在 P1 收口。
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from runtime.brain.decision import BrainDecision, decision_to_main_context
from runtime.brain.quality import hard_fail

MiniProvider = Any
MainBrainFn = Callable[..., Awaitable[dict]]
ToolGetter = Callable[[], Any]
EventCb = Callable[[str, dict], Awaitable[None]]


class BrainPipeline:
    def __init__(self, provider_getter: Optional[Callable[[], Optional[MiniProvider]]] = None,
                 main_brain: Optional[MainBrainFn] = None,
                 tool_getter: Optional[ToolGetter] = None) -> None:
        self._provider_getter = provider_getter or _default_provider_getter
        self._main_brain = main_brain
        self._tool_getter = tool_getter or _default_tool_getter

    def set_main_brain(self, fn: MainBrainFn) -> None:
        self._main_brain = fn

    def set_tool_getter(self, fn: ToolGetter) -> None:
        self._tool_getter = fn

    # ---------------- P1 双段输出 ----------------
    def _maybe_immediate(self, d: BrainDecision) -> None:
        """main/tool 且 MiniMind 有合格 candidate → 先发即时反应，再走 MainBrain 最终回复。

        candidate 已过 quick_reply 质量门槛；这里再套一层硬规则（重复碎句/空/循环）防漏。
        """
        if d.mode not in ("main", "tool", "vision"):
            return
        cand = (d.candidate_reply or "").strip()
        if not cand or hard_fail(cand):
            return
        d.response_mode = "immediate_then_final"
        d.immediate_reaction = cand

    def _merge_immediate(self, decision: BrainDecision, pieces: list) -> list:
        """最终消息数组 = 即时反应段 + MainBrain 段（前端按协议去重播放）。"""
        if decision.response_mode == "immediate_then_final" and decision.immediate_reaction:
            return ([{"text": decision.immediate_reaction, "type": "immediate", "delay": 0}]
                    + list(pieces or []))
        return list(pieces or [])

    async def _execute_tool(self, decision: BrainDecision, ctx: dict) -> Optional[dict]:
        """P1：Decision.need_tool=true 时真实执行 ToolAgent（不靠 MainBrain 口头搜索）。"""
        if not decision.need_tool:
            return None
        tool = self._tool_getter() if self._tool_getter else None
        if tool is None:
            return {"success": False, "items": [], "error": "ToolAgent 未就绪"}
        query = (decision.topic or "").strip() or "；".join(
            [str(t or "") for t in ctx.get("_user_texts") or []]).strip()[:160]
        if not query:
            query = str(ctx.get("user_text") or "")[:160]
        category = str((decision.meta or {}).get("route_category") or "")
        try:
            if category == "image_request":
                ev = await tool.search_images(query)
            else:
                ev = await tool.search(query)
            return ev.to_dict() if hasattr(ev, "to_dict") else {
                "success": bool(ev and getattr(ev, "success", False)),
                "items": getattr(ev, "items", []) or [], "error": getattr(ev, "error", "")}
        except Exception as e:
            logger.warning(f"[BrainPipeline] ToolAgent 执行异常: {e}")
            return {"success": False, "items": [], "error": str(e)}

    async def complete(self, decision: BrainDecision, ctx: Optional[dict] = None) -> dict:
        """Decision 已经产出后执行后续：ToolAgent → MainBrain / Vision（P1）。
        与 decide() 分离，便于流式链路先推即时反应再继续主脑。"""
        ctx = ctx or {}
        pieces: list[dict] = []
        main_text = ""
        chain: list[dict] = []
        tool_evidence = None

        if decision.need_tool:
            tool_evidence = await self._execute_tool(decision, ctx)
            decision.meta["tool_evidence"] = tool_evidence or {}
            chain.append({
                "step": "ToolAgent",
                "ok": bool(tool_evidence and tool_evidence.get("success")),
                "items": len((tool_evidence or {}).get("items") or []),
            })

        if decision.mode == "direct" and decision.candidate_reply:
            pieces = [{"text": decision.candidate_reply, "type": "statement", "delay": 0}]
            chain.append({"step": "Direct Reply"})
            return {"pieces": pieces, "text": decision.candidate_reply,
                    "chain": chain, "tool_evidence": tool_evidence}

        if decision.need_vision and not ctx.get("images"):
            chain.append({"step": "Vision", "status": "P1_TODO_NO_IMAGE",
                          "reason": "need_vision=true 但没有实际图片输入；若为找图需求应走 ToolAgent"})

        if self._main_brain is None:
            chain.append({"step": "MainBrain", "status": "NO_MAIN_BRAIN_CALLBACK"})
            return {"pieces": self._merge_immediate(decision, pieces), "text": main_text, "chain": chain,
                    "tool_evidence": tool_evidence}

        brain_ctx = decision_to_main_context(decision)
        # Quest MR 等外部入口可注入额外真实上下文（默认不存在，不影响既有链路）
        extra_ctx = str(ctx.get("_extra_brain_context") or "").strip()
        if extra_ctx:
            brain_ctx = f"{brain_ctx}\n\n{extra_ctx}"
        if tool_evidence is not None:
            if tool_evidence.get("success") and tool_evidence.get("items"):
                ev_lines = "\n".join(
                    f"- {it.get('title', '')}（{it.get('url') or it.get('image_url') or ''}）"
                    f"{it.get('snippet', '') or ''}"[:180]
                    for it in tool_evidence.get("items", [])[:6])
                brain_ctx += f"\n\n【ToolAgent 真实结果（成功）】\n{ev_lines}"
            else:
                brain_ctx += (f"\n\n【ToolAgent 结果（失败，必须如实告诉用户，禁止说搜到了/发你了）】\n"
                              f"{tool_evidence.get('error') or '没有找到结果'}")
        ctx = dict(ctx)
        ctx["_brain_context"] = brain_ctx
        ctx["_tool_evidence"] = tool_evidence
        try:
            res = await self._main_brain(ctx.get("_user_texts") or ctx.get("texts") or [],
                                         decision, ctx, brain_ctx)
            main_text = str(res.get("text") or "").strip()
            pieces = res.get("pieces") or (
                [{"text": main_text, "type": "statement", "delay": 0}] if main_text else [])
            chain.append({"step": "MainBrain", "ok": bool(main_text)})
        except Exception as e:
            chain.append({"step": "MainBrain", "error": str(e)})
            # 空 str(e) 的异常（asyncio.TimeoutError / ConnectError）无法定位，
            # 先打出类型与 repr，再原样重试一次（偶发超时/连接抖动可自愈）。
            logger.warning(f"[BrainPipeline] MainBrain 失败: {type(e).__name__} {e!r}")
            try:
                res = await self._main_brain(ctx.get("_user_texts") or ctx.get("texts") or [],
                                             decision, ctx, brain_ctx)
                main_text = str(res.get("text") or "").strip()
                pieces = res.get("pieces") or (
                    [{"text": main_text, "type": "statement", "delay": 0}] if main_text else [])
                chain.append({"step": "MainBrain", "ok": bool(main_text), "retried": True})
                logger.info("[BrainPipeline] MainBrain 重试成功")
            except Exception as e2:
                chain.append({"step": "MainBrain", "error": f"{type(e2).__name__}: {e2}"})
                logger.warning(f"[BrainPipeline] MainBrain 重试仍失败: {type(e2).__name__} {e2!r}")
        return {"pieces": self._merge_immediate(decision, pieces), "text": main_text, "chain": chain,
                "tool_evidence": tool_evidence}

    # ---------------- MiniMind 前置执行 ----------------
    async def _preprocess(self, text: str, ctx: dict) -> tuple[Optional[dict], dict]:
        """先调用真实 MiniMind 后端（不预分类），产出 candidate 与耗时。"""
        rt = self._provider_getter() if self._provider_getter else None
        if rt is None:
            return None, {"reason": "Realtime Provider 未就绪", "attempted": False}
        loaded = False
        try:
            h = rt.health()
            loaded = bool(h.get("loaded") or h.get("ok")) if isinstance(h, dict) else True
        except Exception:
            loaded = True
        if not loaded:
            return None, {"reason": "MiniMind 后端未加载", "attempted": False}
        try:
            rr = await rt.quick_reply(
                text,
                max_tokens=int(ctx.get("max_tokens") or 16),
                timeout_s=float(ctx.get("timeout_s") or 8.0),
                char_hint=str(ctx.get("char_hint") or ""),
                role_context=str(ctx.get("role_context") or ""),
            )
            return (rr or None), {"attempted": True, "reason": "" if rr else "MiniMind 执行但无合格 candidate"}
        except asyncio.TimeoutError:
            return None, {"reason": "MiniMind 超时", "attempted": True}
        except Exception as e:
            logger.warning(f"[BrainPipeline] MiniMind preprocess 异常: {e}")
            return None, {"reason": f"MiniMind 异常: {e}", "attempted": True}

    # ---------------- Decision 组装 ----------------
    async def decide(self, texts: list[str], context: Optional[dict] = None) -> BrainDecision:
        ctx = context or {}
        batch = [str(t or "").strip() for t in texts if str(t or "").strip()]
        if not batch:
            batch = [""]
        joined = "；".join(batch)
        images = bool(ctx.get("images") or ctx.get("has_image"))

        rt = self._provider_getter() if self._provider_getter else None
        # 规格 §23：小脑线已废弃（0.05.24）。默认不再走「先问小脑」的判定，
        # 直接由主脑承担；工具/记忆/情绪副作用仍走 complete()。
        from runtime.legacy_gate import log_once, minimind_enabled
        if not minimind_enabled():
            log_once(logger, "BrainPipeline.decide")
            d = self._fallback_decision(
                joined, ctx,
                reason="MiniMind 小脑线已废弃（0.05.24）→ 直接 MainBrain")
            d.meta["legacy_disabled"] = True
            return d
        rr, mini_meta = await self._preprocess(joined, ctx)
        candidate = str((rr or {}).get("text") or "").strip() if rr else ""
        attempted = bool(mini_meta.get("attempted"))

        # MiniMind 真实不可用 → 明确 fallback（不假装小脑已执行）
        if rt is None or not attempted:
            d = self._fallback_decision(
                joined, ctx,
                reason=mini_meta.get("reason", "MiniMind 不可用/未加载"))
            d.meta["preprocess"] = mini_meta or {}
            return d

        # 决策结构化提取：发生在 MiniMind 执行之后，只负责“把模型反应翻译成字段”。
        # classifier 不是前置路由，只在这层做 need_tool/need_vision/复杂度的兜底翻译。
        try:
            from runtime.classifier import classify_user_message, route_confidence
            route = classify_user_message(joined, has_images=images,
                                          web_enabled=bool(ctx.get("web_enabled", True)))
            conf = route_confidence(joined, route.action, route.category)
        except Exception as e:
            route = None
            conf = 0.0
            logger.warning(f"[BrainPipeline] 决策字段提取异常，按 main 处理: {e}")

        d = BrainDecision(
            candidate_reply=candidate,
            mini_ran=attempted,
            model=str((rr or {}).get("model") or ""),
            backend=str((rr or {}).get("backend") or ""),
            topic=str(ctx.get("topic") or ""),
            topic_transition=str(ctx.get("topic_transition") or "continue"),
            memory_hint=str(ctx.get("memory_hint") or ""),
            emotion=dict(ctx.get("emotion_state") or {}),
            confidence=round(float(conf or 0.0), 3),
            meta={"route_category": getattr(route, "category", "") if route else "",
                  "preprocess": mini_meta or {},
                  "candidate_took_ms": (rr or {}).get("took_ms"),
                  "candidate_ttft_ms": (rr or {}).get("ttft_ms")},
        )

        if images:
            d.need_vision = True
            d.need_main_brain = True
            d.mode = "vision"
            d.reason = "need_vision=true → Vision/MainBrain"
            d.intent_summary = "用户消息带图片，需视觉理解；MiniMind 已完成第一轮前置执行。"
            self._maybe_immediate(d)
            return d

        if route is not None and getattr(route, "needs_tool", False):
            d.need_tool = True
            d.need_main_brain = True
            d.mode = "tool"
            d.reason = str(getattr(route, "reason", "") or "need_tool=true → ToolAgent")
            d.intent_summary = f"用户需要搜索/工具类处理（{getattr(route, 'category', '')}）。"
            self._maybe_immediate(d)
            return d

        simple = (route is not None
                  and getattr(route, "action", "") in ("direct_reply", "emotion")
                  and len(joined.strip()) <= 12
                  and getattr(route, "category", "") in ("simple_chat", "simple_emotion"))
        if simple and candidate:
            d.mode = "direct"
            d.need_main_brain = False
            d.reason = str(getattr(route, "reason", "") or "MiniMind 直接短回复")
            d.confidence = max(d.confidence, 0.8)
            d.intent_summary = "简单闲聊/情绪，MiniMind 直接完成。"
            return d

        # 未命中简单直答 / MiniMind 无合格候选 → 升级 MainBrain，但保留 candidate 与预判
        d.mode = "main"
        d.need_main_brain = True
        if candidate:
            d.reason = "MiniMind 已产出首轮反应，但任务需要 MainBrain 深入处理"
        else:
            d.reason = str(getattr(route, "reason", "") or "MiniMind 无合格直答 → MainBrain")
            if not d.confidence:
                d.confidence = 1.0
        d.intent_summary = f"规则摘要：{getattr(route, 'reason', '') or '复杂/深度任务'}；MiniMind 已先执行。"
        self._maybe_immediate(d)
        return d

    def _fallback_decision(self, text: str, ctx: dict, reason: str) -> BrainDecision:
        """MiniMind 不可用的明确 fallback：classifier 只在这里被允许前置判断。"""
        images = bool(ctx.get("images") or ctx.get("has_image"))
        try:
            from runtime.classifier import classify_user_message, route_confidence
            route = classify_user_message(text, has_images=images,
                                          web_enabled=bool(ctx.get("web_enabled", True)))
            conf = route_confidence(text, route.action, route.category)
        except Exception:
            route = None
            conf = 0.0
        d = BrainDecision(
            mode="fallback_main",
            need_main_brain=True,
            need_tool=bool(getattr(route, "needs_tool", False)) if route else False,
            need_vision=images or bool(getattr(route, "has_image", False)),
            topic=str(ctx.get("topic") or ""),
            topic_transition=str(ctx.get("topic_transition") or "continue"),
            memory_hint=str(ctx.get("memory_hint") or ""),
            emotion=dict(ctx.get("emotion_state") or {}),
            confidence=round(float(conf or 1.0), 3),
            reason=f"fallback（MiniMind 不可用）: {reason}",
            mini_ran=False,
            intent_summary="MiniMind 不可用，明确进入 fallback，不伪装成 MiniMind 已理解。",
        )
        return d

    # ---------------- 完整运行 ----------------
    async def run(self, texts: list[str], context: Optional[dict] = None,
                  on_event: Optional[EventCb] = None) -> dict:
        t0 = time.time()
        ctx = context or {}
        decision = await self.decide(texts, ctx)
        # P1 双段：即时反应段先给调用方（流式前端先推），后台继续 MainBrain
        if (on_event and decision.response_mode == "immediate_then_final"
                and decision.immediate_reaction):
            try:
                await on_event("immediate_reaction",
                               {"text": decision.immediate_reaction,
                                "mode": decision.mode})
            except Exception as e:
                logger.warning(f"[BrainPipeline] on_event(immediate_reaction) 异常: {e}")
        chain = [{"step": "MessageGateway", "ts": round(time.time(), 3)},
                 {"step": "MiniMind", "ran": decision.mini_ran,
                  "candidate": decision.candidate_reply or "",
                  "backend": decision.backend, "model": decision.model},
                 {"step": "BrainDecision", "mode": decision.mode,
                  "need_tool": decision.need_tool, "need_vision": decision.need_vision}]

        reply_pieces = []
        main_text = ""
        comp = await self.complete(decision, {**ctx, "_user_texts": texts})
        reply_pieces = comp.get("pieces") or []
        main_text = comp.get("text") or ""
        chain.extend(comp.get("chain") or [])

        if not reply_pieces:
            chain.append({"step": "Empty", "warning": "无输出，不生成假回复"})

        return {
            "decision": decision.to_internal(),
            "mode": decision.mode,
            "reply_text": "".join(p.get("text", "") for p in reply_pieces),
            "pieces": reply_pieces,
            "chain": chain,
            "took_ms": round((time.time() - t0) * 1000.0, 1),
            "main_brain_text": main_text,
            "tool_evidence": comp.get("tool_evidence"),
        }


def _default_provider_getter():
    try:
        from runtime.manager import get_runtime_manager
        mgr = get_runtime_manager()
        return getattr(mgr, "realtime", None) if mgr else None
    except Exception:
        return None


def _default_tool_getter():
    try:
        from runtime.toolagent import tool_agent
        return tool_agent
    except Exception:
        return None


brain_pipeline = BrainPipeline()

__all__ = ["BrainPipeline", "brain_pipeline"]
