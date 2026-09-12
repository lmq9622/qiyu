"""QQ 官方机器人通道（沙箱/正式）。

协议依据：https://bot.q.qq.com/wiki/develop/api/ 与官方开放消息 API。
鉴权：POST https://bots.qq.com/app/getAppAccessToken
事件：WebSocket 长连接 wss://{sandbox|api}.sgroup.qq.com/websocket
发送：POST /v2/users/{openid}/messages（私聊）/ /v2/groups/{group_openid}/messages（群聊）

未配置官方凭据时不虚报可用：available=False；integrated=True（真实协议已实现），
完整消息回路需 QQ 开放平台 AppID/Token/Secret 才能端到端验证（UNVERIFIED）。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Optional

from loguru import logger

from .base import BaseChannel
from . import store

try:
    import httpx
except Exception:  # pragma: no cover
    httpx = None

try:
    import websockets
except Exception:  # pragma: no cover
    websockets = None


def _runtime_settings() -> dict:
    try:
        from companion.settings import load_runtime_settings
        return load_runtime_settings() or {}
    except Exception:
        return {}


class QQBotChannel(BaseChannel):
    """QQ 官方开放平台机器人通道（WebSocket 长连接 + REST 发送）。"""

    integrated = True

    def __init__(self, channel_id: str = "qqbot"):
        self.id = channel_id
        self.kind = "qqbot"
        self.name = "QQ 官方机器人"
        self.mode = "qqbot"
        self.icon = "qq"
        self.available = False
        self.integrated = True
        self.running = False
        self.qr_status = "idle"
        self.qr_message = "未配置或未验证（需 QQ 开放平台 AppID/Token/Secret）"
        self.config_schema = [
            {"key": "appid", "label": "AppID", "type": "text",
             "placeholder": "QQ 开放平台 Bot AppID"},
            {"key": "token", "label": "Token", "type": "password",
             "placeholder": "Bot Token", "secret": True},
            {"key": "secret", "label": "AppSecret", "type": "password",
             "placeholder": "AppSecret", "secret": True},
            {"key": "sandbox", "label": "沙箱环境", "type": "checkbox",
             "hint": "沙箱只对机器人后台添加的测试成员生效"},
            {"key": "enabled", "label": "启用", "type": "checkbox"},
        ]
        self.config = {
            "appid": "", "token": "", "secret": "", "sandbox": True, "enabled": False,
        }
        self._token = ""
        self._token_exp = 0.0
        self._ws_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._load_config()

    def _load_config(self):
        saved = dict(store.load_config(self.id))
        rt = _runtime_settings().get("qqbot") or {}
        if rt:
            saved.update(rt)
        # 兼容旧占位通道的 app_id/app_secret 字段名
        if "app_id" in saved and "appid" not in saved:
            saved["appid"] = saved.pop("app_id")
        if "app_secret" in saved and "secret" not in saved:
            saved["secret"] = saved.pop("app_secret")
        for k in self.config:
            if k in saved and saved[k] not in (None, ""):
                self.config[k] = saved[k]
        self._refresh_available()

    def save_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        for k, v in cfg.items():
            if k in self.config:
                self.config[k] = v
        try:
            store.save_config(self.id, self.config)
            rt = _runtime_settings()
            rt["qqbot"] = dict(self.config)
            from companion.settings import save_runtime_settings
            save_runtime_settings(rt)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[QQBot] 保存配置失败: {e}")
        self._refresh_available()

    def _refresh_available(self):
        cfg = self.config
        configured = bool(cfg.get("appid") and (cfg.get("secret") or cfg.get("token")))
        self.available = configured and httpx is not None
        if self.available:
            self.qr_message = "已配置；尚未通过线上凭据验证（UNVERIFIED）"
        else:
            self.qr_message = "缺 AppID/Secret/Token 或 httpx 不可用"

    def access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if httpx is None:
            raise RuntimeError("httpx 不可用")
        resp = httpx.post(
            "https://bots.qq.com/app/getAppAccessToken",
            json={"appId": self.config.get("appid"),
                  "clientSecret": self.config.get("secret")},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = str(data.get("access_token") or "")
        self._token_exp = time.time() + int(data.get("expires_in") or 7200)
        if not self._token:
            raise RuntimeError(f"QQ 鉴权失败: {data}")
        return self._token

    @property
    def _api_host(self) -> str:
        return "sandbox.api.sgroup.qq.com" if self.config.get("sandbox") else "api.sgroup.qq.com"

    def _headers(self) -> dict:
        return {"Authorization": f"QQBot {self.access_token()}",
                "Content-Type": "application/json"}

    def send(self, user_id: str, text: str) -> bool:
        if not text or (not self.available and not self.running):
            return False
        remote = str(user_id or "")
        if remote.startswith("qq_"):
            body = remote[3:]
            _, _, openid = body.partition("__")
        else:
            openid = remote
        if not openid:
            return False
        try:
            url = f"https://{self._api_host}/v2/users/{openid}/messages"
            payload = {"content": str(text)[:2000], "msg_type": 0,
                       "msg_seq": int(time.time() * 1000) % 100000}
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[QQBot] 发送失败: {e}")
            return False

    def send_to_group(self, group_openid: str, text: str) -> bool:
        try:
            url = f"https://{self._api_host}/v2/groups/{group_openid}/messages"
            payload = {"content": str(text)[:2000], "msg_type": 0,
                       "msg_seq": int(time.time() * 1000) % 100000}
            resp = httpx.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[QQBot] 群发失败: {e}")
            return False

    def start(self, **kwargs) -> bool:
        if not self.config.get("enabled") or not self.available:
            return False
        if self.running:
            return True
        self._stop.clear()
        self._ws_thread = threading.Thread(target=self._ws_loop, daemon=True,
                                           name="qqbot-ws")
        self._ws_thread.start()
        self.running = True
        self.qr_status = "running"
        self.qr_message = "长连接启动中（真实事件回路以线上凭据验证为准）"
        return True

    def stop(self):
        self._stop.set()
        self.running = False
        self.qr_status = "idle"
        if self._ws_thread:
            self._ws_thread.join(timeout=2)
            self._ws_thread = None

    def _ws_loop(self):
        if websockets is None:
            self.qr_message = "缺少 websockets 库，无法建立长连接"
            self.running = False
            return
        url = f"wss://{self._api_host}/websocket"
        while not self._stop.is_set():
            try:
                import asyncio

                async def _once():
                    async with websockets.connect(
                        url, additional_headers=self._headers(),
                        ping_interval=20, ping_timeout=15,
                    ) as ws:
                        async for raw in ws:
                            try:
                                data = json.loads(raw)
                            except Exception:  # noqa: BLE001
                                continue
                            if data.get("op") == 10:
                                await ws.send(json.dumps({
                                    "op": 1, "d": {"token": self.access_token()},
                                }))
                            elif data.get("op") == 0 and data.get("t") in (
                                "MESSAGE_CREATE", "C2C_MESSAGE_CREATE",
                                "GROUP_AT_MESSAGE_CREATE",
                            ):
                                self._on_message(data.get("d") or {})
                asyncio.run(_once())
            except Exception as e:  # noqa: BLE001
                if not self._stop.is_set():
                    logger.warning(f"[QQBot] WS 断开，5s 后重连: {e}")
                    self._stop.wait(5)

    def _on_message(self, d: dict):
        if not d or not self._handler:
            return
        import asyncio
        author = d.get("author") or {}
        openid = str(author.get("id") or author.get("member_openid") or "")
        content = str(d.get("content") or "").strip()
        if not openid or not content:
            return
        user_id = f"qq_{self.config.get('appid', self.id)}__{openid}"
        try:
            if asyncio.iscoroutinefunction(self._handler):
                reply = asyncio.run(self._handler(user_id, content, self, []))
            else:
                reply = self._handler(user_id, content, self, [])
            if reply:
                text = reply if isinstance(reply, str) else (
                    reply[0] if isinstance(reply, tuple) else "")
                self.send(user_id, str(text))
        except Exception as e:  # noqa: BLE001
            logger.error(f"[QQBot] 处理消息失败: {e}")


def build_qqbot_channel() -> QQBotChannel:
    return QQBotChannel()


__all__ = ["QQBotChannel", "build_qqbot_channel"]
