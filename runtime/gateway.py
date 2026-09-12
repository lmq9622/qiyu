# -*- coding: utf-8 -*-
"""Qiyu Runtime · MessageGateway（P0 骨架）。

P0 只把 Web 聊天入口收口到 BrainPipeline；P1 再把 pending queue、
微信、Telegram/Discord、主动消息、Storycheck 全部收口到这里。
"""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from runtime.brain.pipeline import BrainPipeline


class MessageGateway:
    def __init__(self, pipeline: Optional[BrainPipeline] = None) -> None:
        self.pipeline = pipeline or BrainPipeline()

    async def handle_web_chat(self, user_id: str, char_id: str,
                              texts: list[str], context: Optional[dict] = None,
                              on_event: Optional[Any] = None) -> dict:
        """P0：Web 一条主链路 = gateway → MiniMind/BrainPipeline。"""
        ctx = dict(context or {})
        ctx.setdefault("user_id", user_id)
        ctx.setdefault("char_id", char_id)
        result = await self.pipeline.run(texts, ctx, on_event=on_event)
        logger.info(f"[Gateway] web chat {user_id}/{char_id} -> mode={result.get('mode')} "
                    f"mini_ran={result.get('decision', {}).get('mini_ran')}")
        return result

    async def handle_wechat(self, user_id: str, char_id: str,
                            texts: list[str], context: Optional[dict] = None) -> dict:
        """P1：微信与 Web 同一条 Pipeline（MiniMind 永远是第一入口）。"""
        return await self.handle_web_chat(user_id, char_id, texts, context)

    async def handle_pending(self, user_id: str, char_id: str,
                             texts: list[str], context: Optional[dict] = None) -> dict:
        """P1：pending 批量进入 Pipeline 一次，而不是逐条 MainBrain。"""
        return await self.handle_web_chat(user_id, char_id, texts, context)

    async def handle_active(self, kind: str, user_id: str, char_id: str,
                            texts: list[str], context: Optional[dict] = None) -> dict:
        """P1：主动消息/Storycheck/reminder 等也先进 MiniMind Pipeline。
        kind ∈ proactive/story_check/reminder/webcheck/imagecheck/nudge。"""
        ctx = dict(context or {})
        ctx["active_kind"] = kind
        return await self.handle_web_chat(user_id, char_id, texts, ctx)


message_gateway = MessageGateway()

__all__ = ["MessageGateway", "message_gateway"]
