"""
栖语 (Qiyu) - 微信机器人模块
支持 itchat（UOS协议），自动接入对话系统
覆盖原开源工具的完整功能：文字 / 图片 / 语音 / 视频 / 表情 / 文件 / 群聊@ / 新好友自动通过
"""

import os
import base64
import asyncio
import threading
import time
from typing import Callable, Optional
from pathlib import Path

from loguru import logger

# 尝试导入 itchat
try:
    import itchat
    from itchat.content import (
        TEXT, PICTURE, RECORDING, VIDEO, ATTACHMENT, FRIENDS, NOTE, MAP, CARD, SHARING,
    )
    ITCHAT_AVAILABLE = True
except ImportError:
    ITCHAT_AVAILABLE = False
    logger.warning("itchat 未安装，微信功能不可用。安装命令: pip install itchat-uos")

STUCK_SCAN_HINT = "已扫码；如果手机端已确认仍停在这一步，说明该微信号可能被限制网页/UOS登录，建议改用上方 ClawBot 官方通道。"


def _download_media(msg, tag: str) -> str:
    """下载微信图片/语音/视频/文件到本地，返回 (本地路径, base64_dataURL)。下载失败返回 ('', '')"""
    try:
        fn = msg.get("FileName") or f"wechat_{tag}_{int(time.time()*1000)}"
        safe = "".join(ch for ch in str(fn) if ch.isalnum() or ch in "._- ").strip() or "media.bin"
        workdir = os.environ.get("QIYU_DATA_DIR") or os.path.expanduser("~/.ai_companion")
        savedir = Path(workdir) / "uploads" / "wechat"
        savedir.mkdir(parents=True, exist_ok=True)
        dest = savedir / safe
        msg.download(dest=str(dest))
        if dest.exists() and dest.stat().st_size > 0:
            data = dest.read_bytes()
            b64 = base64.b64encode(data).decode("ascii")
            return str(dest), f"data:image/png;base64,{b64}"
    except Exception as e:
        logger.warning(f"[微信] 下载媒体失败: {e}")
    return "", ""


