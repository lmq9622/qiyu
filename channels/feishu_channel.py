"""飞书自建应用机器人通道。

协议依据：https://open.feishu.cn/document/home/introduction-to-custom-app-development
- 鉴权：POST /open-apis/auth/v3/tenant_access_token/internal
- 发送：POST /open-apis/im/v1/messages?receive_id_type=open_id
- 事件：HTTP 回调（demo.py 挂 /v2/channels/feishu/webhook）→ challenge 校验 + 文本消息入站

未配置官方凭据时不虚报可用：available=False；integrated=True（真实协议已实现），
事件回路需飞书开放平台 App ID/Secret 与回调地址才能端到端验证（UNVERIFIED）。
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


def _runtime_settings() -> dict:
    try:
        from companion.settings import load_runtime_settings
        return load_runtime_settings() or {}
    except Exception:
        return {}


class FeishuChannel(BaseChannel):
    """飞书自建应用机器人（Webhook 接收 + REST 发送）。"""

    integrated = True

    def __init__(self, channel_id: str = "feishu"):
        self.id = channel_id
        self.kind = "feishu"
        self.name = "飞书机器人"
        self.mode = "feishu"
        self.icon = "feishu"
        self.available = False
        self.integrated = True
        self.running = False
        self.qr_status = "idle"
        self.qr_message = "未配置或未验证（需飞书 App ID / App Secret）"
        self.config_schema = [
            {"key": "app_id", "label": "App ID", "type": "text",
             "placeholder": "cli_xxxxxxxx"},
            {"key": "app_secret", "label": "App Secret", "type": "password",
             "placeholder": "应用密钥", "secret": True},
            {"key": "receive_id_type", "label": "接收者类型", "type": "select",
             "options": ["open_id", "user_id"], "hint": "默认 open_id"},
            {"key": "enabled", "label": "启用", "type": "checkbox"},
        ]
        self.config = {
            "app_id": "", "app_secret": "", "receive_id_type": "open_id",
            "enabled": False,
        }
        self._token = ""
        self._token_exp = 0.0
        self._lock = threading.Lock()
        self._load_config()

    def _load_config(self):
        saved = dict(store.load_config(self.id))
        rt = _runtime_settings().get("feishu") or {}
        if rt:
            saved.update(rt)
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
            rt["feishu"] = dict(self.config)
            from companion.settings import save_runtime_settings
            save_runtime_settings(rt)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Feishu] 保存配置失败: {e}")
        self._refresh_available()

    def _refresh_available(self):
        cfg = self.config
        self.available = bool(cfg.get("app_id") and cfg.get("app_secret")) and httpx is not None
        self.qr_message = (
            "已配置；尚未通过线上凭据验证（UNVERIFIED）" if self.available
            else "缺 App ID / App Secret 或 httpx 不可用"
        )

    def tenant_access_token(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        if httpx is None:
            raise RuntimeError("httpx 不可用")
        resp = httpx.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.config.get("app_id"),
                  "app_secret": self.config.get("app_secret")},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书鉴权失败: {data.get('msg')}")
        self._token = str(data.get("tenant_access_token") or "")
        self._token_exp = time.time() + int(data.get("expire") or 7200)
        return self._token

    def start(self, **kwargs) -> bool:
        if not self.config.get("enabled") or not self.available:
            return False
        # Webhook 模式：进程启动即视为“就绪”；配置飞书事件订阅时使用外网可访问回调。
        self.running = True
        self.qr_status = "running"
        self.qr_message = "回调监听就绪（需在飞书后台配置事件订阅 URL）"
        return True

    def stop(self):
        self.running = False
        self.qr_status = "idle"

    def send(self, user_id: str, text: str) -> bool:
        if not text or not self.available:
            return False
        openid = str(user_id or "")
        if openid.startswith("feishu_"):
            body = openid[7:]
            _, _, openid = body.partition("__")
        if not openid:
            return False
        try:
            url = ("https://open.feishu.cn/open-apis/im/v1/messages"
                   f"?receive_id_type={self.config.get('receive_id_type') or 'open_id'}")
            content = json.dumps({"text": str(text)[:1500]}, ensure_ascii=False)
            payload = {"receive_id": openid, "msg_type": "text", "content": content}
            headers = {"Authorization": f"Bearer {self.tenant_access_token()}",
                       "Content-Type": "application/json"}
            with self._lock:
                resp = httpx.post(url, json=payload, headers=headers, timeout=10)
            resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[Feishu] 发送失败: {e}")
            return False

    async def handle_webhook(self, payload: dict) -> dict:
        """飞书事件订阅回调：校验 challenge / 处理文本消息。

        返回值交给 demo.py 返回给飞书；URL 校验成功回显 challenge。
        """
        if not isinstance(payload, dict):
            return {"error": "bad payload"}
        # URL 校验（Event Subscription 首次配置）
        if "challenge" in payload:
            return {"challenge": payload["challenge"]}
        header = payload.get("header") or {}
        event = payload.get("event") or {}
        event_type = header.get("event_type") or ""
        if event_type != "im.message.receive_v1":
            return {"code": 0}
        message = event.get("message") or {}
        content_raw = message.get("content") or "{}"
        try:
            content_obj = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
        except Exception:  # noqa: BLE001
            content_obj = {}
        text = str(content_obj.get("text") or "").strip()
        sender = event.get("sender") or {}
        sender_id = sender.get("sender_id") or {}
        openid = str(sender_id.get("open_id") or "")
        if not text or not openid:
            return {"code": 0}
        user_id = f"feishu_{self.config.get('app_id', self.id)}__{openid}"
        if self._handler:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(self._handler):
                    reply = await self._handler(user_id, text, self, [])
                else:
                    reply = self._handler(user_id, text, self, [])
                if reply:
                    reply_text = reply if isinstance(reply, str) else (
                        reply[0] if isinstance(reply, tuple) else "")
                    await asyncio.to_thread(self.send, user_id, str(reply_text))
            except Exception as e:  # noqa: BLE001
                logger.error(f"[Feishu] 处理消息失败: {e}")
        return {"code": 0}


def build_feishu_channel() -> FeishuChannel:
    return FeishuChannel()


__all__ = ["FeishuChannel", "build_feishu_channel"]
