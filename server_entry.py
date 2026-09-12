"""栖语 (Qiyu) · Linux 服务器分支入口
=================================
与桌面版 demo.py 的区别：
1. 复用 demo.py 的完整 FastAPI 应用（角色 / 聊天 / 记忆 / RAG / 渠道全部保留）
2. 新增「用户池」API：注册 / 登录 / Token 会话 / 管理员开户管理（/v1/pool/*）
3. 根路径 / 直接服务竖屏移动端 UI（server/mobile/index.html），桌面 UI 移到 /desktop
4. 对话数据全部落在服务器 data/ 目录（按池内用户 user_key 隔离）

启动：
    python server_entry.py
    # 或
    QIYU_PORT=8765 QIYU_HOST=0.0.0.0 python server_entry.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# Linux 服务器部署：数据目录默认放 /var/lib/qiyu（可用 QIYU_DATA_DIR 覆盖）
if sys.platform.startswith("linux") and not os.getenv("QIYU_DATA_DIR"):
    os.environ.setdefault("QIYU_DATA_DIR", "/var/lib/qiyu/data")

# 复用桌面版完整后端（导入即完成 app 构建与全部路由注册）
import demo  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from loguru import logger  # noqa: E402

from server.userpool import get_user_pool  # noqa: E402

app: FastAPI = demo.app

MOBILE_DIR = _ROOT / "server" / "mobile"
DESKTOP_INDEX = _ROOT / "gateway" / "static" / "index.html"


# ============ 鉴权辅助 ============

def _extract_token(request: Request) -> str:
    """从 Authorization: Bearer xxx 或 X-Qiyu-Token 头取 Token"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.headers.get("x-qiyu-token", "").strip()


def _current_user(request: Request, required: bool = True):
    """解析当前池内用户；required=False 时匿名返回 None"""
    pool = get_user_pool()
    uid = pool.user_id_by_token(_extract_token(request))
    if uid is None:
        if required:
            raise HTTPException(401, "未登录或会话已过期")
        return None
    user = pool.get(uid)
    if not user or user["status"] != "active":
        raise HTTPException(403, "账号不存在或已被停用")
    return user


def _require_admin(request: Request) -> dict:
    user = _current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


# ============ 请求日志（池内用户可见的审计线索） ============

