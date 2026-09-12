# -*- coding: utf-8 -*-
"""Qiyu Runtime · llama.cpp 编译后端探测。

用途：区分 llama.cpp 真实可用的 GPU 后端（CUDA / Vulkan / 无）。
背景：llama_supports_gpu_offload() 在 CUDA 版与 Vulkan 版都返回 True，
llama_max_devices() 也无法区分，导致非 NVIDIA 机器被误报 CUDA=true。
llama.cpp 在进程内第一次 llama_backend_init() 时会把真实注册的后端与
设备打到 stderr（ggml_cuda / ggml_vulkan ...）。本模块在首个 backend
初始化前捕获这段 banner，据此返回真实后端种类。

探测分三层（都失败时诚实返回空集，绝不误报）：
1) 进程内首次 llama_backend_init（llama-cpp-python 的 C 日志回调写 sys.stderr，
   可用 redirect_stderr 捕获）；
2) llama_cpp 已被别的模块 import 且 backend 已初始化 → 子进程探测（开发/测试环境）；
3) 仍无法判定 → 保守返回空集（CPU 仍可用）。
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
import subprocess
import sys

logger = logging.getLogger("qiyu.runtime")

_CACHE = None


def _parse_banner(banner: str) -> frozenset:
    low = (banner or "").lower()
    kinds = set()
    if "ggml_cuda" in low or "cuda_init" in low or "cuda devices" in low or "ggml_cuda" in low:
        kinds.add("cuda")
    if "ggml_vulkan" in low or "vulkan devices" in low or "ggml_vulkan" in low:
        kinds.add("vulkan")
    if "ggml_metal" in low or "metal_init" in low or "metal devices" in low:
        kinds.add("metal")
    return frozenset(kinds)


def _backend_initialized() -> bool:
    try:
        import llama_cpp  # noqa: F401
        ll = getattr(llama_cpp, "Llama", None)
        if ll is not None:
            return bool(getattr(ll, "_Llama__backend_initialized", False))
        return False
    except Exception:
        return False


def _probe_in_process() -> frozenset:
    """进程内首次 backend init：banner 会打到 sys.stderr（经 llama-cpp-python 日志回调）。"""
    try:
        import llama_cpp
    except Exception:
        return frozenset()
    if _backend_initialized():
        return frozenset()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            llama_cpp.llama_backend_init()
    except Exception:
        return frozenset()
    return _parse_banner(buf.getvalue())


def _probe_subprocess() -> frozenset:
    """开发/测试环境：新进程内 llama_backend_init，抓 stderr banner。

    PyInstaller 打包后绝不能走这条路：sys.executable 是 Qiyu.exe 本身，
    不是 python 解释器，`-c` 不会执行探测脚本，反而会再次拉起完整应用，
    形成“启动 → 探测 → 再启动”的连环进程爆炸（并在每次硬件检测时弹
    PowerShell 窗口）。打包版直接走进程内探测，探测不到就诚实按纯 CPU。
    """
    if getattr(sys, "frozen", False):
        return frozenset()
    code = (
        "import sys\n"
        "try:\n"
        "    import llama_cpp\n"
        "    llama_cpp.llama_backend_init()\n"
        "except Exception:\n"
        "    pass\n"
        "sys.stderr.flush()\n"
    )
    try:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=180, **kwargs,
        )
    except Exception:
        return frozenset()
    return _parse_banner(r.stderr or "")


def llama_gpu_kinds() -> frozenset:
    """返回 llama.cpp 真实 GPU 后端种类：{"cuda", "vulkan", "metal"} 的子集。

    探测失败/无法判定时返回空集（不误报），CPU 不受影响。
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    kinds = _probe_in_process()
    if not kinds:
        # 可能被别的模块先初始化过：换子进程再试一次
        kinds = _probe_subprocess()
    if not kinds:
        try:
            import llama_cpp
            if not llama_cpp.llama_supports_gpu_offload():
                _CACHE = frozenset()
                return _CACHE
        except Exception:
            pass
        logger.warning("llama.cpp GPU 后端无法确认（banner 不可捕获），保守按纯 CPU 处理，避免误报 CUDA")
    _CACHE = kinds
    return kinds


def llama_supports_gpu_offload() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return bool(llama_cpp.llama_supports_gpu_offload())
    except Exception:
        return False


def llama_supports_backend(backend: str) -> bool:
    """backend 在（cuda/vulkan/metal）且 llama.cpp 构建真实包含该后端。"""
    if backend == "cpu":
        return True
    return backend in llama_gpu_kinds()


def reset_cache() -> None:
    global _CACHE
    _CACHE = None


__all__ = [
    "llama_gpu_kinds",
    "llama_supports_backend",
    "llama_supports_gpu_offload",
    "reset_cache",
]
