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


def default_model_dir(use_moe: bool = False) -> Path:
    from runtime import get_models_dir
    return get_models_dir("realtime") / ("minimind-3o-moe" if use_moe else "minimind-3o")


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


def torch_runtime_available() -> bool:
    """官方权重能否真实加载（torch + transformers + tokenizers 是否随包/随环境存在）。

    用 find_spec 做廉价探测，不在状态查询里 import 重型库；加载真正发生时仍会
    重新验证。打包版没有这些运行库时返回 False，让调用方回退 GGUF/llama.cpp，
    避免“权重在包里但模型跑不起来”的假可用。
    """
    try:
        import importlib.util
        return all(
            importlib.util.find_spec(m) is not None
            for m in ("torch", "transformers", "tokenizers")
        )
    except Exception:
        return False


def discover_model_dir(root: Optional[Path] = None,
                       use_moe: Optional[bool] = None) -> Optional[Path]:
    """自动发现 models/realtime/ 下的 MiniMind-O 完整模型目录。

    优先级：同结构（MoE/非 MoE）的已训练目录 → 对应官方 base。
    use_moe=None 时读取 QIYU_REALTIME_USE_MOE（1/true 为 MoE）。
    """
    if use_moe is None:
        use_moe = os.environ.get("QIYU_REALTIME_USE_MOE", "").strip().lower() in ("1", "true", "yes", "on")
    root = Path(root) if root else default_model_dir().parent
    if not root.exists():
        return None
    tags = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or not is_complete(d):
            continue
        name = d.name.lower()
        is_moe_dir = "moe" in name
        if use_moe != is_moe_dir:
            continue
        if (d.name.startswith("minimind-tag-") or d.name.startswith("minimind-sft-")
                or d.name.endswith("-local") or "moe" in name):
            tags.append(d)
    if tags:
        tags.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        return tags[0]
    preferred = ("minimind-3o-moe",) if use_moe else ("minimind-3o",)
    for name in preferred + ("minimind-3o-moe", "minimind-3o", "minimind_o", "minimindo"):
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
    target = Path(target) if target else default_model_dir(use_moe)
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
                 use_moe: bool = False, adapter_dir: Optional[Path] = None):
        if not use_moe:
            use_moe = os.environ.get("QIYU_REALTIME_USE_MOE", "").strip().lower() in (
                "1", "true", "yes", "on")
        if model_dir is None and os.environ.get("QIYU_REALTIME_MODEL_DIR"):
            _env_dir = Path(os.environ["QIYU_REALTIME_MODEL_DIR"])
            if is_complete(_env_dir):
                model_dir = _env_dir
        self.model_dir = Path(model_dir) if model_dir else (
            discover_model_dir(use_moe=use_moe) or default_model_dir(use_moe=use_moe))
        self.use_moe = use_moe
        if adapter_dir is None and os.environ.get("QIYU_REALTIME_ADAPTER"):
            adapter_dir = Path(os.environ["QIYU_REALTIME_ADAPTER"])
        if adapter_dir is None:
            # Parity 修复：绝不“自动叠 adapter”。
            # 训练产物（LoRA）必须显式用 QIYU_REALTIME_ADAPTER 指定；
            # 否则运行时只加载完整合并权重（如 minimind-tag-D6）。
            # 旧逻辑“取 adapters/<最新>”会把已经合并过的 tag 权重再叠一次 LoRA，
            # 造成 D6 被应用两次 / 或与评测链路不等价的坏输出。
            pass
        self.adapter_dir = Path(adapter_dir) if adapter_dir else None
        if self.adapter_dir is not None:
            _nm = str(self.model_dir.name)
            if _nm.startswith("minimind-tag-") or _nm.endswith("-local"):
                logger.warning(
                    f"[MiniMind-O] 显式加载 adapter={self.adapter_dir}，但 model_dir="
                    f"{self.model_dir.name} 看起来已是合并权重；若重复应用会造成与评测"
                    f"链路不等价，请确认这是有意的（仅训练/对比时使用）。")
        self.device = device or self._auto_device()
        self._model = None
        self._tokenizer = None      # tokenizers.Tokenizer（官方 tokenizer.json，零 transformers 依赖）
        self._load_error: Optional[str] = None
        self._last_ms = 0.0
        self._load_lock = threading.Lock()
        self._adapter_ok = False
        # 远程推理见 _remote_url property：每次读取环境变量，
        # 避免 runtime 重建/重载后丢失远程开关。

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
    def _remote_url(self) -> str:
        return (os.environ.get("QIYU_REALTIME_REMOTE_URL") or "").strip().rstrip("/")

    @property
    def loaded(self) -> bool:
        return self._model is not None or bool(self._remote_url)

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    @property
    def adapter_ok(self) -> bool:
        return self._adapter_ok

    def available(self) -> bool:
        if self._load_error:
            return False
        if not is_complete(self.model_dir):
            return False
        if self._remote_url:
            return True
        # M12：权重完整还不够——torch/transformers/tokenizers 必须真实可用才上报可用
        return torch_runtime_available()

    def ready(self) -> bool:
        """可立即推理（已加载或可加载）。"""
        if self._model is not None or self._remote_url:
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
        if self._remote_url:
            return
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            import json
            import torch
            from tokenizers import Tokenizer
            from runtime.minimindo.model_omni import MiniMindOmni, OmniConfig
            try:
                logger.info(f"[MiniMind-O] 加载官方权重: {self.model_dir} (device={self.device})")
                # 直接读 config.json 构造本地 OmniConfig，避免 transformers 动态加载
                # auto_map 里的 model_omni.py（PyInstaller 下源码不在文件系统，会 FileNotFoundError）
                with open(self.model_dir / "config.json", "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                config = OmniConfig(**config_data)
                # 文本推理：audio/vision 编码器传空路径 → 自动返回 None（不加载重依赖）
                model = MiniMindOmni(config, audio_encoder_path="", vision_model_path="")
                sd = torch.load(str(self.model_dir / "pytorch_model.bin"), map_location="cpu")
                missing, _unexpected = model.load_state_dict(sd, strict=False)
                extra = [k for k in missing if "audio" not in k and "vision" not in k
                         and k != "lm_head.weight"]
                if extra:
                    logger.warning(f"[MiniMind-O] 未匹配权重: {extra[:8]}")
                model.eval().to(self.device)
                if self.adapter_dir is not None:
                    if not (self.adapter_dir / "adapter_config.json").exists():
                        raise FileNotFoundError(
                            f"SFT adapter 目录缺少 adapter_config.json: {self.adapter_dir}")
                    from peft import PeftModel
                    peft = PeftModel.from_pretrained(model, str(self.adapter_dir))
                    model = peft.base_model.model if hasattr(peft, "base_model") else peft
                    model.eval().to(self.device)
                    self._adapter_ok = True
                    logger.info(f"[MiniMind-O] SFT adapter 已加载: {self.adapter_dir}")
                # 官方 tokenizer.json 直接本地加载：打包版不依赖 transformers.AutoTokenizer
                # 的动态懒加载（该路径在 PyInstaller 下会报“Could not import module 'AutoTokenizer'”）
                tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
                self._model, self._tokenizer = model, tokenizer
                n_params = sum(p.numel() for p in model.parameters()) / 1e6
                logger.info(f"[MiniMind-O] 加载完成：{n_params:.1f}M 参数，device={self.device} "
                            f"adapter={'on' if self._adapter_ok else 'off'}")
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
        if self._remote_url:
            return self._generate_text_remote(user_text, system, max_new_tokens,
                                              temperature, top_p, open_thinking)
        self._ensure_loaded()
        import torch
        # 与官方 chat_template.jinja 等价的本地模板（文本路径不使用 tools/tool_calls）
        parts = []
        if system:
            parts.append(f"<|im_start|>system\n{system}<|im_end|>\n")
        parts.append(f"<|im_start|>user\n{user_text}<|im_end|>\n")
        parts.append("<|im_start|>assistant\n")
        if open_thinking:
            parts.append("<think>\n")
        else:
            parts.append("<think>\n\n</think>\n\n")
        inputs_text = "".join(parts)
        x = torch.tensor(self._tokenizer.encode(inputs_text).ids,
                         dtype=torch.long, device=self.device)[None, ...]
        t0 = time.time()
        generated = None
        try:
            generated = self._model.generate_text_sync(
                x, eos_token_id=self._tokenizer.token_to_id("<|im_end|>"),
                max_new_tokens=max_new_tokens, temperature=temperature,
                top_p=top_p,
                open_thinking=open_thinking)
        except Exception as e:
            logger.warning(f"[MiniMind-O] 生成失败: {e}")
            return {"text": "", "ttft_ms": 0.0, "took_ms": (time.time() - t0) * 1000.0,
                    "decode_tok_s": 0.0, "tokens": 0, "error": str(e)}
        text = self._tokenizer.decode(generated.reshape(-1).tolist(), skip_special_tokens=True) if generated is not None else ""
        took_ms = (time.time() - t0) * 1000.0
        tokens = int(generated.numel()) if generated is not None else 0
        decode_ms = max(1.0, took_ms)
        ttft_ms = took_ms / max(1.0, tokens) if tokens else 0.0
        tok_s = tokens / (decode_ms / 1000.0) if tokens > 0 else 0.0
        self._last_ms = took_ms
        return {"text": text.strip(), "ttft_ms": ttft_ms, "took_ms": took_ms,
                "decode_tok_s": round(tok_s, 2), "tokens": tokens}

    def _generate_text_remote(self, user_text: str, system: str, max_new_tokens: int,
                              temperature: float, top_p: float, open_thinking: bool) -> dict:
        """走远程 GPU 服务（x99）生成，本机零前向开销。"""
        import json as _json
        import urllib.request
        t0 = time.time()
        try:
            payload = _json.dumps({
                "user": user_text, "system": system,
                "max_new_tokens": max_new_tokens, "temperature": temperature,
                "top_p": top_p, "open_thinking": bool(open_thinking),
            }).encode("utf-8")
            req = urllib.request.Request(self._remote_url + "/generate", data=payload,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read().decode("utf-8", "replace"))
            took_ms = float(data.get("took_ms") or (time.time() - t0) * 1000.0)
            self._last_ms = took_ms
            return {"text": (data.get("text") or "").strip(),
                    "ttft_ms": float(data.get("ttft_ms") or 0.0),
                    "took_ms": took_ms,
                    "decode_tok_s": float(data.get("decode_tok_s") or 0.0),
                    "tokens": int(data.get("tokens") or 0)}
        except Exception as e:
            logger.warning(f"[MiniMind-O] 远程推理失败: {e}")
            return {"text": "", "ttft_ms": 0.0, "took_ms": (time.time() - t0) * 1000.0,
                    "decode_tok_s": 0.0, "tokens": 0, "error": str(e)}

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
    "model_repo", "torch_runtime_available",
]
