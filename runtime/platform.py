# -*- coding: utf-8 -*-
"""Qiyu Runtime · MessagePlatformProvider（消息平台抽象，规格§46）。

Companion Core 不直接写 Wechaty 专属代码：统一
- IncomingMessage（平台输入统一转换）
- OutgoingMessage（平台输出统一）
- MessagePlatformProvider：WeChatProvider（现在）/ TelegramProvider / DiscordProvider（真实实现）

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
    """Telegram Bot API（真实实现，规格§46/§53）。

    token 来源：环境变量 TELEGRAM_BOT_TOKEN（优先）或运行时设置 telegram_bot_token。
    probe() 用 getMe 验证 token；send() 真实发送 sendMessage/sendPhoto；
    API 地址可经 TELEGRAM_API_BASE 覆盖（代理/自建网关/测试）。
    """

    id = "telegram"
    name = "消息平台（Telegram Bot API）"
    platform_id = "telegram"

    def __init__(self):
        super().__init__()
        self._bot_info: Optional[dict] = None

    def _token(self) -> str:
        import os
        tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        if tok:
            return tok
        try:
            from companion.settings import load_runtime_settings
            return str(load_runtime_settings().get("telegram_bot_token") or "").strip()
        except Exception:
            return ""

    def _api_base(self) -> str:
        import os
        return os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").rstrip("/")

    def probe(self) -> ProviderStatus:
        tok = self._token()
        if not tok:
            return ProviderStatus(False, backend="", reason="未配置 Telegram Bot Token（设 TELEGRAM_BOT_TOKEN）")
        try:
            import httpx
            r = httpx.get(f"{self._api_base()}/bot{tok}/getMe", timeout=10)
            data = r.json() if r.status_code == 200 else {}
            if r.status_code == 200 and data.get("ok"):
                self._bot_info = data.get("result") or {}
                uname = self._bot_info.get("username") or "?"
                return ProviderStatus(True, backend="api", device=f"@{uname}",
                                     reason="Telegram Bot API getMe 验证通过")
            return ProviderStatus(False, backend="api", reason=f"getMe 验证失败（HTTP {r.status_code}）")
        except Exception as e:
            return ProviderStatus(False, backend="api", reason=f"Telegram API 不可达（{type(e).__name__}）")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def send(self, msg: OutgoingMessage) -> bool:
        tok = self._token()
        if not tok or not msg.to_user:
            return False
        text = (msg.text or "").strip()
        pieces = [p for p in (msg.pieces or []) if (p.get("text") or "").strip()]
        if pieces and not text:
            text = "\n".join(p.get("text", "").strip() for p in pieces)
        try:
            import httpx
            base = self._api_base()
            async with httpx.AsyncClient(timeout=20) as client:
                if msg.image_url:
                    r = await client.post(f"{base}/bot{tok}/sendPhoto", json={
                        "chat_id": msg.to_user, "photo": msg.image_url, "caption": text[:1024]})
                    if r.status_code == 200:
                        return True
                r = await client.post(f"{base}/bot{tok}/sendMessage", json={
                    "chat_id": msg.to_user, "text": text[:4096]})
                return r.status_code == 200
        except Exception as e:
            logger.warning(f"[平台] Telegram 发送失败: {e}")
            return False

    def list_channels(self) -> list[dict]:
        if not self._bot_info:
            return []
        uname = self._bot_info.get("username") or ""
        return [{"id": f"@{uname}", "name": f"Telegram Bot @{uname}"}] if uname else []


class DiscordPlatformProvider(MessagePlatformProvider):
    """Discord Bot API（真实实现，规格§46/§53）。

    token 来源：环境变量 DISCORD_BOT_TOKEN（优先）或运行时设置 discord_bot_token。
    probe() 用 GET /users/@me 验证 token；send() 真实发送到频道/私信（to_user=channel_id）；
    API 地址可经 DISCORD_API_BASE 覆盖（代理/自建网关/测试）。
    """

    id = "discord"
    name = "消息平台（Discord Bot API）"
    platform_id = "discord"

    def __init__(self):
        super().__init__()
        self._bot_info: Optional[dict] = None

    def _token(self) -> str:
        import os
        tok = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        if tok:
            return tok
        try:
            from companion.settings import load_runtime_settings
            return str(load_runtime_settings().get("discord_bot_token") or "").strip()
        except Exception:
            return ""

    def _api_base(self) -> str:
        import os
        return os.getenv("DISCORD_API_BASE", "https://discord.com/api/v10").rstrip("/")

    def probe(self) -> ProviderStatus:
        tok = self._token()
        if not tok:
            return ProviderStatus(False, backend="", reason="未配置 Discord Bot Token（设 DISCORD_BOT_TOKEN）")
        try:
            import httpx
            r = httpx.get(f"{self._api_base()}/users/@me",
                          headers={"Authorization": f"Bot {tok}"}, timeout=10)
            if r.status_code == 200:
                self._bot_info = r.json()
                return ProviderStatus(True, backend="api", device=self._bot_info.get("username") or "",
                                     reason="Discord API 身份验证通过（/users/@me）")
            return ProviderStatus(False, backend="api", reason=f"Discord 身份验证失败（HTTP {r.status_code}）")
        except Exception as e:
            return ProviderStatus(False, backend="api", reason=f"Discord API 不可达（{type(e).__name__}）")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def send(self, msg: OutgoingMessage) -> bool:
        tok = self._token()
        if not tok or not msg.to_user:
            return False
        text = (msg.text or "").strip()
        pieces = [p for p in (msg.pieces or []) if (p.get("text") or "").strip()]
        if pieces and not text:
            text = "\n".join(p.get("text", "").strip() for p in pieces)
        try:
            import httpx
            headers = {"Authorization": f"Bot {tok}"}
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(f"{self._api_base()}/channels/{msg.to_user}/messages",
                                      json={"content": text[:2000]}, headers=headers)
                return r.status_code in (200, 201)
        except Exception as e:
            logger.warning(f"[平台] Discord 发送失败: {e}")
            return False

    def list_channels(self) -> list[dict]:
        # 频道列表需要 gateway/intents，保持诚实：不伪造
        return []


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
