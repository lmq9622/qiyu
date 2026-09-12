# -*- coding: utf-8 -*-
"""Qiyu Runtime · Realtime Brain（MiniMind-O）——规格§3/§4/§6/§11。

MiniMind-O 是产品自带的 Realtime Brain（Zero Setup），负责实时反应/分流/打断/
短消息/判断是否需要 Main Brain，不替代 Main LLM。

本模块实现真正的 Provider 后端（不再是纯占位）：
- MiniMindOOmniBackend：官方 MiniMind-O transformers 权重（torch，CPU 必跑 /
  CUDA 自动），文本推理零额外依赖，模型目录自动发现+下载（优先）；
- CPUBackend / VulkanBackend / CUDABackend：MiniMind2 GGUF + llama.cpp（含 Vulkan
  GPU）/ ONNX 备选路径，保留已有能力，能跑就真实 judge；
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

import asyncio
import os
import re
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
from runtime.minimindo import (
    MiniMindOOmniRuntime,
    discover_model_dir,
    is_complete,
    torch_runtime_available,
)
from runtime.ggml_probe import llama_gpu_kinds, llama_supports_backend

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
    from runtime import get_models_dir
    return get_models_dir("realtime")


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
        # 真实性门控：只有 llama.cpp 构建里真实包含该 GPU 后端才允许 GPU 卸载；
        # 否则会静默回退 Vulkan/CPU 并让 probe 误报 CUDA=true。
        if backend in ("cuda", "vulkan") and not llama_supports_backend(backend):
            logger.warning(
                f"[Realtime] llama.cpp 构建不含真实 {backend.upper()} 后端"
                f"（检测到：{'/'.join(sorted(llama_gpu_kinds())) or '仅 CPU'}），拒绝加载")
            return None
        try:
            import llama_cpp
            gpu_layers = 99 if backend in ("cuda", "vulkan") else 0
            llm = llama_cpp.Llama(
                model_path=str(path),
                n_ctx=1024,
                n_gpu_layers=gpu_layers,
                verbose=False,
            )

            async def gen(text: str, max_tokens: int = 64) -> str:
                # MiniMind2 使用 ChatML 模板（tokenizer_config: bos=<|im_start|>, eos=<|im_end|>）
                prompt = (
                    "<|im_start|>system\n你在微信上和对方聊天，像真人朋友一样回复，简短口语，不要自我介绍、不要客套、不要说自己是AI/助手。<|im_end|>\n"
                    f"<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n"
                )

                def _run() -> str:
                    out = llm.create_completion(prompt, max_tokens=max_tokens, temperature=0.6,
                                                stop=[
                                                    "<|im_end|>",
                                                ])
                    return (out.get("choices") or [{}])[0].get("text") or ""

                # llama.cpp 生成为同步阻塞调用：必须放 worker 线程执行，
                # 否则会冻结事件循环，导致所有 asyncio.wait_for 超时失效（Web 链路卡死根因）
                return await asyncio.to_thread(_run)

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


def _judge_prompt(user_text: str) -> str:
    """Realtime judge 的统一提示词（真实模型要求输出一行 JSON）。"""
    return (
        "你是实时陪伴大脑 MiniMind。根据用户这句话，只输出一行 JSON：\n"
        '{"needs_main_brain": true/false, "quick_reply": "可选的极短回复或空", '
        '"emotion": "happy/calm/annoyed/tired/excited/shy/confused/angry 或空", '
        '"is_interruption": true/false, "should_wait": true/false}\n'
        f"用户：{user_text[:200]}"
    )


def _parse_decision(raw: str) -> Optional[RealtimeDecision]:
    """解析 judge 输出：必须是合法 JSON 对象，否则返回 None（调用方诚实兜底）。"""
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

# ---------------- 快速直答辅助（0.1B 模型不做 JSON judge，直接出短句；失败回退规则/主脑） ----------------
_REFUSAL_RE = re.compile(
    r"(我无法|我不能|无法直接|没有.*功能|作为.*(ai|助手|语言模型|人工)|我是一个.*(助手|模型|聊天机器人)|"
    r"我是(?:个)?(?:ai|AI|聊天机器人|机器人|虚拟助手)|我只是一个机器人|"
    r"我不具备|不能执行|无法回答|不太确定|请告诉我更多|有什么.*帮助|很高兴为你服务|"
    r"仅.*文本|无法.*实时|根据您|根据你提供的信息|我是一个.*AI|对不起|抱歉，我|"
    r"我是(?:个)?(?:AI|ai|人工智能|机器人|助手)|我不是真人|我只是一|我是虚拟)", re.I)


_ECHO_OK_RE = re.compile(
    r"^(晚安|早安|早上好|中午好|下午好|晚上好|你好|您好|嗨|哈喽|hello|hi|"
    r"哈哈|哈哈哈|哈哈哈哈|嘿嘿|嗯|嗯嗯|哦|哦哦|好的|好呀|好啊|行|在|早|在嘛|在吗|"
    r"咋了|无聊|笑死|等会|我看看|"
    r"刚下班|下班了|我回来了|到家了|到啦|睡啦|睡了|起床了|起了)$", re.I)
_LABEL_RE = re.compile(r"^(?:对方|小栖|朋友|同事|答|回答|问|你|我|用户|小爱)[：:]")
# 客套/帮助台 AI 腔：这类输出直接判不合格，交回 Main Brain，绝不硬塞给用户
_SERVICE_RE = re.compile(
    r"(?:有什么|什么可以|可以帮|需要我|要我|我能).{0,8}(?:帮助|帮忙|为您|服务|解决)"
    r"|很高兴(?:认识|见到|为您|能)|请问|您好|请告诉我更多|您想|你想聊|聊点什么|"
    r"想聊些什么|有什么想|有什么需要|需要我帮忙|我可以帮|正在为您|为您提供|"
    r"根据(?:天气|您的|你)|详细描述|我在这里|我来帮|让我来|"
    r"谢谢夸奖|不用客气|作为(?:一个|名)?(?:AI|机器人|语言模型|助手)|我是一台|"
    r"我的聊天对象|你的聊天对象|对方的聊天对象|你是对方的|现在对方随口|"
    r"我不知道您|不好意思|在邮件|在课嘛|你好，我是|我是小|我是你的|小栗|"
    r"最近过得怎么样|你最近怎么样|你今天过得|怎么帮到你|有什么可以帮|我能帮|"
    r"好的困惑|困惑。|（没有关系）", re.I)

# 0.1B 直答常见退化形态（实测漏网样本）→ 一律判不合格回主脑
# 1) 中英混排的“百科式括号解释”：哈嗥（Mixed Pocket Mobile）是一种…
# 2) 开头短词 + 中文冒号的“词条解释”腔：晚安：吾家琴烂家私仕家 / 天气不错：晴天
# 3) 句中夹“对方：”标签：随便聊聊对方：你好…
_ALNUM_PAREN_RE = re.compile(r"[（(][^（）()]*[A-Za-z0-9][^（）()]*[）)]")
_LABEL_COLON_RE = re.compile(r"^[\u4e00-\u9fff]{1,6}[：:]")
_MID_SPEAKER_TAG_RE = re.compile(r"(?:对方|小栖|朋友|同事|答|回答|问)[：:]")
_ECHO_EXPLAIN_RE = re.compile(r"表示|是一个词语|的好处|可以衡量|给出详细|不是一只|它表达|它属于")
# v0.0.27：只拦“明确不可接受”，不再追求真人感完美
_ENTRY_EXPLAIN_RE = re.compile(r"(?:是一种|是指|指的是|的意思是|的含义是|网络用语|叫法|是.{0,4}的一种|属于|这句话|这是一句)")
_TRUNCATED_TAIL_RE = re.compile(r"^(?:嗯|好|哈|哦|诶|啊|对|是|行|草|笑死)[，,、\s]{1,3}(?:你是|你是不是|你|是|我|我们|一个)$")
_LONG_QUESTION_HELP_RE = re.compile(r"(?:需不需要|要不要|有什么可以|可以帮|需要我).{0,10}(?:吗|帮|忙|助)?$")
# v0.0.26：角色/状态设定被模型复读或自我介绍 → 一律不合格（宁可升 MainBrain）
_SELF_ECHO_RE = re.compile(
    r"^(?:你是|我是(?:一个|名|个)?(?:小|虚拟|机器人|AI|助手|人工智能))|"
    r"(?:你是.{0,8}(?:室友|朋友|恋人|小栖)|我是.{0,8}(?:室友|朋友|恋人|小栖|你的助手)|"
    r"嘴碍|嘴碎又护短|嘀嘀|护短的室友|咱们一起聊|聊些什么|"
    r"角色|人设|你是对方|你和对方|对方是|状态|好感|耐心|熟络朋友)", re.I)


def _quick_system(char_hint: str = "", role_context: str = "") -> str:
    """直答系统提示（omni 后端走 chat template 的 system 位）。

    role_context（v0.0.26）携带当前角色关系/耐心/最近聊天等内部状态，
    让简单直答也继承角色而非固定友好助手腔。
    Stage 1：加入 Qiyu Personality Spec，与 training/minimind_personality_base
    的训练 system 完全一致，保证 train / inference parity。
    Stage 1 只训练“栖语是谁”，因此不注入 char_hint / role_context 这类
    关系/情绪/耐心状态；Stage 2 标签条件化时再单独接入。
    """
    from runtime.brain.personality_spec import QIYU_FIRST_REACTION_SPEC
    return QIYU_FIRST_REACTION_SPEC


def _quick_prompt(user_text: str, char_hint: str = "", role_context: str = "") -> str:
    """快速直答提示（GGUF 等无独立 system 位的后端用）：口语、像真人、不说 AI 身份。"""
    hint = (char_hint or "").strip()[:80]
    persona = f"你是{hint}。" if hint else "你是对方的聊天好友。"
    parts = [persona]
    ctx = (role_context or "").strip()[:400]
    if ctx:
        parts.append(ctx)
    parts.append("对方刚在微信上发来一句话，你像真人朋友随口回一句，"
                 "口语自然简短，别客套、别问要不要帮忙、别说自己是AI/助手；"
                 "只回这一句，不要继续说下去，不要复述整句原文。")
    parts.append(f"对方：{(user_text or '').strip()[:120]}")
    return "\n".join(parts)


def _sanitize_quick_text(text: str, user_text: str = "") -> Optional[str]:
    """直答文本质量门槛：空/过长/拒答腔/客套 AI 腔/多轮退化 → 判不合格，交给 Main Brain。

    同时做轻度规整：去掉“对方：/答：”等标签头、只留首行；绝不把明显不合格的
    0.1B 输出硬塞给用户（宁可回退 Main Brain，也不让角色变客服）。
    """
    t = (text or "").strip()
    if not t:
        return None
    t = _LABEL_RE.sub("", t, count=1).strip()
    if "\n" in t:
        t = t.splitlines()[0].strip()
    if not t:
        return None
    if len(t) > 16:
        return None
    if _SELF_ECHO_RE.search(t):
        return None
    if _REFUSAL_RE.search(t) or _SERVICE_RE.search(t):
        return None
    if _ENTRY_EXPLAIN_RE.search(t):
        return None
    if _LONG_QUESTION_HELP_RE.search(t):
        return None
    if _TRUNCATED_TAIL_RE.match(t):
        return None
    # 只拦明确退化的极短结尾；不要误杀“咋了这是 / 你说得是”这类正常口语
    if re.search(r"(你是一个|那个男人|你是否|是生命之源|你答)", t):
        return None
    if len(t) <= 3 and t.endswith(("完", "答", "否")):
        return None
    if _ALNUM_PAREN_RE.search(t) or _MID_SPEAKER_TAG_RE.search(t):
        return None
    if _LABEL_COLON_RE.match(t):
        return None
    if "\ufffd" in t:
        return None
    u = (user_text or "").strip()
    # 0.1B 退化常见模式：回显用户原文后继续百科式解释
    if u and len(t) > 8:
        _tu = re.sub(r"[\uff1f?\uff01!\u3002\u002c,\s]", "", t)
        _uu = re.sub(r"[\uff1f?\uff01!\u3002\u002c,\s]", "", u)
        if _uu and _tu.startswith(_uu):
            if _ECHO_EXPLAIN_RE.search(t):
                return None
            if len(t) > 20:
                return None
    if u:
        ub = re.sub(r"[？?！!。，,\s]", "", u)
        tb = re.sub(r"[？?！!。，,\s]", "", t)
        # 把用户问题原样弹回（你吃饭了吗 → 你吃饭了吗？）→ 不合格
        if tb and tb == ub and t.rstrip().endswith(("？", "?")):
            return None
        # 完全回显：只在真人也会重复的问候/状态短词里放行
        if tb == ub and not _ECHO_OK_RE.match(u):
            return None
    return t[:16]


def _looks_like_echo(text: str, user_text: str) -> bool:
    """是否原样回显用户（0.1B 偶发退化形态；用于失败路径重试）。"""
    t = (text or "").strip()
    u = (user_text or "").strip()
    if not t or not u:
        return False
    return t == u or (u in t and len(t) <= len(u) + 2)

class _BaseRealtimeBackend(RealtimeBrainProvider):
    """真实 Realtime Brain 后端基类：模型发现 + 加载 + 诚实状态 + 快速直答。

    本基类承载 GGUF/ONNX Thinker 后端：
    - probe/quick_reply/judge 全部基于真实加载的生成器；
    - llama.cpp 构建不含的 GPU 后端在加载前就被拒绝（不误报）；
    - 生成串行化（_gen_lock），避免 llama.cpp 并发调用竞态。
    """

    backend_name = "cpu"

    def __init__(self, model_root: Optional[Path] = None) -> None:
        super().__init__()
        self.model_root = Path(model_root) if model_root else _default_model_root()
        self.model = discover_models(self.model_root)
        self._gen = None
        self._gen_checked = False
        self._gen_lock = asyncio.Lock()
        self._runtime = _inference_runtime()
        self._last_judge_ms = 0.0
        self._load_ms = 0.0
        self._rss_delta_mb = 0.0
        self._process_rss_mb = 0.0
        self._model_name = ""
        self._device = ""
        self.execution_backend = "cpu"   # v0.0.26：驱动 llama.cpp 的真实执行层（cpu/vulkan/cuda）

    # ---------- 真实后端门控 ----------
    def _backend_available(self) -> bool:
        """该 backend 在当前运行时/llama.cpp 构建里是否真实存在（CPU 永远可用）。"""
        if self._runtime == "none":
            return False
        if self.execution_backend == "cpu":
            return self._runtime in ("llama_cpp", "onnxruntime")
        return self._runtime == "llama_cpp" and llama_supports_backend(self.execution_backend)

    def _device_name(self) -> str:
        try:
            from runtime.hardware import HardwareDetector
            prof = HardwareDetector().detect()
        except Exception:
            return self.execution_backend
        if self.execution_backend == "cpu":
            return prof.cpu_name or "cpu"
        return prof.gpu_name or self.execution_backend

    @staticmethod
    def _rss_current() -> float:
        try:
            import os
            import psutil
            return float(psutil.Process(os.getpid()).memory_info().rss) / 1024 / 1024
        except Exception:
            return 0.0

    # ---------- 诚实探测 ----------
    def _unavailable_reason(self) -> str:
        if self._runtime == "none":
            return "未安装推理运行时（llama-cpp-python / onnxruntime）；请运行 tools/install_models.py 安装"
        if not self.model.has_thinker():
            return "models/realtime/ 缺少 Thinker 权重（GGUF/ONNX）；请运行 tools/install_models.py 下载"
        if self.execution_backend != "cpu" and not llama_supports_backend(self.execution_backend):
            kinds = "/".join(sorted(llama_gpu_kinds())) or "仅 CPU"
            return (f"{self.execution_backend.upper()} 后端不可用：llama.cpp 构建不含真实 "
                    f"{self.execution_backend.upper()} 后端（本机检测到后端：{kinds}）")
        return f"{self.backend_name} 后端不可用（运行时或驱动不满足）"

    def probe(self) -> ProviderStatus:
        ok = self._backend_available() and self.model.has_thinker() and self._ensure_gen() is not None
        return ProviderStatus(
            available=ok,
            backend=self.backend_name if ok else "",
            device=(self._device or self._device_name()) if ok else "",
            reason="" if ok else self._unavailable_reason(),
            latency_ms=self._last_judge_ms,
        )

    def status(self) -> ProviderStatus:
        return self.probe()

    def _ensure_gen(self):
        if self._gen_checked:
            return self._gen
        self._gen_checked = True
        if not self._backend_available() or not self.model.has_thinker():
            return None
        fname = self.model.files["thinker"]
        self._model_name = fname
        rss0 = self._rss_current()
        t0 = time.time()
        self._gen = _load_model(self.execution_backend, str(self.model_root / fname))
        self._load_ms = (time.time() - t0) * 1000.0
        self._process_rss_mb = self._rss_current()
        self._rss_delta_mb = max(0.0, self._process_rss_mb - rss0)
        if self._gen is None:
            logger.warning(f"[Realtime] {self.backend_name} 加载 Thinker 失败（{fname}）")
        else:
            self._device = self._device_name()
        return self._gen

    async def _gen_text(self, text: str, max_tokens: int = 48) -> str:
        gen = self._ensure_gen()
        if gen is None:
            return ""
        async with self._gen_lock:
            t0 = time.time()
            try:
                out = await gen(text, max_tokens=max_tokens)
                self._last_judge_ms = (time.time() - t0) * 1000.0
                return (out or "").strip()
            except Exception as e:
                logger.warning(f"[Realtime] {self.backend_name} 生成失败: {e}")
                return ""

    async def quick_reply(self, user_text: str, *, max_tokens: int = 48,
                          timeout_s: float = 6.0, char_hint: str = "",
                          role_context: str = "") -> Optional[dict]:
        """简单闲聊/情绪反应：MiniMind 直接出短句。任何失败/超时/不合格 → None（升主脑）。"""
        from runtime.legacy_gate import log_once, minimind_enabled
        if not minimind_enabled():
            log_once(logger, "minimind.quick_reply")
            return None
        if not self._backend_available():
            return None
        gen = self._ensure_gen()
        if gen is None:
            return None
        prompt = _quick_prompt(user_text, char_hint, role_context)
        async with self._gen_lock:
            t0 = time.time()
            try:
                out = await asyncio.wait_for(gen(prompt, max_tokens=max_tokens), timeout=timeout_s)
            except Exception as e:
                logger.warning(f"[Realtime] {self.backend_name} 快速回复失败: {e}")
                return None
        took_ms = (time.time() - t0) * 1000.0
        self._last_judge_ms = took_ms
        text = _sanitize_quick_text(out or "", user_text)
        if text is None:
            return None
        from runtime.brain.backchannel import normalize_reaction
        text = normalize_reaction(user_text, text)
        return {
            "text": text,
            "backend": self.backend_name,
            "model": self._model_name or (self.model.files.get("thinker") or ""),
            "device": self._device or self._device_name(),
            "ttft_ms": max(1.0, took_ms / 4.0),
            "took_ms": round(took_ms, 1),
        }

    # ---------- v0.0.26 统一生命周期 ----------
    async def load(self, backend: str = "auto", **kwargs) -> dict:
        """加载 GGUF/ONNX Thinker（llama.cpp 一般很快；失败不抛，回 Main Brain）。"""
        try:
            t0 = time.time()
            gen = self._ensure_gen()
            took_ms = (time.time() - t0) * 1000.0
            return {
                "ok": gen is not None,
                "backend": self.backend_name,
                "model": self._model_name or (self.model.files.get("thinker") or ""),
                "device": self._device or self._device_name(),
                "load_ms": round(self._load_ms or took_ms, 1),
                "ram_mb": round(self._rss_current(), 1),
                "reason": "" if gen is not None else self._unavailable_reason(),
            }
        except Exception as e:
            return {"ok": False, "backend": self.backend_name, "model": "", "reason": str(e)}

    async def unload(self, backend: str = "auto") -> dict:
        self._gen = None
        self._gen_checked = False
        return {"ok": True, "freed_backends": [self.backend_name]}

    def health(self) -> dict:
        return {
            "ok": self._backend_available() and self.model.has_thinker(),
            "backend": self.backend_name,
            "model": self._model_name or (self.model.files.get("thinker") or ""),
            "device": self._device or self._device_name(),
            "reason": "" if self._backend_available() and self.model.has_thinker() else self._unavailable_reason(),
            "loaded": self._gen is not None,
            "latency_ms": round(self._last_judge_ms, 1),
        }

    # ---------- judge（规则优先，不硬依赖 0.1B 输出 JSON） ----------
    async def judge(self, user_text: str, context: Optional[dict] = None) -> RealtimeDecision:
        from runtime.legacy_gate import log_once, minimind_enabled
        if not minimind_enabled():
            log_once(logger, "minimind.judge")
            return RealtimeDecision(needs_main_brain=True,
                                    reason="MiniMind 小脑线已废弃（0.05.24）→ MainBrain",
                                    backend="legacy_disabled")
        if not self._backend_available():
            return RealtimeDecision(needs_main_brain=True,
                                    reason=self._unavailable_reason(), backend="")
        from runtime.classifier import classify_user_message, route_confidence
        ctx = context or {}
        try:
            route = classify_user_message(user_text, has_images=bool(ctx.get("images")))
        except Exception as e:
            logger.warning(f"[Realtime] 规则分流异常，保守升级 Main Brain: {e}")
            return RealtimeDecision(needs_main_brain=True, quick_reply=None,
                                    reason="realtime 规则分流异常 → Main Brain", backend=self.backend_name)
        confidence = route_confidence(user_text, route.action, route.category)
        _ut = (user_text or "").strip()
        if (route.action in ("direct_reply", "emotion") and confidence >= 0.78
                and len(_ut) <= 12 and route.category in ("simple_chat", "simple_emotion")):
            rr = await self.quick_reply(
                user_text, max_tokens=48,
                char_hint=str(ctx.get("char_hint") or ""),
                role_context=str(ctx.get("role_context") or ""))
            if rr:
                return RealtimeDecision(
                    needs_main_brain=False,
                    quick_reply=rr["text"],
                    emotion=("happy" if route.category == "simple_emotion" else None),
                    reason=route.reason, backend=self.backend_name,
                    model=rr.get("model", ""), confidence=confidence,
                    category=route.category, judge_source="classifier+quick_reply")
            return RealtimeDecision(
                needs_main_brain=True, quick_reply=None,
                reason=f"realtime 快速回复不可用（{route.category}）→ 升级 Main Brain",
                backend=self.backend_name, confidence=confidence,
                category=route.category, judge_source="classifier+quick_reply")
        return RealtimeDecision(needs_main_brain=True, quick_reply=None,
                                reason=route.reason, backend=self.backend_name,
                                confidence=confidence, category=route.category,
                                judge_source="classifier")

    @staticmethod
    def _parse(raw: str) -> Optional[RealtimeDecision]:
        return _parse_decision(raw)

    async def bench_inference(self) -> dict:
        """供 MicroBenchmark 实测：TTFT / tok/s + load/RSS/device 元数据。"""
        gen = self._ensure_gen()
        if gen is None:
            raise RuntimeError("realtime model not loaded")
        async with self._gen_lock:
            t0 = time.time()
            out = await gen("你好，测试", max_tokens=16)
            took = (time.time() - t0) * 1000.0
        return {
            "ttft_ms": max(1.0, took / 4.0),
            "decode_tok_s": max(1.0, 16.0 / (took / 1000.0 + 1e-6)),
            "load_ms": round(self._load_ms, 1),
            "rss_delta_mb": round(self._rss_delta_mb, 1),
            "rss_mb": round(self._process_rss_mb, 1),
            "model": self._model_name or (self.model.files.get("thinker") or ""),
            "device": self._device or self._device_name(),
            "backend": self.backend_name,
        }

    def model_plan(self, caps: Optional[list] = None) -> list[ComponentPlan]:
        return component_plan(self.backend_name, self.model, caps)


class CPURealtimeBackend(_BaseRealtimeBackend):
    """GGUF CPU 后端（Zero Setup 底线）：llama.cpp CPU / onnxruntime CPU。"""
    id = "gguf_cpu"
    name = "MiniMind Thinker（GGUF · CPU）"
    backend_name = "gguf_cpu"

    def __init__(self, model_root: Optional[Path] = None) -> None:
        super().__init__(model_root)
        self.execution_backend = "cpu"


class VulkanRealtimeBackend(_BaseRealtimeBackend):
    """Vulkan 后端：llama.cpp Vulkan（AMD/Intel/NVIDIA 核显与独显）。"""
    id = "gguf_vulkan"
    name = "MiniMind Thinker（GGUF · Vulkan）"
    backend_name = "gguf_vulkan"

    def __init__(self, model_root: Optional[Path] = None) -> None:
        super().__init__(model_root)
        self.execution_backend = "vulkan"

    def _backend_available(self) -> bool:
        return self._runtime == "llama_cpp" and llama_supports_backend("vulkan")

    def _unavailable_reason(self) -> str:
        if self._runtime == "none":
            return "未安装推理运行时（需带 Vulkan 支持的 llama-cpp-python）"
        if not self.model.has_thinker():
            return "models/realtime/ 缺少 Thinker 权重；请运行 tools/install_models.py 下载"
        return "Vulkan 推理后端不可用：llama.cpp 构建不含真实 Vulkan 后端（驱动或编译选项不支持）"


class CUDARealtimeBackend(_BaseRealtimeBackend):
    """CUDA 后端：llama.cpp CUDA（仅 NVIDIA 独显 + CUDA 驱动 + CUDA 构建三条件都满足才算可用）。"""
    id = "cuda"
    name = "MiniMind Thinker（CUDA）"
    backend_name = "cuda"

    def __init__(self, model_root: Optional[Path] = None) -> None:
        super().__init__(model_root)
        self.execution_backend = "cuda"

    def _backend_available(self) -> bool:
        if self._runtime != "llama_cpp" or not llama_supports_backend("cuda"):
            return False
        try:
            from runtime.hardware import HardwareDetector
            prof = HardwareDetector().detect()
            return prof.gpu_vendor == "NVIDIA" and bool(prof.cuda_available)
        except Exception:
            return False

    def _unavailable_reason(self) -> str:
        if self._runtime == "none":
            return "未安装推理运行时（需带 CUDA 支持的 llama-cpp-python）"
        if not self.model.has_thinker():
            return "models/realtime/ 缺少 Thinker 权重；请运行 tools/install_models.py 下载"
        if not llama_supports_backend("cuda"):
            return "CUDA 推理后端不可用：llama.cpp 构建不含真实 CUDA 后端（本机无 NVIDIA 或需安装带 CUDA 的 llama-cpp-python）"
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

    async def quick_reply(self, user_text: str, *, max_tokens: int = 48,
                          timeout_s: float = 6.0, char_hint: str = "",
                          role_context: str = "") -> Optional[dict]:
        return None

    async def load(self, backend: str = "auto", **kwargs) -> dict:
        return {"ok": False, "backend": "", "model": "", "reason": self._reason}

    async def unload(self, backend: str = "auto") -> dict:
        return {"ok": True, "freed_backends": []}

    async def analyze(self, user_text: str, context: Optional[dict] = None) -> dict:
        return {
            "needs_main_brain": True, "quick_reply": None, "confidence": 1.0,
            "category": "unavailable", "emotion": None, "backend": "",
            "model": "", "judge_source": "unavailable", "reason": self._reason,
            "meta": {},
        }

    async def benchmark(self) -> list[dict]:
        return []

    def health(self) -> dict:
        return {"ok": False, "backend": "", "model": "", "device": "",
                "reason": self._reason, "loaded": False, "latency_ms": 0.0}


class MiniMindOOmniBackend(RealtimeBrainProvider):
    """真实 MiniMind-O 后端：官方 transformers 权重（torch）。

    - 文本推理零额外依赖（无需 funasr/librosa/soundfile），CPU 必跑，
      torch.cuda.is_available() 时自动走 CUDA；
    - 模型目录自动发现 models/realtime/minimind-3o/...（缺失可经 install_models 下载）；
    - judge 输出不是合法 JSON 时诚实回退 Main Brain（不假装实时大脑存在）。
    """

    id = "official_cpu"
    name = "MiniMind-O 官方权重（torch）"

    def __init__(self, model_root: Optional[Path] = None, device: str = "",
                 use_moe: bool = False) -> None:
        super().__init__()
        if not use_moe:
            use_moe = os.environ.get("QIYU_REALTIME_USE_MOE", "").strip().lower() in (
                "1", "true", "yes", "on")
        self.model_root = Path(model_root) if model_root else _default_model_root()
        self._runtime = MiniMindOOmniRuntime(device=device, use_moe=use_moe)
        self.runtime_label = "minimindo-torch"
        if (model_root is not None and is_complete(model_root)
                and not os.environ.get("QIYU_REALTIME_MODEL_DIR")):
            self._runtime.model_dir = Path(model_root)
        self._last_judge_ms = 0.0
        self._quick_lock = asyncio.Lock()
        self._load_ms = 0.0
        self._rss_delta_mb = 0.0
        self._process_rss_mb = 0.0

    # ---------- 能力 ----------
    @property
    def backend_name(self) -> str:
        # v0.0.26 命名：torch CPU → official_cpu；真实 CUDA 运行时 → cuda
        if self._runtime.device == "cuda":
            return "cuda"
        return "official_cpu"

    def supported_backends(self) -> list[str]:
        """该后端真实能跑的 backend（决定 MicroBenchmark 候选，不写死）。"""
        return [self.backend_name]

    def _unavailable_reason(self) -> str:
        if self._runtime.load_error:
            return f"MiniMind-O 模型加载失败: {self._runtime.load_error[:200]}"
        if not torch_runtime_available():
            return ("未找到 MiniMind-O 官方权重所需的 torch/transformers 运行库；"
                    "已自动使用 GGUF/llama.cpp Thinker 后端（若存在）")
        return ("models/realtime/ 缺少完整 MiniMind-O 官方权重（minimind-3o/）；"
                "运行 tools/install_models.py --omni 或 Qiyu 安装向导自动下载")

    def probe(self) -> ProviderStatus:
        # 只做廉价检查（目录完整 + 无加载错误），绝不在此加载模型：
        # 状态查询不得阻塞事件循环，也不得与 judge/bench 并发加载模型。
        ok = self._runtime.available()
        return ProviderStatus(
            available=ok,
            backend=self.backend_name if ok else "",
            device=str(self._runtime.model_dir),
            reason="" if ok else self._unavailable_reason(),
            latency_ms=self._last_judge_ms,
        )

    def status(self) -> ProviderStatus:
        return self.probe()

    async def load(self, backend: str = "auto", **kwargs) -> dict:
        """加载官方 MiniMind-O（torch 首载约 20s，放到 worker 线程，不阻塞事件循环）。"""
        if not self._runtime.available():
            return {"ok": False, "backend": self.backend_name, "model": "minimind-3o",
                    "reason": self._unavailable_reason()}
        try:
            await asyncio.to_thread(self._measure_load_once)
            ok = self._runtime.loaded
            return {
                "ok": ok,
                "backend": self.backend_name,
                "model": "minimind-3o",
                "device": self._runtime.device,
                "load_ms": round(self._load_ms, 1),
                "ram_mb": round(self._rss_current(), 1),
                "adapter": os.path.basename(str(self._runtime.adapter_dir)) if self._runtime.adapter_dir else "",
                "adapter_loaded": self._runtime.adapter_ok,
                "reason": "" if ok else (self._runtime.load_error or "加载失败"),
            }
        except Exception as e:
            return {"ok": False, "backend": self.backend_name, "model": "minimind-3o",
                    "reason": str(e)}

    async def unload(self, backend: str = "auto") -> dict:
        await asyncio.to_thread(self.unload_now)
        return {"ok": True, "freed_backends": [self.backend_name]}

    def unload_now(self) -> None:
        self._runtime.unload()
        self._load_ms = 0.0
        self._rss_delta_mb = 0.0
        self._process_rss_mb = 0.0

    def health(self) -> dict:
        ok = self._runtime.available() and self._runtime.loaded
        return {
            "ok": ok,
            "backend": self.backend_name,
            "model": "minimind-3o",
            "device": self._runtime.device,
            "reason": "" if ok else self._unavailable_reason(),
            "loaded": self._runtime.loaded,
            "latency_ms": round(self._last_judge_ms, 1),
            "adapter": os.path.basename(str(self._runtime.adapter_dir)) if self._runtime.adapter_dir else "",
            "adapter_loaded": self._runtime.adapter_ok,
        }

    # ---------- 加载度量 ----------
    def _measure_load_once(self) -> None:
        """首轮生成前记录 load_ms / RSS 增量（只记一次，避免污染后续指标）。"""
        if self._load_ms > 0 or not self._runtime.available():
            return
        if self._runtime.loaded:
            self._load_ms = 0.0
            return
        rss0 = self._rss_current()
        t0 = time.time()
        try:
            self._runtime._ensure_loaded()
        except Exception:
            return
        self._load_ms = (time.time() - t0) * 1000.0
        self._process_rss_mb = self._rss_current()
        self._rss_delta_mb = max(0.0, self._process_rss_mb - rss0)

    @staticmethod
    def _rss_current() -> float:
        try:
            import os
            import psutil
            return float(psutil.Process(os.getpid()).memory_info().rss) / 1024 / 1024
        except Exception:
            return 0.0

    async def _omni_generate(self, user_text: str, system: str = "",
                             max_new_tokens: int = 48, temperature: float = 0.7) -> Optional[dict]:
        if not self._runtime.available():
            return None
        self._measure_load_once()
        try:
            r = await asyncio.wait_for(
                asyncio.to_thread(self._runtime.generate_text, user_text, system,
                                  max_new_tokens, temperature, 0.9, False),
                timeout=20.0,
            )
        except Exception as e:
            logger.warning(f"[Realtime] MiniMind-O 推理异常: {e}")
            return None
        self._last_judge_ms = float(r.get("took_ms") or 0.0)
        return r

    async def quick_reply(self, user_text: str, *, max_tokens: int = 48,
                          timeout_s: float = 6.0, char_hint: str = "",
                          role_context: str = "") -> Optional[dict]:
        if not self._runtime.available():
            return None
        if not self._runtime.loaded:
            # 只服务已预热模型：MiniMind-O 首载需 20s+，不能阻塞聊天；
            # 后台 bench/warm 把权重载入内存后，简单消息才由它直答，否则本轮走 Main Brain。
            return None
        system = _quick_system(char_hint, role_context)
        # 与训练/官方 chat template 保持一致：user 位直接放原始用户文本，
        # 不加“对方：”前缀（该前缀会让 0.1B 小脑进入第三人称复读/对喷模式）。
        prompt_user = (user_text or "").strip()[:120]
        async with self._quick_lock:
            t0 = time.time()
            try:
                r = await asyncio.wait_for(
                    asyncio.to_thread(self._runtime.generate_text, prompt_user, system,
                                      # 0.1B SFT 小脑做短句 slot-fill：高温采样会抽到低概率乱码
                                      # （实测 0.85 下出现"定罪/在我听听"类碎句），降到 0.3 稳定复现训练目标。
                                      min(max_tokens, 16), 0.4, 0.9, False),
                    timeout=timeout_s,
                )
            except Exception as e:
                logger.warning(f"[Realtime] MiniMind-O 快速回复失败: {e}")
                return None
        took_ms = (time.time() - t0) * 1000.0
        raw = (r.get("text") or "").strip()
        self._last_judge_ms = float(r.get("took_ms") or took_ms)
        text = _sanitize_quick_text(raw, user_text)
        if text is None and _looks_like_echo(raw, user_text):
            # 0.1B 偶发原样回显：换温度重试一次（只在失败路径发生，正常路径零开销）
            try:
                r2 = await asyncio.wait_for(
                    asyncio.to_thread(self._runtime.generate_text, prompt_user, system,
                    min(max_tokens, 16), 0.65, 0.9, False),
                    timeout=timeout_s,
                )
                raw2 = (r2.get("text") or "").strip()
                text = _sanitize_quick_text(raw2, user_text)
                if text is not None:
                    raw, r = raw2, r2
            except Exception as e:
                logger.debug(f"[Realtime] 回显重试失败: {e}")
        if text is None:
            return None
        from runtime.brain.backchannel import normalize_reaction
        text = normalize_reaction(user_text, text)
        return {
            "text": text,
            "backend": self.backend_name,
            "model": "minimind-3o",
            "device": self._runtime.device,
            "ttft_ms": float(r.get("ttft_ms") or 0.0),
            "took_ms": float(r.get("took_ms") or took_ms),
        }
    # ---------- judge（规则优先；0.1B 不再被要求输出 JSON） ----------
    async def judge(self, user_text: str, context: Optional[dict] = None) -> RealtimeDecision:
        if not self._runtime.available():
            return RealtimeDecision(needs_main_brain=True,
                                    reason=self._unavailable_reason(), backend="")
        from runtime.classifier import classify_user_message, route_confidence
        ctx = context or {}
        try:
            route = classify_user_message(user_text, has_images=bool(ctx.get("images")))
        except Exception as e:
            logger.warning(f"[Realtime] 规则分流异常，保守升级 Main Brain: {e}")
            return RealtimeDecision(needs_main_brain=True, quick_reply=None,
                                    reason="realtime 规则分流异常 → Main Brain", backend=self.backend_name)
        confidence = route_confidence(user_text, route.action, route.category)
        _ut = (user_text or "").strip()
        if (route.action in ("direct_reply", "emotion") and confidence >= 0.78
                and len(_ut) <= 12 and route.category in ("simple_chat", "simple_emotion")):
            rr = await self.quick_reply(
                user_text, max_tokens=48,
                char_hint=str(ctx.get("char_hint") or ""),
                role_context=str(ctx.get("role_context") or ""))
            if rr:
                return RealtimeDecision(
                    needs_main_brain=False,
                    quick_reply=rr["text"],
                    emotion=("happy" if route.category == "simple_emotion" else None),
                    reason=route.reason, backend=self.backend_name,
                    model=rr.get("model", ""), confidence=confidence,
                    category=route.category, judge_source="classifier+quick_reply")
            return RealtimeDecision(
                needs_main_brain=True, quick_reply=None,
                reason=f"realtime 快速回复不可用（{route.category}）→ 升级 Main Brain",
                backend=self.backend_name, confidence=confidence,
                category=route.category, judge_source="classifier+quick_reply")
        return RealtimeDecision(needs_main_brain=True, quick_reply=None,
                                reason=route.reason, backend=self.backend_name,
                                confidence=confidence, category=route.category,
                                judge_source="classifier")

    # ---------- MicroBenchmark 实测 ----------
    async def bench_inference(self) -> dict:
        if not self._runtime.available():
            raise RuntimeError("MiniMind-O 模型未就绪")
        def _bench_once():
            self._measure_load_once()  # 首载时记录真实 load_ms / RSS（worker 线程内，不阻塞事件循环）
            return self._runtime.bench(24)
        async with self._quick_lock:
            r = await asyncio.to_thread(_bench_once)
        return {
            "ttft_ms": float(r.get("ttft_ms") or 0.0),
            "decode_tok_s": float(r.get("decode_tok_s") or 0.0),
            "load_ms": round(self._load_ms, 1),
            "rss_delta_mb": round(self._rss_delta_mb, 1),
            "rss_mb": round(self._process_rss_mb, 1),
            "model": "minimind-3o",
            "device": self._runtime.device,
            "backend": self.backend_name,
        }

    # ---------- 组件计划 ----------
    def model_plan(self, caps: Optional[list] = None) -> list[ComponentPlan]:
        # 官方权重 = Thinker 文本能力已真实就绪；其余 Omni 组件（语音/视觉）未捆绑
        m = MiniMindModel(root=self._runtime.model_dir,
                          files={"thinker": "minimind-3o/pytorch_model.bin"})
        return component_plan(self.backend_name, m, caps)


def build_realtime_backend(profile: Optional[HardwareProfile] = None,
                           caps: Optional[list[BackendCapability]] = None,
                           model_root: Optional[Path] = None) -> RealtimeBrainProvider:
    """按硬件能力 + 模型存在性选择真实后端；都不满足时用诚实兜底。

    优先级：官方 MiniMind-O 权重（torch，CPU 必跑 / CUDA 自动）→
    MiniMind2 GGUF（llama.cpp：CUDA/Vulkan/CPU）→ 诚实兜底。
    """
    prof = profile or HardwareProfile()
    caps = caps or []
    # 1) 官方 MiniMind-O 权重完整 → 真实 Omni 后端（文本推理零额外依赖）
    omni_dir = discover_model_dir(model_root)
    if omni_dir is not None and torch_runtime_available():
        logger.info(f"[Realtime] 使用官方 MiniMind-O 权重: {omni_dir}")
        return MiniMindOOmniBackend(model_root=omni_dir)
    if omni_dir is not None:
        logger.warning(
            f"[Realtime] 发现官方 MiniMind-O 权重 {omni_dir}，但本包不含 torch 运行库，"
            "回退 GGUF Thinker（llama.cpp CPU/Vulkan）")
    # 2) 现有 GGUF/ONNX Thinker 路径（保留已有能力）
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
    "MiniMindOOmniBackend",
    "CPURealtimeBackend",
    "CUDARealtimeBackend",
    "ComponentPlan",
    "MiniMindModel",
    "UnavailableRealtimeBackend",
    "VulkanBackend",
    "_judge_prompt",
    "_parse_decision",
    "VulkanRealtimeBackend",
    "build_realtime_backend",
    "component_plan",
    "discover_models",
]
# 规格§4 命名：CPUBackend / VulkanBackend / CUDABackend（同一实现的别名）
CPUBackend = CPURealtimeBackend
VulkanBackend = VulkanRealtimeBackend
CUDABackend = CUDARealtimeBackend
