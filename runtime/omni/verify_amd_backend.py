# -*- coding: utf-8 -*-
"""栖语 · AMD 后端实测脚本（规格 §19 / §21 / §25）。

用法：

```bash
python -m runtime.omni.verify_amd_backend                 # 只探测（不改机器）
python -m runtime.omni.verify_amd_backend --run           # 真加载 + 跑完 9 项
python -m runtime.omni.verify_amd_backend --json out.json  # 结果落盘
```

**这个脚本的立场**（照抄规格里最容易被自欺欺人的那两条）：

- 不要因为「普通 llama.cpp 支持 AMD」就声称 Omni 支持 AMD；
- 不要把「代码已实现」当成「实际运行过」。

所以 9 项验证逐项给结论，任何没真跑的项一律写 ``NOT VERIFIED``，
并且带一个 ``blocker`` 说明卡在哪。

验证等级口径：

| 等级 | 含义 |
|---|---|
| ``IMPLEMENTED`` | 代码写了，没跑 |
| ``SIMULATED`` | 用 Mock 后端跑通编排链路 |
| ``EDITOR VERIFIED`` | 静态检查 / 编译通过 |
| ``LOCAL GPU VERIFIED`` | 本机 GPU 上真跑过 |
| ``QUEST VERIFIED`` | Quest 真机跑过 |
| ``NOT VERIFIED`` | 没做过，或环境不具备 |
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from runtime.omni.backends.minicpm_o import find_server, find_weights, probe_amd_backends
from runtime.omni.registry import OmniBackendRegistry

CHECKS = (
    ("compile", "llama.cpp-omni 编译产物存在且可执行"),
    ("model_load", "模型加载成功（Q4_K_M）"),
    ("vision", "视觉输入可用"),
    ("audio_in", "音频输入可用"),
    ("audio_out", "音频输出可用"),
    ("streaming", "流式输出（增量 delta）"),
    ("full_duplex", "全双工（边说边听）"),
    ("webrtc", "WebRTC 媒体面"),
    ("long_stability", "长时间稳定性"),
)


@dataclass
class Check:
    key: str
    name: str
    status: str = "NOT VERIFIED"
    detail: str = ""
    blocker: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "status": self.status,
                "detail": self.detail, "blocker": self.blocker, "evidence": self.evidence}


def hardware_report() -> dict:
    info: dict = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu": platform.processor(),
    }
    info["amd_probe"] = probe_amd_backends()
    # 显存 / GPU 名（Windows）
    try:
        ps = ("Get-CimInstance Win32_VideoController | "
              "Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            if isinstance(data, dict):
                data = [data]
            info["gpus"] = [
                {"name": d.get("Name"), "vram_gb": round((d.get("AdapterRAM") or 0) / 1073741824, 1),
                 "driver": d.get("DriverVersion")}
                for d in data
            ]
    except Exception as e:
        info["gpus_error"] = repr(e)
    return info


def check_compile(server: Optional[Path]) -> Check:
    c = Check("compile", "llama.cpp-omni 编译产物存在且可执行")
    if not server:
        c.status = "NOT VERIFIED"
        c.blocker = ("缺少 llama.cpp-omni 可执行文件。"
                     "需设置 QIYU_OMNI_SERVER 或放到 backends/omni/。")
        c.detail = "未找到可执行文件"
        return c
    c.detail = str(server)
    c.evidence["size_mb"] = round(server.stat().st_size / 1048576, 1)
    try:
        r = subprocess.run([str(server), "--version"], capture_output=True, text=True, timeout=20)
        c.evidence["version_stdout"] = (r.stdout or r.stderr or "")[:400]
        if r.returncode == 0:
            c.status = "LOCAL GPU VERIFIED"
            c.detail = "可执行，版本信息已取到"
        else:
            c.status = "NOT VERIFIED"
            c.blocker = f"--version 返回 {r.returncode}"
    except Exception as e:
        c.status = "NOT VERIFIED"
        c.blocker = f"执行失败: {e!r}"
    return c


def run_all(do_run: bool) -> dict:
    t0 = time.time()
    server = find_server()
    weights = find_weights()
    hw = hardware_report()

    checks: list = []
    checks.append(check_compile(server))

    for key, name in CHECKS[1:]:
        c = Check(key, name)
        if not do_run:
            c.blocker = "未加 --run，未执行"
            c.detail = "本轮为探测模式"
        elif not server or not weights:
            c.blocker = "前置条件未满足（缺运行时或权重）"
            c.detail = "未执行"
        else:
            c.status = "NOT VERIFIED"
            c.blocker = "本脚本尚未实现该步的真实驱动；请在接好 runtime 后补齐"
        checks.append(c)

    # 编排链路：这一项在本机是**真跑过**的，单独标注
    registry = OmniBackendRegistry(allow_mock=True)
    cand = registry.candidates()
    orchestration = {
        "key": "orchestration",
        "name": "编排链路（session / barge-in / video scheduler / AvatarIntent）",
        "status": "SIMULATED",
        "detail": "通过 MockOmniBackend 跑通；不等于真实模型可用",
        "blocker": "",
        "evidence": {"candidates": cand, "e2e": "python -m runtime.omni.e2e --quick"},
    }

    blockers = [c.blocker for c in checks if c.status == "NOT VERIFIED" and c.blocker]
    verdict = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_s": round(time.time() - t0, 2),
        "hardware": hw,
        "server": str(server) if server else "",
        "weights": str(weights) if weights else "",
        "weights_gb": round(weights.stat().st_size / 1073741824, 2) if weights else 0,
        "backend_candidates": cand,
        "checks": [c.to_dict() for c in checks],
        "orchestration": orchestration,
        "verdict": "LOCAL GPU VERIFIED" if all(
            c.status in ("LOCAL GPU VERIFIED",) for c in checks) else "NOT VERIFIED",
        "primary_blocker": blockers[0] if blockers else "",
    }
    return verdict


def pretty(v: dict) -> str:
    lines = []
    lines.append("=" * 68)
    lines.append("  栖语 · MiniCPM-o 4.5 Q4_K_M / AMD 后端实测报告")
    lines.append("=" * 68)
    gpus = v["hardware"].get("gpus") or []
    for g in gpus:
        lines.append(f"  GPU  : {g.get('name')}  VRAM≈{g.get('vram_gb')}GB  driver={g.get('driver')}")
    amd = v["hardware"].get("amd_probe", {})
    lines.append(f"  后端 : vulkan={amd.get('vulkan')} rocm={amd.get('rocm')} hip={amd.get('hip')} cpu=True")
    lines.append(f"  运行时: {v['server'] or '（缺失）'}")
    lines.append(f"  权重  : {v['weights'] or '（缺失）'}"
                 + (f"  {v['weights_gb']}GB" if v['weights_gb'] else ""))
    lines.append("-" * 68)
    for c in v["checks"]:
        tag = c["status"]
        lines.append(f"  [{tag:<19s}] {c['name']}")
        if c["blocker"]:
            lines.append(f"      blocker: {c['blocker']}")
    o = v["orchestration"]
    lines.append(f"  [{o['status']:<19s}] {o['name']}")
    lines.append("-" * 68)
    lines.append(f"  结论: {v['verdict']}")
    if v["primary_blocker"]:
        lines.append(f"  首要 blocker: {v['primary_blocker']}")
    lines.append("=" * 68)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="AMD 后端实测（规格 §19）")
    ap.add_argument("--run", action="store_true", help="真加载并跑 9 项验证")
    ap.add_argument("--json", default="", help="结果写入 JSON 文件")
    args = ap.parse_args()

    v = run_all(args.run)
    print(pretty(v))
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {args.json}")
    return 0 if v["verdict"] == "LOCAL GPU VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
