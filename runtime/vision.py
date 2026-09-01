# -*- coding: utf-8 -*-
"""Qiyu Runtime · VisionProvider（视觉层，规格§8/§44）。

- 不把视觉写死在某个 LLM：统一走 VisionProvider 接口。
- 当前分发的主视觉能力 = 「主模型多模态直通」（llama.cpp 多模态 / 云端多模态 API）：
  `MainBrainVisionProvider` 把图片交给已注册的 MainBrainProvider，图片理解延迟走
  PerformanceMonitor；主大脑不可用时如实上报 unavailable，绝不假装看图。
- 未来本地 Vision Encoder（SigLIP2 等）就位后，作为独立后端注册进同一接口（架构预留）。
"""
from __future__ import annotations

import time
from typing import Any, Optional

from loguru import logger

from runtime.providers import AIProvider, MainBrainProvider, ProviderKind, ProviderStatus


class MainBrainVisionProvider(AIProvider):
    """视觉 Provider：主大脑多模态直通（当前主实现）。

    图片 → 主模型（llama.cpp/云端多模态）→ 描述/回答。延迟记录到 PerformanceMonitor。
    """

    kind = ProviderKind.VISION
    id = "main-brain-vision"
    name = "Vision（主大脑多模态直通）"

    def __init__(self, main_brain: Optional[MainBrainProvider] = None) -> None:
        super().__init__()
        self._main_brain = main_brain

    def _vision_supported(self) -> bool:
        """主大脑是否支持图片输入：优先读运行时设置 vision_supported。"""
        try:
            from companion.settings import load_runtime_settings
            return bool(load_runtime_settings().get("vision_supported", False))
        except Exception:
            pass
        return False

    def probe(self) -> ProviderStatus:
        mb = self._main_brain
        if mb is None:
            return ProviderStatus(False, backend="", reason="未注入 MainBrainProvider")
        st = mb.status()
        if not st.available:
            return ProviderStatus(False, backend="", reason=f"主大脑不可用（{st.reason}）")
        if not self._vision_supported():
            return ProviderStatus(False, backend="api", reason="主模型未启用/不支持图片输入（vision_supported=false）")
        return ProviderStatus(True, backend="api", device=st.device)

    def status(self) -> ProviderStatus:
        return self.probe()

    async def describe(self, image: Any, prompt: str = "") -> str:
        """图片理解：image 支持 dataURL / http(s) URL / base64 字符串。

        走主大脑的 chat 多模态路径（与聊天链路一致），返回纯文本描述。
        """
        mb = self._main_brain
        if mb is None:
            raise RuntimeError("Vision Provider 未注入主大脑")
        st = self.probe()
        if not st.available:
            raise RuntimeError(f"Vision 不可用：{st.reason}")
        url = _normalize_image(image)
        user_text = prompt or "请描述这张图片里发生了什么，用真人口吻简短说。\n只输出一条纯文本回复。"
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        }]
        char_id = ""
        try:
            from characters import get_character_manager
            _d = get_character_manager().get_default()
            char_id = _d.id if _d else ""
        except Exception:
            pass
        t0 = time.time()
        from runtime.concurrency import concurrency_limiter
        from runtime.perf import perf_monitor
        async with concurrency_limiter.slot("vision"):
            try:
                reply, _pieces = await mb.chat(char_id, messages, user_id="vision_probe",
                                               use_memory=False, use_rag=False)
                return (reply or "").strip()
            finally:
                perf_monitor.record("vision_latency", value=(time.time() - t0) * 1000.0)


def _normalize_image(image: Any) -> str:
    if isinstance(image, str):
        if image.startswith("data:") or image.startswith("http"):
            return image
        return f"data:image/png;base64,{image}"
    return str(image)


vision_provider = None  # 由 demo 启动时注入 MainBrain 后赋值


__all__ = [
    "MainBrainVisionProvider",
    "_normalize_image",
    "vision_provider",
]
