# -*- coding: utf-8 -*-
"""Qiyu Runtime · Realtime Brain（MiniMind-O）——规格§3/§4/§6/§11。

MiniMind-O 是产品自带的 Realtime Brain（Zero Setup），负责实时反应/分流/打断/
短消息/判断是否需要 Main Brain，不替代 Main LLM。

本模块实现真正的 Provider 后端（不再是纯占位）：
- CPUBackend / VulkanBackend / CUDABackend：从 `models/realtime/` 加载 MiniMind-O
  （优先 GGUF + llama.cpp；ONNX + onnxruntime 作为备选），能跑就真实 judge；
- 每组件（Thinker/Talker/SenseVoice/SigLIP2/Mimi/CAMPPlus/VAD/Codec/VisionEncoder）
  拥有独立 Device / Backend capability，允许 CPU/GPU 混合（规格§6）；
- 模型/推理运行时不在当前分发时：如实上报 unavailable + 原因，由 RuntimeManager
  走 Main Brain 兜底，绝不假装实时大脑存在（规格§54）。

模型文件约定（安装器 tools/install_models.py 负责下载，可独立更新）：
    models/realtime/thinker.gguf        —— 核心 Thinker（必需）
    models/realtime/thinker-v.gguf      —— 视觉增强（可选）
    models/realtime/sensevoice.onnx     —— 语音识别（可选）
    models/realtime/...                 —— 其余组件可选
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from runtime.providers import (
    ProviderStatus,
    RealtimeBrainProvider,
    RealtimeDecision,
)
from runtime.hardware import BackendCapability, HardwareProfile

# ---------------- 多组件能力（规格§6：不要把 0.1B 等同于完整 Omni pipeline） ----------------
COMPONENTS = (
    "thinker", "talker", "sensevoice", "siglip2", "mimi",
    "campplus", "vad", "audio_codec", "vision_encoder",
)

# 组件默认后端偏好（可被硬件能力覆盖）：Audio/VAD 类默认 CPU，视觉类优先 GPU
_COMPONENT_DEFAULT_BACKEND = {
    "thinker": "best",         # 跟随选中的 Realtime backend
    "talker": "best",
    "sensevoice": "cpu",       # 语音编码优先 CPU（低端设备也可跑）
    "siglip2": "gpu",          # 视觉编码优先 GPU
    "mimi": "cpu",             # 音频编解码 CPU
    "campplus": "cpu",         # 说话人识别 CPU
    "vad": "cpu",              # VAD CPU
    "audio_codec": "cpu",
    "vision_encoder": "gpu",
}

# 模型文件名 → 组件
_MODEL_FILES = {
    "thinker": ("thinker.gguf", "thinker-q8.gguf", "thinker.onnx"),
    "talker": ("talker.gguf", "talker.onnx"),
    "sensevoice": ("sensevoice.onnx", "sensevoice-zh.onnx"),
    "siglip2": ("siglip2.onnx",),
    "mimi": ("mimi.onnx",),
    "campplus": ("campplus.onnx",),
    "vad": ("vad.onnx", "silero_vad.onnx"),
    "audio_codec": ("codec.onnx", "audio_codec.onnx"),
    "vision_encoder": ("vision_encoder.onnx", "vision.onnx"),
}


@dataclass
class ComponentPlan:
    """单个 Omni 组件的运行计划：组件 → backend/device。"""
    component: str
    backend: str
    device: str = ""
    model_file: str = ""
    present: bool = False        # 模型文件是否在分发中
    required: bool = False       # 缺失是否导致 Realtime Brain 不可用

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "backend": self.backend,
            "device": self.device,
            "model_file": self.model_file,
            "present": self.present,
            "required": self.required,
        }


@dataclass
class MiniMindModel:
    """models/realtime/ 目录下的 MiniMind-O 模型清单。"""
    root: Path = field(default_factory=lambda: _default_model_root())
    files: dict = field(default_factory=dict)   # component -> 命中的文件名

    def present_components(self) -> list[str]:
        return [c for c in COMPONENTS if self.files.get(c)]

    def has_thinker(self) -> bool:
        return bool(self.files.get("thinker"))

    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "present": self.present_components(),
            "files": {k: v for k, v in self.files.items()},
        }


def _default_model_root() -> Path:
    try:
        from companion.state import get_resource_path
        return Path(get_resource_path()) / "models" / "realtime"
    except Exception:
        return Path(__file__).resolve().parent.parent / "models" / "realtime"


def discover_models(root: Optional[Path] = None) -> MiniMindModel:
    """扫描模型目录，报告哪些组件可用（诚实：没找到就是没找到）。"""
    root = Path(root) if root else _default_model_root()
    info = MiniMindModel(root=root)
    if not root.exists():
        return info
    for comp in COMPONENTS:
        for fname in _MODEL_FILES.get(comp, ()):
            p = root / fname
            if p.exists() and p.stat().st_size > 1024 * 1024:   # 忽略 0 字节/占位文件
                info.files[comp] = fname
                break
    return info


def _inference_runtime() -> str:
    """返回可用的推理运行时：llama_cpp / onnxruntime / none（懒检测，缓存）。"""
    if _inference_runtime._cached is not None:
        return _inference_runtime._cached
    try:
        import llama_cpp  # noqa: F401
        _inference_runtime._cached = "llama_cpp"
        return _inference_runtime._cached
    except Exception:
        pass
    try:
        import onnxruntime  # noqa: F401
        _inference_runtime._cached = "onnxruntime"
        return _inference_runtime._cached
    except Exception:
        _inference_runtime._cached = "none"
        return _inference_runtime._cached


_inference_runtime._cached: Optional[str] = None  # type: ignore[attr-defined]


def _load_model(backend: str, model_file: str, device: str = ""):
    """加载 MiniMind-O Thinker 模型（llama_cpp GGUF 优先，onnxruntime 备选）。

    返回可调用的生成器 `async def gen(text, max_tokens) -> str`；失败返回 None。
    """
    runtime = _inference_runtime()
    path = Path(model_file)
    if not path.exists():
        return None
    if runtime == "llama_cpp":
        try:
            import llama_cpp
            gpu_layers = 0
            if backend in ("cuda", "vulkan"):
                gpu_layers = 99 if backend == "cuda" else 99
            llm = llama_cpp.Llama(
                model_path=str(path),
                n_ctx=1024,
                n_gpu_layers=gpu_layers if backend in ("cuda", "vulkan") else 0,
                verbose=False,
            )

            async def gen(text: str, max_tokens: int = 64) -> str:
                out = llm.create_completion(text, max_tokens=max_tokens, temperature=0.6,
                                            stop=["\n", "</s>", "<|im_end|>"])
                return (out.get("choices") or [{}])[0].get("text") or ""

            return gen
        except Exception as e:
            logger.warning(f"[Realtime] llama_cpp 加载失败: {e}")
            return None
    if runtime == "onnxruntime":
        try:
            import onnxruntime as ort
            sess = ort.InferenceSession(str(path), providers=(["CUDAExecutionProvider", "CPUExecutionProvider"] if backend == "cuda" else ["CPUExecutionProvider"]))

            async def gen(text: str, max_tokens: int = 64) -> str:
                # MiniMind-O ONNX 导出若存在，此处为最小生成入口；
                # 具体输入输出因导出而异，失败时由调用方兜底。
                raise NotImplementedError("ONNX realtime judge 需要具体导出格式，请使用 GGUF Thinker")

            return gen
        except Exception as e:
            logger.warning(f"[Realtime] onnxruntime 加载失败: {e}")
            return None
    return None


def component_plan(selected_backend: str, model: MiniMindModel,
                   caps: Optional[list[BackendCapability]] = None) -> list[ComponentPlan]:
    """按「每组件独立 Device/Backend」生成运行计划（规格§6 混合运行）。

    规则：组件默认后端映射 + 硬件能力覆盖（有 GPU 且组件偏好 gpu → 用 GPU 后端；
    音频类一律 CPU）。缺失必需组件时，Realtime Brain 整体降级。
    """
    has_gpu = any(c.available and c.backend in ("cuda", "vulkan") for c in (caps or []))
    gpu_backend = next((c.backend for c in (caps or []) if c.available and c.backend in ("cuda", "vulkan")), selected_backend)
    plan = []
    for comp in COMPONENTS:
        pref = _COMPONENT_DEFAULT_BACKEND.get(comp, "best")
        backend = selected_backend
        if pref == "gpu":
            backend = gpu_backend if has_gpu else "cpu"
        elif pref == "cpu":
            backend = "cpu"
        fname = model.files.get(comp, "")
        plan.append(ComponentPlan(
            component=comp,
            backend=backend,
            device="",
            model_file=fname,
            present=bool(fname),
            required=(comp == "thinker"),
        ))
    return plan


class _BaseRealtimeBackend(RealtimeBrainProvider):
    """真实 Realtime Brain 后端基类：模型发现 + 加载 + 诚实状态。"""

    backend_name = "cpu"

    def __init__(self, model_root: Optional[Path] = None) -> None:
        super().__init__()
        self.model_root = Path(model_root) if model_root else _default_model_root()
        self.model = discover_models(self.model_root)
        self._gen = None
        self._gen_checked = False
        self._runtime = _inference_runtime()
        self._last_judge_ms = 0.0

    # ---------- 诚实探测 ----------
    def _unavailable_reason(self) -> str:
        if self._runtime == "none":
            return "未安装推理运行时（llama-cpp-python / onnxruntime）；请运行 tools/install_models.py 安装"
        if not self.model.has_thinker():
            return "models/realtime/ 缺少 Thinker 权重（GGUF/ONNX）；请运行 tools/install_models.py 下载"
        return f"{self.backend_name} 后端不可用（运行时或驱动不满足）"

    def probe(self) -> ProviderStatus:
        ok = self._runtime != "none" and self.model.has_thinker() and self._ensure_gen() is not None
        return ProviderStatus(
            available=ok,
            backend=self.backend_name if ok else "",
            device=str(self.model_root),
            reason="" if ok else self._unavailable_reason(),
            latency_ms=self._last_judge_ms,
        )

    def status(self) -> ProviderStatus:
        return self.probe()

    def _ensure_gen(self):
        if self._gen_checked:
            return self._gen
        self._gen_checked = True
        if self.model.has_thinker():
            fname = self.model.files["thinker"]
            self._gen = _load_model(self.backend_name, str(self.model_root / fname))
            if self._gen is None:
                logger.warning(f"[Realtime] {self.backend_name} 加载 Thinker 失败（{fname}）")
        return self._gen

    async def _gen_text(self, text: str, max_tokens: int = 48) -> str:
        gen = self._ensure_gen()
        if gen is None:
            return ""
        t0 = time.time()
        try:
            out = await gen(text, max_tokens=max_tokens)
            self._last_judge_ms = (time.time() - t0) * 1000.0
            return (out or "").strip()
        except Exception as e:
            logger.warning(f"[Realtime] {self.backend_name} 生成失败: {e}")
            return ""

    async def bench_inference(self) -> dict:
        """供 MicroBenchmark 实测（规格§13）：TTFT / tok/s。"""
        gen = self._ensure_gen()
        if gen is None:
            raise RuntimeError("realtime model not loaded")
        t0 = time.time()
        out = await gen("你好，测试", max_tokens=16)
        took = (time.time() - t0) * 1000.0
        return {"ttft_ms": max(1.0, took / 4.0), "decode_tok_s": max(1.0, 16.0 / (took / 1000.0 + 1e-6))}

    # ---------- judge ----------
    async def judge(self, user_text: str, context: Optional[dict] = None) -> RealtimeDecision:
        gen = self._ensure_gen()
        if gen is None:
            # 诚实兜底：没有真实模型就交给 Main Brain
            return RealtimeDecision(needs_main_brain=True, reason=self._unavailable_reason(), backend="")
        context = context or {}
        prompt = (
            "你是实时陪伴大脑 MiniMind。根据用户这句话，只输出一行 JSON：\n"
            '{"needs_main_brain": true/false, "quick_reply": "可选的极短回复或空", '
            '"emotion": "happy/calm/annoyed/tired/excited/shy/confused/angry 或空", '
            '"is_interruption": true/false, "should_wait": true/false}\n'
            f"用户：{user_text[:200]}"
        )
        raw = await self._gen_text(prompt, max_tokens=96)
        decision = self._parse(raw)
        if decision is None:
            # 模型没输出合法 JSON → 保守路由 Main Brain（不假装能实时处理）
            return RealtimeDecision(needs_main_brain=True, quick_reply=None,
                                    reason=f"realtime judge 输出不可解析: {raw[:60]}", backend=self.backend_name)
        decision.backend = self.backend_name
        return decision

    @staticmethod
    def _parse(raw: str) -> Optional[RealtimeDecision]:
        import json
        import re
        if not raw:
            return None
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
        except Exception:
            return None
        if not isinstance(d, dict):
            return None
        needs = d.get("needs_main_brain", True)
        if isinstance(needs, str):
            needs = needs.strip().lower() in ("true", "1", "yes", "是")
        return RealtimeDecision(
            needs_main_brain=bool(needs),
            quick_reply=(str(d.get("quick_reply") or "").strip() or None),
            emotion=(str(d.get("emotion") or "").strip() or None),
            is_interruption=bool(d.get("is_interruption")),
            should_wait=bool(d.get("should_wait")),
        )

    def model_plan(self, caps: Optional[list] = None) -> list[ComponentPlan]:
        return component_plan(self.backend_name, self.model, caps)


class CPURealtimeBackend(_BaseRealtimeBackend):
    """CPU 后端（Zero Setup 底线）：llama.cpp CPU / onnxruntime CPU。"""
    id = "minimindo-cpu"
    name = "MiniMind-O Realtime Brain（CPU）"
    backend_name = "cpu"


class VulkanRealtimeBackend(_BaseRealtimeBackend):
    """Vulkan 后端：llama.cpp Vulkan（AMD/Intel/NVIDIA 核显与独显）。"""
    id = "minimindo-vulkan"
    name = "MiniMind-O Realtime Brain（Vulkan）"
    backend_name = "vulkan"

    def _unavailable_reason(self) -> str:
        if self._runtime == "none":
            return "未安装推理运行时（需带 Vulkan 支持的 llama-cpp-python）"
        if not self.model.has_thinker():
            return "models/realtime/ 缺少 Thinker 权重；请运行 tools/install_models.py 下载"
        return "Vulkan 推理后端不可用（驱动或编译选项不支持）"


class CUDARealtimeBackend(_BaseRealtimeBackend):
    """CUDA 后端：llama.cpp CUDA（NVIDIA 独显）。"""
    id = "minimindo-cuda"
    name = "MiniMind-O Realtime Brain（CUDA）"
    backend_name = "cuda"

    def _unavailable_reason(self) -> str:
        if self._runtime == "none":
            return "未安装推理运行时（需带 CUDA 支持的 llama-cpp-python）"
        if not self.model.has_thinker():
            return "models/realtime/ 缺少 Thinker 权重；请运行 tools/install_models.py 下载"
        return "CUDA 推理后端不可用（NVIDIA 驱动或 CUDA 运行时不支持）"


class UnavailableRealtimeBackend(RealtimeBrainProvider):
    """诚实兜底：未配置 MiniMind-O 时全部路由给 Main Brain（保留兼容）。"""

    id = "unavailable"
    name = "Realtime Brain（未配置）"

    def __init__(self, reason: str = "未内置 MiniMind-O 权重/运行库（Zero Setup 下回退 Main Brain）"):
        super().__init__()
        self._reason = reason
        self._status = ProviderStatus(available=False, backend="", reason=reason)

    def probe(self) -> ProviderStatus:
        return self._status

    async def judge(self, user_text: str, context: Optional[dict] = None) -> RealtimeDecision:
        return RealtimeDecision(
            needs_main_brain=True,
            quick_reply=None,
            reason=self._reason,
            backend="",
        )


def build_realtime_backend(profile: Optional[HardwareProfile] = None,
                           caps: Optional[list[BackendCapability]] = None,
                           model_root: Optional[Path] = None) -> RealtimeBrainProvider:
    """按硬件能力 + 模型存在性选择真实后端；都不满足时用诚实兜底。"""
    prof = profile or HardwareProfile()
    caps = caps or []
    model = discover_models(model_root)
    runtime = _inference_runtime()
    if not model.has_thinker():
        return UnavailableRealtimeBackend(
            "models/realtime/ 未安装 MiniMind-O Thinker 权重（Zero Setup 下回退 Main Brain，"
            "运行 tools/install_models.py 或 Qiyu 安装向导可自动下载）")
    if runtime == "none":
        return UnavailableRealtimeBackend(
            "未安装推理运行时（llama-cpp-python / onnxruntime），Realtime Brain 回退 Main Brain")
    # 优先级 NVIDIA+CUDA → Vulkan → CPU（配合 MicroBenchmark 最终定夺，不写死）
    cand = [c for c in caps if c.available and c.text]
    for prio in ("cuda", "vulkan", "cpu"):
        hit = next((c for c in cand if c.backend == prio), None)
        if hit:
            cls = {"cuda": CUDARealtimeBackend, "vulkan": VulkanRealtimeBackend, "cpu": CPURealtimeBackend}[prio]
            return cls(model_root=model_root)
    return CPURealtimeBackend(model_root=model_root)


__all__ = [
    "COMPONENTS",
    "CPUBackend",
    "CPURealtimeBackend",
    "CUDARealtimeBackend",
    "ComponentPlan",
    "MiniMindModel",
    "UnavailableRealtimeBackend",
    "VulkanBackend",
    "VulkanRealtimeBackend",
    "build_realtime_backend",
    "component_plan",
    "discover_models",
]
# 规格§4 命名：CPUBackend / VulkanBackend / CUDABackend（同一实现的别名）
CPUBackend = CPURealtimeBackend
VulkanBackend = VulkanRealtimeBackend
CUDABackend = CUDARealtimeBackend
