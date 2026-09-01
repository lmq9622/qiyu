"""预留通道：企业微信 / QQBot / 飞书（参考 OpenClaw 架构预留配置位，后端接口统一）。"""

from .base import BaseChannel
from . import store


class PlaceholderChannel(BaseChannel):
    """预留通道：配置表单可用、保存到本地，后端接入逻辑待实现。"""

    integrated = False

    def __init__(self, channel_id: str, kind: str, name: str, mode: str, icon: str,
                 schema: list, defaults: dict | None = None, hint: str = ""):
        self.id = channel_id
        self.kind = kind
        self.name = name
        self.mode = mode
        self.icon = icon
        self.available = True       # 配置表单可用
        self.integrated = False     # 后端未接通（预留）
        self.running = False
        self.qr_status = "idle"
        self.qr_message = hint or "预留通道：配置位已就绪，等待接入"
        self.config_schema = schema
        self.config = {s["key"]: (defaults or {}).get(s["key"], "") for s in schema}
        self._load_config()

    def _load_config(self):
        saved = store.load_config(self.id)
        if saved:
            for k, v in saved.items():
                if k in self.config:
                    self.config[k] = v

    def save_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        for k, v in cfg.items():
            if k in self.config:
                self.config[k] = v
        store.save_config(self.id, self.config)

    def start(self, **kwargs) -> bool:
        return False  # 预留未接通

    def stop(self):
        self.running = False

    def send(self, user_id: str, text: str) -> bool:
        return False


def build_placeholder_channels() -> list:
    """企业微信 / QQBot / 飞书 预留通道（OpenClaw 风格架构位）"""
    return [
        PlaceholderChannel(
            "wecom", "wecom", "企业微信", "placeholder", "wecom",
            schema=[
                {"key": "corp_id", "label": "企业 ID（CorpID）", "type": "text",
                 "placeholder": "ww1234567890abcdef", "hint": "企业微信管理后台 → 我的企业"},
                {"key": "agent_id", "label": "应用 AgentId", "type": "text", "placeholder": "1000002"},
                {"key": "secret", "label": "应用 Secret", "type": "password",
                 "placeholder": "输入应用密钥", "secret": True},
                {"key": "token", "label": "回调 Token", "type": "text", "placeholder": "可选"},
                {"key": "aes_key", "label": "回调 EncodingAESKey", "type": "password",
                 "placeholder": "可选", "secret": True},
            ],
            defaults={},
            hint="预留：企业微信自建应用通道（回调接收消息，未接通）",
        ),
        PlaceholderChannel(
            "qqbot", "qqbot", "QQ Bot", "placeholder", "qq",
            schema=[
                {"key": "app_id", "label": "AppID", "type": "text", "placeholder": "QQ 开放平台 Bot AppID"},
                {"key": "app_secret", "label": "AppSecret", "type": "password",
                 "placeholder": "输入 AppSecret", "secret": True},
                {"key": "token", "label": "Token", "type": "password",
                 "placeholder": "QQ 官方 Bot Token", "secret": True},
            ],
            defaults={},
            hint="预留：QQ 开放平台机器人（WebSocket 长连接收消息，未接通）",
        ),
        PlaceholderChannel(
            "feishu", "feishu", "飞书", "placeholder", "feishu",
            schema=[
                {"key": "app_id", "label": "App ID", "type": "text", "placeholder": "cli_xxxxxxxx"},
                {"key": "app_secret", "label": "App Secret", "type": "password",
                 "placeholder": "输入 App Secret", "secret": True},
                {"key": "webhook", "label": "自定义机器人 Webhook", "type": "text",
                 "placeholder": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"},
                {"key": "verification_token", "label": "Verification Token", "type": "password",
                 "placeholder": "可选", "secret": True},
            ],
            defaults={},
            hint="预留：飞书自建应用机器人（事件订阅接收消息，未接通）",
        ),
    ]
