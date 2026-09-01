# -*- coding: utf-8 -*-
"""Qiyu 模型安装器（规格§11：Hardware Detection → Recommended Model → Recommended Backend）。

用法：
    python tools/install_models.py --check                 # 检测硬件 + 已装模型/运行时
    python tools/install_models.py --realtime              # 下载 Realtime Brain（MiniMind GGUF）
    python tools/install_models.py --realtime --url <url>  # 指定 GGUF 直链
    python tools/install_models.py --main <url>            # 下载本地主模型 GGUF 到 models/main/

诚实说明：
- MiniMind-O 官方 Omni 权重当前以 PyTorch（safetensors）发布，官方未发布 GGUF；
  完整 Omni 管线（Thinker/Talker/SenseVoice/SigLIP2/Mimi/VAD/Codec）需要等官方
  GGUF/ONNX 转换或使用 llama.cpp-omni 方案（MiniCPM-o 系）。
- 本安装器支持安装「文本 Realtime Brain」GGUF（MiniMind2-gguf 系列，可直接用
  llama.cpp 跑实时判断），下载失败会如实报错，绝不假装成功。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def detect() -> dict:
    """Hardware Detection（§11）：CPU / GPU / CUDA / Vulkan → 推荐 backend。"""
    from runtime.hardware import HardwareDetector
    prof = HardwareDetector().detect()
    if prof.cuda_available and prof.gpu_vendor == "NVIDIA":
        backend = "cuda"
    elif prof.vulkan_available:
        backend = "vulkan"
    else:
        backend = "cpu"
    return {"profile": prof.to_dict(), "recommended_backend": backend}


def recommend(backend: str = "") -> str:
    """Recommended Model：按 backend 返回建议模型说明。"""
    backend = backend or detect()["recommended_backend"]
    return (
        "Realtime Brain（文本实时判断，llama.cpp 可跑）：MiniMind2-gguf 系列 0.1B~0.3B，"
        f"推荐 backend={backend}。\n"
        "完整 Omni（听/说/看）需官方 GGUF/ONNX 或 llama.cpp-omni 方案，当前以 PyTorch 发布；"
        "架构已按多组件 Device/Backend 预留（见 /v1/runtime/models 的组件计划）。"
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
    model = discover_models()
    print(f"推理运行时 : {_inference_runtime()}")
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
    "https://huggingface.co/jingyaogong/MiniMind2-gguf/resolve/main/MiniMind2-small-0.1B-Q4_K_M.gguf",
    "https://huggingface.co/jingyaogong/MiniMind2-gguf/resolve/main/MiniMind2-0.1B-Q4_K_M.gguf",
    "https://modelscope.cn/models/jingyaogong/MiniMind2-gguf/resolve/master/MiniMind2-small-0.1B-Q4_K_M.gguf",
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
    ap.add_argument("--realtime", action="store_true", help="下载 Realtime Brain（MiniMind GGUF）")
    ap.add_argument("--main", metavar="URL", default="", help="下载本地主模型 GGUF 到 models/main/")
    ap.add_argument("--url", default="", help="指定直链（配合 --realtime）")
    args = ap.parse_args()
    if args.check:
        return check()
    if args.realtime:
        return 0 if install_realtime(args.url) else 1
    if args.main:
        return 0 if install_main(args.main) else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
