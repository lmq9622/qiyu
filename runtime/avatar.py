# -*- coding: utf-8 -*-
"""Qiyu Runtime · Avatar（Live2D / VRC / 未来 3D，规格§40/§41/§44）。

- AvatarProvider：AI 侧只输出 emotion/intensity/action/expression/gesture，
  不写死任何 Live2D 细节；
- GenericAvatarController：Live2D 是第一个实现，VRC 是未来实现；
- Avatar Runtime 决定如何执行（本层产出的 Live2DCommand 由前端/外部 Live2D
  运行时消费，前端不直接拼动作）；
- 视频通话架构预留：CameraInput / AudioInput / AudioOutput / AvatarRenderer
  接口（streaming / interrupt / cancel / partial / incremental）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from runtime.providers import AIProvider, ProviderKind, ProviderStatus

EMOTIONS = ("happy", "calm", "annoyed", "tired", "excited", "shy", "confused", "angry", "neutral")
ACTIONS = ("look_at_user", "look_away", "nod", "shake", "wave", "lean_in", "idle", "sigh", "laugh", "blush")


@dataclass
class AvatarAction:
    """AI 输出的头像动作意图（§40 示例字段）。"""
    emotion: str = "neutral"
    intensity: float = 0.0
    action: str = "idle"
    expression: str = ""
    gesture: str = ""
    text: str = ""                      # 同步台词（供口型/字幕）
    speed: float = 1.0

    def to_dict(self) -> dict:
        return {
            "emotion": self.emotion,
            "intensity": round(max(0.0, min(1.0, self.intensity)), 3),
            "action": self.action,
            "expression": self.expression,
            "gesture": self.gesture,
            "text": self.text[:500],
            "speed": round(self.speed, 2),
        }


@dataclass
class AvatarState:
    """当前头像状态（情绪平滑，§33：不会上一句开心下一句暴怒）。"""
    current_emotion: str = "neutral"
    current_intensity: float = 0.0
    last_action: str = "idle"
    updated_at: float = 0.0
    provider: str = ""

    def to_dict(self) -> dict:
        return {
            "emotion": self.current_emotion,
            "intensity": round(self.current_intensity, 3),
            "action": self.last_action,
            "provider": self.provider,
            "updated_at": round(self.updated_at, 3),
        }


class AvatarProvider(AIProvider):
    """头像 Provider 基类：把 AI 动作意图转成具体平台命令。"""

    kind = ProviderKind.AVATAR
    avatar_type = "generic"

    def supports(self, avatar_type: str) -> bool:
        return avatar_type == self.avatar_type

    async def render(self, action: AvatarAction) -> dict:
        raise NotImplementedError

    def describe_capabilities(self) -> dict:
        return {"type": self.avatar_type, "emotions": EMOTIONS, "actions": ACTIONS}


class Live2DAvatarProvider(AvatarProvider):
    """Live2D 实现（第一个实现，§40/§41）。

    产出现代 Live2D 运行时可消费的命令（motion/expression + 参数），
    渲染由前端/外部 Live2D 运行时执行；不把 Live2D 写死在聊天页面。
    """

    id = "live2d"
    name = "Avatar（Live2D）"
    avatar_type = "live2d"

    def probe(self) -> ProviderStatus:
        # 接口就绪 = 能产出合法 Live2D 命令；真实渲染器由前端/外部运行时消费
        return ProviderStatus(
            available=True,
            backend="live2d-command",
            device="live2d-bridge",
            reason="命令桥接就绪；渲染器由前端 Live2D 运行时消费（未内置模型文件时前端显示静态形象）",
        )

    def status(self) -> ProviderStatus:
        return self.probe()

    async def render(self, action: AvatarAction) -> dict:
        emo = action.emotion if action.emotion in EMOTIONS else "neutral"
        return {
            "provider": "live2d",
            "type": "command",
            "motion": emo,
            "expression": action.expression or emo,
            "intensity": max(0.0, min(1.0, action.intensity)),
            "action": action.action,
            "text": action.text[:500],
            "speed": max(0.5, min(2.0, action.speed)),
            "ts": time.time(),
        }


class VRCAvatarProvider(AvatarProvider):
    """VRC 未来实现（§41/§53 Future）：接口预留，如实上报未实现。"""

    id = "vrc"
    name = "Avatar（VRC，未来）"
    avatar_type = "vrc"

    def probe(self) -> ProviderStatus:
        return ProviderStatus(False, backend="", reason="VRC 为未来实现（规格 Future），当前仅预留接口")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def render(self, action: AvatarAction) -> dict:
        raise NotImplementedError("VRC Avatar 尚未实现（未来阶段）")


class GenericAvatarController:
    """统一头像控制器：按 avatar_type 分发到具体 Provider，并维护平滑状态。"""

    def __init__(self) -> None:
        self._providers: dict[str, AvatarProvider] = {}
        self._state = AvatarState()
        self._register(Live2DAvatarProvider())
        self._register(VRCAvatarProvider())

    def _register(self, p: AvatarProvider) -> None:
        self._providers[p.avatar_type] = p
        logger.info(f"[Avatar] 控制器注册: {p.avatar_type}")

    def list_providers(self) -> list[dict]:
        return [{"type": p.avatar_type, "name": p.name, "status": p.status().to_dict(),
                 "capabilities": p.describe_capabilities()} for p in self._providers.values()]

    def state(self) -> dict:
        return self._state.to_dict()

    async def apply(self, action: AvatarAction, avatar_type: str = "live2d") -> dict:
        """AI 输出动作意图 → 对应平台命令；状态做平滑（避免剧烈跳变）。"""
        t0 = time.time()
        p = self._providers.get(avatar_type)
        if p is None:
            return {"provider": avatar_type, "error": "unsupported_avatar_type"}
        cmd = await p.render(action)
        # 情绪平滑：切换幅度受 intensity 控制；同情绪只更新强度
        if action.emotion in EMOTIONS:
            if action.emotion != self._state.current_emotion:
                self._state.current_emotion = action.emotion
                self._state.current_intensity = min(0.5, max(0.0, action.intensity))  # 刚切换不拉满
            else:
                self._state.current_intensity = action.intensity
        self._state.last_action = action.action or "idle"
        self._state.provider = avatar_type
        self._state.updated_at = time.time()
        from runtime.perf import perf_monitor
        perf_monitor.record("avatar_latency", value=(time.time() - t0) * 1000.0)
        return cmd

    async def interrupt(self) -> dict:
        """打断当前动画（§44 streaming/interrupt/cancel）。"""
        return {"provider": self._state.provider, "action": "interrupt", "ok": True}


# ---- 视频通话架构预留（§44：当前不实现完整视频通话，只预留接口） ----
class CameraInput:
    """摄像头输入（预留）。"""
    async def stream(self): raise NotImplementedError("CameraInput 预留（未来视频通话）")
    async def stop(self): return True


class AudioInput:
    """麦克风输入（预留）。"""
    async def stream(self): raise NotImplementedError("AudioInput 预留（未来视频通话）")
    async def stop(self): return True


class AudioOutput:
    """音频输出（预留，配合 TTS 首包低延迟）。"""
    async def play(self, chunk: bytes): raise NotImplementedError("AudioOutput 预留（未来视频通话）")
    async def interrupt(self): return True


class AvatarRenderer:
    """头像渲染器（预留）：接收 AvatarProvider 命令并渲染。"""
    async def render(self, command: dict): raise NotImplementedError("AvatarRenderer 预留")


avatar_controller = GenericAvatarController()

__all__ = [
    "ACTIONS",
    "AudioInput",
    "AudioOutput",
    "AvatarAction",
    "AvatarProvider",
    "AvatarRenderer",
    "AvatarState",
    "CameraInput",
    "EMOTIONS",
    "GenericAvatarController",
    "Live2DAvatarProvider",
    "VRCAvatarProvider",
    "avatar_controller",
]
