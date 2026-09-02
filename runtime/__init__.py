# -*- coding: utf-8 -*-
"""Qiyu Runtime：Provider 抽象 / 硬件检测 / 运行时管理器（M2）。

业务层只允许通过 runtime 的 Provider 接口访问 AI 能力，
不直接依赖具体 LLM / 后端 / 供应商。
"""
from __future__ import annotations

import sys
from pathlib import Path

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

def get_models_dir(sub: str = "") -> Path:
    """运行时模型目录（可独立更新）：
    - dev：仓库根 models/；
    - exe：Qiyu.exe 旁的 sidecar models/（PyInstaller 单文件模式 sys.frozen 为 True）。
    """
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    d = base / "models"
    if sub:
        d = d / sub
    return d


__all__ = [
    "BackendCapability", "HardwareDetector", "HardwareProfile",
    "RuntimeManager", "MemoryProvider",
    "AIProvider", "EmbeddingProvider", "MainBrainProvider", "ProviderKind",
    "ProviderRegistry", "ProviderStatus", "RealtimeBrainProvider",
    "RealtimeDecision", "STTProvider", "TTSProvider", "VisionProvider",
    "UnavailableRealtimeBackend", "ToolAgent", "ToolEvidence", "tool_agent",
]
