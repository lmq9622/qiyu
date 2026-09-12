"""栖语 (Qiyu) · Linux 服务器分支 —— 用户池（User Pool）

职责：
- 服务端账号池：注册 / 登录 / Token 会话 / 管理（管理员批量开户、停用、重置密码）
- 每个池内用户映射一个稳定 user_key（u_xxx），全项目按 user_key 隔离：
  对话历史、记忆库、关系值、情绪状态全部落在这台服务器的 data/ 目录
- 只依赖 Python 标准库（sqlite3 / hashlib / secrets），不引入新第三方包

数据文件：<QIYU_DATA_DIR 或 项目根>/data/server/userpool.db
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from pathutil import get_data_dir

# ---------- 常量 ----------
PBKDF2_ITER = 200_000          # 密码哈希迭代次数
TOKEN_TTL = 60 * 60 * 24 * 30  # 会话 Token 有效期：30 天
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\u4e00-\u9fa5]{2,24}$")


def _db_path() -> Path:
    d = get_data_dir() / "server"
    d.mkdir(parents=True, exist_ok=True)
    return d / "userpool.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nickname      TEXT NOT NULL DEFAULT '',
    user_key      TEXT NOT NULL UNIQUE,
    char_id       TEXT NOT NULL DEFAULT '',
    role          TEXT NOT NULL DEFAULT 'user',   -- user | admin
    status        TEXT NOT NULL DEFAULT 'active', -- active | disabled
    created_at    REAL NOT NULL,
    last_login_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """pbkdf2-hmac-sha256 加盐哈希，格式 pbkdf2$iter$salt_hex$hash_hex"""
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER)
    return f"pbkdf2${PBKDF2_ITER}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, it, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(it))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def _new_user_key() -> str:
    """池内用户的稳定标识（跨角色隔离键），形如 u_9f3a2b1c"""
    return "u_" + secrets.token_hex(4)


class UserPool:
    """线程安全的用户池（每个进程一个实例，内部按操作加锁）。"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else _db_path()
        self._lock = threading.Lock()
        self._init_db()

    # ---------- 基础 ----------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _row_to_user(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d.pop("password_hash", None)
        return d

    # ---------- 账号 ----------

    def register(self, username: str, password: str, nickname: str = "",
                 role: str = "user", invite_code: Optional[str] = None) -> dict:
        """注册账号。池为空时第一个账号自动成为管理员。

        invite_code：
        - None      → 跳过校验（管理员后台开户等内部路径）
        - 非空字符串 → 必须与 QIYU_INVITE_CODE（默认 lmq9622）一致，否则报错
        - 环境变量 QIYU_INVITE_CODE 设为空串 → 全站免邀请码
        """
        username = (username or "").strip()
        if not _USERNAME_RE.match(username):
            raise ValueError("用户名需为 2~24 位字母/数字/下划线/中文")
        if not password or len(password) < 4:
            raise ValueError("密码至少 4 位")
        if invite_code is not None:
            expected = os.getenv("QIYU_INVITE_CODE", "lmq9622").strip()
            if expected and (invite_code or "").strip() != expected:
                raise ValueError("邀请码不正确，请向管理员确认后重试")
        with self._lock, self._connect() as conn:
            if conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                raise ValueError("用户名已被占用")
            count = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            if count == 0:
                role = "admin"  # 首个账号 = 管理员
            cur = conn.execute(
                "INSERT INTO users(username,password_hash,nickname,user_key,role,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (username, _hash_password(password), (nickname or "").strip(),
                 _new_user_key(), role, time.time()),
            )
            row = conn.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
            return self._row_to_user(row)

    def login(self, username: str, password: str) -> dict:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username=?", (username.strip(),)
            ).fetchone()
            if not row or not _verify_password(password, row["password_hash"]):
                raise ValueError("用户名或密码错误")
            if row["status"] != "active":
                raise ValueError("账号已被停用，请联系管理员")
            conn.execute("UPDATE users SET last_login_at=? WHERE id=?",
                         (time.time(), row["id"]))
            return self._row_to_user(row)

    def get_by_username(self, username: str) -> Optional[dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?",
                               (username.strip(),)).fetchone()
        return self._row_to_user(row) if row else None

    def get(self, user_id: int) -> Optional[dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._row_to_user(row) if row else None

    def get_by_key(self, user_key: str) -> Optional[dict]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_key=?",
                               (user_key,)).fetchone()
        return self._row_to_user(row) if row else None

    def list_users(self) -> list[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [self._row_to_user(r) for r in rows]

    def set_role(self, user_id: int, role: str) -> None:
        if role not in ("user", "admin"):
            raise ValueError("role 只能是 user 或 admin")
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))

    def set_status(self, user_id: int, status: str) -> None:
        if status not in ("active", "disabled"):
            raise ValueError("status 只能是 active 或 disabled")
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE users SET status=? WHERE id=?", (status, user_id))

    def set_char(self, user_id: int, char_id: str) -> None:
        """记住该用户在池内当前选择的角色（换设备登录也保持）。"""
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE users SET char_id=? WHERE id=?", (char_id or "", user_id))

    def set_password(self, user_id: int, password: str) -> None:
        if not password or len(password) < 4:
            raise ValueError("密码至少 4 位")
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                         (_hash_password(password), user_id))

    def delete_user(self, user_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM users WHERE id=?", (user_id,))

    # ---------- 会话（Token） ----------

    def create_token(self, user_id: int, ttl: int = TOKEN_TTL) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            conn.execute("INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                         (token, user_id, now, now + ttl))
        return token

    def user_id_by_token(self, token: str) -> Optional[int]:
        if not token:
            return None
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM sessions WHERE token=? AND expires_at>?",
                (token, time.time()),
            ).fetchone()
        return row["user_id"] if row else None

    def revoke_token(self, token: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))

    def revoke_all(self, user_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))

    # ---------- 超管播种 ----------

    def seed_admins(self, spec: Optional[str] = None) -> list:
        """播种超管账号：spec 形如 'user:pass;user2:pass2'，缺省读 QIYU_ADMIN_ACCOUNTS（默认 lmq:lmq081015）。

        账号不存在 → 直接以 admin 创建；已存在 → 只保证 role=admin、status=active，不改密码。
        返回本次新创建的账号列表（供上层日志）。
        """
        spec = (spec or os.getenv("QIYU_ADMIN_ACCOUNTS", "lmq:lmq081015") or "").strip()
        if not spec:
            return []
        created: list = []
        for part in re.split(r"[;；,，]", spec):
            part = part.strip()
            if not part or ":" not in part:
                continue
            username, _, password = part.partition(":")
            username, password = username.strip(), password.strip()
            if not username or not password:
                continue
            existing = self.get_by_username(username)
            if not existing:
                try:
                    created.append(self.register(username, password, role="admin"))
                except ValueError as e:
                    print(f"[用户池] 超管播种失败 {username}: {e}")
            else:
                if existing["role"] != "admin":
                    self.set_role(existing["id"], "admin")
                if existing["status"] != "active":
                    self.set_status(existing["id"], "active")
        return created

    # ---------- 统计 ----------

    def stats(self) -> dict:
        with self._lock, self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
            active = conn.execute(
                "SELECT COUNT(*) c FROM users WHERE status='active'"
            ).fetchone()["c"]
            sessions = conn.execute(
                "SELECT COUNT(*) c FROM sessions WHERE expires_at>?", (time.time(),)
            ).fetchone()["c"]
        return {"total_users": total, "active_users": active,
                "online_sessions": sessions, "db_file": str(self.db_path)}


# 进程级单例
_pool: Optional[UserPool] = None
_pool_lock = threading.Lock()


def get_user_pool() -> UserPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = UserPool()
    return _pool


__all__ = [
    "UserPool", "get_user_pool", "TOKEN_TTL",
]
