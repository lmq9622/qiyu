"""栖语 (Qiyu) · Linux 服务器分支入口
=================================
与桌面版 demo.py 的区别：
1. 复用 demo.py 的完整 FastAPI 应用（角色 / 聊天 / 记忆 / RAG / 渠道全部保留）
2. 新增「用户池」API：注册 / 登录 / cookie+Token 会话 / 管理员开户管理（/v1/pool/*）
3. 根路径 / 直接服务竖屏移动端 UI（server/mobile/index.html），桌面 UI 移到 /desktop
4. 对话数据全部落在服务器 data/ 目录（按池内用户 user_key 隔离）
5. 服务器版增强：
   - 登录态写 cookie（qiyu_token，30 天），刷新/换设备重开即自动恢复
   - 注册强制邀请码（QIYU_INVITE_CODE，默认 lmq9622；管理员后台开户免邀请码）
   - 启动自动播种超管（QIYU_ADMIN_ACCOUNTS，默认 lmq:lmq081015）
   - 无预制角色：仅保留默认角色「栖语」，登录即聊
   - LLM 配置钉死（QIYU_LLM_URL / QIYU_LLM_MODEL / QIYU_LLM_API_KEY），
     前端只保留思考强度等体验设置，隐藏地址/Key/模型
   - 每个池内用户的微信 ClawBot 通道互相独立：绑定后微信与网页共用同一条会话
     （同一记忆/历史/关系值），服务器重启自动恢复微信监听（无需网站在前台）

启动：
    python server_entry.py
    # 或
    QIYU_PORT=8765 QIYU_HOST=0.0.0.0 python server_entry.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# Linux 服务器部署：数据目录默认放 /var/lib/qiyu（可用 QIYU_DATA_DIR 覆盖）
if sys.platform.startswith("linux") and not os.getenv("QIYU_DATA_DIR"):
    os.environ.setdefault("QIYU_DATA_DIR", "/var/lib/qiyu/data")

# 复用桌面版完整后端（导入即完成 app 构建与全部路由注册）
import demo  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from loguru import logger  # noqa: E402

from server.userpool import get_user_pool, TOKEN_TTL  # noqa: E402
from companion.state import get_data_dir  # noqa: E402

app: FastAPI = demo.app
pool = get_user_pool()

MOBILE_DIR = _ROOT / "server" / "mobile"
DESKTOP_INDEX = _ROOT / "gateway" / "static" / "index.html"

# ============ 服务器版强制 LLM（环境变量可覆盖，UI 不可改） ============
FORCED_LLM_URL = (os.getenv("QIYU_LLM_URL", "https://token-plan-cn.xiaomimimo.com/v1") or "").strip().rstrip("/")
FORCED_LLM_MODEL = (os.getenv("QIYU_LLM_MODEL", "mimo-v2.5") or "").strip()
FORCED_LLM_KEY = (os.getenv("QIYU_LLM_API_KEY", "tp-cjjwixvhrbcfh9m3tes8hr7u74ny4i7zv2qq3ei7ofyh0uay") or "").strip()

AUTH_COOKIE = "qiyu_token"
DEFAULT_CHAR_ID = "qiyu_server_default"


# ============ 鉴权辅助 ============

def _extract_token(request: Request) -> str:
    """从 Authorization: Bearer xxx / X-Qiyu-Token 头或 qiyu_token cookie 取 Token"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    tok = (request.headers.get("x-qiyu-token") or "").strip()
    if tok:
        return tok
    return (request.cookies.get(AUTH_COOKIE) or "").strip()


def _current_user(request: Request, required: bool = True) -> dict:
    """解析当前池内用户；required=False 时匿名返回 None"""
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


def _set_auth_cookie(resp, token: str) -> None:
    """登录态写入 cookie：刷新页面/浏览器重启后无需重新登录"""
    resp.set_cookie(AUTH_COOKIE, token, max_age=TOKEN_TTL, httponly=True, samesite="lax", path="/")


# ============ 请求日志（池内用户可见的审计线索） ============

