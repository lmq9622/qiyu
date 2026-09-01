# 栖语 (Qiyu) - 本地 AI 陪伴机器人

## 架构

```
Open WebUI (UI层，可选)  <--OpenAI API-->  适配网关  <--Letta API-->  Letta Agent
                                              |
                                     llama.cpp (LLM推理)
                                     bge-small-zh (Embedding)
                                     内置 numpy 记忆/RAG (Qdrant 可选)
```

## 快速开始（无需 Docker）

### 1. 安装依赖

```bash
# Python 3.10+
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填写你的 LLM 地址和模型名（可随时切换任意 OpenAI 兼容后端）
```

### 3. 启动服务

**前置要求：PostgreSQL**（Letta 数据库，端口 5432）
- 本机已运行 PostgreSQL 则直接使用；否则请手动启动，并在 `.env` 中配置 `LETTA_PG_URI`。

```bash
# 终端1: Letta Server
letta server

# 终端2: 适配网关
python gateway/main.py

# 终端3 (可选): Open WebUI
pip install open-webui
open-webui serve
# 在设置中把 API 指向 http://localhost:8000/v1

# 或者直接运行桌面客户端（自动拉起后端，端口 8765）
python client.py
```

Qdrant 为可选组件：内置 RAG 使用 numpy 记忆实现，不依赖 Qdrant。
如需启用，请手动下载并启动 Qdrant 本地二进制（`qdrant`，端口 6333）。

### 4. 初始化 Letta Agent

```bash
python agent/init_agent.py
```

### 5. 访问 UI

- 桌面客户端: `python client.py`（或打包后的 `dist/Qiyu.exe`）
- Open WebUI: http://localhost:8080
- 网关 API: http://localhost:8000/v1

## 目录结构

| 目录 | 说明 |
|------|------|
| `gateway/` | OpenAI 兼容适配网关 |
| `agent/` | Letta Agent 配置和初始化 |
| `embedding/` | 本地 Embedding 服务 |
| `rag/` | RAG 文档索引与监控 |
| `wechat/` | 微信机器人 |
| `characters/` | 角色卡配置 |
| `data/` | 数据存储（记忆、SQLite、上传文件） |
| `installer/` | 安装诊断脚本 |

## 角色配置

编辑 `characters/default.json` 自定义机器人人格。

## RAG 自动写入

将文档放入 `data/uploads/` 目录，系统会自动解析、分块、Embedding 并写入内置记忆库（Qdrant 可选）。

## 许可证

MIT
