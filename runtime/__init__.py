# -*- coding: utf-8 -*-
"""Qiyu Runtime：Provider 抽象 / 硬件检测 / 运行时管理器（M2）。

业务层只允许通过 runtime 的 Provider 接口访问 AI 能力，
不直接依赖具体 LLM / 后端 / 供应商。
"""
from runtime.hardware import (
    BackendCapability,
    HardwareDetector,
    HardwareProfile,
)
from runtime.manager import RuntimeManager
from runtime.memory import MemoryProvider
from runtime.providers import (
    AIProvider,
    EmbeddingProvider,
    MainBrainProvider,
    ProviderKind,
    ProviderRegistry,
    ProviderStatus,
    RealtimeBrainProvider,
    RealtimeDecision,
    STTProvider,
    TTSProvider,
    VisionProvider,
)
from runtime.realtime import UnavailableRealtimeBackend
from runtime.toolagent import ToolAgent, ToolEvidence, tool_agent

__all__ = [
    "BackendCapability", "HardwareDetector", "HardwareProfile",
    "RuntimeManager", "MemoryProvider",
    "AIProvider", "EmbeddingProvider", "MainBrainProvider", "ProviderKind",
    "ProviderRegistry", "ProviderStatus", "RealtimeBrainProvider",
    "RealtimeDecision", "STTProvider", "TTSProvider", "VisionProvider",
    "UnavailableRealtimeBackend", "ToolAgent", "ToolEvidence", "tool_agent",
]