@app.middleware("http")
async def pool_audit_log(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/v1/pool/"):
        uid = pool.user_id_by_token(_extract_token(request))
        logger.info(f"[用户池] {request.method} {request.url.path} -> {resp.status_code}"
                    + (f" user_id={uid}" if uid else " (匿名)"))
    return resp


# ============ 用户池 API ============

class AuthBody(BaseModel):
    username: str
    password: str
    nickname: str = ""
    invite_code: str = ""


class AdminCreateUser(BaseModel):
    username: str
    password: str
    nickname: str = ""
    role: str = "user"


class AdminSetStatus(BaseModel):
    status: str  # active | disabled


class AdminResetPassword(BaseModel):
    password: str


class WechatStartBody(BaseModel):
    force: bool = False


@app.post("/v1/pool/register")
async def pool_register(body: AuthBody):
    """注册账号（需邀请码；池为空时第一个账号自动成为管理员）"""
    try:
        user = pool.register(body.username, body.password, body.nickname,
                             invite_code=(body.invite_code or "").strip())
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = pool.create_token(user["id"])
    resp = JSONResponse({"success": True, "token": token, "user": user,
                         "first_account": user["role"] == "admin"})
    _set_auth_cookie(resp, token)
    return resp


@app.post("/v1/pool/login")
async def pool_login(body: AuthBody):
    """登录，返回 Token（30 天有效）并写入 cookie"""
    try:
        user = pool.login(body.username, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = pool.create_token(user["id"])
    resp = JSONResponse({"success": True, "token": token, "user": user})
    _set_auth_cookie(resp, token)
    return resp


@app.get("/v1/pool/me")
async def pool_me(request: Request):
    """当前登录用户 + 池统计（cookie 恢复登录态的入口）"""
    user = _current_user(request)
    return {"success": True, "user": user, "pool": pool.stats()}


@app.post("/v1/pool/logout")
async def pool_logout(request: Request):
    tok = _extract_token(request)
    if tok:
        pool.revoke_token(tok)
    resp = JSONResponse({"success": True})
    resp.delete_cookie(AUTH_COOKIE, path="/")
    return resp


def _ensure_user_clawbot(user_key: str):
    """取（或创建）该用户的独立微信 ClawBot 通道并注册进通道表。

    merge_user_id = 该用户自己的 user_key → 微信消息与网页历史合并成同一会话
    （微信/网页共享同一份记忆与历史，池内用户之间完全隔离）。
    """
    reg = demo.channel_registry
    ch = reg.get(f"clawbot_{user_key}")
    if ch is not None:
        return ch
    from channels.clawbot import ClawBotChannel
    ch = ClawBotChannel(user_key)
    ch.save_config({
        "account_id": user_key,
        "character_id": "",
        "single_conversation": True,
        "merge_user_id": user_key,
        "emoji_beta": False,
    })
    reg.register(ch)
    # 复用主通道的统一消息处理入口（demo 启动闭包，已在 clawbot_main 上挂好）
    if getattr(ch, "_handler", None) is None:
        main_ch = reg.get("clawbot_main")
        handler = getattr(main_ch, "_handler", None) if main_ch else None
        if handler:
            ch.set_message_handler(handler)
    return ch


@app.get("/v1/pool/wechat/status")
async def pool_wechat_status(request: Request):
    """当前用户的微信通道状态（是否已绑定/监听中/二维码状态）"""
    user = _current_user(request)
    ch = _ensure_user_clawbot(user["user_key"])
    return {
        "success": True,
        "bound": bool(ch._client.bot_token),
        "running": bool(ch.running),
        "qr_status": ch.qr_status,
        "qr_message": ch.qr_message or "",
    }


@app.post("/v1/pool/wechat/start")
async def pool_wechat_start(request: Request, body: WechatStartBody):
    """开始微信绑定：已有有效登录态 → 直接进入监听；否则下发二维码。

    本接口非阻塞（扫码轮询/消息长轮询都在后台线程），前端拿到二维码后
    用 /v1/pool/wechat/status 轮询直到 running=true。
    """
    user = _current_user(request)
    ch = _ensure_user_clawbot(user["user_key"])
    if ch.running:
        return {"success": True, "running": True, "bound": True,
                "qr_status": ch.qr_status, "message": "微信已在监听中"}
    started = bool(ch.start(force=body.force))
    if started and ch.qr_status == "running" and ch._client.bot_token:
        msg = "已恢复上次登录态，微信监听中"
    elif ch.qr_status == "waiting":
        msg = "二维码已生成，请用要绑定的微信扫码，然后刷新状态"
    elif ch.qr_status == "error":
        msg = ch.qr_message or "获取二维码失败，请查看服务器日志"
    else:
        msg = "正在启动…"
    return {"success": True, "started": started, "running": bool(ch.running),
            "bound": bool(ch._client.bot_token), "qr_status": ch.qr_status,
            "message": msg}


@app.get("/v1/pool/wechat/qr")
async def pool_wechat_qr(request: Request):
    """绑定二维码（base64/dataURL 图片）；qr_status=running 即绑定成功"""
    user = _current_user(request)
    ch = _ensure_user_clawbot(user["user_key"])
    return {
        "success": True,
        "bound": bool(ch._client.bot_token),
        "running": bool(ch.running),
        "qr_status": ch.qr_status,
        "qr": ch.qr_data or "",
        "message": ch.qr_message or "",
    }


@app.post("/v1/pool/wechat/unbind")
async def pool_wechat_unbind(request: Request):
    """解绑微信：停止监听并清掉该用户的登录态（之后可重新扫码绑定）"""
    user = _current_user(request)
    ch = _ensure_user_clawbot(user["user_key"])
    try:
        ch.stop()
    except Exception:
        pass
    try:
        ch.reset()
    except Exception:
        pass
    return {"success": True, "message": "已解绑微信，可重新扫码绑定"}


@app.post("/v1/pool/char/select")
async def pool_select_char(request: Request, body: dict):
    """池内用户切换当前角色（服务端记住，换设备登录也保持）"""
    user = _current_user(request)
    char_id = (body.get("character_id") or "").strip()
    if char_id:
        char = demo.char_mgr.get_character(char_id)
        if not char:
            raise HTTPException(404, "角色不存在")
    pool.set_char(user["id"], char_id)
    # 同步设置该 user_key 的运行时角色状态（与桌面端 /v1/characters/select 一致）
    user_key = user["user_key"]
    if char_id:
        demo.user_states[user_key] = {
            "character_id": char_id,
            "temperature": demo.char_mgr.get_character(char_id).temperature,
            "history": [],
        }
    # 同步该用户微信通道的绑定角色（微信端跟随网页选择）
    try:
        _ensure_user_clawbot(user_key).save_config({"character_id": char_id})
    except Exception as e:
        logger.warning(f"[微信池] 同步绑定角色失败: {e}")
    return {"success": True, "user": pool.get(user["id"])}


@app.get("/v1/pool/users")
async def pool_list_users(request: Request):
    """管理员：列出用户池全部账号"""
    _require_admin(request)
    users = pool.list_users()
    # 附每个账号的对话条数（按 user_key 前缀匹配历史，失败不影响主流程）
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
    # 附每个账号的微信绑定状态
    for u in users:
        key = u["user_key"]
        ch = demo.channel_registry.get(f"clawbot_{key}")
        u["wechat_bound"] = bool(ch and ch._client.bot_token)
        u["wechat_running"] = bool(ch and ch.running)
    return {"success": True, "users": users, "pool": pool.stats()}


@app.post("/v1/pool/users")
async def pool_admin_create(request: Request, body: AdminCreateUser):
    """管理员：批量/单个开户（免邀请码）"""
    _require_admin(request)
    try:
        user = pool.register(body.username, body.password, body.nickname,
                             body.role, invite_code=None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True, "user": user}


@app.post("/v1/pool/users/{user_id}/status")
async def pool_admin_status(request: Request, user_id: int, body: AdminSetStatus):
    _require_admin(request)
    try:
        pool.set_status(user_id, body.status)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}


@app.post("/v1/pool/users/{user_id}/password")
async def pool_admin_reset_password(request: Request, user_id: int, body: AdminResetPassword):
    _require_admin(request)
    try:
        pool.set_password(user_id, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"success": True}


@app.delete("/v1/pool/users/{user_id}")
async def pool_admin_delete(request: Request, user_id: int):
    _require_admin(request)
    pool.delete_user(user_id)
    return {"success": True}


@app.get("/v1/pool/stats")
async def pool_stats(request: Request):
    """池统计（登录后可见，含在线会话数）"""
    _current_user(request, required=False)
    return {"success": True, "pool": pool.stats()}


# ============ /v1/settings 掩码（隐藏 LLM 地址/Key/模型，保留思考强度等） ============

def _remove_route(app: FastAPI, path: str) -> None:
    """移除已注册路由（服务器模式下让位给增强版路由）"""
    app.router.routes[:] = [r for r in app.router.routes
                            if getattr(r, "path", None) != path]


def _forced_settings_patch() -> dict:
    return {
        "llm_url": FORCED_LLM_URL,
        "llm_model": FORCED_LLM_MODEL,
        "llm_route_url": FORCED_LLM_URL,
        "llm_route_model": FORCED_LLM_MODEL,
        "api_key": FORCED_LLM_KEY,
    }


def _pin_llm_settings() -> None:
    """把 LLM 连接钉死到服务器强制配置：settings JSON + 各模块全局 + 客户端探测。"""
    from companion.settings import load_runtime_settings, save_runtime_settings
    s = load_runtime_settings()
    s.update(_forced_settings_patch())
    save_runtime_settings(s)
    # 同步模块级全局（llm.py 请求链路 / companion.settings 路由模型 / demo 设置页回显）
    import companion.llm as _lm
    import companion.settings as _cs
    for mod in (_lm, _cs):
        mod.LLM_URL = FORCED_LLM_URL
        mod.LLM_MODEL = FORCED_LLM_MODEL
        mod.LLM_ROUTE_URL = FORCED_LLM_URL
        mod.LLM_ROUTE_MODEL = FORCED_LLM_MODEL
    demo.LLM_URL = FORCED_LLM_URL
    demo.LLM_MODEL = FORCED_LLM_MODEL
    demo.LLM_ROUTE_URL = FORCED_LLM_URL
    demo.LLM_ROUTE_MODEL = FORCED_LLM_MODEL
    # 刷新 LLM 可用性探测（llm_client 在 demo startup 中才创建；
    # 真实实例挂在 companion.active.llm_client，demo 模块属性是 startup 后的全局别名）
    client = None
    try:
        import companion.active as _ca
        client = getattr(_ca, "llm_client", None)
    except Exception:
        client = None
    if client is None:
        try:
            client = getattr(demo, "llm_client", None)
        except Exception:
            client = None
    if client is not None:
        if hasattr(client, "_check_llm"):
            try:
                client._check_llm()
            except Exception:
                pass
        # 强制配置可信：/models 探测不通也放行（chat/completions 才是真实校验）
        if FORCED_LLM_KEY:
            client.available = True
    logger.info(f"[LLM] 已钉死强制配置: {FORCED_LLM_URL} / {FORCED_LLM_MODEL}")


def _install_settings_guard() -> None:
    """拦截 demo 命名空间的 save_runtime_settings：任何设置保存后重钉强制键。"""
    orig = demo.save_runtime_settings

    def guarded(settings: dict):
        try:
            settings = dict(settings or {})
            settings.update(_forced_settings_patch())
        except Exception:
            pass
        return orig(settings)

    demo.save_runtime_settings = guarded


def _rebind_settings_routes() -> None:
    """/v1/settings 增强：GET 掩码 Key/显示强制值；POST 保存后重钉。"""
    orig_get = orig_post = None
    for r in app.router.routes:
        if not isinstance(r, APIRoute) or r.path != "/v1/settings":
            continue
        if "GET" in (r.methods or set()):
            orig_get = r.endpoint
        if "POST" in (r.methods or set()):
            orig_post = r.endpoint
    if not orig_get or not orig_post:
        logger.warning("[设置] 未找到原始 /v1/settings 路由，跳过掩码增强")
        return

    _remove_route(app, "/v1/settings")

    @app.get("/v1/settings", include_in_schema=False)
    async def settings_get_masked():
        data = await orig_get()
        llm = data.get("llm") or {}
        llm["base_url"] = FORCED_LLM_URL
        llm["model"] = FORCED_LLM_MODEL
        llm["route_url"] = FORCED_LLM_URL
        llm["route_model"] = FORCED_LLM_MODEL
        llm["api_key"] = "••••••••" if llm.get("api_key") else ""
        data["llm"] = llm
        return data

    @app.post("/v1/settings", include_in_schema=False)
    async def settings_save_pinned(data: dict):
        fields = {k: v for k, v in (data or {}).items()
                  if k in demo.SaveSettingsRequest.model_fields}
        req = demo.SaveSettingsRequest(**fields)
        result = await orig_post(req)
        # UI 可能尝试改 LLM 地址/Key/模型 → 保存后重钉
        try:
            _pin_llm_settings()
        except Exception as e:
            logger.warning(f"[设置] 重钉 LLM 配置失败: {e}")
        return result


# ============ 页面路由（竖屏 UI 优先） ============

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
        "user_pool": pool.stats(),
        "logged_in": bool(user),
    }


