"""栖语 外部通讯通道层（参考 OpenClaw channel 抽象）。

微信：
- ClawBot：官方 iLink 协议，前端扫码绑定，多账号并行（推荐，置顶）
- Wechatauto：本机接管（wechatauto-replica，读取纯被动 / 发送低干扰，直接操作本机微信 4.x）
- Wechaty：单账号接管（模式 B，Node 网关，wechat4u 免费 / service token 稳定方案）

预留（配置位已就绪）：
- 企业微信 / QQBot / 飞书
"""

from .base import BaseChannel
from .registry import get_channel_registry, ChannelRegistry
from .clawbot import ClawBotChannel, ILinkClient
from .wechaty_channel import WechatyChannel
from .wechatauto_channel import WechatautoChannel
from .placeholders import PlaceholderChannel, build_placeholder_channels
from . import store

__all__ = [
    "BaseChannel",
    "ChannelRegistry",
    "get_channel_registry",
    "ClawBotChannel",
    "ILinkClient",
    "WechatyChannel",
    "WechatautoChannel",
    "PlaceholderChannel",
    "build_placeholder_channels",
    "store",
]
