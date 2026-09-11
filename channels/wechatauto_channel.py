# -*- coding: utf-8 -*-
"""微信 · 本机接管通道（wechatauto-replica，参考 OpenClaw channel 抽象）。

原理：直接操作本机已登录的微信 4.x Windows 客户端——
- 读消息：解密本地 SQLCipher 数据库，纯被动轮询，不动 UI、不抢焦点、不打扰正常使用；
- 发消息：UIA/剪贴板 驱动微信窗口，需要微信窗口存在且桌面未锁屏。

与电脑微信的关系（务必如实告知用户）：
- 读 = 零打扰（只读数据库，微信本体完全无感）；
- 发 = 操作的就是用户正在用的那个微信窗口，**做不到和电脑微信完全隔离**。
  低干扰策略：
  1) 「使用中暂停」默认开启：检测到微信窗口正处于前台（用户正在用微信）时，
     先把发送挂起，等用户切走再发（最多等 pause_timeout 秒，超时仍会发送）；
  2) 桌面锁屏 / 会话断开时 `desktop_available()` 返回 False，发送接口直接失败，
     不会硬抢窗口；
  3) 若用户要真正互不干扰，只能走 ClawBot（独立 bot 号）或把微信放虚拟机/另一台机。
"""
import asyncio
import base64
import os
import tempfile
import threading
import time
from pathlib import Path

from loguru import logger

from .base import BaseChannel
from . import store

SEND_RETRY_INTERVAL = 2.0      # 「使用中暂停」重试间隔（秒）
SEND_PAUSE_TIMEOUT = 30.0      # 最多等多久（秒），超时仍发送
PAUSE_FOREGROUND_MATCH = True  # 微信窗口在前台时视为「用户正在用微信」


def _data_dir() -> Path:
    try:
        from pathutil import get_data_dir
        return get_data_dir()
    except Exception:
        return Path(__file__).resolve().parent.parent / "data"


def _image_to_data_url(path: str) -> str:
    """本地图片文件 → data URL（喂给视觉模型 / 前端渲染）"""
    try:
        ext = (Path(path).suffix or ".png").lower().lstrip(".")
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "webp": "image/webp", "bmp": "image/bmp"}.get(ext, "image/png")
        with open(path, "rb") as f:
            raw = f.read()
        return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
    except Exception as e:
        logger.warning(f"[wechatauto] 图片转 data URL 失败: {e}")
        return ""


