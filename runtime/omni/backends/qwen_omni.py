# -*- coding: utf-8 -*-
"""栖语 · QwenOmniBackend（**预留**，规格 §20）。

存在的理由是「以后换模型不重写 Quest/AI 架构」。当前**没有**接入真权重，
``available()`` 恒为 False，registry 会跳过它。

接入时要做的事（照 MiniCPM-o 的路子走即可）：

1. 把 Qwen-Omni 的 GGUF（或官方推理服务）放到 ``models/omni/qwen*``；
2. 确认运行时支持 audio in / audio out / video in 与双工；
3. 覆盖 ``find_weights()`` 的 glob 与 ``_stream_reply()`` 的请求体字段；
4. 其余（session、barge-in、video scheduler、指标）零改动。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from runtime.omni.backends.minicpm_o import MiniCPMOBackend
from runtime.omni.types import BackendCapabilities


class QwenOmniBackend(MiniCPMOBackend):
    name = "qwen_omni"
    display_name = "Qwen-Omni（预留后端 · 未接入）"

    def capabilities(self) -> BackendCapabilities:
        caps = super().capabilities()
        caps.notes = "预留后端：接口已对齐，尚未接入真实权重。"
        return caps

    def available(self) -> bool:
        return False

    def health(self) -> dict:
        base = super().health()
        base.update({
            "reserved": True,
            "notes": "预留后端。available() 恒为 False，不会被 registry 选中。",
        })
        return base


__all__ = ["QwenOmniBackend"]
