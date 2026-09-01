# -*- coding: utf-8 -*-
"""Qiyu Runtime · 统一数据库数据模型（规格§47）。

所有聊天记录 / 记忆 / 关系 / 情绪 / 主动聊天 / 工具记录 / 任务 拥有统一数据模型，
避免「每个模块自己存一份」：

    Conversation / Message / Memory / RelationshipState / EmotionState /
    ToolCall / ProactiveEvent

实现：stdlib sqlite3（无额外依赖，低端设备可用），数据落 `data/qiyu.db`
（exe 环境走用户数据目录）。现有 JSON 运行时存储保持不变（它们仍是热路径），
本库作为统一模型层：关键事件写入统一表，并提供查询/审计接口。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    char_id TEXT NOT NULL,
    started_at REAL,
    ended_at REAL,
    meta TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    user_id TEXT NOT NULL,
    char_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT,
    pieces TEXT DEFAULT '[]',
    images TEXT DEFAULT '[]',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    char_id TEXT,
    tier TEXT NOT NULL,              -- today / short / long
    text TEXT NOT NULL,
    weight REAL DEFAULT 0.3,
    source TEXT DEFAULT '',
    topic TEXT DEFAULT '',
    importance REAL DEFAULT 0.5,
    created_at REAL,
    entry_id TEXT
);
CREATE TABLE IF NOT EXISTS relationship_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    char_id TEXT NOT NULL,
    affinity INTEGER DEFAULT 50,
    friendship INTEGER DEFAULT 50,
    tier TEXT DEFAULT '',
    relationship TEXT DEFAULT '',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS emotion_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    char_id TEXT NOT NULL,
    emotions TEXT DEFAULT '{}',
    composite REAL DEFAULT 0,
    mood_event TEXT DEFAULT '',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    char_id TEXT,
    tool TEXT NOT NULL,
    query TEXT,
    success INTEGER DEFAULT 0,
    latency_ms REAL DEFAULT 0,
    evidence TEXT DEFAULT '{}',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS proactive_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    char_id TEXT,
    kind TEXT NOT NULL,
    text TEXT,
    topic TEXT DEFAULT '',
    decision TEXT DEFAULT '',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    char_id TEXT,
    kind TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    due_at REAL,
    done INTEGER DEFAULT 0,
    created_at REAL
);
CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id, char_id, created_at);
CREATE INDEX IF NOT EXISTS idx_mem_user ON memories(user_id, tier);
"""


