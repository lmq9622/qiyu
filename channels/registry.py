"""通道注册表：统一路由 栖语 user_id → 通道，供主动消息下发与状态查询。"""

from typing import Callable, Optional

from loguru import logger

from .base import BaseChannel


class ChannelRegistry:
    """所有外部通讯通道的注册中心"""

    def __init__(self):
        self._channels: dict[str, BaseChannel] = {}

    def register(self, channel: BaseChannel) -> BaseChannel:
        self._channels[channel.id] = channel
        logger.info(f"[通道] 注册: {channel.id}（{channel.name}）")
        return channel

    def get(self, channel_id: str) -> Optional[BaseChannel]:
        return self._channels.get(channel_id)

    def list_channels(self) -> list:
        return [c.status() for c in self._channels.values()]

    def set_message_handler(self, handler: Callable):
        for c in self._channels.values():
            if c.integrated:
                try:
                    c.set_message_handler(handler)
                except Exception as e:
                    logger.warning(f"[通道] 设置 {c.id} 消息处理器失败: {e}")

    def get_channel_for_user(self, user_id: str) -> Optional[BaseChannel]:
        """按栖语内部 user_id 路由到通道：
        wx_<通道id>__<对方id> → 对应通道；
        单一对话合并后的 user_id（如 web_user） → 有绑定微信联系人的通道（resolve_remote 命中）。
        找不到返回 None（前端普通对话）。"""
        if not user_id:
            return None
        if user_id.startswith("wx_"):
            body = user_id[3:]
            if "__" in body:
                acc = body.split("__", 1)[0]
                ch = self.get(acc)
                if ch:
                    return ch
            return self.get("wechatauto") or self.get("wechaty") or self.get("clawbot_main")
        # 合并对话：找最近绑定过微信联系人的通道
        for ch in self._channels.values():
            try:
                if getattr(ch, "running", False) and getattr(ch, "resolve_remote", None):
                    if ch.resolve_remote(user_id):
                        return ch
            except Exception:
                continue
        return None

    def send(self, user_id: str, text: str) -> bool:
        """主动消息下发：按 user_id 路由到对应通道"""
        ch = self.get_channel_for_user(user_id)
        if ch and ch.running:
            try:
                return ch.send(user_id, text)
            except Exception as e:
                logger.warning(f"[通道] {ch.id} 发送失败: {e}")
                return False
        return False

    def running_channels(self) -> list[BaseChannel]:
        return [c for c in self._channels.values() if c.running]


_registry: Optional[ChannelRegistry] = None


def get_channel_registry() -> ChannelRegistry:
    global _registry
    if _registry is None:
        _registry = ChannelRegistry()
    return _registry
