# -*- coding: utf-8 -*-
"""栖语 · Omni 真实本机验证 · 环境探测（规格 §一 / §二）。

跑这个脚本回答三个问题：

1. 这台机器上 llama.cpp 到底支持什么（Vulkan / mtmd / 哪些 arch）
2. MiniCPM-o 的候选权重到底存在哪些（HF / ModelScope / 本地）
3. 缺什么

```bash
python -m runtime.omni.smoke.probe_env
python -m runtime.omni.smoke.probe_env --search
python -m runtime.omni.smoke.probe_env --repo openbmb/MiniCPM-o-2_6-gguf
```
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]

SEARCH_TERMS = ("MiniCPM-o-4_5", "MiniCPM-o", "MiniCPMo", "minicpm-o GGUF")


def _llama_lib_dir() -> Optional[Path]:
    try:
        import llama_cpp

        d = Path(llama_cpp.__file__).resolve().parent / "lib"
        return d if d.is_dir() else None
    except Exception:
        return None


def probe_llama_cpp() -> dict:
    out: dict = {"installed": False}
    try:
        import llama_cpp
        import llama_cpp.llama_cpp as lc
    except Exception as e:
        out["error"] = repr(e)
        return out

    out["installed"] = True
    out["version"] = getattr(llama_cpp, "__version__", "?")
    lib = _llama_lib_dir()
    out["lib_dir"] = str(lib) if lib else ""
    try:
        out["gpu_offload"] = bool(lc.llama_supports_gpu_offload())
    except Exception as e:
        out["gpu_offload_error"] = repr(e)

    dlls = sorted(p.name for p in lib.glob("ggml-*.dll")) if lib else []
    out["ggml_backends"] = dlls
    out["has_vulkan"] = any("vulkan" in d for d in dlls)
    out["has_mtmd"] = bool(lib and (lib / "mtmd.dll").exists())

    try:
        import llama_cpp.llama_chat_format as cf

        out["chat_handlers"] = sorted(
            n for n in dir(cf)
            if n.endswith("ChatHandler") and not n.startswith("_")
        )
        out["minicpm_handlers"] = sorted(n for n in dir(cf) if "MiniCPM" in n)
    except Exception as e:
        out["chat_handlers_error"] = repr(e)

    if lib and (lib / "llama.dll").exists():
        try:
            raw = (lib / "llama.dll").read_bytes()
            txt = raw.decode("latin-1", "ignore")
            toks = set(re.findall(r"[a-z0-9_]{3,30}", txt))
            wanted = {
                "minicpm", "minicpm2", "minicpm3", "minicpm5", "minicpmv", "minicpmo",
                "qwen2vl", "qwen3vl", "qwen3vlmoe", "qwen3tts", "smolvlm",
                "gemma3", "llava", "pixtral", "hunyuan_vl", "glm4v",
            }
            out["arch_candidates"] = sorted(t for t in toks if t in wanted)
        except Exception as e:
            out["arch_error"] = repr(e)

    out["vulkan_devices"] = list_vulkan_devices()
    return out


def list_vulkan_devices() -> list:
    """把 ggml 的 Vulkan 枚举输出抓出来（stderr 里的 ggml_vulkan: 行）。"""
    try:
        import contextlib
        import io

        import llama_cpp.llama_cpp as lc

        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            try:
                lc.llama_backend_init()
            except Exception:
                pass
        return [l.strip() for l in buf.getvalue().splitlines() if "vulkan" in l.lower()]
    except Exception:
        return []


def probe_hardware() -> dict:
    info = {"platform": platform.platform(), "python": sys.version.split()[0]}
    try:
        ps = ("Get-CimInstance Win32_VideoController | "
              "Select-Object Name,DriverVersion | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=25)
        if r.stdout.strip():
            d = json.loads(r.stdout)
            info["gpus"] = d if isinstance(d, list) else [d]
    except Exception as e:
        info["gpu_error"] = repr(e)
    try:
        ps = ("Get-ItemProperty 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\"
              "{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' | "
              "Select-Object DriverDesc,@{n='VRAM_GB';e={[math]::Round($_.'HardwareInformation.qwMemorySize'/1GB,1)}} | "
              "ConvertTo-Json -Compress")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=25)
        if r.stdout.strip():
            d = json.loads(r.stdout)
            info["vram"] = d if isinstance(d, list) else [d]
    except Exception as e:
        info["vram_error"] = repr(e)
    return info


def _http_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "qiyu-omni-probe"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def search_hf(terms=SEARCH_TERMS, limit: int = 25) -> dict:
    out: dict = {}
    for t in terms:
        try:
            url = "https://huggingface.co/api/models?search=" + urllib.parse.quote(t) + f"&limit={limit}"
            data = _http_json(url)
            out[t] = [
                {"id": m.get("modelId"), "downloads": m.get("downloads"),
                 "gguf": "gguf" in (m.get("tags") or [])}
                for m in data
            ]
        except Exception as e:
            out[t] = [{"error": repr(e)}]
    return out


def search_hf_files(repo: str) -> list:
    """列某个 repo 的 GGUF / mmproj / config 文件。"""
    try:
        d = _http_json(f"https://huggingface.co/api/models/{repo}?blobs=true")
        out = []
        for f in (d.get("siblings") or []):
            name = f.get("rfilename") or ""
            low = name.lower()
            if low.endswith(".gguf") or "mmproj" in low or low.endswith(".json"):
                out.append({"name": name, "gb": round((f.get("size") or 0) / 1073741824, 2),
                            "size": f.get("size")})
        return out
    except Exception as e:
        return [{"error": repr(e)}]


def local_candidates() -> list:
    hits = []
    roots = [PROJECT_ROOT / "models", Path(r"D:\models"), Path(r"D:\gguf")]
    for root in roots:
        if not root.is_dir():
            continue
        try:
            for p in root.rglob("*.gguf"):
                n = p.name.lower()
                if any(k in n for k in ("minicpm", "mmproj", "omni")):
                    hits.append({"path": str(p), "gb": round(p.stat().st_size / 1073741824, 2)})
        except Exception:
            pass
    return hits


def verdict(llama: dict, local: list) -> dict:
    blockers = []
    if not llama.get("installed"):
        blockers.append("llama-cpp-python 未安装")
    else:
        if not llama.get("has_vulkan"):
            blockers.append("llama.cpp 未编译 Vulkan 后端")
        if not llama.get("has_mtmd"):
            blockers.append("llama.cpp 未编译 mtmd（多模态入口）")
        if not llama.get("minicpm_handlers"):
            blockers.append("llama-cpp-python 没有 MiniCPM 多模态 chat handler")
    if not local:
        blockers.append("本地没有 MiniCPM-o GGUF 权重")
    return {
        "vulkan_ok": bool(llama.get("has_vulkan")) and bool(llama.get("vulkan_devices")),
        "mtmd_ok": bool(llama.get("has_mtmd")),
        "minicpm_handler": bool(llama.get("minicpm_handlers")),
        "weights_present": bool(local),
        "blockers": blockers,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Omni 真实本机环境探测")
    ap.add_argument("--search", action="store_true", help="联网搜索候选权重")
    ap.add_argument("--repo", default="", help="列出某个 HF repo 的 GGUF 文件")
    ap.add_argument("--json", default="", help="结果写入文件")
    args = ap.parse_args()

    llama = probe_llama_cpp()
    hw = probe_hardware()
    local = local_candidates()
    v = verdict(llama, local)
    rep: dict = {"llama_cpp": llama, "hardware": hw, "local_weights": local, "verdict": v}

    print("=" * 70)
    print("  栖语 · Omni 本机环境探测")
    print("=" * 70)
    print(f"  llama-cpp-python : {llama.get('version')}")
    print(f"  lib              : {llama.get('lib_dir')}")
    print(f"  ggml 后端        : {', '.join(llama.get('ggml_backends') or [])}")
    print(f"  Vulkan           : {llama.get('has_vulkan')}")
    for line in (llama.get("vulkan_devices") or [])[:6]:
        print(f"     {line}")
    print(f"  mtmd（多模态）   : {llama.get('has_mtmd')}")
    print(f"  MiniCPM handler  : {llama.get('minicpm_handlers')}")
    print(f"  编译进的 arch    : {', '.join(llama.get('arch_candidates') or [])}")
    print("-" * 70)
    for g in (hw.get("vram") or []):
        if g.get("VRAM_GB"):
            print(f"  {g.get('DriverDesc')} : {g.get('VRAM_GB')} GB")
    print("-" * 70)
    print(f"  本地候选权重     : {len(local)}")
    for h in local[:10]:
        print(f"     {h['gb']:>7.2f} GB  {h['path']}")
    print("-" * 70)
    print(f"  结论: vulkan_ok={v['vulkan_ok']} mtmd_ok={v['mtmd_ok']} "
          f"minicpm_handler={v['minicpm_handler']} weights={v['weights_present']}")
    for b in v["blockers"]:
        print(f"  blocker: {b}")
    print("=" * 70)

    if args.search:
        print("\n[HF 搜索]")
        for term, items in search_hf().items():
            print(f"  -- {term}")
            for it in (items or [])[:12]:
                print("     ", it)

    if args.repo:
        rep["repo_files"] = search_hf_files(args.repo)
        print(f"\n[{args.repo} 文件]")
        for f in rep["repo_files"]:
            print("   ", f)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已写入 {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
