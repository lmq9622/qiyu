"""通道状态与配置持久化：data/channels/*.json"""

import json
import os
from pathlib import Path

try:
    from pathutil import get_data_dir
except Exception:
    def get_data_dir() -> Path:
        return Path(__file__).resolve().parent.parent / "data"


def _channel_dir() -> Path:
    d = get_data_dir() / "channels"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_channel_state(channel_id: str) -> dict:
    """读取通道运行时状态（ClawBot 的 bot_token / baseurl / cursor 等）"""
    p = _channel_dir() / f"state_{channel_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_channel_state(channel_id: str, data: dict):
    p = _channel_dir() / f"state_{channel_id}.json"
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        import logging
        logging.getLogger("channels").warning(f"保存通道状态失败 {channel_id}: {e}")


def load_config(channel_id: str) -> dict:
    """读取用户配置（企业微信/QQBot/飞书 表单、ClawBot 账户名等）"""
    p = _channel_dir() / f"config_{channel_id}.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(channel_id: str, cfg: dict):
    p = _channel_dir() / f"config_{channel_id}.json"
    try:
        p.write_text(json.dumps(cfg or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        import logging
        logging.getLogger("channels").warning(f"保存通道配置失败 {channel_id}: {e}")
