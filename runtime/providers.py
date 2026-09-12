# -*- coding: utf-8 -*-
"""Qiyu Runtime · Provider 抽象（M2）。

原则：
- 业务层不直接调用 transformers / torch / llama.cpp / OpenAI API / MiniMind。
- 所有 AI 能力通过 Provider 接口访问，未来 Local / Cloud / API / Self-host 自由切换。
- 不把 Vulkan / CUDA 写死：backend 由 HardwareDetector + 能力探测共同决定。
- 不假装可用：Provider 必须诚实上报 available 与原因，不可用则走兜底。
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from loguru import logger


class ProviderKind(str, enum.Enum):
    """Provider 能力分类（对应架构图中的各 Brain / 外围模块）"""
    REALTIME_BRAIN = "realtime_brain"   # MiniMind-O 实时大脑
    MAIN_BRAIN = "main_brain"           # 主大脑（复杂聊天/长上下文/推理）
    VISION = "vision"                   # 图片理解
    STT = "stt"                         # 语音识别
    TTS = "tts"                         # 语音合成
    EMBEDDING = "embedding"             # 向量化
    TOOL = "tool"                       # 工具/搜索执行
    MEMORY = "memory"                   # 记忆（分层检索：bag-of-words / embedding）
    AVATAR = "avatar"                   # 头像（Live2D / VRC / 未来 3D）
    PLATFORM = "platform"               # 消息平台（微信 / Telegram / Discord / 预留）


@dataclass
class ProviderStatus:
    """Provider 诚实状态"""
    available: bool
    backend: str = ""              # cpu / vulkan / cuda / api / ...
    device: str = ""               # 具体设备名
    reason: str = ""               # 不可用时的原因（不要留空）
    latency_ms: float = 0.0
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "backend": self.backend,
            "device": self.device,
            "reason": self.reason,
            "latency_ms": round(self.latency_ms, 1),
            "checked_at": round(self.checked_at, 3),
        }


class AIProvider:
    """所有 AI Provider 的基类"""

    kind: ProviderKind = ProviderKind.MAIN_BRAIN
    id: str = "base"
    name: str = "Base Provider"

    def __init__(self) -> None:
        self._status: Optional[ProviderStatus] = None

    def status(self) -> ProviderStatus:
        """返回当前状态；未探测过时先探测一次。"""
        if self._status is None:
            self._status = self.probe()
        return self._status

    def probe(self) -> ProviderStatus:
        """诚实探测可用性（子类必须实现）。"""
        return ProviderStatus(available=False, reason="未实现")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind.value,
            "status": self.status().to_dict(),
        }


class MainBrainProvider(AIProvider):
    """主大脑：复杂聊天 / 长上下文 / 复杂推理 / 工具调用 / 搜索。

    与具体供应商解耦：OpenAI-compatible API、llama.cpp、LM Studio、Ollama 等
    都通过同一个接口接入。
    """

    kind = ProviderKind.MAIN_BRAIN

    async def chat(self, char_id: str, messages: list, user_id: str = "",
                   channel=None, **kwargs) -> tuple[str, list]:
        raise NotImplementedError

    async def chat_stream(self, char_id: str, messages: list, user_id: str = "",
                          channel=None, **kwargs) -> AsyncIterator[dict]:
        raise NotImplementedError

    async def complete(self, prompt: str, *, max_tokens: int = 512,
                       temperature: float = 0.7, **kwargs) -> str:
        raise NotImplementedError


class RealtimeDecision:
    """Realtime Brain 的单轮判断结果。

    由 RealtimeBrainProvider 产出，Main Brain / 调度器根据它决定：
    是否需要主大脑、是否可即时短回复、情绪反应、是否打断、是否等待。
    """

    def __init__(self, needs_main_brain: bool = True,
                 quick_reply: Optional[str] = None,
                 emotion: Optional[str] = None,
                 is_interruption: bool = False,
                 should_wait: bool = False,
                 reason: str = "",
                 backend: str = "",
                 model: str = "",
                 confidence: float = 0.0,
                 category: str = "",
                 judge_source: str = ""):
        self.needs_main_brain = needs_main_brain
        self.quick_reply = quick_reply
        self.emotion = emotion
        self.is_interruption = is_interruption
        self.should_wait = should_wait
        self.reason = reason
        self.backend = backend
        self.model = model
        self.confidence = confidence
        self.category = category
        self.judge_source = judge_source

    def to_dict(self) -> dict:
        return {
            "needs_main_brain": self.needs_main_brain,
            "quick_reply": self.quick_reply,
            "emotion": self.emotion,
            "is_interruption": self.is_interruption,
            "should_wait": self.should_wait,
            "reason": self.reason,
            "backend": self.backend,
            "model": self.model,
            "confidence": round(self.confidence, 3),
            "category": self.category,
            "judge_source": self.judge_source,
        }


class RealtimeBrainProvider(AIProvider):
    """实时大脑（MiniMind-O 的目标接口）。

    职责：实时聊天反应 / 简单判断 / 情绪反应 / 用户输入分流 / 打断处理 /
    短消息生成 / 判断是否需要 Main Brain / 判断是否需要工具 / 是否等待。
    不做复杂推理——那是 Main Brain 的事。

    注意：不要把「0.1B Transformer」等同于「整个 Omni 管线」；完整 Omni
    Pipeline 由 Thinker/Talker/SenseVoice/SigLIP2/Mimi/VAD/Codec 等组件组成，
    每个组件可以有自己的 Device / Backend capability（允许 CPU/GPU 混合）。
    """

    kind = ProviderKind.REALTIME_BRAIN

    async def judge(self, user_text: str, context: Optional[dict] = None) -> RealtimeDecision:
        """对用户输入做一次实时判断。"""
        raise NotImplementedError

    async def quick_reply(self, user_text: str, *, max_tokens: int = 48,
                          timeout_s: float = 6.0, char_hint: str = "") -> Optional[dict]:
        """真实 Realtime Brain 直接回话：简单闲聊/情绪反应由本模型直接产出短回复。

        返回 {"text", "backend", "model", "ttft_ms", "took_ms"} 或 None（不可用/超时/
        输出不合格 → 调用方自动升级 Main Brain）。绝不抛异常阻塞聊天。
        """
        raise NotImplementedError

    # ========== v0.0.26 统一运行接口 ==========
    async def load(self, backend: str = "auto", **kwargs) -> dict:
        """加载选中（或指定）的 Realtime Brain 后端。

        返回统一结构：
        {"ok", "backend", "model", "device", "load_ms", "ram_mb", "reason"}。
        """
        raise NotImplementedError

    async def unload(self, backend: str = "auto") -> dict:
        """卸载模型并释放内存；返回 {"ok", "freed_backends", "reason"}。"""
        raise NotImplementedError

    async def analyze(self, user_text: str, context: Optional[dict] = None) -> dict:
        """统一实时判断：路由 + 置信度 + 可用即返回角色化 quick reply。

        返回统一结构（业务层不再需要知道 official/gguf/vulkan/cuda）：
        {
          "needs_main_brain": bool,
          "quick_reply": str|None,
          "confidence": float,
          "category": str,
          "emotion": str|None,
          "backend": str,
          "model": str,
          "judge_source": str,
          "reason": str,
          "meta": {...}   # 直答计时/质量信息（不可用时为空 dict）
        }
        """
        raise NotImplementedError

    async def benchmark(self) -> list[dict]:
        """对当前所有真实可用后端做实测，返回排序后的统一结果列表。"""
        raise NotImplementedError

    def health(self) -> dict:
        """当前 Realtime Brain 健康状态（同步、便宜；加载等重操作不在此发生）。"""
        raise NotImplementedError


class VisionProvider(AIProvider):
    """图片理解（外围模块，不依赖具体 LLM）"""
    kind = ProviderKind.VISION

    async def describe(self, image: Any, prompt: str = "") -> str:
        raise NotImplementedError


class STTProvider(AIProvider):
    """语音识别"""
    kind = ProviderKind.STT

    async def transcribe(self, audio: Any) -> str:
        raise NotImplementedError


class TTSProvider(AIProvider):
    """语音合成"""
    kind = ProviderKind.TTS

    async def synthesize(self, text: str, **kwargs) -> Any:
        raise NotImplementedError


class EmbeddingProvider(AIProvider):
    """向量化"""
    kind = ProviderKind.EMBEDDING

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class ProviderRegistry:
    """Provider 注册表：业务层通过 kind 取能力，支持兜底链。"""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._fallback: dict[str, list[str]] = {}

    def register(self, provider: AIProvider, fallback_ids: Optional[list[str]] = None) -> None:
        key = f"{provider.kind.value}:{provider.id}"
        self._providers[key] = provider
        self._fallback.setdefault(provider.kind.value, [])
        if fallback_ids:
            self._fallback[provider.kind.value] = fallback_ids
        logger.info(f"[Runtime] Provider 注册: {provider.id} ({provider.kind.value})")

    def get(self, kind: ProviderKind, provider_id: str = "") -> Optional[AIProvider]:
        if provider_id:
            return self._providers.get(f"{kind.value}:{provider_id}")
        # 优先已注册且 available 的；否则按兜底链
        candidates = [p for k, p in self._providers.items() if k.startswith(kind.value + ":")]
        if not candidates:
            return None
        candidates.sort(key=lambda p: (0 if p.status().available else 1, p.id))
        return candidates[0]

    def resolve(self, kind: ProviderKind) -> Optional[AIProvider]:
        """带兜底链的解析：主候选不可用 → 依次尝试 fallback。"""
        chain = []
        ids = self._fallback.get(kind.value, [])
        for pid in ids:
            chain.append(self._providers.get(f"{kind.value}:{pid}"))
        chain = [p for p in chain if p is not None]
        primary = self.get(kind)
        if primary not in chain:
            chain.insert(0, primary)
        for p in chain:
            if p is None:
                continue
            st = p.status()
            if st.available:
                return p
        return chain[0] if chain else None

    def list(self) -> list[dict]:
        return [p.to_dict() for p in sorted(self._providers.values(), key=lambda x: x.id)]
