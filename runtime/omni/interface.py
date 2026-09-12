# -*- coding: utf-8 -*-
"""栖语 · Realtime Omni 统一接口（规格 §2 与 §20）。

分两层，职责严格分开：

- ``IRealtimeOmni``：**上层业务看到的接口**。UI / Quest 网关 / demo 主链路只依赖它，
  永远不知道底下跑的是 MiniCPM-o、Qwen-Omni 还是云端 Realtime。
- ``IRealtimeOmniBackend``：**模型适配器接口**（规格 §20 的 ModelAdapter）。
  MiniCPMOBackend / QwenOmniBackend / CloudRealtimeBackend / FutureOmniBackend 都实现它。

硬性要求（写进 ABC 注释，改代码的人必须看）：

- 必须支持**长连接 session**，禁止「一次请求 → 等完整结果 → 返回」。
- 必须真正 streaming：文本 delta、音频 chunk 都是增量产出。
- 必须支持 ``interrupt()`` / ``cancel()``：用户插话时立刻停掉当前输出。
"""

from __future__ import annotations

import abc
from typing import Any, AsyncIterator, Optional

from runtime.omni.types import (
    AudioChunk,
    BackendCapabilities,
    HumanInteractionEvent,
    SessionConfig,
    UnifiedBrainEvent,
    VideoFrame,
    WorldEvent,
)


class IRealtimeOmni(abc.ABC):
    """上层业务唯一的 Omni 入口。

    典型用法（全双工）::

        omni = registry.build_omni()                 # 选后端 + 云端 fallback
        await omni.start_session(cfg)                # 长连接
        # 三条输入通道并行喂
        await omni.send_audio_chunk(chunk)           # 麦克风，持续
        await omni.send_video_frame(frame)           # 由 VideoScheduler 降采样后
        await omni.send_text("你在看啥？")
        # 输出侧：文本 delta / 音频 chunk / 统一事件
        async for ev in omni.receive_event():
            if ev.conversation:  ui.push(ev.conversation)
            if ev.avatar_intent: quest.apply(ev.avatar_intent)
        # 用户插话
        await omni.interrupt(reason="barge_in")
    """

    # ---------- 生命周期 ----------

    @abc.abstractmethod
    async def start_session(self, config: Optional[SessionConfig] = None) -> str:
        """建立长连接 session，返回 session_id。**不是**一次性请求。"""

    @abc.abstractmethod
    async def close(self) -> None:
        """关闭 session 并释放后端资源。"""

    # ---------- 输入（规格 §3：统一进 OmniSession） ----------

    @abc.abstractmethod
    async def send_audio_chunk(self, chunk: AudioChunk) -> None:
        """持续音频输入。必须支持 partial speech，不等整句结束。"""

    @abc.abstractmethod
    async def send_video_frame(self, frame: VideoFrame) -> None:
        """视频帧输入。由上层的 VideoScheduler 决定发哪些帧。"""

    @abc.abstractmethod
    async def send_text(self, text: str, *, speaker_id: str = "local_user") -> None:
        """文本输入。"""

    @abc.abstractmethod
    async def send_world_event(self, event: WorldEvent) -> None:
        """WorldState / 世界事件（房间、物体、注意力、交互摘要）。"""

    @abc.abstractmethod
    async def send_motion_event(self, event: HumanInteractionEvent) -> None:
        """HumanInteractionEvent（wave / point / high_five …），由 Quest 本地产生。"""

    # ---------- 输出（全部 streaming） ----------

    @abc.abstractmethod
    def receive_text_delta(self) -> AsyncIterator[str]:
        """流式文本增量。"""

    @abc.abstractmethod
    def receive_audio_chunk(self) -> AsyncIterator[AudioChunk]:
        """流式语音输出（原生 speech output 优先，不是等完整文本再 TTS）。"""

    @abc.abstractmethod
    def receive_event(self) -> AsyncIterator[UnifiedBrainEvent]:
        """统一大脑事件（ConversationOutput + AvatarIntent + 生命周期）。"""

    # ---------- 打断 ----------

    @abc.abstractmethod
    async def interrupt(self, reason: str = "") -> None:
        """高优先级打断（barge-in）。必须立刻停止当前 TTS/audio playback 与行为。"""

    @abc.abstractmethod
    async def cancel(self) -> None:
        """取消当前一轮生成，但保持 session 存活，新输入继续进同一 session。"""

    # ---------- 状态 ----------

    def capabilities(self) -> BackendCapabilities:
        """当前后端能力。默认保守声明。"""
        return BackendCapabilities()

    def health(self) -> dict:
        return {"status": "unknown"}

    @property
    def state(self) -> str:
        return "idle"

    @property
    def backend_name(self) -> str:
        return "unknown"


class IRealtimeOmniBackend(abc.ABC):
    """模型适配器接口（规格 §20）。

    实现方只负责「怎么把模型跑起来 + 怎么喂帧/喂音频 + 怎么吐出 delta」，
    不负责 session 编排、barge-in 判定、视频调度、指标采集 —— 那些是
    ``OmniSession`` 的事。这样换模型不需要重写 Quest/AI 架构。
    """

    name: str = "abstract"
    display_name: str = "抽象后端"

    # ---------- 生命周期 ----------

    @abc.abstractmethod
    async def load(self) -> dict:
        """加载模型/建立连接。返回 {"ok": bool, ...}。"""

    @abc.abstractmethod
    async def unload(self) -> dict:
        """卸载模型/断开连接。"""

    # ---------- 能力与健康 ----------

    @abc.abstractmethod
    def capabilities(self) -> BackendCapabilities:
        ...

    @abc.abstractmethod
    def health(self) -> dict:
        ...

    @abc.abstractmethod
    def available(self) -> bool:
        """当前机器上这个后端是否可用（权重是否存在、运行时是否可加载）。"""

    # ---------- 会话级流式接口 ----------

    @abc.abstractmethod
    async def open_stream(self, config: SessionConfig) -> "IRealtimeOmniStream":
        """开一路流式会话。"""


class IRealtimeOmniStream(abc.ABC):
    """后端内部的一路流式会话。由 ``OmniSession`` 持有。"""

    @abc.abstractmethod
    async def push_audio(self, chunk: AudioChunk) -> None:
        ...

    @abc.abstractmethod
    async def push_video(self, frame: VideoFrame) -> None:
        ...

    @abc.abstractmethod
    async def push_text(self, text: str, *, speaker_id: str = "local_user") -> None:
        ...

    @abc.abstractmethod
    async def push_event(self, payload: dict) -> None:
        """世界事件 / 动捕事件 / 记忆提示 / Avatar 状态等统一入口。"""

    @abc.abstractmethod
    def outputs(self) -> AsyncIterator[UnifiedBrainEvent]:
        """后端产出的统一事件流（文本 delta / 音频 chunk / AvatarIntent / 生命周期）。"""

    @abc.abstractmethod
    async def interrupt(self, reason: str = "") -> None:
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        ...


class BackendUnavailable(RuntimeError):
    """后端在当前机器上不可用（权重缺失 / 运行时无法加载 / GPU 不支持）。"""


__all__ = [
    "BackendUnavailable",
    "IRealtimeOmni",
    "IRealtimeOmniBackend",
    "IRealtimeOmniStream",
]
