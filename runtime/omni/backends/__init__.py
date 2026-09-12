# -*- coding: utf-8 -*-
"""栖语 · Omni 后端实现（ModelAdapter 层，规格 §20）。

| 后端 | 状态 | 说明 |
|---|---|---|
| ``MiniCPMOBackend`` | **首选** | MiniCPM-o 4.5 Q4_K_M + llama.cpp-omni，AMD 可用性待实测 |
| ``QwenOmniBackend`` | 预留 | 接口已对齐，未接入权重 |
| ``CloudRealtimeBackend`` | fallback | 接口已对齐，云端协议未接线 |
| ``MockOmniBackend`` | 测试 | 本地模拟，用于验证编排链路（SIMULATED） |
"""

from runtime.omni.backends.base import BaseBackend, PendingInput, QueueStream
from runtime.omni.backends.cloud_realtime import CloudRealtimeBackend
from runtime.omni.backends.minicpm_o import MiniCPMOBackend, find_server, find_weights, probe_amd_backends
from runtime.omni.backends.minicpm_ws import MiniCPMOWsBackend, MiniCPMOWsStream
from runtime.omni.backends.mock import MockOmniBackend
from runtime.omni.backends.qwen_omni import QwenOmniBackend

__all__ = [
    "BaseBackend",
    "CloudRealtimeBackend",
    "MiniCPMOBackend",
    "MiniCPMOWsBackend",
    "MiniCPMOWsStream",
    "MockOmniBackend",
    "PendingInput",
    "QueueStream",
    "QwenOmniBackend",
    "find_server",
    "find_weights",
    "probe_amd_backends",
]
