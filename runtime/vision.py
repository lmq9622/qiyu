# -*- coding: utf-8 -*-
"""Qiyu Runtime · VisionProvider（视觉层，规格§8/§44）。

- 不把视觉写死在某个 LLM：统一走 VisionProvider 接口。
- 当前分发的主视觉能力 = 「主模型多模态直通」（llama.cpp 多模态 / 云端多模态 API）：
  `MainBrainVisionProvider` 把图片交给已注册的 MainBrainProvider，图片理解延迟走
  PerformanceMonitor；主大脑不可用时如实上报 unavailable，绝不假装看图。
- 视觉支持判定 = 启动后真实探测（发一张 1x1 测试图给主模型，能返回非空内容才算支持），
  不再只信静态设置；模型/地址变化时自动重新探测。
- 未来本地 Vision Encoder（SigLIP2 等）就位后，作为独立后端注册进同一接口（架构预留）。
"""
from __future__ import annotations

import base64
import struct
import time
import zlib
from typing import Any, Optional

import httpx
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
        self._vision_ok: Optional[bool] = None   # 真实探测结果缓存
        self._vision_key: tuple = ("", "")
        self._vision_reason = "尚未探测"

    def _vision_supported(self) -> bool:
        """主大脑是否支持图片输入：启动后真实探测一次并缓存（发一张 1x1 测试图，
        主模型能返回非空正文/推理内容才算支持；模型或地址变化时自动重新探测）。"""
        if self._vision_ok is not None:
            key = self._probe_key()
            if key == self._vision_key:
                return self._vision_ok
        self._vision_key = self._probe_key()
        self._vision_ok = self._probe_vision_once()
        if self._vision_ok:
            logger.success("[Vision] 主模型视觉能力探测通过（真实图片输入验证）")
        else:
            logger.warning(f"[Vision] 主模型视觉能力探测未通过: {self._vision_reason}")
        return self._vision_ok

    def _probe_key(self) -> tuple:
        try:
            from companion.settings import load_runtime_settings
            rt = load_runtime_settings()
            return (str(rt.get("llm_url") or ""), str(rt.get("llm_model") or ""))
        except Exception:
            return ("", "")

    def _probe_vision_once(self) -> bool:
        """真实探测：把 1x1 红色 PNG 发给主模型，能返回非空内容才判定支持视觉。"""
        try:
            from companion.settings import load_runtime_settings
            rt = load_runtime_settings()
        except Exception:
            rt = {}
        url = str(rt.get("llm_url") or "").rstrip("/")
        model = str(rt.get("llm_model") or "")
        api_key = str(rt.get("api_key") or "")
        if not url or not model:
            self._vision_reason = "未配置主模型地址/模型名"
            return False
        payload = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "这张图是什么颜色？"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_tiny_red_png_b64()}"}},
                ],
            }],
            "max_tokens": 128,
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        try:
            resp = httpx.post(f"{url}/chat/completions", json=payload, headers=headers, timeout=30)
            if resp.status_code == 400:
                self._vision_reason = "该模型不支持图片输入（vision 接口返回 400）"
                return False
            if resp.status_code != 200:
                self._vision_reason = f"vision 探测返回 HTTP {resp.status_code}"
                return False
            msg = (resp.json().get("choices") or [{}])[0].get("message") or {}
            content = (msg.get("content") or "").strip()
            if not content:
                content = (msg.get("reasoning_content") or "").strip()
            if content:
                self._vision_reason = f"模型接受了图片请求并返回内容（{content[:20]}…）"
                return True
            self._vision_reason = "模型对图片请求返回空正文"
            return False
        except Exception as e:
            self._vision_reason = f"vision 探测失败（{type(e).__name__}: {e}）"
            return False

    def probe(self) -> ProviderStatus:
        mb = self._main_brain
        if mb is None:
            return ProviderStatus(False, backend="", reason="未注入 MainBrainProvider")
        st = mb.status()
        if not st.available:
            return ProviderStatus(False, backend="", reason=f"主大脑不可用（{st.reason}）")
        if not self._vision_supported():
            return ProviderStatus(False, backend="api", reason=f"主模型不支持图片输入（{self._vision_reason}）")
        return ProviderStatus(True, backend="api", device=st.device, reason=self._vision_reason)

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


def _tiny_red_png_b64() -> str:
    """生成 1x1 红色 PNG 的 base64 data（视觉能力探测用，避免依赖外部资源）。"""
    def _png_chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = _png_chunk(b"IDAT", zlib.compress(b"\x00" + bytes([255, 0, 0])))
    iend = _png_chunk(b"IEND", b"")
    return base64.b64encode(sig + ihdr + idat + iend).decode()


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
    "_tiny_red_png_b64",
    "vision_provider",
]