@app.middleware("http")
async def pool_audit_log(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/v1/pool/"):
        pool = get_user_pool()
        uid = pool.user_id_by_token(_extract_token(request))
        logger.info(f"[用户池] {request.method} {request.url.path} -> {resp.status_code}"
                    + (f" user_id={uid}" if uid else " (匿名)"))
    return resp


# ============ 用户池 API ============

class AuthBody(BaseModel):
    username: str
    password: str
    nickname: str = ""


class AdminCreateUser(BaseModel):
    username: str
    password: str
    nickname: str = ""
    role: str = "user"


class AdminSetStatus(BaseModel):
    status: str  # active | disabled


class AdminResetPassword(BaseModel):
    password: str


@app.post("/v1/pool/register")
async def pool_register(body: AuthBody):
    """注册账号（池为空时第一个账号自动成为管理员）"""
    pool = get_user_pool()
    try:
        user = pool.register(body.username, body.password, body.nickname)
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = pool.create_token(user["id"])
    return {"success": True, "token": token, "user": user,
            "first_account": user["role"] == "admin"}


@app.post("/v1/pool/login")
async def pool_login(body: AuthBody):
    """登录，返回 Token（30 天有效）"""
    pool = get_user_pool()
    try:
        user = pool.login(body.username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = pool.create_token(user["id"])
    return {"success": True, "token": token, "user": user}


@app.get("/v1/pool/me")
async def pool_me(request: Request):
    """当前登录用户 + 池统计"""
    user = _current_user(request)
    return {"success": True, "user": user, "pool": get_user_pool().stats()}


@app.post("/v1/pool/logout")
async def pool_logout(request: Request):
    get_user_pool().revoke_token(_extract_token(request))
    return {"success": True}


@app.post("/v1/pool/char/select")
async def pool_select_char(request: Request, body: dict):
    """池内用户切换当前角色（服务端记住，换设备也保持）"""
    user = _current_user(request)
    char_id = (body.get("character_id") or "").strip()
    if char_id:
        char = demo.char_mgr.get_character(char_id)
        if not char:
            raise HTTPException(404, "角色不存在")
    get_user_pool().set_char(user["id"], char_id)
    # 同步设置该 user_key 的运行时角色状态（与桌面端 /v1/characters/select 一致）
    user_key = user["user_key"]
    if char_id:
        demo.user_states[user_key] = {
            "character_id": char_id,
            "temperature": demo.char_mgr.get_character(char_id).temperature,
            "history": [],
        }
    return {"success": True, "user": get_user_pool().get(user["id"])}


@app.get("/v1/pool/users")
async def pool_list_users(request: Request):
    """管理员：列出用户池全部账号"""
    _require_admin(request)
    users = get_user_pool().list_users()
    # 附每个账号的对话条数（按 user_key 前缀匹配历史文件，失败不影响主流程）
    try:
        mem = demo.mem_mgr
        for u in users:
            key = u["user_key"]
            total = 0
            try:
                for hk in list(mem._chat_histories.keys()):
                    if hk == key or hk.startswith(key + "__"):
                        total += len(mem._chat_histories.get(hk, []))
            except Exception:
                pass
            u["message_count"] = total
    except Exception:
        for u in users:
            u["message_count"] = 0
    return {"success": True, "users": users, "pool": get_user_pool().stats()}


@app.post("/v1/pool/users")
async def pool_admin_create(request: Request, body: AdminCreateUser):
    """管理员：批量/单个开户"""
    _require_admin(request)
    pool = get_user_pool()
    try:
        user = pool.register(body.username, body.password, body.nickname, body.role)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "user": user}


@app.post("/v1/pool/users/{user_id}/status")
async def pool_admin_status(request: Request, user_id: int, body: AdminSetStatus):
    _require_admin(request)
    try:
        get_user_pool().set_status(user_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}


@app.post("/v1/pool/users/{user_id}/password")
async def pool_admin_reset_password(request: Request, user_id: int, body: AdminResetPassword):
    _require_admin(request)
    try:
        get_user_pool().set_password(user_id, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}


@app.delete("/v1/pool/users/{user_id}")
async def pool_admin_delete(request: Request, user_id: int):
    _require_admin(request)
    get_user_pool().delete_user(user_id)
    return {"success": True}


@app.get("/v1/pool/stats")
async def pool_stats(request: Request):
    """池统计（登录后可见，含在线会话数）"""
    _current_user(request, required=False)
    return {"success": True, "pool": get_user_pool().stats()}


# ============ 页面路由（竖屏 UI 优先） ============

def _remove_route(app: FastAPI, path: str) -> None:
    """移除已注册路由（服务器模式下根路径让位给竖屏 UI）"""
    app.router.routes[:] = [r for r in app.router.routes
                            if not (getattr(r, "path", None) == path)]


_remove_route(app, "/")


@app.get("/", include_in_schema=False)
async def server_root():
    """服务器模式根路径 = 竖屏移动端 UI"""
    if MOBILE_DIR.joinpath("index.html").exists():
        resp = FileResponse(str(MOBILE_DIR / "index.html"))
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
    return JSONResponse({"message": "栖语服务器已运行，竖屏 UI 缺失", "status": "running"})


@app.get("/mobile", include_in_schema=False)
async def mobile_alias():
    return RedirectResponse(url="/")


@app.get("/desktop", include_in_schema=False)
async def desktop_ui():
    """桌面版完整管理台（原根路径 UI），服务器上也保留可用"""
    if DESKTOP_INDEX.exists():
        return FileResponse(str(DESKTOP_INDEX))
    raise HTTPException(404, "桌面 UI 不存在")


@app.get("/v1/server/info", include_in_schema=False)
async def server_info(request: Request):
    """服务器分支信息页：模式 / 版本 / 用户池概况"""
    user = _current_user(request, required=False)
    from companion.version import current_version, APP_TITLE
    return {
        "success": True,
        "mode": "linux-server",
        "version": current_version(),
        "title": APP_TITLE,
        "user_pool": get_user_pool().stats(),
        "logged_in": bool(user),
    }


# ============ 启动 ============

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("QIYU_HOST", "0.0.0.0")
    port = int(os.getenv("QIYU_PORT", "8765"))
    logger.info("=" * 60)
    logger.info("栖语 · Linux 服务器分支启动")
    logger.info(f"竖屏 UI:  http://{host}:{port}/")
    logger.info(f"桌面管理台: http://{host}:{port}/desktop")
    logger.info(f"用户池 API:  http://{host}:{port}/v1/pool/*")
    logger.info("=" * 60)
    uvicorn.run("server_entry:app", host=host, port=port, reload=False, log_level="info")
