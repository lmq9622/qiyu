"""通道抽象基类：所有外部通讯通道的统一接口（参考 OpenClaw channel 抽象）。

一个 Channel = 一种外部通讯接入方式：
- 微信 ClawBot（官方 iLink 协议，扫码绑定，多账号）
- 微信 itchat（单账号接管，模式 B）
- 企业微信 / QQBot / 飞书（预留，配置位已就绪）
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional


class BaseChannel(ABC):
    """外部通讯通道统一接口"""

    # 基本属性
    id: str = ""            # 唯一 ID：itchat / clawbot_main / wecom / qqbot / feishu
    kind: str = ""          # wechat / wecom / qqbot / feishu
    name: str = ""          # 展示名
    mode: str = ""          # clawbot / itchat / placeholder
    icon: str = ""          # 前端图标标识

    # 能力标记
    available: bool = False   # 依赖/通道本身可用（占位通道 = 表单可用）
    integrated: bool = True  # 后端是否真正接通（占位通道 = False）
    running: bool = False

    # 二维码
    qr_status: str = "idle"   # idle / waiting / scanned / confirmed / running / error
    qr_data: str = ""         # base64 或 data URL
    qr_message: str = ""

    # 前端可配置表单
    config: dict = {}
    config_schema: list = []  # [{key,label,type,placeholder,hint,secret}]

    _handler: Optional[Callable] = None

    def set_message_handler(self, handler: Callable):
        """设置统一消息处理回调 handler(user_id, content) -> str|tuple"""
        self._handler = handler

    @abstractmethod
    def start(self, **kwargs) -> bool:
        """启动通道；微信类通道启动后进入扫码等待"""
        ...

    @abstractmethod
    def stop(self):
        """停止通道"""
        ...

    @abstractmethod
    def send(self, user_id: str, text: str) -> bool:
        """按栖语内部 user_id 发送文本（user_id 由通道自己构造）"""
        ...

    def save_config(self, cfg: dict):
        """保存用户配置（可覆盖）"""
        if not isinstance(cfg, dict):
            return
        for k, v in cfg.items():
            if k in self.config:
                self.config[k] = v

    def status(self) -> dict:
        """对外状态快照（密钥自动打码）"""
        masked = dict(self.config or {})
        for s in self.config_schema or []:
            if s.get("secret") and masked.get(s["key"]):
                masked[s["key"]] = "******"
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "mode": self.mode,
            "icon": self.icon,
            "available": self.available,
            "integrated": self.integrated,
            "running": self.running,
            "qr_status": self.qr_status,
            "qr": self.qr_data or None,
            "qr_message": self.qr_message,
            "config": masked,
            "config_schema": self.config_schema,
        }