class UnifiedStore:
    """统一数据模型存储（sqlite3，线程安全）。"""

    def __init__(self, path: Optional[Path] = None) -> None:
        if path is None:
            try:
                from companion.state import get_data_dir
                path = get_data_dir() / "qiyu.db"
            except Exception:
                path = Path("data") / "qiyu.db"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path), timeout=15)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._lock:
            try:
                c = self._conn()
                c.executescript(_SCHEMA)
                c.commit()
                c.close()
            except Exception as e:
                logger.warning(f"[DB] 初始化失败: {e}")

    def _exec(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            try:
                c = self._conn()
                c.execute(sql, params)
                c.commit()
                c.close()
            except Exception as e:
                logger.debug(f"[DB] 写入失败: {e}")

    def _query(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            try:
                c = self._conn()
                rows = [dict(r) for r in c.execute(sql, params).fetchall()]
                c.close()
                return rows
            except Exception:
                return []

    # ---------- 写入 ----------
    def record_conversation(self, conversation_id: str, user_id: str, char_id: str,
                            started_at: float = 0.0, meta: dict | None = None) -> None:
        self._exec(
            "INSERT INTO conversations(conversation_id,user_id,char_id,started_at,meta) VALUES(?,?,?,?,?)",
            (conversation_id, user_id, char_id, started_at or time.time(), json.dumps(meta or {}, ensure_ascii=False)))

    def record_message(self, user_id: str, char_id: str, role: str, text: str,
                       pieces: list | None = None, images: list | None = None,
                       conversation_id: str = "") -> None:
        self._exec(
            "INSERT INTO messages(conversation_id,user_id,char_id,role,text,pieces,images,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (conversation_id, user_id, char_id, role, (text or "")[:4000],
             json.dumps(pieces or [], ensure_ascii=False), json.dumps(images or [], ensure_ascii=False), time.time()))

    def record_memory(self, user_id: str, char_id: str, tier: str, text: str,
                      weight: float = 0.3, source: str = "", topic: str = "",
                      importance: float = 0.5, entry_id: str = "") -> None:
        self._exec(
            "INSERT INTO memories(user_id,char_id,tier,text,weight,source,topic,importance,created_at,entry_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (user_id, char_id or "", tier, (text or "")[:2000], float(weight or 0.3),
             source or "", topic or "", float(importance or 0.5), time.time(), entry_id or ""))

    def record_relationship(self, user_id: str, char_id: str, affinity: int, friendship: int,
                            tier: str = "", relationship: str = "") -> None:
        self._exec(
            "INSERT INTO relationship_state(user_id,char_id,affinity,friendship,tier,relationship,created_at) "
            "VALUES(?,?,?,?,?,?,?)",
            (user_id, char_id, int(affinity or 0), int(friendship or 0), tier or "", relationship or "", time.time()))

    def record_emotion(self, user_id: str, char_id: str, emotions: dict, composite: float = 0.0,
                       mood_event: str = "") -> None:
        self._exec(
            "INSERT INTO emotion_state(user_id,char_id,emotions,composite,mood_event,created_at) VALUES(?,?,?,?,?,?)",
            (user_id, char_id, json.dumps(emotions or {}, ensure_ascii=False),
             float(composite or 0), mood_event or "", time.time()))

    def record_tool_call(self, user_id: str, char_id: str, tool: str, query: str,
                         success: bool, latency_ms: float = 0.0, evidence: dict | None = None) -> None:
        self._exec(
            "INSERT INTO tool_calls(user_id,char_id,tool,query,success,latency_ms,evidence,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (user_id, char_id or "", tool, (query or "")[:500], 1 if success else 0,
             float(latency_ms or 0), json.dumps(evidence or {}, ensure_ascii=False), time.time()))

    def record_proactive(self, user_id: str, char_id: str, kind: str, text: str,
                         topic: str = "", decision: str = "") -> None:
        self._exec(
            "INSERT INTO proactive_events(user_id,char_id,kind,text,topic,decision,created_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, char_id or "", kind, (text or "")[:500], topic or "", decision or "", time.time()))

    def record_task(self, user_id: str, char_id: str, kind: str, payload: dict,
                    due_at: float = 0.0, done: bool = False) -> None:
        self._exec(
            "INSERT INTO tasks(user_id,char_id,kind,payload,due_at,done,created_at) VALUES(?,?,?,?,?,?,?)",
            (user_id, char_id or "", kind, json.dumps(payload or {}, ensure_ascii=False),
             float(due_at or 0), 1 if done else 0, time.time()))

    # ---------- 查询 ----------
    def recent_messages(self, user_id: str, char_id: str = "", limit: int = 50) -> list[dict]:
        if char_id:
            return self._query(
                "SELECT * FROM messages WHERE user_id=? AND char_id=? ORDER BY created_at DESC LIMIT ?",
                (user_id, char_id, limit))
        return self._query("SELECT * FROM messages WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit))

    def count(self, table: str) -> int:
        rows = self._query(f"SELECT COUNT(*) AS n FROM {table}")
        return int(rows[0]["n"]) if rows else 0

    def stats(self) -> dict:
        return {t: self.count(t) for t in ("conversations", "messages", "memories",
                                           "relationship_state", "emotion_state",
                                           "tool_calls", "proactive_events", "tasks")}


unified_store = UnifiedStore()

__all__ = ["UnifiedStore", "unified_store"]
