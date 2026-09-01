# -*- coding: utf-8 -*-
"""Qiyu Runtime · MessagePlatformProvider（消息平台抽象，规格§46）。

Companion Core 不直接写 Wechaty 专属代码：统一
- IncomingMessage（平台输入统一转换）
- OutgoingMessage（平台输出统一）
- MessagePlatformProvider：WeChatProvider（现在）/ TelegramProvider / DiscordProvider（未来）

业务层只依赖 MessagePlatformProvider 接口；新平台（Telegram/Discord/QQ）按同一
接口注册即可，核心逻辑零改动。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from loguru import logger

from runtime.providers import AIProvider, ProviderKind, ProviderStatus


@dataclass
class IncomingMessage:
    """统一入站消息。"""
    id: str
    platform: str
    user_id: str
    text: str = ""
    images: list = field(default_factory=list)
    audio: Any = None
    timestamp: float = field(default_factory=time.time)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "platform": self.platform, "user_id": self.user_id,
            "text": self.text, "images": len(self.images), "has_audio": self.audio is not None,
            "timestamp": round(self.timestamp, 3),
        }


@dataclass
class OutgoingMessage:
    """统一出站消息（支持分条 + 图片）。"""
    text: str = ""
    pieces: list = field(default_factory=list)
    image_url: str = ""
    platform: str = ""
    to_user: str = ""

    def to_dict(self) -> dict:
        return {"text": self.text[:500], "pieces": len(self.pieces),
                "image_url": self.image_url[:200] if self.image_url else "",
                "platform": self.platform, "to_user": self.to_user}


class MessagePlatformProvider(AIProvider):
    """消息平台 Provider 基类。"""

    kind = ProviderKind.PLATFORM
    platform_id = "base"

    async def send(self, msg: OutgoingMessage) -> bool:
        raise NotImplementedError

    def list_channels(self) -> list[dict]:
        return []


class WeChatPlatformProvider(MessagePlatformProvider):
    """微信平台（现在）：包装 channel_registry，Companion Core 不直接碰 Wechaty。"""

    id = "wechat"
    name = "消息平台（微信 / ClawBot / Wechaty / Wechatauto）"
    platform_id = "wechat"

    def _registry(self):
        try:
            from channels import get_channel_registry
            return get_channel_registry()
        except Exception:
            return None

    def probe(self) -> ProviderStatus:
        reg = self._registry()
        if reg is None:
            return ProviderStatus(False, backend="", reason="通道注册表未就绪")
        try:
            channels = reg.list_channels() or []
        except Exception:
            channels = []
        return ProviderStatus(
            available=bool(channels),
            backend="channel-registry",
            device="wechat",
            reason="" if channels else "无可用微信通道",
        )

    def status(self) -> ProviderStatus:
        return self.probe()

    async def send(self, msg: OutgoingMessage) -> bool:
        reg = self._registry()
        if reg is None or not msg.to_user:
            return False
        try:
            text = msg.text or ""
            pieces = msg.pieces or []
            if pieces:
                ok = all(reg.send(msg.to_user, (p.get("text") or "").strip()) for p in pieces if (p.get("text") or "").strip())
                return bool(ok) if pieces else bool(reg.send(msg.to_user, text))
            return bool(reg.send(msg.to_user, text))
        except Exception as e:
            logger.warning(f"[平台] 微信发送失败: {e}")
            return False

    def list_channels(self) -> list[dict]:
        reg = self._registry()
        if reg is None:
            return []
        try:
            return reg.list_channels() or []
        except Exception:
            return []


class TelegramPlatformProvider(MessagePlatformProvider):
    """Telegram（未来，§46/§53）：接口预留。"""

    id = "telegram"
    name = "消息平台（Telegram，未来）"
    platform_id = "telegram"

    def probe(self) -> ProviderStatus:
        return ProviderStatus(False, backend="", reason="Telegram 为未来实现（接口已预留）")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def send(self, msg: OutgoingMessage) -> bool:
        return False


class DiscordPlatformProvider(MessagePlatformProvider):
    """Discord（未来，§46/§53）：接口预留。"""

    id = "discord"
    name = "消息平台（Discord，未来）"
    platform_id = "discord"

    def probe(self) -> ProviderStatus:
        return ProviderStatus(False, backend="", reason="Discord 为未来实现（接口已预留）")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def send(self, msg: OutgoingMessage) -> bool:
        return False


class MessagePlatformRegistry:
    """平台注册表：Companion Core 经它发消息，不感知具体平台。"""

    def __init__(self) -> None:
        self._providers: dict[str, MessagePlatformProvider] = {}
        self._register(WeChatPlatformProvider())
        self._register(TelegramPlatformProvider())
        self._register(DiscordPlatformProvider())

    def _register(self, p: MessagePlatformProvider) -> None:
        self._providers[p.platform_id] = p

    def get(self, platform: str = "") -> Optional[MessagePlatformProvider]:
        if not platform:
            for p in self._providers.values():
                if p.status().available:
                    return p
            return next(iter(self._providers.values()), None)
        return self._providers.get(platform)

    async def send(self, msg: OutgoingMessage, platform: str = "") -> bool:
        p = self.get(platform)
        if p is None:
            return False
        if not msg.platform:
            msg.platform = p.platform_id
        return await p.send(msg)

    def list(self) -> list[dict]:
        return [{"id": pid, "name": p.name, "status": p.status().to_dict(),
                 "channels": p.list_channels()} for pid, p in self._providers.items()]


platform_registry = MessagePlatformRegistry()

__all__ = [
    "DiscordPlatformProvider",
    "IncomingMessage",
    "MessagePlatformProvider",
    "MessagePlatformRegistry",
    "OutgoingMessage",
    "TelegramPlatformProvider",
    "WeChatPlatformProvider",
    "platform_registry",
]