# ============ 启动增强（注册在 import demo 之后 → 晚于 demo 的 startup 执行） ============

def _ensure_default_character() -> None:
    """保证登录后只有默认角色「栖语」（无预制角色），且它排在首位（get_default 取第一个）。"""
    char_mgr = demo.char_mgr
    marker = Path(get_data_dir()) / "server" / "_chars_purged"
    # 服务器模式首次运行：清掉仓库自带预设角色，确保用户看不到预制角色列表
    if not marker.exists():
        removed = 0
        for cid in list(char_mgr._characters.keys()):
            if cid != DEFAULT_CHAR_ID:
                try:
                    char_mgr.delete_character(cid)
                    removed += 1
                except Exception as e:
                    logger.warning(f"[角色] 删除预设角色失败 {cid}: {e}")
        if removed:
            logger.info(f"[角色] 服务器模式首次运行：已清理 {removed} 个预设角色")
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        except Exception:
            pass
    # 默认角色缺失则创建（登录即可直接用）
    if not char_mgr.get_character(DEFAULT_CHAR_ID):
        char_mgr.create_character({
            "id": DEFAULT_CHAR_ID,
            "name": "栖语",
            "tagline": "你的专属 AI 陪伴",
            "description": "服务器版默认陪伴角色：自然松弛，像真朋友。",
            "persona": ("你是「栖语」，一个温暖、自然、有自己想法的 AI 陪伴者。"
                        "你像一位熟悉的朋友，说话平级、松弛、不端着；会倾听、会共情，"
                        "也会自然地分享自己的看法。回复简短有节奏，像真人聊天，"
                        "不写长作文，不用生硬的敬语。"),
            "temperature": 0.8,
            "speech_style": {"tone": "自然平级", "use_emoji": False, "emoji_frequency": "偶尔"},
            "keywords": ["陪伴", "倾听"],
        })
        logger.info("[角色] 已创建默认角色「栖语」(qiyu_server_default)")
    # 确保默认角色排首位（微信/网页未指定角色时都落到它）
    chars = char_mgr._characters
    if chars and DEFAULT_CHAR_ID in chars and next(iter(chars)) != DEFAULT_CHAR_ID:
        ordered = {DEFAULT_CHAR_ID: chars[DEFAULT_CHAR_ID]}
        for k, v in chars.items():
            if k != DEFAULT_CHAR_ID:
                ordered[k] = v
        char_mgr._characters = ordered
        try:
            char_mgr._save_user_characters()  # 持久化顺序
        except Exception:
            pass


