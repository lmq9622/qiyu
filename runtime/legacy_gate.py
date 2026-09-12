# -*- coding: utf-8 -*-
"""栖语 · 旧链运行时开关（规格 §23）。

架构决定：**MiniMind-O / 前置小脑整条线判为废案**（版本冻结在 `0.05.24`）。
但在我们把新链路彻底接完之前，物理删除历史代码是不负责任的 ——
所以按规格要求做三级标注，并且加一道**运行时闸门**：

- 代码保留：`ACTIVE` / `DEPRECATED` / `LEGACY`；
- 运行时默认**不允许**再调用旧小脑；
- 想临时回退对比，必须显式设置环境变量:

```bat
set QIYU_ENABLE_MINIMIND_LEGACY=1
```

没有这个变量时：

- ``runtime/brain/router.py`` 直接判定走 MainBrain；
- ``MiniMindAutoRealtimeProvider`` 的 analyze/quick_reply/judge 直接拒绝；
- ``BrainPipeline.decide()`` 跳过小脑分支。

这样「运行时不偷偷调用旧 MiniMind」是可检查的事实，而不是承诺。
"""

from __future__ import annotations

import os
import time
from typing import Optional

_ENV_KEY = "QIYU_ENABLE_MINIMIND_LEGACY"

# 三级清单：名字 → 处置说明。供 /v1/omni/legacy 与验收报告直接引用。
INVENTORY: dict = {
    "ACTIVE": {
        "runtime/classifier.py": "轻量规则分类；给 Omni 当「是否需要深度推理」的辅助信号",
        "runtime/brain/quality.py": "输出质量门（空回/碎句/客服腔/回显）",
        "runtime/brain/personality_spec.py": "人格 Spec 单一来源，改注入 Omni session",
        "runtime/brain/backchannel.py": "反应池，退化为本地 barge-in 提示池",
        "runtime/brain/decision.py": "内部控制数据结构（工具/记忆/情绪副作用仍复用）",
        "runtime/omni/": "新核心：IRealtimeOmni / OmniSession / VideoScheduler / backends",
        "quest-mr-client/behavior_policy/": "Quest 本地行为层（Behavior Policy v1）",
    },
    "DEPRECATED": {
        "runtime/brain/router.py": "保留文件；默认直接走 MainBrain，不再问小脑",
        "runtime/brain/pipeline.py": "小脑判定分支默认短路；工具/记忆能力保留",
        "runtime/realtime_unified.py": "保留；不再自动加载小脑权重",
        "runtime/realtime.py": "保留全部后端类；默认不加载",
        "runtime/minimindo/": "保留 model_minimind.py / model_omni.py",
        "models/realtime/minimind-*": "权重保留在仓库，不再进主线包",
    },
    "LEGACY": {
        "training/minimind_realtime/": "第一/二代训练脚本与 runs",
        "training/minimind_personality_base/": "Personality Base 训练",
        "training/minimind_backchannel/": "MoE 首轮反应训练",
        "training/minimind_official/": "官方七阶段复现评测",
        "../legacy/MiniMind-O-0.05.24/": "整包归档 + 一键安装包",
    },
}


def minimind_enabled() -> bool:
    """旧小脑是否被显式允许。默认 False。"""
    return os.environ.get(_ENV_KEY, "").strip() == "1"


def set_minimind_enabled(on: bool) -> dict:
    """运行时开关（仅供对比测试与回归使用）。"""
    if on:
        os.environ[_ENV_KEY] = "1"
    else:
        os.environ.pop(_ENV_KEY, None)
    return status()


def status() -> dict:
    return {
        "minimind_enabled": minimind_enabled(),
        "env_key": _ENV_KEY,
        "default": "disabled",
        "line": "0.05.x",
        "final_version": "0.05.24",
        "deprecated": True,
        "reason": "MiniCPM-o 4.5 原生全双工 omni 已替代 MiniMind → MainBrain 两级语言生成",
        "checked_at": time.time(),
        "inventory": {k: sorted(v.keys()) for k, v in INVENTORY.items()},
    }


def disabled_result(kind: str = "analyze") -> dict:
    """给旧接口用的「统一拒绝」返回体（形状与 RealtimeDecision/analyze 兼容）。"""
    return {
        "needs_main_brain": True,
        "quick_reply": None,
        "reason": "MiniMind 小脑线已废弃（0.05.24），运行时默认不再调用；"
                  "如需对比请设 QIYU_ENABLE_MINIMIND_LEGACY=1",
        "confidence": 0.0,
        "category": "legacy_disabled",
        "backend": "legacy_disabled",
        "model": "",
        "meta": {"gate": kind, "legacy_disabled": True},
    }


def log_once(logger_obj, reason: str = "") -> None:
    """只在第一次拒绝时打日志，避免刷屏。"""
    global _warned
    if _warned:
        return
    _warned = True
    try:
        logger_obj.warning(
            "[LegacyGate] MiniMind 小脑已废弃，运行时默认不再调用"
            + (f"（{reason}）" if reason else "")
            + "；如需对比请设 QIYU_ENABLE_MINIMIND_LEGACY=1"
        )
    except Exception:
        pass


_warned = False


def install_into(module_globals: Optional[dict] = None) -> None:
    """给旧模块用的门面（保留扩展位）。"""
    return None


__all__ = [
    "INVENTORY",
    "disabled_result",
    "install_into",
    "log_once",
    "minimind_enabled",
    "set_minimind_enabled",
    "status",
]
