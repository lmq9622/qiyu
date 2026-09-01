# -*- coding: utf-8 -*-
"""Qiyu Runtime · 本地 Main Brain（规格§7/§9 LOCAL MODE）。

Main Brain 使用 llama.cpp，模型优先 GGUF，backend=CPU/Vulkan/CUDA。
`LlamaCppMainBrainProvider` 实现 MainBrainProvider：本地 GGUF 走 llama-cpp-python，
不可用时如实上报 unavailable（业务层自动切回远端 API / 提示用户配置），绝不假装能本地推理。

LOCAL MODE：所有模型本地运行；CLOUD/REMOTE MODE：OpenAI-compatible API。
统一通过 MainBrainProvider 访问（规格§8），业务层不感知切换。
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from runtime.providers import MainBrainProvider, ProviderStatus


def _default_models_dir() -> Path:
    try:
        from companion.state import get_resource_path
        base = Path(get_resource_path()) / "models" / "main"
    except Exception:
        base = Path(__file__).resolve().parent.parent / "models" / "main"
    base.mkdir(parents=True, exist_ok=True)
    return base


def find_local_model() -> str:
    """在 models/main/ 找第一个 .gguf（本地主模型）。"""
    base = _default_models_dir()
    try:
        for p in sorted(base.rglob("*.gguf")):
            if p.stat().st_size > 10 * 1024 * 1024:
                return str(p)
    except Exception:
        pass
    return ""


class LlamaCppMainBrainProvider(MainBrainProvider):
    """本地 llama.cpp 主大脑（GGUF）。"""

    id = "llamacpp-local"
    name = "Main LLM（本地 llama.cpp / GGUF）"

    def __init__(self, model_path: str = "", backend: str = "") -> None:
        super().__init__()
        self._model_path = model_path or find_local_model()
        self._backend = backend or "auto"
        self._llm = None
        self._load_error = ""

    def _import(self):
        try:
            import llama_cpp  # noqa: F401
            return llama_cpp
        except Exception:
            return None

    def probe(self) -> ProviderStatus:
        if self._import() is None:
            return ProviderStatus(False, backend="", reason="未安装 llama-cpp-python（本地模式可选依赖）")
        if not self._model_path:
            return ProviderStatus(False, backend="", reason="models/main/ 没有 GGUF 模型；请用 tools/install_models.py 下载")
        if self._load_error:
            return ProviderStatus(False, backend="", reason=f"模型加载失败: {self._load_error[:120]}")
        return ProviderStatus(True, backend=self._backend if self._backend != "auto" else "cpu",
                              device=self._model_path)

    def status(self) -> ProviderStatus:
        return self.probe()

    def _ensure(self):
        if self._llm is not None:
            return self._llm
        lc = self._import()
        if lc is None or not self._model_path:
            return None
        try:
            gpu = 0
            if self._backend == "cuda":
                gpu = 99
            elif self._backend == "vulkan":
                gpu = 99
            self._llm = lc.Llama(model_path=self._model_path, n_ctx=8192,
                                 n_gpu_layers=gpu, verbose=False)
        except Exception as e:
            self._load_error = str(e)
            logger.warning(f"[MainBrain] 本地模型加载失败: {e}")
            self._llm = None
        return self._llm

    async def chat(self, char_id: str, messages: list, user_id: str = "",
                   channel=None, **kwargs) -> tuple[str, list]:
        llm = self._ensure()
        if llm is None:
            raise RuntimeError(f"本地 Main Brain 不可用: {self.probe().reason}")
        prompt = _messages_to_prompt(messages)
        out = llm.create_completion(prompt, max_tokens=1024, temperature=0.7, stop=["</s>", "<|im_end|>"])
        text = ((out.get("choices") or [{}])[0].get("text") or "").strip()
        return text, [{"text": text, "type": "statement", "delay": 0}]

    async def chat_stream(self, char_id: str, messages: list, user_id: str = "",
                          channel=None, **kwargs):
        llm = self._ensure()
        if llm is None:
            raise RuntimeError(f"本地 Main Brain 不可用: {self.probe().reason}")
        prompt = _messages_to_prompt(messages)
        for chunk in llm.create_completion(prompt, max_tokens=1024, temperature=0.7,
                                           stream=True, stop=["</s>", "<|im_end|>"]):
            delta = (chunk.get("choices") or [{}])[0].get("text") or ""
            yield "", delta

    async def complete(self, prompt: str, *, max_tokens: int = 512,
                       temperature: float = 0.7, **kwargs) -> str:
        llm = self._ensure()
        if llm is None:
            raise RuntimeError(f"本地 Main Brain 不可用: {self.probe().reason}")
        out = llm.create_completion(prompt, max_tokens=max_tokens, temperature=temperature,
                                    stop=["</s>", "<|im_end|>"])
        return ((out.get("choices") or [{}])[0].get("text") or "").strip()


def _messages_to_prompt(messages: list) -> str:
    lines = []
    for m in messages or []:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            parts = []
            for it in content:
                if isinstance(it, dict):
                    parts.append(it.get("text") or "[图片]")
            content = " ".join(parts)
        lines.append(f"{'用户' if role == 'user' else 'AI'}: {content or ''}")
    return "\n".join(lines) + "\nAI:"


local_main_brain = LlamaCppMainBrainProvider()

__all__ = [
    "LlamaCppMainBrainProvider",
    "find_local_model",
    "local_main_brain",
]