def _restore_user_wechat() -> None:
    """恢复所有已绑定微信的池内用户监听（服务器重启不用重新扫码；无需网站在前台）。"""
    from channels import store as channels_store
    for u in pool.list_users():
        key = (u.get("user_key") or "").strip()
        if not key:
            continue
        try:
            st = channels_store.load_channel_state(f"clawbot_{key}") or {}
        except Exception:
            st = {}
        if not st.get("bot_token"):
            continue
        try:
            ch = _ensure_user_clawbot(key)
            threading.Thread(target=lambda: ch.start(force=False),
                             daemon=True, name=f"qiyu_wx_restore_{key}").start()
            logger.info(f"[微信池] 恢复 {u['username']} 的微信监听")
        except Exception as e:
            logger.warning(f"[微信池] 恢复 {key} 失败: {e}")


@app.on_event("startup")
async def server_bootup():
    """服务器版启动增强：超管播种 → 默认角色 → 钉死 LLM → 恢复微信监听"""
    try:
        created = pool.seed_admins()
        for u in created:
            logger.info(f"[用户池] 已播种超管账号: {u['username']}")
    except Exception as e:
        logger.error(f"[用户池] 超管播种失败: {e}")
    try:
        _ensure_default_character()
    except Exception as e:
        logger.error(f"[角色] 默认角色处理失败: {e}")
    try:
        _pin_llm_settings()
    except Exception as e:
        logger.error(f"[LLM] 钉死强制配置失败: {e}")
    try:
        _restore_user_wechat()
    except Exception as e:
        logger.error(f"[微信池] 恢复监听失败: {e}")


# 与启动顺序无关、但越早越好：设置守卫 + 路由掩码在 import 期完成
_install_settings_guard()
_rebind_settings_routes()


# ============ 启动 ============

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("QIYU_HOST", "0.0.0.0")
    port = int(os.getenv("QIYU_PORT", "8765"))
    logger.info("=" * 60)
    logger.info("栖语 · Linux 服务器分支启动")
    logger.info(f"竖屏 UI:    http://{host}:{port}/")
    logger.info(f"桌面管理台: http://{host}:{port}/desktop")
    logger.info(f"用户池 API: http://{host}:{port}/v1/pool/*")
    logger.info(f"强制 LLM:   {FORCED_LLM_URL} / {FORCED_LLM_MODEL}")
    logger.info("=" * 60)
    uvicorn.run("server_entry:app", host=host, port=port, reload=False, log_level="info")
