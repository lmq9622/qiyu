# -*- coding: utf-8 -*-
"""栖语 · Omni 后端注册表（规格 §19 / §20 / §22 / §23）。

按优先级挑选后端，并保证**上层业务感知不到具体 backend**：

```text
本地 Omni（MiniCPM-o） → 云端 Realtime Omni → Mock（仅测试/兜底）
```

- ``prefer`` 可显式指定后端名；
- 每个后端都会做 ``available()`` 检查，不可用直接跳过；
- 记录「为什么选它 / 为什么跳过别人」，供验收报告直接引用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from runtime.omni.backends.base import BaseBackend
from runtime.omni.backends.cloud_realtime import CloudRealtimeBackend
from runtime.omni.backends.minicpm_o import MiniCPMOBackend
from runtime.omni.backends.minicpm_ws import MiniCPMOWsBackend
from runtime.omni.backends.mock import MockOmniBackend
from runtime.omni.backends.qwen_omni import QwenOmniBackend
from runtime.omni.interface import IRealtimeOmniBackend

# 默认优先级：本地原生 omni 优先，云端兜底，mock 最后（只在显式允许时用）
DEFAULT_ORDER: tuple = ("minicpm_o", "qwen_omni", "cloud_realtime", "mock_omni")


@dataclass
class SelectionReport:
    chosen: str = ""
    reason: str = ""
    considered: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"chosen": self.chosen, "reason": self.reason, "considered": self.considered}


class OmniBackendRegistry:
    def __init__(self, allow_mock: Optional[bool] = None) -> None:
        if allow_mock is None:
            # 只有显式打开才允许 mock 兜底，避免生产环境悄悄跑模拟后端
            allow_mock = os.environ.get("QIYU_OMNI_ALLOW_MOCK", "") == "1"
        self.allow_mock = allow_mock
        self._factories = {
            # 优先用 WS /backend 的真实双工后端（master 分支实测可用）；
            # MiniCPMOBackend（HTTP unary）保留为对照/回退。
            "minicpm_o": MiniCPMOWsBackend,
            "qwen_omni": QwenOmniBackend,
            "cloud_realtime": CloudRealtimeBackend,
            "mock_omni": MockOmniBackend,
        }
        self.last_report = SelectionReport()

    def register(self, name: str, factory) -> None:
        self._factories[name] = factory

    def order(self) -> tuple:
        env = os.environ.get("QIYU_OMNI_ORDER")
        if env:
            return tuple(x.strip() for x in env.split(",") if x.strip())
        order = list(DEFAULT_ORDER)
        if not self.allow_mock:
            order = [x for x in order if x != "mock_omni"]
        return tuple(order)

    def candidates(self) -> list:
        out = []
        for name in self.order():
            factory = self._factories.get(name)
            if factory is None:
                out.append({"name": name, "available": False, "reason": "未注册"})
                continue
            try:
                inst = factory()
                avail = bool(inst.available())
                reason = "" if avail else self._why_unavailable(inst)
            except Exception as e:
                avail, reason = False, f"实例化失败: {e!r}"
            out.append({"name": name, "available": avail, "reason": reason})
        return out

    @staticmethod
    def _why_unavailable(inst: IRealtimeOmniBackend) -> str:
        health = inst.health() if hasattr(inst, "health") else {}
        if health.get("reserved"):
            return "预留后端，未接入"
        if health.get("server") == "" and inst.name == "minicpm_o":
            return "缺少 llama.cpp-omni 运行时（QIYU_OMNI_SERVER 或 backends/omni/）"
        if health.get("weights") == "" and inst.name == "minicpm_o":
            return "缺少 MiniCPM-o 4.5 Q4_K_M 权重（QIYU_OMNI_GGUF 或 models/omni/）"
        return health.get("last_error") or "不可用"

    def select(self, prefer: str = "") -> Optional[IRealtimeOmniBackend]:
        considered = []
        if prefer:
            factory = self._factories.get(prefer)
            if factory is None:
                self.last_report = SelectionReport("", f"指定后端 {prefer} 未注册", considered)
                return None
            inst = factory()
            considered.append({"name": prefer, "available": bool(inst.available()),
                               "reason": "" if inst.available() else "指定后端不可用"})
            self.last_report = SelectionReport(
                prefer if inst.available() else "",
                f"显式指定 {prefer}" if inst.available() else f"指定后端 {prefer} 不可用",
                considered,
            )
            return inst if inst.available() else None

        for name in self.order():
            factory = self._factories.get(name)
            if factory is None:
                continue
            try:
                inst = factory()
            except Exception as e:
                considered.append({"name": name, "available": False, "reason": f"实例化失败: {e!r}"})
                continue
            avail = bool(inst.available())
            considered.append({
                "name": name, "available": avail,
                "reason": "" if avail else self._why_unavailable(inst),
            })
            if avail:
                self.last_report = SelectionReport(
                    name, f"按优先级选中 {name}", considered)
                return inst
        self.last_report = SelectionReport("", "所有 Omni 后端都不可用", considered)
        return None

    def report(self) -> dict:
        return self.last_report.to_dict()


_default_registry: Optional[OmniBackendRegistry] = None


def get_registry() -> OmniBackendRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = OmniBackendRegistry()
    return _default_registry


__all__ = [
    "DEFAULT_ORDER",
    "OmniBackendRegistry",
    "SelectionReport",
    "get_registry",
]
