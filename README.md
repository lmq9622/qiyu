# 栖语 (Qiyu) - 本地 AI 陪伴机器人

## 当前 Runtime 架构（P0/P1，区别于下方旧 Letta 架构）

```text
MessageGateway（Web / 微信 / pending / 主动）
→ BrainPipeline（MiniMind-O 永远第一入口）
→ BrainDecision（内部控制：direct/main/tool/vision）
→ Direct | MainBrain | ToolAgent | Vision
→ Emotion/State → TTS/Avatar（待 P2）
```

状态：
- P0：BrainDecision/BrainPipeline/MessageGateway 已真实跑通；
- P1：ToolAgent 真执行、pending 合并、主动/Storycheck 入口代码已统一，E2E 仍在补测；
- MiniMind v4.1 标签化 LoRA（当前推荐 D4）已能经 `QIYU_REALTIME_MODEL_DIR` +
  `QIYU_REALTIME_ADAPTER` 真实挂载；D4 已无重复/空回类坏例，简单直答与 RAG 均优于 tag-D，
  详见 `PROJECT_LOG.md M14/M15`。
- 2026-09-06：不再沿用旧 D 系 LoRA，按官方 minimind-o 链路（T2A→A2A→I2T）在
  x99（192.168.2.6，2×V100）从头训练，先得官方等价基线再做人设定制；当前运行
  mini 冒烟/7 阶段 full 中，进度见 `PROJECT_LOG.md M16`。
- 前端整机重写为 `ui2/`（液玻璃风格 x86 桌面壳），开发入口 `/app2`，
  打包入口已改为 `client.py → /app2`；本轮修改合并进 0.1.0，最终打包待
  新官方权重训练完成后执行。
- 2026-09-09/10：Quest MR 角色实时行为系统落在
  `quest-mr-client/`：Protocol v1.1、Character Behavior Runtime、Reflex、
  Behavior Policy（x99 CUDA 训练）、Human Motion Capture / Motion Understanding /
  SharedAttention / InteractionState 已实现；真机验收待 Quest 连接。

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
