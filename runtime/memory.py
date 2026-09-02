# -*- coding: utf-8 -*-
"""Qiyu Memory Provider（记忆分层，M4）。

规格（记忆系统 + 低端设备优先）：检索层不绑定具体向量库——
- 默认 backend = bag-of-words（memory.SimpleVectorizer，零依赖、低端设备可用）；
- 若注册了可用 EmbeddingProvider，则自动升级为 embedding 优先，并保留 bag-of-words 兜底。
业务层只调用 MemoryProvider，不直接碰 VectorStore / 向量库实现。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from runtime.providers import AIProvider, EmbeddingProvider, ProviderKind, ProviderStatus


class MemoryProvider(AIProvider):
    """Companion Memory：分层检索（bag-of-words / embedding 自由切换，诚实上报 backend）。"""

    kind = ProviderKind.MEMORY
    id = "companion-memory"
    name = "Companion Memory（bag-of-words / embedding 分层检索）"

    def __init__(self, memory_manager=None) -> None:
        super().__init__()
        self._mem = memory_manager
        self._embedding: Optional[EmbeddingProvider] = None

    def attach_embedding(self, provider: Optional[EmbeddingProvider]) -> None:
        """注入 embedding 层；没有或不可用时自动回退 bag-of-words。"""
        self._embedding = provider

    @property
    def mem(self):
        return self._mem

    def probe(self) -> ProviderStatus:
        backend = "bag-of-words"
        reason = ""
        device = "memory/VectorStore"
        if self._embedding is not None:
            st = self._embedding.status()
            if st.available:
                backend = f"embedding({st.backend})+bag-of-words"
            else:
                reason = f"embedding 不可用（{st.reason}），回退 bag-of-words"
        return ProviderStatus(
            available=self._mem is not None,
            backend=backend,
            device=device,
            reason=reason,
        )

    def status(self) -> ProviderStatus:
        return self.probe()

    async def retrieve(self, user_id: str, query: str, char_id: str = "",
                       top_k: int = 5) -> list:
        """结构化召回：优先走 embedding 重排；embedding 不可用则用 bag-of-words 检索。

        返回 [{text, score, ...}]；失败返回 []（调用方自行兜底）。
        """
        import time as _t
        _t0 = _t.time()
        try:
            return await self._retrieve_inner(user_id, query, char_id, top_k)
        finally:
            try:
                from runtime.perf import perf_monitor
                perf_monitor.record("memory_retrieve", value=(_t.time() - _t0) * 1000.0)
            except Exception:
                pass

    async def _retrieve_inner(self, user_id: str, query: str, char_id: str = "",
                              top_k: int = 5) -> list:
        from runtime.concurrency import concurrency_limiter
        async with concurrency_limiter.slot("memory"):
            return await self._retrieve_slot(user_id, query, char_id, top_k)

    async def _retrieve_slot(self, user_id: str, query: str, char_id: str = "",
                             top_k: int = 5) -> list:
        if self._mem is None:
            return []
        try:
            store = self._mem._get_store(user_id, char_id)
        except Exception:
            store = None
        if store is None:
            return []
        # embedding 可用 → 整批向量化后按余弦相似度排序（与 bag-of-words 向量维度不同，不能混算）
        if self._embedding is not None and self._embedding.status().available:
            try:
                entries = store.list_all()
                if not entries:
                    return []
                texts = [e.get("text") or "" for e in entries]
                vecs = await self._embedding.embed(texts)
                qv = (await self._embedding.embed([query]))[0]
                scored = []
                for e, v in zip(entries, vecs):
                    if not v:
                        continue
                    dot = sum(a * b for a, b in zip(qv, v))
                    scored.append({**e, "score": round(dot, 4)})
                scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
                return scored[:top_k]
            except Exception as e:
                logger.warning(f"[Memory] embedding 重排失败，保留 bag-of-words 结果: {e}")
        out = store.search(query, top_k=top_k)
        try:
            from runtime.logging_setup import logger_mem
            logger_mem.info(
                f"[retrieve] user={user_id} char={char_id} query={query[:80]!r} "
                f"hits={len(out)} backend={self.probe().backend}"
            )
        except Exception:
            pass
        return out

    def context(self, user_id: str, query: str, char_id: str = "", top_k: int = 5) -> str:
        """返回给提示词用的上下文文本（生产路径：bag-of-words，与旧行为一致）。"""
        if self._mem is None:
            return ""
        return self._mem.get_context(user_id, query, char_id, top_k=top_k)


__all__ = [
    "MemoryProvider",
]