class WeChatBot:
    """微信机器人"""

    def __init__(self, account_id: str = ""):
        # 多账号并行架构预留：一个微信账号 = 一个 WeChatBot 实例；account_id 为空表示默认账号
        self.account_id = account_id
        self.enabled = False
        self.config = {"character_id": ""}   # 绑定角色（透传），与通道层对齐
        self._message_handler: Optional[Callable] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._login_thread: Optional[threading.Thread] = None
        self.bot_name = "栖语"
        self.qr_callback: Optional[Callable] = None  # 二维码显示回调
        self._qr_base64: str = ""  # 二维码 base64（无 data: 前缀）
        self._qr_status: str = "idle"  # idle/waiting/scanned/confirmed/running
        self._scan_stuck_since: float = 0.0  # 卡在“已扫码”的时间戳，用于超时提示
        self._stuck_hint: str = ""

    def set_message_handler(self, handler: Callable):
        """设置消息处理回调 handler(user_id, content, channel=None, images=None)"""
        self._message_handler = handler

    def set_qr_callback(self, callback: Callable):
        """设置二维码回调"""
        self.qr_callback = callback

    def _invoke_handler(self, user_id: str, content: str, images: list | None = None):
        """调用统一消息处理回调；返回 reply 或 (reply, pieces)"""
        if not self._message_handler:
            return None
        try:
            if asyncio.iscoroutinefunction(self._message_handler):
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    reply = loop.run_until_complete(self._message_handler(user_id, content, None, images or []))
                finally:
                    loop.close()
            else:
                reply = self._message_handler(user_id, content, None, images or [])
            return reply
        except Exception as e:
            logger.error(f"[微信] 处理消息失败: {e}")
            return None

    def _handle_text_msg(self, msg):
        """处理文本消息（含群聊@）"""
        from_user = msg.get("FromUserName", "")
        content = msg.get("Text", "").strip()
        is_group = msg.get("isAt", False) or "@@" in from_user
        if self.account_id:
            user_id = f"wx_{self.account_id}__{from_user}"
        else:
            user_id = f"wx_{from_user}"
        if is_group:
            if not content.startswith(f"@{self.bot_name}"):
                return
            content = content.replace(f"@{self.bot_name}", "").strip()
        logger.info(f"[微信] 收到消息 [{user_id}]: {content[:50]}")
        reply = self._invoke_handler(user_id, content)
        if reply:
            self._send_reply(from_user, reply)

    def _handle_media_msg(self, msg, tag: str, text_marker: str):
        """处理图片/语音/视频/文件：下载媒体 → [标记] + 图片透传给视觉链路"""
        from_user = msg.get("FromUserName", "")
        if self.account_id:
            user_id = f"wx_{self.account_id}__{from_user}"
        else:
            user_id = f"wx_{from_user}"
        local_path, data_url = _download_media(msg, tag)
        images = [data_url] if (data_url and tag == "image") else []
        content = text_marker
        if local_path:
            content = f"{text_marker}（{Path(local_path).name}）"
        logger.info(f"[微信] 收到媒体 [{user_id}] {tag}: {content[:60]}")
        reply = self._invoke_handler(user_id, content, images)
        if reply:
            self._send_reply(from_user, reply)

    def _send_reply(self, to_user: str, reply):
        """把回复（str 或 (text, pieces)）按 pieces 的 delay 逐条发送；支持 image 字段"""
        if isinstance(reply, tuple):
            reply_text, pieces = reply
            items = pieces or []
        else:
            reply_text, pieces = reply, None
            items = [{"text": reply_text, "delay": 0}] if reply_text else []
        for i, p in enumerate(items):
            txt = (p.get("text") or "").strip()
            img = str(p.get("image") or p.get("image_url") or "").strip()
            try:
                if img and (img.startswith("http://") or img.startswith("https://")):
                    # 远程图片：先下载到本地再 send_image（itchat 只收本地文件）
                    _ok, _local = _save_remote_image(img, to_user)
                    if _ok:
                        itchat.send_image(_local, toUserName=to_user)
                    elif txt:
                        itchat.send(txt, toUserName=to_user)
                elif img:
                    # base64 / data URL：转本地临时文件再发送
                    _ok, _local = _save_data_image(img, to_user)
                    if _ok:
                        itchat.send_image(_local, toUserName=to_user)
                    elif txt:
                        itchat.send(txt, toUserName=to_user)
                elif txt:
                    itchat.send(txt, toUserName=to_user)
            except Exception as e:
                logger.error(f"[微信] 发送失败: {e}")
                return
            delay = (p.get("delay") or 0) / 1000.0
            if i < len(items) - 1 and delay > 0:
                time.sleep(min(delay, 3.0))

    def _show_qr(self, uuid, status, qrcode):
        """显示二维码；status: 0=待扫 201=已扫码待确认 200=确认成功"""
        try:
            if status == "0":
                import base64 as _b64
                if isinstance(qrcode, bytes):
                    self._qr_base64 = _b64.b64encode(qrcode).decode("ascii")
                elif isinstance(qrcode, str):
                    self._qr_base64 = qrcode
                elif hasattr(qrcode, "png_as_base64_str"):
                    self._qr_base64 = qrcode.png_as_base64_str(scale=10)
                else:
                    self._qr_base64 = ""
                self._qr_status = "waiting"
                self._stuck_hint = ""
                logger.info("[微信] 请扫描二维码登录")
                if self.qr_callback:
                    self.qr_callback(qrcode)
            elif status == "200":
                self._qr_status = "confirmed"
                self._stuck_hint = ""
                logger.info("[微信] 扫码确认，正在登录...")
            elif status == "201":
                self._qr_status = "scanned"
                if not self._scan_stuck_since:
                    self._scan_stuck_since = time.time()
                # 卡在“已扫码”超过 75 秒给出 UOS 被限提示（不阻塞，可继续等）
                if time.time() - self._scan_stuck_since > 75:
                    self._stuck_hint = STUCK_SCAN_HINT
                logger.info("[微信] 已扫码，等待确认")
        except Exception as e:
            logger.warning(f"[微信] 二维码回调异常: {e}")

    def start(self) -> bool:
        """启动微信机器人（后台线程登录，不阻塞调用方）"""
        if not ITCHAT_AVAILABLE:
            logger.error("[微信] itchat 未安装，无法启动微信机器人")
            return False

        if self._running:
            logger.info("[微信] 机器人已在运行")
            return True
        if self._login_thread and self._login_thread.is_alive():
            logger.info("[微信] 正在登录中，请先完成扫码")
            return True

        try:
            def worker():
                # 会话文件（hotReload）写入可写目录
                workdir = os.environ.get("QIYU_DATA_DIR") or os.path.expanduser("~/.ai_companion")
                try:
                    Path(workdir).mkdir(parents=True, exist_ok=True)
                    os.chdir(workdir)
                except Exception:
                    pass
                try:
                    @itchat.msg_register(TEXT)
                    def text_handler(msg):
                        self._handle_text_msg(msg)

                    @itchat.msg_register(PICTURE)
                    def picture_handler(msg):
                        self._handle_media_msg(msg, "image", "[图片]")

                    @itchat.msg_register(RECORDING)
                    def recording_handler(msg):
                        self._handle_media_msg(msg, "voice", "[语音]")

                    @itchat.msg_register(VIDEO)
                    def video_handler(msg):
                        self._handle_media_msg(msg, "video", "[视频]")

                    @itchat.msg_register("Emoji")
                    def animation_handler(msg):
                        # 微信表情：直接透传文本
                        self._handle_media_msg(msg, "emoji", "[表情]")

                    @itchat.msg_register(ATTACHMENT)
                    def attachment_handler(msg):
                        self._handle_media_msg(msg, "file", "[文件]")

                    @itchat.msg_register(FRIENDS)
                    def friends_handler(msg):
                        # 自动通过好友申请（对应原工具“好友管理”功能）
                        try:
                            msg.user.verify()
                            logger.info(f"[微信] 已自动通过好友申请: {msg.user.nickName}")
                        except Exception as e:
                            logger.warning(f"[微信] 自动通过好友失败: {e}")

                    @itchat.msg_register([MAP, CARD, SHARING, NOTE])
                    def misc_handler(msg):
                        # 位置 / 名片 / 分享 / 系统通知：不静默丢弃，转成文本标记进对话链路
                        from_user = msg.get("FromUserName", "")
                        if self.account_id:
                            uid = f"wx_{self.account_id}__{from_user}"
                        else:
                            uid = f"wx_{from_user}"
                        marker = "[位置]"
                        if str(getattr(msg, "type", "")) in ("Card", "名片"):
                            marker = "[名片]"
                        elif str(getattr(msg, "type", "")) in ("Sharing", "分享"):
                            marker = "[分享]"
                        elif str(getattr(msg, "type", "")) in ("Note", "系统通知"):
                            marker = "[系统通知]"
                        logger.info(f"[微信] 收到消息 [{uid}] {marker}: {str(msg.get('Text') or '')[:50]}")
                        reply = self._invoke_handler(uid, marker)
                        if reply:
                            self._send_reply(from_user, reply)

                    logger.info("[微信] 正在登录（请扫描二维码）...")
                    self._scan_stuck_since = 0.0
                    self._stuck_hint = ""
                    itchat.auto_login(
                        hotReload=True,
                        qrCallback=self._show_qr,
                    )

                    self_info = itchat.search_friends()
                    if self_info:
                        self.bot_name = self_info[0].get("NickName", "栖语")

                    self._running = True
                    self.enabled = True
                    self._qr_status = "running"
                    self._stuck_hint = ""
                    logger.success(f"[微信] 机器人已启动 (昵称: {self.bot_name})")
                    itchat.run(debug=False)
                except Exception as e:
                    logger.error(f"[微信] 启动失败: {e}")
                    self._running = False
                    self.enabled = False
                    self._qr_status = "idle"

            self._login_thread = threading.Thread(target=worker, daemon=True)
            self._login_thread.start()
            return True

        except Exception as e:
            logger.error(f"[微信] 启动失败: {e}")
            return False

    def stop(self):
        """停止微信机器人"""
        if not self._running:
            return
        try:
            if ITCHAT_AVAILABLE:
                itchat.logout()
        except Exception:
            pass
        self._running = False
        self.enabled = False
        self._qr_status = "idle"
        self._qr_base64 = ""
        self._stuck_hint = ""
        logger.info("[微信] 机器人已停止")

    def send_message(self, user_id: str, content: str):
        """主动发送消息"""
        if not ITCHAT_AVAILABLE or not self._running:
            return False
        try:
            wx_id = user_id.replace("wx_", "")
            if "__" in wx_id:
                acc_part, _, rest = wx_id.partition("__")
                bot = get_bot_for_user(user_id)
                if bot is not None and bot is not self and bot._running:
                    return bot.send_message(f"wx_{rest}", content)
                wx_id = rest
            itchat.send(content, toUserName=wx_id)
            return True
        except Exception as e:
            logger.error(f"[微信] 发送消息失败: {e}")
            return False

    @property
    def is_available(self) -> bool:
        return ITCHAT_AVAILABLE

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def qr_data(self) -> str:
        b = self._qr_base64
        if b and not b.startswith("data:image") and not b.startswith("http"):
            return "data:image/png;base64," + b
        return b

    @property
    def qr_status(self) -> str:
        return self._qr_status

    @property
    def qr_message(self) -> str:
        return self._stuck_hint


