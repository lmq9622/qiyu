# -*- coding: utf-8 -*-
"""Qiyu Runtime · 真人感硬规则（唯一事实来源）。

golden 评测（training/minimind_realtime/evaluate_golden_v4.py）与
runtime 回归（runtime/brain/simple20_test.py）共用同一套判定：
- 空回复 → FAIL
- 重复碎句 → FAIL（例：你又咋又咋咋咋就咋）
- 无意义循环 → FAIL（例：咋了咋了咋了 / 好的好的好的）

纯笑声/语气词（哈哈、嘿嘿、嗯嗯）属于真人感，允许。
"""
from __future__ import annotations

import re

_PUNCT_RE = re.compile(r"[\s，。！？!?,.、~～…—\-·]")
_LAUGH_CHARS = set("哈嘿嘻呵嗯啊哦呜哇嗨耶嘻")


def hard_fail(out: str) -> str:
    """返回 '' 表示通过；否则返回失败原因（empty/char_repeat/bigram_repeat/loop）。"""
    core = _PUNCT_RE.sub("", out or "")
    if not core:
        return "empty"
    if all(c in _LAUGH_CHARS for c in core):
        return ""
    for ch in set(core):
        if ch in _LAUGH_CHARS:
            continue
        n = core.count(ch)
        if n >= 4:
            return f"char_repeat:{ch}x{n}"
    for i in range(len(core) - 1):
        g = core[i:i + 2]
        if core.count(g) >= 3:
            return f"bigram_repeat:{g}x3"
    if len(core) >= 6 and len(set(core)) / len(core) < 0.45:
        return "low_diversity_loop"
    return ""


def is_acceptable_reply(out: str) -> bool:
    """直答硬门槛：非空 + 通过全部硬规则。"""
    return not hard_fail(out)


__all__ = ["hard_fail", "is_acceptable_reply"]
