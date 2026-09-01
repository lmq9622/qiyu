# -*- coding: utf-8 -*-
"""Qiyu Runtime · Realtime Brain Provider（M2）。

MiniMind-O 是产品自带的 Realtime Brain（Zero Setup），职责是实时反应/分流/打断/
短消息/判断是否需要 Main Brain，而不是替代 Main LLM。

诚实原则：当前分发若未内置 MiniMind-O 权重与推理运行库，UnavailableRealtimeBackend
必须如实上报 unavailable 并给出原因，由 RuntimeManager 走 Main Brain 兜底——
绝不用「假工具/假搜索/模板台词」冒充实时大脑。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from runtime.providers import (
    ProviderStatus,
    RealtimeBrainProvider,
    RealtimeDecision,
)


class UnavailableRealtimeBackend(RealtimeBrainProvider):
    """未配置 MiniMind-O 时的诚实兜底：全部路由给 Main Brain。

    当未来分发包内置 `models/realtime/`（MiniMind-O GGUF/ONNX 等）与对应推理
    运行库后，替换为 CPUBackend / VulkanBackend / CUDABackend 的真实实现，
    本类作为 `disable_realtime_brain` 开关的兜底保留。
    """

    id = "unavailable"
    name = "Realtime Brain（未配置）"

    def __init__(self, reason: str = "未内置 MiniMind-O 权重/运行库（Zero Setup 下回退 Main Brain）"):
        super().__init__()
        self._reason = reason
        self._status = ProviderStatus(available=False, backend="", reason=reason)

    def probe(self) -> ProviderStatus:
        return self._status

    async def judge(self, user_text: str, context: Optional[dict] = None) -> RealtimeDecision:
        return RealtimeDecision(
            needs_main_brain=True,
            quick_reply=None,
            reason=self._reason,
            backend="",
        )


# 预留：以下类在 MiniMind-O 组件就位后实现（每个组件可独立选择 Device/Backend）
# class CPURealtimeBackend(RealtimeBrainProvider): ...
# class VulkanRealtimeBackend(RealtimeBrainProvider): ...
# class CUDARealtimeBackend(RealtimeBrainProvider): ...
