# -*- coding: utf-8 -*-
"""探测 quick 直答失败样本：打印 D3/D2 adapter 的原始生成 + _sanitize_quick_text 判定。

用法（env 指定 base + adapter，同 simple20_test）：
  =...; =...
  python -X utf8 runtime/brain/probe_quick_raw.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from runtime.realtime import MiniMindOOmniBackend, _quick_system, _sanitize_quick_text  # noqa: E402

INPUTS = ["草", "笑死", "无聊", "啊？", "哈哈", "嘿嘿", "好烦", "服了", "真的假的", "无聊死了"]


async def main() -> None:
    backend = MiniMindOOmniBackend()
    r = await backend.load()
    if not r.get("ok"):
        raise SystemExit(f"MiniMind 加载失败: {r.get('reason')}")
    rt = backend._runtime
    system = _quick_system("小办，普通朋友 · 有空就聊",
                           "【状态】你和对方现在是普通朋友（好感50/100，耐心70/100）。")
    print(f"BASE={rt.model_dir}\nADAPTER={rt.adapter_dir}\n")
    for u in INPUTS:
        prompt_user = f"对方：{u}"
        runs = []
        for _ in range(3):
            raw = (rt.generate_text(prompt_user, system, 24, 0.3, 0.9, False).get("text") or "").strip()
            ok = _sanitize_quick_text(raw, u)
            runs.append(f"raw={raw!r}->{'PASS:'+ok if ok else 'REJECT'}")
        print(f"[{u}]")
        for s in runs:
            print("   ", s)


asyncio.run(main())
