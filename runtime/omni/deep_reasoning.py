# -*- coding: utf-8 -*-
"""深推理后端（DeepReasoningBackend）：把 MainBrain 接成 Omni 的按需下游。

架构位置（规格 B / L）：

    Realtime Omni --(只有复杂任务)--> DeepReasoningBackend --> 结果回注 Omni Session

这里实现的是一个 **OpenAI 兼容** 的调用适配器（仓库既有 MainBrain 走的就是这个协议，
默认指向本机/局域网 llama.cpp，例如 ``http://192.168.2.6:8081/v1``）。

约束：
- **默认不参与主链**：只有 ``maybe_deep_reason()`` 判定为复杂任务时才调用；
- 调用结果只是「补充信息」，回到 Omni 会话继续走对话，不直接产生 AvatarIntent；
- 无 LLM 可用时明确返回 available=False，不伪造结果。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx


@dataclass
class DeepReasoningConfig:
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    timeout_s: float = 60.0
    max_tokens: int = 512
    temperature: float = 0.6
    system_prompt: str = (
        "你是栖语的深度推理后端。用户在实时对话里提出了复杂问题，"
        "请给出准确、简洁、可执行的中文回答，不要寒暄。")
    require_keywords: tuple = ("计划", "步骤", "分析", "对比", "为什么", "方案",
                               "写一段", "帮我写", "计算", "推理", "总结", "代码")
    min_chars: int = 40

    @staticmethod
    def from_env() -> "DeepReasoningConfig":
        return DeepReasoningConfig(
            base_url=os.getenv("LLM_BASE_URL", "http://192.168.2.6:8081/v1"),
            model=os.getenv("LLM_MODEL", "qwen3.8-27b"),
            api_key=os.getenv("LLM_API_KEY", ""),
            timeout_s=float(os.getenv("DEEP_REASONING_TIMEOUT", "60")),
            max_tokens=int(os.getenv("DEEP_REASONING_MAX_TOKENS", "512")),
        )


class MainBrainDeepReasoning:
    """MainBrain 侧的深推理适配器（OpenAI 兼容 /chat/completions）。"""

    def __init__(self, config: Optional[DeepReasoningConfig] = None):
        self.config = config or DeepReasoningConfig.from_env()
        self.calls = 0
        self.failures = 0
        self.last_latency_ms = 0.0

    # ---------- 可用性 ----------
    async def available(self) -> bool:
        url = self.config.base_url.rstrip("/") + "/models"
        try:
            async with httpx.AsyncClient(timeout=6.0) as c:
                r = await c.get(url, headers=self._headers())
                return r.status_code < 500
        except Exception:
            return False

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.config.api_key:
            h["Authorization"] = f"Bearer {self.config.api_key}"
        return h

    # ---------- 复杂度闸门 ----------
    def is_complex(self, text: str, context: Optional[dict] = None) -> bool:
        """规则判定「是否需要深推理」。宁可漏判也不要把每句闲聊都送过去。"""
        if not text:
            return False
        ctx = context or {}
        if ctx.get("force_deep_reasoning"):
            return True
        if len(text) >= self.config.min_chars:
            return True
        return any(k in text for k in self.config.require_keywords)

    # ---------- 调用 ----------
    async def __call__(self, text: str, context: Optional[dict] = None) -> dict:
        ctx = context or {}
        messages = []
        system = ctx.get("system_prompt") or self.config.system_prompt
        messages.append({"role": "system", "content": system})
        for h in (ctx.get("history") or [])[-6:]:
            if isinstance(h, dict) and h.get("role") and h.get("content"):
                messages.append({"role": h["role"], "content": str(h["content"])})
        messages.append({"role": "user", "content": text})

        payload = {"model": self.config.model, "messages": messages,
                   "temperature": self.config.temperature,
                   "max_tokens": self.config.max_tokens, "stream": False}
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        t0 = time.perf_counter()
        self.calls += 1
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_s) as c:
                r = await c.post(url, headers=self._headers(), json=payload)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            self.failures += 1
            return {"ok": False, "error": f"{type(e).__name__}: {e}",
                    "backend": "mainbrain", "model": self.config.model}
        self.last_latency_ms = (time.perf_counter() - t0) * 1000.0
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            content = ""
        return {"ok": True, "text": content, "backend": "mainbrain",
                "model": data.get("model", self.config.model),
                "latency_ms": round(self.last_latency_ms, 1),
                "usage": data.get("usage") or {}}

    def stats(self) -> dict:
        return {"calls": self.calls, "failures": self.failures,
                "last_latency_ms": round(self.last_latency_ms, 1),
                "model": self.config.model, "base_url": self.config.base_url}


def build_deep_reasoning(config: Optional[DeepReasoningConfig] = None):
    """工厂：主链默认用这个。"""
    return MainBrainDeepReasoning(config)