def _save_remote_image(url: str, to_user: str):
    """下载远程图片到本地临时文件（itchat 发送需要本地路径）"""
    try:
        import urllib.request
        workdir = os.environ.get("QIYU_DATA_DIR") or os.path.expanduser("~/.ai_companion")
        savedir = Path(workdir) / "uploads" / "wechat"
        savedir.mkdir(parents=True, exist_ok=True)
        dest = savedir / f"remote_{int(time.time()*1000)}.png"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as r, open(dest, "wb") as f:
            f.write(r.read())
        return True, str(dest)
    except Exception as e:
        logger.warning(f"[微信] 远程图片下载失败: {e}")
        return False, ""


def _save_data_image(data: str, to_user: str):
    """把 base64 / data URL 图片写成本地临时文件"""
    try:
        import re
        workdir = os.environ.get("QIYU_DATA_DIR") or os.path.expanduser("~/.ai_companion")
        savedir = Path(workdir) / "uploads" / "wechat"
        savedir.mkdir(parents=True, exist_ok=True)
        dest = savedir / f"data_{int(time.time()*1000)}.png"
        payload = data
        m = re.match(r"data:image/[\w.+-]+;base64,([\s\S]+)", data)
        if m:
            payload = m.group(1)
        raw = base64.b64decode(payload)
        dest.write_bytes(raw)
        return True, str(dest)
    except Exception as e:
        logger.warning(f"[微信] base64 图片落盘失败: {e}")
        return False, ""


# ============ 全局实例 ============
_wechat_bot = None
BOT_REGISTRY: dict = {}  # account_id -> WeChatBot（多账号并行：一个用户固定对应一个微信号）


def register_bot(bot: WeChatBot, account_id: str = "default"):
    """注册一个微信账号实例到路由表"""
    BOT_REGISTRY[account_id] = bot


def get_bot_for_user(user_id: str) -> WeChatBot | None:
    """根据用户ID路由到对应微信账号实例（wx_账号id__wxid / wx_wxid → default）"""
    if not user_id.startswith("wx_"):
        return None
    body = user_id[3:]
    if "__" in body:
        acc_part = body.split("__", 1)[0]
        return BOT_REGISTRY.get(acc_part) or BOT_REGISTRY.get("default")
    return BOT_REGISTRY.get("default")

def get_wechat_bot() -> WeChatBot:
    global _wechat_bot
    if _wechat_bot is None:
        _wechat_bot = WeChatBot()
        register_bot(_wechat_bot, "default")
    return _wechat_bot
