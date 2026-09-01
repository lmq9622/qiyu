# -*- coding: utf-8 -*-
"""微信独立接入通道（Wechaty，模式 B 替换）：Python 后端桥接 Node Wechaty 网关。

架构：Python 侧 spawn `wechaty/gateway.js`（Node 进程），通过 HTTP 通信：
- 启动/登录：POST /start（网关内部触发 Wechaty scan/login）
- 状态/二维码：GET /status（Python 轮询，qr 字符串本地转二维码图）
- 入站消息：网关 POST 到 /v1/channels/wechaty/webhook（带共享密钥）
- 主动/回复发送：POST /send（单条 text/image）

支持两种 puppet：
- wechaty-puppet-wechat4u：本地免费 web 协议（扫码登录，web 协议被微信限制的风险与 itchat 相同）
- wechaty-puppet-service：需要 WECHATY_PUPPET_SERVICE_TOKEN（padlocal 等稳定方案）
"""
import asyncio
import base64
import io
import os
import random
import string
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import requests
from loguru import logger

from .base import BaseChannel

GATEWAY_PORT = int(os.getenv("QIYU_GATEWAY_PORT", "18765"))
GATEWAY_HOST = "127.0.0.1"
QR_POLL_INTERVAL = 2.0


def _wechaty_dir() -> Path:
    """定位 wechaty 网关目录：环境变量 > exe 同目录 > 项目根目录"""
    env_dir = os.getenv("QIYU_WECHATY_DIR", "")
    if env_dir:
        return Path(env_dir)
    if hasattr(sys, "_MEIPASS"):
        exe_dir = Path(sys.executable).resolve().parent if sys.executable else Path.cwd()
        for cand in (exe_dir / "wechaty", Path.home() / ".ai_companion" / "wechaty"):
            if (cand / "gateway.js").exists():
                return cand
    return Path(__file__).resolve().parent.parent / "wechaty"


def _node_available() -> bool:
    try:
        r = subprocess.run(["node", "--version"], capture_output=True, timeout=8, text=True)
        return r.returncode == 0
    except Exception:
        return False


