# -*- coding: utf-8 -*-
"""栖语版本号单一来源（2026-09-11 版本体系 v2）。

三条线（详见 docs/VERSION_SCHEME.md）：

- ``0.0.x``  历史 demo 线（v0.0.3 ~ v0.0.24，归档，不再演进）
- ``0.05.x`` **MiniMind-O 小脑专线（已废案）**，冻结在 ``0.05.24``
- ``0.1.x``  产品主线 = 本机 Realtime Omni 架构

打包时：

- 默认打产品主线包（``APP_VERSION``）；
- 需要重建旧小脑专线包时设 ``QIYU_LEGACY_MINIMIND_O=1``，
  版本号自动切到 ``MINIMIND_O_LEGACY_VERSION``。
"""

from __future__ import annotations

# ---------- 产品主线（ACTIVE） ----------
APP_VERSION = "0.1.0"
APP_NAME = "栖语"
APP_NAME_EN = "Qiyu"
APP_TITLE = f"{APP_NAME_EN} {APP_NAME} · AI 伴侣 {APP_VERSION}"

# ---------- 小脑专线（DEPRECATED / 废案） ----------
MINIMIND_O_LEGACY_VERSION = "0.05.24"
MINIMIND_O_LEGACY_LINE = "0.05.x"
MINIMIND_O_LEGACY_ITERATIONS = 25          # 0.05.0 → 0.05.24

# ---------- 版本线说明（供 /v1/settings 与诊断输出） ----------
VERSION_SCHEME = {
    "0.0.x": "历史 demo 线（v0.0.3 ~ v0.0.24，归档）",
    "0.05.x": "MiniMind-O 小脑专线（废案，0.05.0 → 0.05.24）",
    "0.1.x": "产品主线（本机 Realtime Omni）",
}


def is_legacy_build() -> bool:
    """当前进程是否运行在旧小脑专线包里。"""
    import os

    return os.environ.get("QIYU_LEGACY_MINIMIND_O") == "1"


def current_version() -> str:
    return MINIMIND_O_LEGACY_VERSION if is_legacy_build() else APP_VERSION


__all__ = [
    "APP_NAME",
    "APP_NAME_EN",
    "APP_TITLE",
    "APP_VERSION",
    "MINIMIND_O_LEGACY_ITERATIONS",
    "MINIMIND_O_LEGACY_LINE",
    "MINIMIND_O_LEGACY_VERSION",
    "VERSION_SCHEME",
    "current_version",
    "is_legacy_build",
]
