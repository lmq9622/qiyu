# -*- coding: utf-8 -*-
"""Qiyu Runtime · EmbeddingProvider（向量化，规格§8）。

- 优先 sentence-transformers + bge-small-zh-v1.5（本地，中文检索效果好）；
- 未安装（当前打包排除 torch/transformers）→ 如实 unavailable，
  MemoryProvider 自动回退 bag-of-words（低端设备底线，规格§26）。
- 探测用 find_spec（毫秒级，不阻塞事件循环）；模型加载保持懒执行，
  首次 embed() 时才真正导入 torch/sentence-transformers。
"""
from __future__ import annotations

import importlib.util
from typing import Optional

from loguru import logger

from runtime.providers import AIProvider, ProviderKind, ProviderStatus

_EMBED_MODEL = "BAAI/bge-small-zh-v1.5"


class SentenceTransformersEmbeddingProvider(AIProvider):
    """本地 embedding（sentence-transformers）。模型懒加载，失败不阻塞。"""

    kind = ProviderKind.EMBEDDING
    id = "sentence-transformers"
    name = "Embedding（bge-small-zh-v1.5 本地向量化）"

    def __init__(self, model_name: str = _EMBED_MODEL) -> None:
        super().__init__()
        self._model_name = model_name
        self._model = None
        self._load_error = ""

    def _installed(self) -> bool:
        """快路径：包是否存在（不导入 torch，毫秒级）。"""
        try:
            return importlib.util.find_spec("sentence_transformers") is not None
        except Exception:
            return False

    def _import(self):
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
            return SentenceTransformer
        except Exception:
            return None

    def probe(self) -> ProviderStatus:
        if not self._installed():
            return ProviderStatus(False, backend="", reason="未安装 sentence-transformers（可选依赖）")
        if self._load_error:
            return ProviderStatus(False, backend="", reason=f"模型加载失败: {self._load_error[:120]}")
        # 已安装即视为可用（首次 embed() 时才懒加载权重，避免阻塞启动）
        return ProviderStatus(True, backend="cpu", device=self._model_name,
                              reason="已安装（权重懒加载，首次调用时加载）")

    def status(self) -> ProviderStatus:
        return self.probe()

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        ST = self._import()
        if ST is None:
            return None
        try:
            self._model = ST(self._model_name)
        except Exception as e:
            self._load_error = str(e)
            logger.warning(f"[Embedding] 模型加载失败: {e}")
            self._model = None
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化；失败返回空列表（调用方回退 bag-of-words）。"""
        model = self._ensure_model()
        if model is None:
            return []
        try:
            vecs = model.encode([t or "" for t in texts], normalize_embeddings=True)
            return [[float(x) for x in v] for v in vecs]
        except Exception as e:
            logger.warning(f"[Embedding] 编码失败: {e}")
            return []


embedding_provider = SentenceTransformersEmbeddingProvider()

__all__ = ["SentenceTransformersEmbeddingProvider", "embedding_provider"]
