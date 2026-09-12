# -*- coding: utf-8 -*-
"""Qiyu Runtime · BrainRouter（大小脑真实路由，v0.0.27 目标）。

用户输入统一先到这里：
  1. 轻量规则分类（不依赖模型 JSON）；
  2. 简单消息 → RealtimeBrain（MiniMind）真实 analyze；
  3. 失败/低置信/复杂 → MainBrain；
  4. 返回统一 RouteResult，demo 只消费这个结果。

本模块不做空壳：demo.py 的聊天主链路会真正调用它；MainBrain 实际生成仍在
原有 llm_client 链路执行（不删除），Router 只负责“该谁上”。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from runtime.providers import ProviderKind, RealtimeBrainProvider


@dataclass
class RouteResult:
    """统一路由结果。business 只消费这个，不直接碰 MiniMind backend。"""
    router_decision: str = "main_brain"      # realtime / main_brain / skip
    quick_reply: Optional[str] = None
    reason: str = ""
    confidence: float = 0.0
    category: str = ""
    emotion: Optional[str] = None
    backend: str = ""
    model: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def needs_main_brain(self) -> bool:
        return self.router_decision != "realtime"


ProviderGetter = Callable[[], Optional[RealtimeBrainProvider]]
ClassifierFn = Callable[..., Any]


class BrainRouter:
    """把 demo 里散落的简单/复杂判断收口成真正调用的路由。"""

    def __init__(self, provider_getter: Optional[ProviderGetter] = None) -> None:
        self._provider_getter = provider_getter

    # ---------- 轻量路由（先于模型，稳定且永不阻塞） ----------
    def classify(self, text: str, images: bool = False, web_enabled: bool = True) -> Any:
        from runtime.classifier import classify_user_message
        return classify_user_message(text, has_images=images, web_enabled=web_enabled)

    @staticmethod
    def _route_confidence(text: str, action: str, category: str) -> float:
        from runtime.classifier import route_confidence
        return route_confidence(text, action, category)

    # ---------- MiniMind / MainBrain ----------
    async def route_message(self, user_text: str, context: Optional[dict] = None,
                            provider: Optional[RealtimeBrainProvider] = None) -> RouteResult:
        """单条用户消息的大小脑路由。

        - 复杂/图片/长文/工具/记忆 → MainBrain
        - 简单/情绪且置信度达标 → MiniMind.analyze
        - MiniMind 不可用/输出不合格 → MainBrain（绝不因小脑失败中断聊天）
        """
        text = (user_text or "").strip()
        ctx = context or {}
        # 规格 §23：小脑线已废弃（0.05.24），运行时默认不再调用旧 MiniMind。
        # 想临时对比，必须显式设 QIYU_ENABLE_MINIMIND_LEGACY=1。
        from runtime.legacy_gate import log_once, minimind_enabled
        if not minimind_enabled():
            log_once(logger, "BrainRouter.route_message")
            return RouteResult(router_decision="main_brain",
                               reason="MiniMind 小脑线已废弃（0.05.24）→ MainBrain",
                               category="legacy_disabled")
        if not text:
            return RouteResult(router_decision="main_brain", reason="空消息 → MainBrain", category="empty")
        try:
            route = self.classify(text, images=bool(ctx.get("images")),
                                  web_enabled=bool(ctx.get("web_enabled", True)))
        except Exception as e:
            logger.warning(f"[BrainRouter] 分类失败 → MainBrain: {e}")
            return RouteResult(router_decision="main_brain", reason=f"classifier error: {e}", category="classifier_error")

        conf = self._route_confidence(text, route.action, route.category)
        role_ctx = str(ctx.get("role_context") or "")
        has_relevant_memory = "【相关记忆" in role_ctx
        memory_can_try = (has_relevant_memory and len(text) <= 60
                          and route.category in ("memory_query", "complex_question", "other", "simple_chat"))
        if route.action == "main_brain" or conf < 0.78:
            if not memory_can_try:
                return RouteResult(
                    router_decision="main_brain",
                    reason=route.reason or "规则 → MainBrain",
                    confidence=conf, category=route.category)
        if route.action == "main_brain" and not memory_can_try:
            return RouteResult(
                router_decision="main_brain",
                reason=route.reason or "规则 → MainBrain",
                confidence=conf, category=route.category)

        rt = provider or (self._provider_getter() if self._provider_getter else None)
        if rt is None:
            return RouteResult(router_decision="main_brain", reason="Realtime Provider 未就绪 → MainBrain",
                               confidence=conf, category=route.category)
        try:
            analysis = await rt.analyze(text, ctx)
        except Exception as e:
            logger.warning(f"[BrainRouter] MiniMind analyze 异常 → MainBrain: {e}")
            return RouteResult(router_decision="main_brain", reason=f"analyze error: {e}",
                               confidence=conf, category=route.category)

        if analysis.get("needs_main_brain") or not str(analysis.get("quick_reply") or "").strip():
            return RouteResult(
                router_decision="main_brain",
                reason=analysis.get("reason") or "MiniMind 输出不合格 → MainBrain",
                confidence=float(analysis.get("confidence") or conf),
                category=analysis.get("category") or route.category,
                backend=analysis.get("backend", ""), model=analysis.get("model", ""),
                meta=analysis.get("meta") or {})

        return RouteResult(
            router_decision="realtime",
            quick_reply=str(analysis.get("quick_reply")),
            reason=analysis.get("reason") or route.reason,
            confidence=float(analysis.get("confidence") or conf),
            category=analysis.get("category") or route.category,
            emotion=analysis.get("emotion"),
            backend=analysis.get("backend", ""), model=analysis.get("model", ""),
            meta=analysis.get("meta") or {},
        )

    # ---------- 兼容当前 demo：只尝试简单直答；复杂直接让原链路走 MainBrain ----------
    async def try_realtime_direct(self, text: str, context: Optional[dict] = None) -> Optional[RouteResult]:
        result = await self.route_message(text, context)
        return result if result.router_decision == "realtime" else None


def _default_provider_getter():
    try:
        from runtime.manager import get_runtime_manager
        mgr = get_runtime_manager()
        return getattr(mgr, "realtime", None) if mgr is not None else None
    except Exception:
        return None


# demo.py 启动时会把全局 brain_router 替换成绑定 runtime_manager 的实例
brain_router = BrainRouter(provider_getter=_default_provider_getter)

__all__ = ["BrainRouter", "RouteResult", "brain_router"]
