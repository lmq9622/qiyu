"""
栖语 (Qiyu) - gewechat 微信机器人接入
通过适配网关与 Letta Agent 交互
"""

import os
import time
import json
import threading
from typing import Optional

import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")
GATEWAY_API_KEY = os.getenv("GATEWAY_API_KEY", "")
WECHAT_BOT_NAME = os.getenv("WECHAT_BOT_NAME", "栖语")

# gewechat 相关导入（需要安装 gewechat 包）
# gewechat 是一个 Python 微信机器人框架
try:
    from gewechat import GewechatClient
    GEWECHAT_AVAILABLE = True
except ImportError:
    GEWECHAT_AVAILABLE = False
    logger.warning("gewechat 未安装，微信功能不可用")


class WechatBot:
    """微信机器人"""
    
    def __init__(self):
        self.gateway_url = GATEWAY_URL.rstrip("/")
        self.api_key = GATEWAY_API_KEY
        self.bot_name = WECHAT_BOT_NAME
        self.enabled = os.getenv("WECHAT_ENABLED", "false").lower() == "true"
        
        # 会话映射: wxid -> user_id
        self._sessions: dict[str, str] = {}
    
    def _call_gateway(self, user_id: str, message: str) -> str:
        """调用适配网关"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        
        payload = {
            "model": "qwen3.6-35b",
            "messages": [
                {"role": "user", "content": message}
            ],
            "stream": False,
            "user": user_id,
        }
        
        try:
            resp = requests.post(
                f"{self.gateway_url}/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            return "（服务器返回异常）"
        except requests.exceptions.ConnectionError:
            logger.error("连接适配网关失败，请确认网关已启动")
            return "（连接失败，请检查服务状态）"
        except Exception as e:
            logger.error(f"调用网关失败: {e}")
            return f"（出错了: {str(e)[:50]}）"
    
    def _get_user_id(self, wxid: str) -> str:
        """获取或创建用户 ID"""
        if wxid not in self._sessions:
            self._sessions[wxid] = f"wechat_{wxid}"
        return self._sessions[wxid]
    
    def handle_message(self, msg_data: dict) -> str:
        """
        处理微信消息
        
        msg_data 格式（gewechat）:
        {
            "wxid": "发送者ID",
            "content": "消息内容",
            "is_group": false,
            ...
        }
        """
        wxid = msg_data.get("wxid", "")
        content = msg_data.get("content", "").strip()
        is_group = msg_data.get("is_group", False)
        
        if not content:
            return ""
        
        # 群聊中需要 @ 机器人才回复
        if is_group:
            if self.bot_name not in content and "@" not in content:
                return ""
            # 移除 @ 机器人的内容
            content = content.replace(f"@{self.bot_name}", "").replace(self.bot_name, "").strip()
        
        logger.info(f"收到消息 [{wxid}]: {content[:50]}...")
        
        user_id = self._get_user_id(wxid)
        reply = self._call_gateway(user_id, content)
        
        logger.info(f"回复 [{wxid}]: {reply[:50]}...")
        return reply
    
    def start(self):
        """启动微信机器人"""
        if not self.enabled:
            logger.info("微信机器人未启用（设置 WECHAT_ENABLED=true 开启）")
            return
        
        if not GEWECHAT_AVAILABLE:
            logger.error("gewechat 未安装，无法启动微信机器人")
            logger.info("请安装: pip install gewechat")
            return
        
        logger.info("启动微信机器人...")
        logger.info(f"适配网关: {self.gateway_url}")
        
        # gewechat 的具体启动方式取决于其实际 API
        # 以下为示例框架，需根据 gewechat 实际版本调整
        try:
            # 假设 gewechat 的用法
            client = GewechatClient()
            
            @client.on_message
            def on_msg(msg):
                reply = self.handle_message(msg)
                if reply:
                    client.send_text(msg["wxid"], reply)
            
            client.run()
        except Exception as e:
            logger.error(f"启动微信机器人失败: {e}")
            raise


def start_bot():
    """入口函数"""
    bot = WechatBot()
    bot.start()


if __name__ == "__main__":
    start_bot()