class WechatyChannel(BaseChannel):
    """Wechaty 单账号接管：登录一个微信号，替换原 itchat 通道"""

    kind = "wechat"
    mode = "wechaty"
    icon = "wechat"

    def __init__(self, callback_url: str = ""):
        self.id = "wechaty"
        self.name = "微信 · Wechaty 接管"
        self.available = False
        self.integrated = True
        self.running = False
        self.qr_status = "idle"
        self.qr_data = ""
        self.qr_message = ""
        self.config = {
            "puppet": "wechaty-puppet-wechat4u",
            "token": "",
            "character_id": "",
            "single_conversation": True,
            "merge_user_id": "web_user",
        }
        self.config_schema = [
            {"key": "puppet", "label": "登录方案", "type": "select",
             "options": ["wechaty-puppet-wechat4u", "wechaty-puppet-service"],
             "hint": "wechat4u=本地免费 web 协议（扫码）；service=需 puppet token（padlocal 等稳定方案）"},
            {"key": "token", "label": "Puppet Service Token", "type": "password",
             "placeholder": "WECHATY_PUPPET_SERVICE_TOKEN",
             "hint": "选 service 方案时必填；wechat4u 方案留空"},
            {"key": "character_id", "label": "绑定角色（透传）", "type": "select",
             "options_source": "characters",
             "hint": "该微信号发来的消息走这个角色；留空使用默认角色"},
            {"key": "single_conversation", "label": "单一对话（并入 App 主对话）", "type": "checkbox",
             "hint": "默认开启：微信只是另一个前端，消息并入 App 同一个对话线程；关闭后每个微信联系人独立会话。"},
            {"key": "merge_user_id", "label": "并入的对话 ID", "type": "text",
             "placeholder": "web_user",
             "hint": "单一对话模式并入哪个栖语对话；默认 web_user（App 主对话）。"},
        ]
        self._handler = None
        self._callback_url = callback_url
        self._secret = "".join(random.choices(string.ascii_letters + string.digits, k=24))
        self._proc: subprocess.Popen | None = None
        self._poll_thread: threading.Thread | None = None
        self._stop_ev = threading.Event()
        self._gateway_ready = False
        self._restoring_login = False
        self._merged_remote: dict = {}
        try:
            from . import store
            saved = store.load_config(self.id)
            if saved:
                for k in list(self.config):
                    if k in saved:
                        if k == "single_conversation":
                            self.config[k] = str(saved[k]).strip().lower() in ("1", "true", "yes", "on")
                        else:
                            self.config[k] = saved[k]
        except Exception:
            pass
        self._check_deps()

    # ---------- 依赖检测 ----------
    def _check_deps(self):
        wd = _wechaty_dir()
        node_ok = _node_available()
        wechaty_ok = (wd / "node_modules" / "wechaty").exists()
        if not node_ok:
            self.available = False
            self.qr_message = "未检测到 Node.js 运行时（Wechaty 网关需要 node）"
        elif not wechaty_ok:
            self.available = False
            self.qr_message = f"Wechaty 依赖未安装：请运行 {wd / 'install.bat'}（npm install）"
        else:
            self.available = True
            self.qr_message = "Wechaty 网关就绪，点「启动」扫码登录"

    def save_config(self, cfg: dict):
        if not isinstance(cfg, dict):
            return
        for k, v in cfg.items():
            if k == "single_conversation":
                self.config[k] = str(v).strip().lower() in ("1", "true", "yes", "on")
            elif k in self.config:
                self.config[k] = v
        try:
            from . import store
            store.save_config(self.id, self.config)
        except Exception:
            pass
        self._check_deps()

    def set_message_handler(self, handler):
        self._handler = handler

    # ---------- HTTP 桥接 ----------
    def _gw(self, path: str, method: str = "GET", payload: dict | None = None, timeout: float = 12) -> dict:
        url = f"http://{GATEWAY_HOST}:{GATEWAY_PORT}{path}"
        try:
            if method == "GET":
                r = requests.get(url, timeout=timeout)
            else:
                r = requests.post(url, json=payload or {}, timeout=timeout)
            if r.status_code != 200:
                return {"ok": False, "message": f"gateway http {r.status_code}"}
            return r.json()
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def _normalize_qr(self, qr_str: str) -> str:
        """把 wechaty 的 qrcode 字符串（URL）转成可显示的二维码 data URL"""
        qr_str = (qr_str or "").strip()
        if not qr_str:
            return ""
        if qr_str.startswith("data:image"):
            return qr_str
        try:
            import qrcode as qr_lib
            q = qr_lib.QRCode(box_size=8, border=2)
            q.add_data(qr_str)
            q.make(fit=True)
            img = q.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception as e:
            logger.warning(f"[Wechaty] 本地生成二维码失败: {e}")
            return ""

    # ---------- 生命周期 ----------
    def start(self, **kwargs) -> bool:
        if self.running:
            return True
        if not self.available:
            self.qr_status = "error"
            return False
        # 已有网关进程存活（扫码等待中/登录失败后仍在轮询）：复用，不重复 spawn（避免 EADDRINUSE）
        if self._proc and self._proc.poll() is None:
            rst = self._gw("/start", method="POST", timeout=30)
            if rst.get("ok"):
                self.qr_status = "waiting"
                self.qr_message = "已启动，等待扫码（Wechaty）"
                if not self._poll_thread or not self._poll_thread.is_alive():
                    self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="wechaty_poll")
                    self._poll_thread.start()
                return True
            self._cleanup()
        wd = _wechaty_dir()
        if not (wd / "gateway.js").exists():
            self.qr_status = "error"
            self.qr_message = f"未找到网关脚本: {wd / 'gateway.js'}"
            return False
        # 清理端口占用：18765 若被其它残留网关占用，先 /stop，再杀进程
        self._ensure_gateway_port_free()
        try:
            env = os.environ.copy()
            env["QIYU_GATEWAY_PORT"] = str(GATEWAY_PORT)
            env["QIYU_CALLBACK_URL"] = self._callback_url
            env["QIYU_CALLBACK_SECRET"] = self._secret
            env["WECHATY_PUPPET"] = self.config.get("puppet") or "wechaty-puppet-wechat4u"
            if env["WECHATY_PUPPET"] == "wechaty-puppet-service":
                env["WECHATY_PUPPET_SERVICE_TOKEN"] = self.config.get("token") or ""
            self._proc = subprocess.Popen(
                ["node", "gateway.js"],
                cwd=str(wd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as e:
            self.qr_status = "error"
            self.qr_message = f"启动网关失败: {e}"
            logger.error(f"[Wechaty] 启动网关失败: {e}")
            return False
        # 等网关就绪
        self._stop_ev = threading.Event()
        for _ in range(30):
            if self._stop_ev.is_set():
                break
            st = self._gw("/ping", timeout=2)
            if st.get("ok"):
                self._gateway_ready = True
                break
            time.sleep(0.4)
        if not self._gateway_ready:
            self._cleanup()
            self.qr_status = "error"
            self.qr_message = "Wechaty 网关启动超时（检查 node 与依赖）"
            return False
        # 触发登录
        rst = self._gw("/start", method="POST", timeout=30)
        if not rst.get("ok"):
            self._cleanup()
            self.qr_status = "error"
            self.qr_message = rst.get("message", "登录启动失败")
            return False
        self.qr_status = "waiting"
        self.qr_message = "已启动，等待扫码（Wechaty）"
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True, name="wechaty_poll")
        self._poll_thread.start()
        # 后台读网关日志，避免管道写满卡死
        threading.Thread(target=self._drain_logs, daemon=True, name="wechaty_logs").start()
        return True

    def _ensure_gateway_port_free(self):
        """18765 被残留网关占用时：先 POST /stop 优雅退出，失败则按命令行特征杀掉 node 进程"""
        try:
            ping = self._gw("/ping", timeout=2)
            if ping.get("ok"):
                try:
                    self._gw("/stop", method="POST", timeout=5)
                except Exception:
                    pass
                time.sleep(1.0)
                return
        except Exception:
            pass
        try:
            import psutil  # 仅用于按 PID 杀进程（psutil 已随项目依赖）
            for conn in psutil.net_connections(kind="tcp"):
                if conn.laddr and conn.laddr.port == GATEWAY_PORT and conn.status == "LISTEN":
                    pid = conn.pid
                    if not pid:
                        continue
                    try:
                        proc = psutil.Process(pid)
                        cmdline = " ".join(proc.cmdline() or [])
                        if "gateway.js" in cmdline or "wechaty" in cmdline:
                            logger.warning(f"[Wechaty] 清理残留网关进程 pid={pid}")
                            proc.terminate()
                            try:
                                proc.wait(timeout=3)
                            except Exception:
                                proc.kill()
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[Wechaty] 端口清理失败（跳过）: {e}")

    def _drain_logs(self):
        try:
            if self._proc and self._proc.stdout:
                for line in iter(self._proc.stdout.readline, b""):
                    if not line:
                        break
                    logger.debug(f"[Wechaty] {line.decode('utf-8', 'ignore').strip()}")
        except Exception:
            pass

    def _poll_loop(self):
        while not self._stop_ev.is_set():
            try:
                st = self._gw("/status", timeout=5)
                if st.get("ok"):
                    gs = st.get("state", "idle")
                    self.qr_status = "running" if gs == "loggedin" else ("waiting" if gs in ("waiting", "scanned") else (gs or "idle"))
                    if gs == "scanned":
                        self.qr_message = "已扫码，请在手机上确认登录"
                    elif gs == "loggedin":
                        self.running = True
                        self.qr_message = f"登录成功（{st.get('user', '')}），正在监听消息"
                    elif gs == "error":
                        msg = st.get("message", "Wechaty 错误")
                        if "1 == 0" in msg or "Ret" in msg:
                            self.qr_message = "微信网页协议登录被拒绝（该账号可能被限制网页登录），请在设置里切换到 service 方案并填入 Puppet Service Token"
                        else:
                            self.qr_message = msg
                    elif gs == "logout":
                        self.running = False
                        self.qr_message = st.get("message", "已退出登录")
                    elif gs == "waiting":
                        self.qr_data = self._normalize_qr(st.get("qr", ""))
                        self.qr_message = st.get("message", "请用微信扫码登录（Wechaty）")
                    if self._proc and self._proc.poll() is not None and not self._stop_ev.is_set():
                        self.running = False
                        self.qr_status = "error"
                        self.qr_message = "Wechaty 网关进程已退出"
                        break
            except Exception as e:
                logger.warning(f"[Wechaty] 状态轮询异常: {e}")
            time.sleep(QR_POLL_INTERVAL)

    def stop(self):
        self._stop_ev.set()
        try:
            self._gw("/stop", method="POST", timeout=5)
        except Exception:
            pass
        self._cleanup()
        self.running = False
        self.qr_status = "idle"
        self.qr_data = ""
        self.qr_message = ""

    def _cleanup(self):
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None
        if self._poll_thread:
            try:
                self._poll_thread.join(timeout=2)
            except Exception:
                pass
            self._poll_thread = None
        self._gateway_ready = False

    # ---------- 发送 ----------
    def send(self, user_id: str, text: str) -> bool:
        if not self.running:
            return False
        remote = self.resolve_remote(user_id)
        if not remote:
            return False
        rst = self._gw("/send", method="POST", payload={"to": remote, "text": text})
        return bool(rst.get("ok"))

    def resolve_remote(self, user_id: str) -> str:
        """栖语内部 user_id → 微信联系人 id：
        - wx_wechaty__<对方id> → 对方 id
        - 单一对话合并后的 user_id（如 web_user） → 最近在该对话发过消息的微信联系人
        """
        if not user_id:
            return ""
        if user_id.startswith("wx_"):
            body = user_id[3:]
            _, _, remote = body.partition("__")
            if remote:
                return remote
        return str(self._merged_remote.get(user_id) or "")

    # ---------- 入站（webhook 由 demo.py 调用，async） ----------
    async def handle_webhook(self, payload: dict) -> bool:
        """网关回调：校验密钥 → 构造栖语 user_id → 交给统一 handler（async 桥接主 loop）"""
        if not isinstance(payload, dict):
            return False
        ptype = payload.get("type")
        if ptype == "login":
            self.running = True
            self.qr_status = "running"
            self.qr_message = "登录成功，正在监听消息"
            return True
        if ptype != "message":
            return True
        remote = (payload.get("from") or "").strip()
        text = (payload.get("text") or "").strip()
        image = (payload.get("image") or "").strip()
        if not remote:
            return False
        merge = bool(self.config.get("single_conversation", True))
        if merge:
            user_id = str(self.config.get("merge_user_id") or "web_user").strip() or "web_user"
            self._merged_remote[user_id] = remote
        else:
            user_id = f"wx_{self.id}__{remote}"
        images = [image] if image else []
        content = text
        if not content and images:
            content = "[图片]"
        logger.info(f"[Wechaty] 收到消息 [{remote}]: {content[:40]} 图片数={len(images)}")
        if self._handler:
            try:
                if asyncio.iscoroutinefunction(self._handler):
                    reply = await self._handler(user_id, content, self, images)
                else:
                    reply = self._handler(user_id, content, self, images)
                if reply:
                    await asyncio.to_thread(self._send_reply, remote, reply)
                return True
            except Exception as e:
                logger.error(f"[Wechaty] 处理消息失败: {e}")
                return False
        return False

    def _send_reply(self, remote: str, reply):
        """把回复（str 或 (text, pieces)）按真人节奏逐条发送，支持图片"""
        ctx = ""
        if isinstance(reply, tuple):
            reply_text, pieces = reply
            items = pieces or []
        else:
            items = [{"text": reply, "delay": 0}] if reply else []
        for i, p in enumerate(items):
            txt = (p.get("text") or "").strip()
            img = str(p.get("image") or p.get("image_url") or "").strip()
            if not txt and not img:
                continue
            try:
                if img and img.startswith(("http://", "https://", "data:image", "iVBOR", "/9j/")):
                    self._gw("/send", method="POST", payload={"to": remote, "image": img, "fileName": p.get("image_name", "")})
                if txt:
                    self._gw("/send", method="POST", payload={"to": remote, "text": txt})
            except Exception as e:
                logger.error(f"[Wechaty] 发送失败: {e}")
                return
            delay = (p.get("delay") or 0) / 1000.0
            if i < len(items) - 1 and delay > 0:
                time.sleep(min(delay, 3.0))

    def status(self) -> dict:
        d = super().status()
        d["name"] = self.name
        return d
