"""栖语 外部通讯通道层（参考 OpenClaw channel 抽象）。

微信：
- ClawBot：官方 iLink 协议，前端扫码绑定，多账号并行（推荐，置顶）
- Wechatauto：本机接管（wechatauto-replica，读取纯被动 / 发送低干扰，直接操作本机微信 4.x）
- Wechaty：单账号接管（模式 B，Node 网关，wechat4u 免费 / service token 稳定方案）

已实现（配置位 + 官方协议）：
- QQBot：官方 WebSocket + REST（channels/qqbot_channel.py，线上凭据未验证）
- 飞书：REST 发送 + Webhook 事件订阅（channels/feishu_channel.py，线上凭据未验证）
企业微信仍为预留占位。
"""

from .base import BaseChannel
from .registry import get_channel_registry, ChannelRegistry
from .clawbot import ClawBotChannel, ILinkClient
from .wechaty_channel import WechatyChannel
from .wechatauto_channel import WechatautoChannel
from .placeholders import PlaceholderChannel, build_placeholder_channels
from .qqbot_channel import QQBotChannel, build_qqbot_channel
from .feishu_channel import FeishuChannel, build_feishu_channel
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
    "QQBotChannel",
    "build_qqbot_channel",
    "FeishuChannel",
    "build_feishu_channel",
    "store",
]
