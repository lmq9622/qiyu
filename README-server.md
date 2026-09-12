# 栖语 (Qiyu) · Linux 服务器分支（linux-server 分支）

> 基于 0.1.0 产品主线。桌面版（Windows exe）保持不变；本分支面向 **Linux 服务器部署 + 网站（手机竖屏 UI）访问 + 用户池 + 对话数据全部服务端存储**。

## 架构差异（相对桌面发行版）

| 项 | 桌面版（发行版） | Linux 服务器分支 |
|---|---|---|
| 入口 | `client.py` / `demo.py` | `server_entry.py`（复用 demo 完整后端） |
| 根路径 `/` | 桌面风 Web UI | **竖屏移动端 UI**（`server/mobile/index.html`） |
| 桌面管理台 | `/` | 保留在 `/desktop`（`/app2` 管理台不变） |
| 用户 | 单用户 `web_user` | **用户池**：注册/登录/Token，每账号独立 `user_key` |
| 对话数据 | 本机 `data/`（按 user_id 隔离） | 同机制，全部落在服务器 `data/`（默认 `/var/lib/qiyu/data`），按池内账号隔离 |
| 部署 | PyInstaller exe | venv + systemd / Docker |

## 用户池（/v1/pool/*）

- `POST /v1/pool/register` 注册（**强制邀请码**，默认 `lmq9622`，可用 `QIYU_INVITE_CODE` 覆盖）
- `POST /v1/pool/login` 登录 → Token（30 天，网页端写入 Cookie `qiyu_token`）
- `GET  /v1/pool/me` 当前账号 + 池统计
- `POST /v1/pool/logout` 注销
- `POST /v1/pool/char/select` 记住该账号当前角色（换设备登录保持）
- 管理员：`GET/POST /v1/pool/users`（开户）、`POST /v1/pool/users/{id}/status`（启停）、`POST /v1/pool/users/{id}/password`（改密）、`DELETE /v1/pool/users/{id}`、`GET /v1/pool/stats`
- 超管账号：启动时按 `QIYU_ADMIN_ACCOUNTS`（`user:pass`，多个用 `|` 分隔）**自动播种**，默认 `lmq:lmq081015`
- 微信通道：`GET /v1/pool/wechat/status` / `POST .../start`（body `{force}`）/ `GET .../qr` / `POST .../unbind`，每账号独立，服务端重启自动恢复

鉴权方式：请求头 `Authorization: Bearer <token>`（或 `X-Qiyu-Token`）。
池内账号与既有 API 的 `user_id` 参数打通：聊天请求的 `user` 字段 = 账号 `user_key`，
对话历史/记忆/关系值/情绪全部按 `user_key` 隔离落盘（`data/chat_history/`、`data/memory/` 等）。

## 快速部署

```bash
# 1) 把代码放到服务器（git clone 本仓库 linux-server 分支）
git clone <仓库地址> qiyu && cd qiyu
git checkout linux-server

# 2) 一键安装（venv + 依赖 + systemd 服务 + 自启动）
bash deploy/install.sh

# 3) 手机/浏览器访问
#    http://<服务器IP>:8765/          竖屏 UI（注册/登录/聊天）
#    http://<服务器IP>:8765/desktop   桌面管理台（角色工坊/设置/模型管理）
```

### Docker 方式

```bash
docker build -t qiyu -f deploy/Dockerfile .
docker run -d --name qiyu --restart unless-stopped -p 9622:8765 -v qiyu_data:/data qiyu
```

## 常用环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `QIYU_HOST` | `0.0.0.0` | 监听地址 |
| `QIYU_PORT` | `8765` | 端口 |
| `QIYU_DATA_DIR` | `/data`（Docker）/ `/var/lib/qiyu/data`（systemd） | 对话/记忆/用户池数据目录 |
| `QIYU_ADMIN_ACCOUNTS` | `lmq:lmq081015` | 启动自动播种的超管账号（`user:pass`，`\|` 分隔多个） |
| `QIYU_INVITE_CODE` | `lmq9622` | 注册强制邀请码 |
| `QIYU_LLM_URL` / `QIYU_LLM_MODEL` / `QIYU_LLM_API_KEY` | `https://token-plan-cn.xiaomimimo.com/v1` / `mimo-v2.5` / 内置 key | **强制**对话模型（网站设置页隐藏，不可修改） |
| `LLM_BASE_URL` / `LLM_MODEL` | 同 `QIYU_LLM_*` | 兼容旧变量名 |
| `QIYU_BRAIN_PIPELINE` | `0` | BrainPipeline 开关（0=经典确定性链路） |

## 运维

```bash
systemctl status qiyu-server      # 状态
systemctl restart qiyu-server     # 重启
journalctl -u qiyu-server -f      # 实时日志
```

- 备份：整个 `QIYU_DATA_DIR` 目录（含 `server/userpool.db` 用户池、聊天记录、记忆库）。
- 重置用户池：停服后删除 `server/userpool.db`，重启后按 `QIYU_ADMIN_ACCOUNTS` 重新播种超管。

## 冒烟测试

```bash
curl -s http://127.0.0.1:8765/health
curl -s -X POST http://127.0.0.1:8765/v1/pool/register -H 'Content-Type: application/json' -d '{"username":"admin","password":"admin1234"}'
```
