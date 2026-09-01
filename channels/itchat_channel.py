"""微信单账号接管通道（itchat，模式 B）：包装现有 wechat.WeChatBot 为统一 Channel 接口。"""

from loguru import logger

from .base import BaseChannel


class ItchatChannel(BaseChannel):
    """itchat 单账号接管：直接登录一个微信号处理所有好友消息"""

    kind = "wechat"
    mode = "itchat"
    icon = "wechat"

    def __init__(self, bot):
        self.bot = bot
        self.id = "itchat"
        self.name = "微信 · 单账号接管"
        self.available = bool(getattr(bot, "is_available", False))
        self.integrated = True
        self.running = False
        self.qr_status = "idle"
        self.qr_data = ""
        self.qr_message = ""
        self.config = {"character_id": ""}
        self.config_schema = [
            {"key": "character_id", "label": "绑定角色（透传）", "type": "select",
             "options_source": "characters",
             "hint": "该微信号发来的消息走这个角色；留空使用默认角色"},
        ]
        self._handler = None
        # 恢复已保存的角色绑定
        try:
            from . import store
            saved = store.load_config(self.id)
            if saved and saved.get("character_id"):
                self.config["character_id"] = saved["character_id"]
        except Exception:
            pass

    def save_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        for k, v in cfg.items():
            if k in self.config:
                self.config[k] = v
        try:
            from . import store
            store.save_config(self.id, self.config)
        except Exception:
            pass

    @property
    def bot_name(self) -> str:
        return getattr(self.bot, "bot_name", "栖语")

    def set_message_handler(self, handler):
        self._handler = handler
        self.bot.set_message_handler(handler)

    def start(self, **kwargs) -> bool:
        if not self.available:
            self.qr_status = "error"
            self.qr_message = "itchat 未安装（pip install itchat-uos）"
            return False
        ok = self.bot.start()
        self._sync_state()
        if ok:
            self.qr_message = "请用微信扫码登录（手机确认）" if self.qr_status in ("waiting", "scanned") else ""
        return ok

    def stop(self):
        try:
            self.bot.stop()
        except Exception as e:
            logger.warning(f"[通道:itchat] 停止失败: {e}")
        self._sync_state()
        self.qr_data = ""
        self.qr_message = ""

    def send(self, user_id: str, text: str) -> bool:
        return self.bot.send_message(user_id, text)

    def _sync_state(self):
        self.running = bool(getattr(self.bot, "is_running", False))
        self.qr_status = getattr(self.bot, "qr_status", "idle")
        self.qr_data = self._normalize_qr_data(getattr(self.bot, "qr_data", "") or "")
        self.qr_message = getattr(self.bot, "qr_message", "") or "" 

    @staticmethod
    def _normalize_qr_data(raw: str) -> str:
        """itchat-uos 的 qrCallback 给的是裸 PNG base64，必须补 data URL 前缀前端才能显示"""
        raw = (raw or "").strip()
        if not raw:
            return ""
        if raw.startswith("data:image") or raw.startswith("http"):
            return raw
        return "data:image/png;base64," + raw

    def status(self) -> dict:
        self._sync_state()
        return super().status()
