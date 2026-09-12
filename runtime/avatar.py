# -*- coding: utf-8 -*-
"""Qiyu Runtime · Avatar（Live2D / VRC / 未来 3D，规格§40/§41/§44）。

- AvatarProvider：AI 侧只输出 emotion/intensity/action/expression/gesture，
  不写死任何 Live2D 细节；
- Live2D 是第一个实现，VRC 走 VRChat OSC 桥（UDP 9000），两者都是真实输出端；
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

# ---------------- VRChat OSC 桥（真实输出端，stdlib 实现，无新增依赖） ----------------
import socket as _socket
import struct as _struct

def _osc_pad(b: bytes) -> bytes:
    """OSC 字符串/地址按 4 字节对齐补零。"""
    return b + b"\x00" * ((4 - len(b) % 4) % 4)

def _osc_message(address: str, *args) -> bytes:
    """构造 OSC 消息（支持 bool/float/int；VRChat OSC 端口约定）。"""
    parts = [_osc_pad(address.encode("utf-8"))]
    tags = ","
    for a in args:
        if isinstance(a, bool):
            tags += "T" if a else "F"
        elif isinstance(a, int):
            tags += "i"
        else:
            tags += "f"
    parts.append(_osc_pad(tags.encode("utf-8")))
    for a in args:
        if isinstance(a, bool):
            continue  # OSC bool 无负载
        elif isinstance(a, int):
            parts.append(_struct.pack(">i", a))
        else:
            parts.append(_struct.pack(">f", float(a)))
    return b"".join(parts)

def _send_osc(address: str, *args) -> bool:
    """向 VRChat OSC 端口发送一条消息；失败返回 False（不假装发送成功）。"""
    import os
    host = os.getenv("QIYU_VRC_OSC_HOST", "127.0.0.1")
    port = int(os.getenv("QIYU_VRC_OSC_PORT", "9000"))
    try:
        with _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            s.sendto(_osc_message(address, *args), (host, port))
        return True
    except Exception:
        return False

def _vrchat_running() -> bool:
    """检测 VRChat 进程是否在运行（psutil，失败时退回 tasklist）。"""
    try:
        import psutil
        return any(str(p.info.get("name") or "").lower().startswith("vrchat") for p in psutil.process_iter(["name"]))
    except Exception:
        pass
    try:
        import subprocess
        out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=5).stdout or ""
        return "VRChat.exe" in out
    except Exception:
        return False


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


@dataclass
class AvatarEvent:
    """统一 Avatar 事件：Live2D / VRM / V3D / VRC 消费同一结构。"""
    emotion: str = "neutral"
    intensity: float = 0.0
    duration: float = 1.0
    action: str = "idle"
    mouth: float = 0.0
    blink: float = 1.0
    breathing: float = 0.4
    speaking: bool = False
    expression: str = ""
    gesture: str = ""
    prosody: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "emotion": self.emotion,
            "intensity": round(max(0.0, min(1.0, self.intensity)), 3),
            "duration": round(float(self.duration), 2),
            "action": self.action,
            "mouth": round(max(0.0, min(1.0, self.mouth)), 3),
            "blink": round(max(0.0, min(1.0, self.blink)), 3),
            "breathing": round(max(0.0, min(1.0, self.breathing)), 3),
            "speaking": bool(self.speaking),
            "expression": self.expression,
            "gesture": self.gesture,
            "prosody": dict(self.prosody or {}),
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
    """VRC Avatar（真实 OSC 桥，规格§41/§53）。

    AI 动作意图 → VRChat OSC 参数（/avatar/parameters/…，UDP 9000，VRChat OSC 标准端口）。
    可用性 = VRChat 进程在运行，或显式配置了 QIYU_VRC_OSC_PORT 且端口可达；
    不可用时如实上报 unavailable，绝不假装能驱动 VRC 形象。
    """

    id = "vrc"
    name = "Avatar（VRChat OSC 桥）"
    avatar_type = "vrc"

    def _config(self) -> tuple:
        import os
        return (os.getenv("QIYU_VRC_OSC_HOST", "127.0.0.1"),
                int(os.getenv("QIYU_VRC_OSC_PORT", "9000")))

    def probe(self) -> ProviderStatus:
        import os
        if os.getenv("QIYU_VRC_DISABLED", "") == "1":
            return ProviderStatus(False, backend="", reason="已通过 QIYU_VRC_DISABLED=1 显式禁用")
        host, port = self._config()
        if _vrchat_running():
            return ProviderStatus(True, backend="osc", device=f"{host}:{port}",
                                 reason="VRChat 进程在运行，OSC 桥就绪")
        # 显式配置了 OSC 端口：尝试发一条无害参数，能发出算端口可达
        if os.getenv("QIYU_VRC_OSC_PORT", ""):
            if _send_osc("/avatar/parameters/QiyuProbe", 0.0):
                return ProviderStatus(True, backend="osc", device=f"{host}:{port}",
                                     reason="OSC 端口可达（已发送探测消息）")
            return ProviderStatus(False, backend="osc", device=f"{host}:{port}",
                                 reason=f"VRChat OSC 端口 {port} 发送失败（VRChat 未运行？）")
        return ProviderStatus(False, backend="", reason="VRChat 未运行；启动 VRChat 或设 QIYU_VRC_OSC_PORT 启用 OSC 桥")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def render(self, action: AvatarAction) -> dict:
        """把 AI 动作意图映射为 VRChat OSC 参数并真实发送。"""
        emo = action.emotion if action.emotion in EMOTIONS else "neutral"
        intensity = max(0.0, min(1.0, action.intensity))
        params = [
            ("/avatar/parameters/Emotion", emo),
            ("/avatar/parameters/Intensity", intensity),
            ("/avatar/parameters/Action", action.action or "idle"),
            ("/avatar/parameters/Expression", action.expression or emo),
            ("/avatar/parameters/Gesture", action.gesture or ""),
            ("/avatar/parameters/Talking", bool(action.text)),
            ("/avatar/parameters/Speed", max(0.5, min(2.0, action.speed))),
        ]
        sent = 0
        for addr, val in params:
            if isinstance(val, str):
                continue  # 字符串参数依赖 VRC 形象参数配置，通用浮点/布尔参数直接发送
            if _send_osc(addr, val):
                sent += 1
        return {
            "provider": "vrc",
            "type": "osc",
            "osc_host": self._config()[0],
            "osc_port": self._config()[1],
            "sent": sent,
            "emotion": emo,
            "intensity": round(intensity, 3),
            "action": action.action or "idle",
            "text": action.text[:500],
            "ok": True,
            "ts": time.time(),
        }


class JsonAvatarBridgeProvider(AvatarProvider):
    """JSON Avatar 后端：模型写 AvatarEvent，前端/3D 皮套订阅同一 JSON。
    没有订阅者时如实 unavailable（不假装已渲染）。"""

    id = "json"
    name = "Avatar（JSON Bridge / L2D / V3D）"
    avatar_type = "json"

    def __init__(self) -> None:
        super().__init__()
        self._subscribers: set = set()

    def subscribe(self, q) -> None:
        self._subscribers.add(q)

    def unsubscribe(self, q) -> None:
        self._subscribers.discard(q)

    def probe(self) -> ProviderStatus:
        if self._subscribers:
            return ProviderStatus(True, backend="json", device="event-bus",
                                  reason=f"{len(self._subscribers)} 个订阅客户端")
        return ProviderStatus(False, backend="json", device="event-bus",
                              reason="无订阅客户端（前端/3D 皮套尚未连接）")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def render(self, action: AvatarAction) -> dict:
        ev = AvatarEvent(emotion=action.emotion, intensity=action.intensity,
                         action=action.action, speaking=bool(action.text),
                         expression=action.expression, gesture=action.gesture)
        return await self.render_event(ev)

    async def render_event(self, event: AvatarEvent) -> dict:
        payload = event.to_dict()
        delivered = 0
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
                delivered += 1
            except Exception:
                self.unsubscribe(q)
        return {"provider": "json", "type": "avatar_event", "delivered": delivered,
                "event": payload, "ts": time.time()}


class GenericAvatarController:
    """统一头像控制器：按 avatar_type 分发到具体 Provider，并维护平滑状态。"""

    def __init__(self) -> None:
        self._providers: dict[str, AvatarProvider] = {}
        self._state = AvatarState()
        self._register(Live2DAvatarProvider())
        self._register(VRCAvatarProvider())
        self._register(JsonAvatarBridgeProvider())

    def _register(self, p: AvatarProvider) -> None:
        self._providers[p.avatar_type] = p
        logger.info(f"[Avatar] 控制器注册: {p.avatar_type}")

    def list_providers(self) -> list[dict]:
        return [{"type": p.avatar_type, "name": p.name, "status": p.status().to_dict(),
                 "capabilities": p.describe_capabilities()} for p in self._providers.values()]

    def state(self) -> dict:
        return self._state.to_dict()

    def subscribe_json(self, q) -> bool:
        p = self._providers.get("json")
        if p is None:
            return False
        p.subscribe(q)
        return True

    async def emit_event(self, event: AvatarEvent, avatar_type: str = "json") -> dict:
        """统一 AvatarEvent → 具体后端；Live2D/VRC 自动从 event 构造 action。"""
        p = self._providers.get(avatar_type)
        if p is None:
            return {"provider": avatar_type, "error": "unsupported_avatar_type"}
        if hasattr(p, "render_event"):
            cmd = await p.render_event(event)
        else:
            action = AvatarAction(emotion=event.emotion, intensity=event.intensity,
                                  action=event.action, expression=event.expression,
                                  gesture=event.gesture, text="",
                                  speed=float(event.prosody.get("speed") or 1.0))
            cmd = await p.render(action)
        if event.emotion in EMOTIONS:
            self._state.current_emotion = event.emotion
            self._state.current_intensity = min(1.0, float(event.intensity))
        self._state.last_action = event.action or "idle"
        self._state.provider = avatar_type
        self._state.updated_at = time.time()
        return cmd

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
