# -*- coding: utf-8 -*-
"""Qiyu 运行时状态与配置（从 demo.py 迁移，M1）。"""
import os
import sys
import json
from pathlib import Path

def get_resource_path(relative_path: str = "") -> Path:
    if hasattr(sys, '_MEIPASS'):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    if relative_path:
        return base / relative_path
    return base

def get_data_dir() -> Path:
    """可写数据目录（exe 环境用用户目录，避免写入临时解压目录）"""
    env_data = os.getenv("QIYU_DATA_DIR", "")
    if env_data:
        d = Path(env_data)
    elif hasattr(sys, "_MEIPASS"):
        d = Path(os.path.expanduser("~")) / ".ai_companion" / "data"
    else:
        d = PROJECT_DIR / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d

PROJECT_DIR = get_resource_path()

STATIC_DIR = PROJECT_DIR / "gateway" / "static"

DEMO_PORT = int(os.getenv("QIYU_PORT", "8765"))

DEMO_HOST = os.getenv("QIYU_HOST", "0.0.0.0")

LLM_URL = os.getenv("LLM_BASE_URL", "http://192.168.2.6:8081/v1")

LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6-35b-a3b-uncensored-heretic")

LLM_ROUTE_URL = os.getenv("LLM_ROUTE_URL", "")

LLM_ROUTE_MODEL = os.getenv("LLM_ROUTE_MODEL", "")

DEFAULT_AVATAR_DIR = STATIC_DIR / "avatars"

SETTINGS_JSON = get_data_dir() / "_runtime_settings.json"

AVATAR_UPLOAD_DIR = get_data_dir() / "avatars"

RELATIONS_JSON = get_data_dir() / "relations.json"

PROACTIVE_JSON = get_data_dir() / "proactive.json"

SCHEDULES_JSON = get_data_dir() / "schedules.json"

CONV_STATE_JSON = get_data_dir() / "conv_state.json"

SHARED_EVENTS_JSON = get_data_dir() / "shared_events.json"

EMOTIONS_JSON = get_data_dir() / "emotions.json"

def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

_relations_store: dict = _load_json(RELATIONS_JSON)

_proactive_store: dict = _load_json(PROACTIVE_JSON)

_schedules_store: dict = _load_json(SCHEDULES_JSON)

_conv_store: dict = _load_json(CONV_STATE_JSON)

_shared_events: dict = _load_json(SHARED_EVENTS_JSON)

_emotions_store: dict = _load_json(EMOTIONS_JSON)

_EVIDENCE_CACHE = {}

_USER_NET_CACHE = {"at": 0.0, "text": ""}

user_states: dict = {}

llm_client = None


__all__ = [
    "AVATAR_UPLOAD_DIR",
    "CONV_STATE_JSON",
    "DEFAULT_AVATAR_DIR",
    "DEMO_HOST",
    "DEMO_PORT",
    "EMOTIONS_JSON",
    "LLM_MODEL",
    "LLM_ROUTE_MODEL",
    "LLM_ROUTE_URL",
    "LLM_URL",
    "PROACTIVE_JSON",
    "PROJECT_DIR",
    "RELATIONS_JSON",
    "SCHEDULES_JSON",
    "SETTINGS_JSON",
    "SHARED_EVENTS_JSON",
    "STATIC_DIR",
    "_EVIDENCE_CACHE",
    "_USER_NET_CACHE",
    "_conv_store",
    "_emotions_store",
    "_load_json",
    "_proactive_store",
    "_relations_store",
    "_schedules_store",
    "_shared_events",
    "get_data_dir",
    "get_resource_path",
    "llm_client",
    "user_states",
]