class WechatautoChannel(BaseChannel):
    """微信本机接管：读取纯被动（DB 轮询），发送低干扰（使用中暂停 + 锁屏失败）。"""

    kind = "wechat"
    mode = "wechatauto"
    icon = "wechat"

    def __init__(self):
        self.id = "wechatauto"
        self.name = "微信 · 本机接管（wechatauto）"
        self.available = False
        self.integrated = True
        self.running = False
        self.qr_status = "idle"
        self.qr_data = ""
        self.qr_message = ""
        self._accounts: list = []
        self._db = None
        self._poll_thread = None
        self._stop_ev = threading.Event()
        self._self_wxid = ""
        self._media = None
        self._send_lock = threading.Lock()
        self._merged_remote: dict = {}
        self.config = {
            "account_id": "",
            "character_id": "",
            "single_conversation": True,
            "merge_user_id": "web_user",
            "poll_interval": "1.0",
            "pause_when_using": True,
            "pause_timeout": "30",
            "emoji_beta": False,
            "allow_groups": False,
            "enable_send": True,
        }
        self.config_schema = [
            {"key": "account_id", "label": "接管账号", "type": "select",
             "options": [], "placeholder": "自动检测本机微信账号",
             "hint": "本机已登录的微信 4.x 账号；留空自动选最近活跃的账号。"},
            {"key": "character_id", "label": "绑定角色（透传）", "type": "select",
             "options_source": "characters",
             "hint": "微信发来的消息走这个角色；留空使用默认角色"},
            {"key": "single_conversation", "label": "单一对话（并入 App 主对话）", "type": "checkbox",
             "hint": "默认开启：微信只是另一个前端，消息并入 App 同一个对话线程；关闭后每个微信联系人独立会话。"},
            {"key": "merge_user_id", "label": "并入的对话 ID", "type": "text",
             "placeholder": "web_user",
             "hint": "单一对话模式并入哪个栖语对话；默认 web_user（App 主对话）。"},
            {"key": "poll_interval", "label": "读取轮询间隔（秒）", "type": "text",
             "placeholder": "1.0", "hint": "DB 轮询越频繁延迟越低，纯本地读取不吃性能；默认 1 秒。"},
            {"key": "pause_when_using", "label": "使用中暂停发送（低干扰）", "type": "checkbox",
             "hint": "默认开启：检测到微信窗口在前台（你正在用微信）时先把回复挂起，等你切走再发；读取永远不打扰。"},
            {"key": "pause_timeout", "label": "暂停最长等待（秒）", "type": "text",
             "placeholder": "30", "hint": "超过该时间即使微信仍在前台也会发送（避免回复卡死）；0=不等待立即发。"},
            {"key": "emoji_beta", "label": "微信表情理解（BETA）", "type": "checkbox",
             "hint": "把微信动画表情当图片识别喂给模型；未开启时入站表情显示为 [表情]。"},
            {"key": "allow_groups", "label": "接收群聊消息", "type": "checkbox",
             "hint": "默认关闭（只回单聊）；开启后群消息也会进入对话（建议配合单一对话=关使用）。"},
            {"key": "enable_send", "label": "允许发送", "type": "checkbox",
             "hint": "关闭后只读不回（纯监听）；发送本质是操作微信窗口，锁屏/断开会自动失败。"},
        ]
        try:
            saved = store.load_config(self.id)
            if saved:
                for k in list(self.config):
                    if k in saved:
                        if k in ("single_conversation", "pause_when_using", "emoji_beta",
                                 "allow_groups", "enable_send"):
                            self.config[k] = str(saved[k]).strip().lower() in ("1", "true", "yes", "on")
                        else:
                            self.config[k] = saved[k]
        except Exception:
            pass
        self._check_deps()

    # ---------- 依赖检测 ----------
    def _check_deps(self):
        try:
            import wechatauto  # noqa: F401
        except Exception as e:
            self.available = False
            self.qr_message = f"wechatauto-replica 未安装：pip install wechatauto-replica（本机接管需要）: {e}"
            return
        try:
            from wechatauto import list_accounts
            self._accounts = list_accounts() or []
        except Exception as e:
            self.available = False
            self.qr_message = f"微信数据目录检测失败: {e}"
            return
        if not self._accounts:
            self.available = False
            self.qr_message = "未检测到本机已登录的微信 4.x 账号（需先打开并登录微信客户端）"
            return
        # 账号下拉动态刷新
        for f in self.config_schema:
            if f.get("key") == "account_id":
                f["options"] = [a.get("account") for a in self._accounts if a.get("account")]
        self.available = True
        self.qr_message = f"就绪：读取=只读数据库（零打扰），发送=操作本机微信窗口（开启「使用中暂停」更低调）"

    def save_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        for k, v in cfg.items():
            if k == "single_conversation":
                self.config[k] = str(v).strip().lower() in ("1", "true", "yes", "on")
            elif k == "pause_when_using":
                self.config[k] = str(v).strip().lower() in ("1", "true", "yes", "on")
            elif k == "emoji_beta":
                self.config[k] = str(v).strip().lower() in ("1", "true", "yes", "on")
            elif k == "allow_groups":
                self.config[k] = str(v).strip().lower() in ("1", "true", "yes", "on")
            elif k == "enable_send":
                self.config[k] = str(v).strip().lower() in ("1", "true", "yes", "on")
            elif k in self.config:
                self.config[k] = v
        try:
            store.save_config(self.id, self.config)
        except Exception:
            pass
        self._check_deps()

    def set_message_handler(self, handler):
        self._handler = handler

    # ---------- 生命周期 ----------
    def start(self, **kwargs) -> bool:
        if self.running:
            return True
        if not self.available:
            self.qr_status = "error"
            return False
        # 启动放到后台线程：首次要扫描微信进程内存提取密钥 + 给数百个会话做水位初始化，
        # 可能耗时数十秒，不能阻塞 FastAPI 事件循环（否则整个 App 界面会卡死）。
        self.qr_status = "starting"
        self.qr_message = "正在初始化本机微信读取（首次需扫描微信进程密钥并建立会话水位，请稍候）..."
        threading.Thread(target=self._start_worker, daemon=True, name="wechatauto_start").start()
        return True

    def _start_worker(self):
        try:
            from wechatauto import WeChatDB
            account = str(self.config.get("account_id") or "").strip()
            db = WeChatDB(account=account or None)
            self._db = db
            self._self_wxid = str(getattr(db, "wxid", "") or "")
            interval = float(self.config.get("poll_interval") or 1.0)
            if interval < 0.3:
                interval = 0.3
            self._stop_ev.clear()
            self._poll_thread = threading.Thread(target=self._poll_loop,
                                                 daemon=True, name="wechatauto_poll")
            self._poll_thread.start()
            self.running = True
            self.qr_status = "running"
            self.qr_message = f"正在监听本机微信（{db.get_self_info().get('nick_name', '')}）——读取被动，不打扰正常使用"
            logger.info(f"[wechatauto] 已启动：账号={getattr(db, 'account', '')} 间隔={interval}s")
            return True
        except Exception as e:
            self.running = False
            self.qr_status = "error"
            self.qr_message = f"启动失败: {e}"
            logger.error(f"[wechatauto] 启动失败: {e}")
            return

    def stop(self):
        self._stop_ev.set()
        try:
            if self._poll_thread and self._poll_thread.is_alive():
                self._poll_thread.join(timeout=4)
        except Exception:
            pass
        self._poll_thread = None
        self.running = False
        self.qr_status = "idle"
        self.qr_message = "已停止"
        logger.info("[wechatauto] 已停止")

    # ---------- 读取轮询（自建，健壮：单会话读失败不中断整体） ----------
    def _poll_loop(self):
        """纯被动轮询：每个会话一个 sort_seq 水位，逐会话 try/except。
        微信消息库在客户端运行中可能出现瞬态损坏（SQLCipher+WAL 未落盘），
        读失败的会话跳过，下一轮自动重试，绝不中断监听。"""
        watermarks: dict = {}
        interval = 1.0
        try:
            interval = float(self.config.get("poll_interval") or 1.0)
        except Exception:
            pass
        if interval < 0.3:
            interval = 0.3
        while not self._stop_ev.is_set():
            try:
                if self._db is None:
                    self._stop_ev.wait(interval)
                    continue
                sessions = self._db.get_sessions(limit=300)
                for s in sessions:
                    username = str(s.get("username") or "")
                    if not username:
                        continue
                    if username.endswith("@chatroom") and not self.config.get("allow_groups"):
                        continue
                    try:
                        if username not in watermarks:
                            msgs = self._db.get_messages(username, limit=1)
                            watermarks[username] = int(msgs[0]["sort_seq"]) if msgs else 0
                            continue
                        new = self._db.get_new_messages(username, since_seq=watermarks[username], limit=50)
                    except Exception:
                        continue  # 该会话暂时读不了，下轮重试
                    if not new:
                        continue
                    last_seq = watermarks[username]
                    for m in new:
                        try:
                            seq = int(m.get("sort_seq") or 0)
                        except Exception:
                            seq = 0
                        if seq > last_seq:
                            last_seq = seq
                        try:
                            m = dict(m)
                            m["username"] = username
                            self._on_msg(m, None)
                        except Exception as e:
                            logger.debug(f"[wechatauto] 处理 {username} 消息失败: {e}")
                    watermarks[username] = last_seq
            except Exception as e:
                logger.debug(f"[wechatauto] 轮询异常: {e}")
            self._stop_ev.wait(interval)

    def reset(self):
        """重置：清空 DB/媒体缓存句柄，下次启动重新扫描账号与密钥"""
        self.stop()
        self._db = None
        self._media = None
        self._merged_remote = {}
        self._check_deps()

    # ---------- 入站 ----------
    def _media_downloader(self):
        if self._media is None and self._db is not None:
            try:
                from wechatauto import MediaDownloader
                self._media = MediaDownloader(self._db)
            except Exception as e:
                logger.warning(f"[wechatauto] MediaDownloader 初始化失败: {e}")
        return self._media

    def _on_msg(self, msg: dict, listener):
        """Listener 回调：收到新消息（DB 轮询，纯被动）。"""
        try:
            if not msg:
                return
            mtype = str(msg.get("type") or "")
            content = str(msg.get("content") or "")
            username = str(msg.get("username") or "")
            sender_id = str(msg.get("sender_id") or "")
            if mtype == "系统消息" or not username:
                return
            if username.endswith("@chatroom"):
                if not self.config.get("allow_groups"):
                    return
            if sender_id == "2" or (self._self_wxid and sender_id == self._self_wxid):
                return  # 自己发的，跳过
            nickname = ""
            try:
                nickname = self._db.get_nickname(username) or username
            except Exception:
                nickname = username
            images = []
            text = content
            if mtype == "图片":
                text = "[图片]"
            elif mtype == "语音":
                text = "[语音]"
            elif mtype == "动画表情":
                text = "[表情]"
            elif mtype == "视频":
                text = "[视频]"
            elif mtype == "文件":
                text = "[文件]"
            # 媒体下载：图片 / 动画表情（需开启 beta）→ 图片透传（视觉识别 + 前端显示）
            need_img = True if mtype == "图片" else (bool(self.config.get("emoji_beta", False)) if mtype == "动画表情" else False)
            if need_img:
                local_id = msg.get("local_id")
                if local_id:
                    try:
                        md = self._media_downloader()
                        if md:
                            out = md.download_media(username, str(local_id))
                            if out and os.path.exists(str(out)):
                                images.append(_image_to_data_url(str(out)))
                    except Exception as e:
                        logger.debug(f"[wechatauto] 媒体下载失败: {e}")
            elif mtype == "语音":
                local_id = msg.get("local_id")
                if local_id:
                    try:
                        from .wechat_voice import transcribe_audio_file, local_asr_available
                        if local_asr_available():
                            md = self._media_downloader()
                            if md:
                                out = md.download_media(username, str(local_id))
                                if out and os.path.exists(str(out)):
                                    t = transcribe_audio_file(str(out))
                                    if t:
                                        text = f"[语音] {t}"
                    except Exception as e:
                        logger.debug(f"[wechatauto] 语音转写失败: {e}")
            if not text and not images:
                return
            if self.config.get("emoji_beta") and mtype == "动画表情" and not images:
                text = "[表情]"
            merge = bool(self.config.get("single_conversation", True))
            if merge:
                uid = str(self.config.get("merge_user_id") or "web_user").strip() or "web_user"
                self._merged_remote[uid] = username  # 记住映射，主动消息回发
            else:
                uid = f"wx_{self.id}__{username}"
            logger.info(f"[wechatauto] 收到 [{nickname}] {mtype}: {text[:40]} 图片数={len(images)}")
            if not self._handler:
                return
            try:
                if asyncio.iscoroutinefunction(self._handler):
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        reply = loop.run_until_complete(self._handler(uid, text, self, images))
                    finally:
                        loop.close()
                else:
                    reply = self._handler(uid, text, self, images)
            except Exception as e:
                logger.error(f"[wechatauto] 处理消息失败: {e}")
                return
            if not self.config.get("enable_send", True):
                return
            self._send_reply(username, reply)
        except Exception as e:
            logger.error(f"[wechatauto] 消息解析失败: {e}")

    # ---------- 发送 ----------
    def _wx_is_foreground(self) -> bool:
        """微信主窗口是否处于前台（用于「使用中暂停」）"""
        if not PAUSE_FOREGROUND_MATCH:
            return False
        try:
            import wechatauto.sender as snder
            hwnd = snder.find_main_window()
            if not hwnd:
                return False
            import win32gui
            return win32gui.GetForegroundWindow() == hwnd
        except Exception:
            return False

    def _wait_pause(self) -> bool:
        """「使用中暂停」：微信窗口在前台时挂起，等用户切走；超时仍返回 True（发送）。"""
        if not self.config.get("pause_when_using", True):
            return True
        try:
            timeout = float(self.config.get("pause_timeout") or 30)
        except Exception:
            timeout = 30
        if timeout <= 0:
            return True
        waited = 0.0
        while waited < timeout and self._wx_is_foreground():
            time.sleep(SEND_RETRY_INTERVAL)
            waited += SEND_RETRY_INTERVAL
        return True

    def _resolve_remote(self, user_id: str) -> str:
        """栖语内部 user_id → 微信联系人 username（wxid）"""
        if not user_id:
            return ""
        if user_id.startswith("wx_"):
            body = user_id[3:]
            _, _, remote = body.partition("__")
            if remote:
                return remote
        return str(self._merged_remote.get(user_id) or "")

    def send(self, user_id: str, text: str) -> bool:
        """主动消息下发（单条文本）"""
        if not self.config.get("enable_send", True):
            return False
        remote = self._resolve_remote(user_id)
        if not remote:
            logger.warning(f"[wechatauto] 无法定位微信联系人（user_id={user_id}），主动消息不下发")
            return False
        return self._send_text(remote, text)

    def _send_text(self, remote: str, text: str) -> bool:
        try:
            from wechatauto.guia import quick_send
        except Exception as e:
            logger.warning(f"[wechatauto] wechatauto 发送模块不可用: {e}")
            return False
        self._wait_pause()
        try:
            nickname = self._db.get_nickname(remote) or remote
        except Exception:
            nickname = remote
        try:
            resp = quick_send(text, who=nickname, verify=False)
            ok = bool(getattr(resp, "ok", True) if resp else True)
            if not ok:
                logger.warning(f"[wechatauto] 发送失败: {getattr(resp, 'message', resp)}")
            return ok
        except Exception as e:
            logger.warning(f"[wechatauto] 发送异常: {e}")
            return False

    def _prepare_image_file(self, img: str) -> str:
        """把 http URL / data URL / base64 图片转成本地临时文件路径（quick_send_image 需要）"""
        img = (img or "").strip()
        if not img:
            return ""
        tmp = Path(tempfile.gettempdir()) / f"qiyu_wx_img_{int(time.time() * 1000)}.png"
        try:
            if img.startswith("data:image"):
                m = img.split(",", 1)
                raw = base64.b64decode(m[1]) if len(m) > 1 else b""
            elif img.startswith("http://") or img.startswith("https://"):
                import requests
                raw = requests.get(img, timeout=15).content
            else:
                raw = base64.b64decode(img)
            tmp.write_bytes(raw)
            return str(tmp)
        except Exception as e:
            logger.warning(f"[wechatauto] 图片准备失败: {e}")
            return ""

    def _send_reply(self, remote: str, reply):
        """按真人节奏逐条发送回复；每条校验结果，图片先落盘再发。"""
        if isinstance(reply, tuple):
            reply_text, pieces = reply
            items = pieces or []
        else:
            reply_text, pieces = reply, None
            items = [{"text": reply_text, "delay": 0}] if reply_text else []
        with self._send_lock:
            for i, p in enumerate(items):
                txt = (p.get("text") or "").strip()
                img = str(p.get("image") or p.get("image_url") or "").strip()
                if not txt and not img:
                    continue
                try:
                    if img:
                        local = self._prepare_image_file(img)
                        if local:
                            from wechatauto.guia import quick_send_image
                            self._wait_pause()
                            resp = quick_send_image(local, who=self._db.get_nickname(remote) or remote, verify=False)
                            logger.info(f"[wechatauto] 已发送图片给 {remote}（{i+1}/{len(items)}）ok={getattr(resp,'ok',True)}")
                            try:
                                os.remove(local)
                            except Exception:
                                pass
                    if txt:
                        self._send_text(remote, txt)
                        logger.info(f"[wechatauto] 已发送 {remote}: {txt[:30]}（{i+1}/{len(items)}）")
                except Exception as e:
                    logger.error(f"[wechatauto] 发送失败（第 {i+1} 条）: {e}")
                    self.qr_message = f"微信发送失败（第 {i+1}/{len(items)} 条）: {e}"
                    return
                delay = (p.get("delay") or 0) / 1000.0
                if i < len(items) - 1 and delay > 0:
                    time.sleep(min(delay, 8.0))

    def resolve_remote(self, user_id: str) -> str:
        return self._resolve_remote(user_id)
