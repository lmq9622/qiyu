# -*- coding: utf-8 -*-
"""Qiyu 模型安装器（规格§11：Hardware Detection → Recommended Model → Recommended Backend）。

用法：
    python tools/install_models.py --check                 # 检测硬件 + 已装模型/运行时
    python tools/install_models.py --omni                  # 下载官方 MiniMind-O 权重（ModelScope/HF，CPU 可跑）
    python tools/install_models.py --omni --moe            # 下载 MiniMind-3o-MoE 版本
    python tools/install_models.py --realtime              # 下载 Realtime Brain（MiniMind2 GGUF，llama.cpp）
    python tools/install_models.py --realtime --url <url>  # 指定 GGUF 直链
    python tools/install_models.py --main <url>            # 下载本地主模型 GGUF 到 models/main/

诚实说明：
- MiniMind-O 官方权重以 PyTorch（transformers 格式）发布，官方未发布 GGUF；
  Qiyu 用 torch/transformers 直接跑官方权重（文本推理零额外依赖，CPU 必跑，
  CUDA 自动），这是当前最稳定、最易跨平台部署的方案。
- --realtime 仍支持安装 MiniMind2-gguf 文本 Thinker（llama.cpp：CUDA/Vulkan/CPU），
  作为官方权重缺失时的备选后端。下载失败会如实报错，绝不假装成功。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def detect() -> dict:
    """Hardware Detection（§11）：CPU / GPU / CUDA / Vulkan → 推荐 backend。

    若已安装官方 MiniMind-O 权重（torch/transformers），推荐 backend 跟随 torch
    真实可用设备（cuda 或 cpu）；否则按 llama.cpp 能力推荐 cuda→vulkan→cpu。
    """
    from runtime.hardware import HardwareDetector
    prof = HardwareDetector().detect()
    from runtime.minimindo import MiniMindOOmniRuntime, discover_model_dir
    if discover_model_dir() is not None:
        return {"profile": prof.to_dict(),
                "recommended_backend": MiniMindOOmniRuntime._auto_device(),
                "realtime_model": "minimind-3o-official"}
    if prof.cuda_available and prof.gpu_vendor == "NVIDIA":
        backend = "cuda"
    elif prof.vulkan_available:
        backend = "vulkan"
    else:
        backend = "cpu"
    return {"profile": prof.to_dict(), "recommended_backend": backend,
            "realtime_model": "minimind2-gguf"}


def recommend(backend: str = "") -> str:
    """Recommended Model：按 backend 返回建议模型说明。"""
    backend = backend or detect()["recommended_backend"]
    return (
        "Realtime Brain（官方 MiniMind-O 权重，torch 文本推理，CPU 必跑 / CUDA 自动）："
        "运行 tools/install_models.py --omni 下载（ModelScope/HF）。\n"
        "备选：MiniMind2-gguf 文本 Thinker（llama.cpp，CUDA/Vulkan/CPU）可用 --realtime 安装。"
        f"当前推荐 backend={backend}。"
    )


def check() -> int:
    d = detect()
    prof = d["profile"]
    print("=" * 60)
    print("Qiyu 模型安装器 · 环境检测")
    print("=" * 60)
    cpu = prof.get("cpu") or {}
    print(f"CPU    : {cpu.get('name') or '未知'} ({cpu.get('threads') or 0} 线程)")
    print(f"RAM    : {prof.get('ram_mb')} MB")
    gpu = prof.get("gpu") or {}
    print(f"GPU    : {gpu.get('name') or '无'} ({gpu.get('vendor')}) VRAM={gpu.get('vram_mb')}MB")
    print(f"CUDA   : {prof.get('cuda_available')} | Vulkan: {prof.get('vulkan_available')}")
    print(f"推荐backend: {d['recommended_backend']}")
    from runtime.realtime import discover_models, _inference_runtime
    from runtime.minimindo import discover_model_dir
    omni_dir = discover_model_dir()
    print(f"推理运行时 : {_inference_runtime()}")
    print(f"MiniMind-O 官方权重: {omni_dir or '未安装（可用 --omni 下载）'}"
          f"{'（' + str(omni_dir) + '）' if omni_dir else ''}")
    model = discover_models()
    print(f"Realtime Thinker 已装: {model.has_thinker()}（组件: {model.present_components() or '无'}）")
    from runtime.main_brain import find_local_model
    print(f"本地主模型  : {find_local_model() or '未安装（可用 --main <url> 下载或配置远程 API）'}")
    print("\n" + recommend(d["recommended_backend"]))
    return 0


def download(url: str, dest: Path, expect_size_mb: float = 0.0) -> bool:
    """真实下载到 dest（流式写盘）；失败返回 False，不假装成功。"""
    import httpx
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
            if r.status_code != 200:
                print(f"[ERR] {url} -> HTTP {r.status_code}")
                return False
            total = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    total += len(chunk)
            if expect_size_mb and total < expect_size_mb * 1024 * 1024:
                print(f"[ERR] 文件过小（{total/1048576:.1f}MB < {expect_size_mb}MB），疑似占位/失败")
                tmp.unlink(missing_ok=True)
                return False
            tmp.replace(dest)
        print(f"[OK] 已下载: {dest} ({total/1048576:.1f} MB)")
        return True
    except Exception as e:
        print(f"[ERR] 下载失败: {e}")
        tmp.unlink(missing_ok=True)
        return False


DEFAULT_REALTIME_URLS = [
    # MiniMind2-gguf 文本实时大脑（llama.cpp 可跑）；若官方文件名变化导致 404，用 --url 指定直链。
    "https://huggingface.co/jingyaogong/MiniMind2-gguf/resolve/main/Q4-MiniMind2-Small.gguf",
    "https://huggingface.co/jingyaogong/MiniMind2-gguf/resolve/main/MiniMind2-Small.gguf",
    "https://huggingface.co/jingyaogong/MiniMind2-gguf/resolve/main/Q4-MiniMind2.gguf",
    "https://modelscope.cn/models/jingyaogong/MiniMind2-gguf/resolve/master/Q4-MiniMind2-Small.gguf",
]


def install_realtime(url: str = "") -> bool:
    from runtime.realtime import _default_model_root
    dest_dir = _default_model_root()
    dest_dir.mkdir(parents=True, exist_ok=True)
    if url:
        urls = [url]
    else:
        urls = DEFAULT_REALTIME_URLS
    for u in urls:
        print(f"[..] 尝试: {u}")
        if download(u, dest_dir / "thinker.gguf", expect_size_mb=50):
            print(f"[OK] Realtime Brain 安装完成: {dest_dir / 'thinker.gguf'}")
            return True
    print("[ERR] 所有候选地址都不可用。请手动下载 MiniMind2-gguf 系列的 GGUF 放到 "
          "models/realtime/thinker.gguf，或用 --url 指定直链。")
    return False


def install_omni(use_moe: bool = False) -> bool:
    """下载官方 MiniMind-O transformers 权重到 models/realtime/（CPU 可跑）。

    ModelScope 优先，HuggingFace(hf-mirror) 兜底；已完整则跳过（幂等）。
    """
    try:
        from runtime.minimindo import download_model, is_complete
        target = download_model(use_moe=use_moe)
        if is_complete(target):
            print(f"[OK] MiniMind-O 官方权重安装完成: {target}")
            return True
        print(f"[ERR] 权重不完整: {target}")
        return False
    except Exception as e:
        print(f"[ERR] MiniMind-O 权重下载失败: {e}")
        return False


DEFAULT_ASR_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    "sherpa-onnx-paraformer-zh-small-2024-03-09.tar.bz2"
)


def install_asr() -> bool:
    """下载 sherpa-onnx paraformer-zh 小模型到 models/asr/（真实 ASR，STT Provider 使用）。"""
    import tarfile
    from runtime import get_models_dir
    dest_dir = get_models_dir("asr")
    dest_dir.mkdir(parents=True, exist_ok=True)
    tmp = dest_dir / "sherpa-onnx-paraformer-zh-small.tar.bz2"
    if not download(DEFAULT_ASR_URL, tmp, expect_size_mb=60):
        print("[ERR] ASR 模型下载失败，请手动下载 sherpa-onnx-paraformer-zh-small 放到 models/asr/")
        return False
    try:
        with tarfile.open(tmp, "r:bz2") as tf:
            tf.extractall(dest_dir)
        tmp.unlink(missing_ok=True)
        print(f"[OK] ASR 模型安装完成: {dest_dir}")
        return True
    except Exception as e:
        print(f"[ERR] ASR 模型解压失败: {e}")
        return False


def install_main(url: str) -> bool:
    from runtime.main_brain import _default_models_dir
    dest_dir = _default_models_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = url.rsplit("/", 1)[-1].split("?")[0] or "main.gguf"
    if download(url, dest_dir / name, expect_size_mb=100):
        print(f"[OK] 本地主模型安装完成: {dest_dir / name}")
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Qiyu 模型安装器")
    ap.add_argument("--check", action="store_true", help="检测环境并给出推荐")
    ap.add_argument("--realtime", action="store_true", help="下载 Realtime Brain（MiniMind2 GGUF，llama.cpp）")
    ap.add_argument("--omni", action="store_true", help="下载官方 MiniMind-O 权重（torch/transformers，CPU 可跑）")
    ap.add_argument("--moe", action="store_true", help="配合 --omni 下载 MiniMind-3o-MoE 版本")
    ap.add_argument("--asr", action="store_true", help="下载 STT 模型（sherpa-onnx paraformer-zh）到 models/asr/")
    ap.add_argument("--main", metavar="URL", default="", help="下载本地主模型 GGUF 到 models/main/")
    ap.add_argument("--url", default="", help="指定直链（配合 --realtime）")
    args = ap.parse_args()
    if args.check:
        return check()
    if args.omni:
        return 0 if install_omni(args.moe) else 1
    if args.realtime:
        return 0 if install_realtime(args.url) else 1
    if args.asr:
        return 0 if install_asr() else 1
    if args.main:
        return 0 if install_main(args.main) else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
