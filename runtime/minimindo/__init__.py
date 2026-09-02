# -*- coding: utf-8 -*-
"""Qiyu Runtime · MiniMind-O 官方权重加载器（真实 Realtime Brain 后端）。

MiniMind-O 是官方端到端 Omni 模型（Thinker–Talker 双路，0.1B）：
单一权重支持文本/音频/图像输入 + 文本/流式语音输出，CPU 即可推理。

本模块只负责「把官方 transformers 权重真正跑起来」：
- vendor 官方 model_minimind.py / model_omni.py 的纯文本裁剪版
  （runtime/minimindo/，Apache-2.0，来源 github.com/jingyaogong/minimind-o）；
- 文本推理路径零额外依赖（不需要 funasr / librosa / soundfile），CPU 必跑，
  torch.cuda.is_available() 时自动走 CUDA；
- 模型目录自动发现 + 一键下载（ModelScope 优先，HF/hf-mirror 兜底）；
- 不硬编码模型路径：优先扫 models/realtime/ 下完整目录。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Optional

from loguru import logger

# 官方 transformers 格式权重仓库
MODEL_REPO = "gongjy/minimind-3o"           # ModelScope（国内主源）
MODEL_REPO_MOE = "gongjy/minimind-3o-moe"   # ModelScope MoE 版（312M-A115M）
HF_REPO = "jingyaogong/minimind-3o"         # HuggingFace（经 hf-mirror 兜底）
HF_REPO_MOE = "jingyaogong/minimind-3o-moe"

# 完整模型目录必须包含的文件
REQUIRED_FILES = (
    "config.json", "pytorch_model.bin", "model_omni.py", "model_minimind.py",
    "tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
)
_MIN_BIN_BYTES = 50 * 1024 * 1024  # 权重小于 50MB 视为未下载完整（占位/断点）


def default_model_dir() -> Path:
    from runtime import get_models_dir
    return get_models_dir("realtime") / "minimind-3o"


def model_repo(use_moe: bool = False) -> str:
    return MODEL_REPO_MOE if use_moe else MODEL_REPO


def hf_repo(use_moe: bool = False) -> str:
    return HF_REPO_MOE if use_moe else HF_REPO


def is_complete(model_dir) -> bool:
    """目录是否为可加载的完整官方权重（诚实检查，不把占位文件当真）。"""
    try:
        d = Path(model_dir)
        if not d.is_dir():
            return False
        for f in REQUIRED_FILES:
            if not (d / f).exists():
                return False
        return (d / "pytorch_model.bin").stat().st_size >= _MIN_BIN_BYTES
    except Exception:
        return False


def discover_model_dir(root: Optional[Path] = None) -> Optional[Path]:
    """自动发现 models/realtime/ 下的 MiniMind-O 完整模型目录。

    优先级：minimind-3o（0.1B）→ minimind-3o-moe → 任意包含完整权重的子目录。
    """
    root = Path(root) if root else default_model_dir().parent
    if not root.exists():
        return None
    for name in ("minimind-3o", "minimind-3o-moe", "minimind_o", "minimindo"):
        d = root / name
        if d.is_dir() and is_complete(d):
            return d
    # 兜底：一级子目录里找完整目录
    for d in sorted(root.iterdir()):
        if d.is_dir() and is_complete(d):
            return d
    return None


def download_model(target: Optional[Path] = None, use_moe: bool = False,
                   source: str = "auto") -> Path:
    """下载官方 MiniMind-O 权重（transformers 格式）到 models/realtime/。

    优先 ModelScope（国内可达）；失败后经 HF_ENDPOINT=hf-mirror 走 HuggingFace。
    已完整则跳过（幂等）。返回模型目录。
    """
    target = Path(target) if target else default_model_dir()
    target.mkdir(parents=True, exist_ok=True)
    if is_complete(target):
        logger.info(f"[MiniMind-O] 模型已存在: {target}")
        return target
    repo = model_repo(use_moe)
    hf = hf_repo(use_moe)
    # 1) ModelScope SDK
    if source in ("auto", "modelscope"):
        try:
            from modelscope import snapshot_download
            logger.info(f"[MiniMind-O] 从 ModelScope 下载 {repo} → {target}")
            snapshot_download(repo, local_dir=str(target))
            if is_complete(target):
                return target
        except Exception as e:
            logger.warning(f"[MiniMind-O] ModelScope 下载失败: {e}")
    # 2) huggingface_hub + hf-mirror
    if source in ("auto", "hf"):
        try:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            from huggingface_hub import snapshot_download as hf_dl
            logger.info(f"[MiniMind-O] 从 HF(hf-mirror) 下载 {hf} → {target}")
            hf_dl(hf, local_dir=str(target))
            if is_complete(target):
                return target
        except Exception as e:
            logger.warning(f"[MiniMind-O] HF(hf-mirror) 下载失败: {e}")
    raise RuntimeError(
        f"MiniMind-O 权重下载失败（ModelScope/HF 均不可用），目标目录: {target}")


class MiniMindOOmniRuntime:
    """真实 MiniMind-O 推理运行时（官方 transformers 权重 + torch）。

    - 文本推理零额外依赖（无 funasr/librosa/soundfile）
    - CPU 必跑；torch.cuda.is_available() 时自动用 CUDA
    - generate_text / bench 供 Realtime Brain 与 MicroBenchmark 实测
    """

    def __init__(self, model_dir: Optional[Path] = None, device: str = "",
                 use_moe: bool = False):
        self.model_dir = Path(model_dir) if model_dir else (
            discover_model_dir() or default_model_dir())
        self.use_moe = use_moe
        self.device = device or self._auto_device()
        self._model = None
        self._tokenizer = None
        self._load_error: Optional[str] = None
        self._last_ms = 0.0
        self._load_lock = threading.Lock()

    # ---------- 状态 ----------
    @staticmethod
    def _auto_device() -> str:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    @property
    def backend_name(self) -> str:
        return self.device  # "cpu" / "cuda"

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def available(self) -> bool:
        if self._load_error:
            return False
        if not is_complete(self.model_dir):
            return False
        return True

    def ready(self) -> bool:
        """可立即推理（已加载或可加载）。"""
        if self._model is not None:
            return True
        if not self.available():
            return False
        try:
            self._ensure_loaded()
            return self._model is not None
        except Exception:
            return False

    # ---------- 加载 ----------
    def _ensure_loaded(self) -> None:
        """加载模型（线程安全：judge/bench 并发时只加载一次）。"""
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            import torch
            from transformers import AutoTokenizer
            from runtime.minimindo.model_omni import MiniMindOmni, OmniConfig
            try:
                logger.info(f"[MiniMind-O] 加载官方权重: {self.model_dir} (device={self.device})")
                config = OmniConfig.from_pretrained(str(self.model_dir))
                # 文本推理：audio/vision 编码器传空路径 → 自动返回 None（不加载重依赖）
                model = MiniMindOmni(config, audio_encoder_path="", vision_model_path="")
                sd = torch.load(str(self.model_dir / "pytorch_model.bin"), map_location="cpu")
                missing, _unexpected = model.load_state_dict(sd, strict=False)
                extra = [k for k in missing if "audio" not in k and "vision" not in k
                         and k != "lm_head.weight"]
                if extra:
                    logger.warning(f"[MiniMind-O] 未匹配权重: {extra[:8]}")
                model.eval().to(self.device)
                tokenizer = AutoTokenizer.from_pretrained(str(self.model_dir))
                self._model, self._tokenizer = model, tokenizer
                n_params = sum(p.numel() for p in model.parameters()) / 1e6
                logger.info(f"[MiniMind-O] 加载完成：{n_params:.1f}M 参数，device={self.device}")
            except Exception as e:
                self._load_error = f"{type(e).__name__}: {e}"
                logger.error(f"[MiniMind-O] 模型加载失败: {self._load_error}")
                raise

    def unload(self) -> None:
        self._model = None
        self._tokenizer = None
        self._load_error = None

    # ---------- 文本推理 ----------
    def generate_text(self, user_text: str, system: str = "",
                      max_new_tokens: int = 96, temperature: float = 0.6,
                      top_p: float = 0.9, open_thinking: bool = False) -> dict:
        """文本推理（Thinker 文本路径）：返回 text / ttft_ms / tok_s / tokens。

        open_thinking=False（默认）：直接输出答案，适合实时 judge；
        open_thinking=True：先 <think> 再回答（模型自行决定）。
        """
        self._ensure_loaded()
        import torch
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_text})
        inputs_text = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            open_thinking=open_thinking)
        x = torch.tensor(self._tokenizer(inputs_text)["input_ids"],
                         dtype=torch.long, device=self.device)[None, ...]
        t0 = time.time()
        ttft_ms = 0.0
        generated = None
        try:
            gen = self._model.generate(
                x, eos_token_id=self._tokenizer.eos_token_id,
                max_new_tokens=max_new_tokens, temperature=temperature,
                top_p=top_p, stream=True, return_audio_codes=False,
                open_thinking=open_thinking)
            for y, _frame in gen:
                if y is None:
                    break
                if ttft_ms <= 0.0:
                    decoded = self._tokenizer.decode(y[0].tolist(), skip_special_tokens=True)
                    if decoded and decoded[-1] != "\ufffd":
                        ttft_ms = (time.time() - t0) * 1000.0
                generated = y[0]
        except Exception as e:
            logger.warning(f"[MiniMind-O] 生成失败: {e}")
            return {"text": "", "ttft_ms": 0.0, "took_ms": (time.time() - t0) * 1000.0,
                    "decode_tok_s": 0.0, "tokens": 0, "error": str(e)}
        text = self._tokenizer.decode(generated.tolist(), skip_special_tokens=True) if generated is not None else ""
        took_ms = (time.time() - t0) * 1000.0
        tokens = int(generated.shape[0]) if generated is not None else 0
        decode_ms = max(1.0, took_ms - ttft_ms)
        tok_s = tokens / (decode_ms / 1000.0) if tokens > 0 else 0.0
        self._last_ms = took_ms
        return {"text": text.strip(), "ttft_ms": ttft_ms, "took_ms": took_ms,
                "decode_tok_s": round(tok_s, 2), "tokens": tokens}

    def bench(self, max_tokens: int = 24) -> dict:
        """MicroBenchmark 实测：真实 TTFT / 解码速度。"""
        r = self.generate_text("你好，测试一下速度", max_new_tokens=max_tokens,
                               temperature=0.6)
        return {"ttft_ms": r.get("ttft_ms") or 0.0,
                "decode_tok_s": r.get("decode_tok_s") or 0.0,
                "tokens": r.get("tokens") or 0,
                "took_ms": r.get("took_ms") or 0.0}


__all__ = [
    "HF_REPO", "MODEL_REPO", "MODEL_REPO_MOE", "MiniMindOOmniRuntime",
    "default_model_dir", "discover_model_dir", "download_model", "is_complete",
    "model_repo",
]
