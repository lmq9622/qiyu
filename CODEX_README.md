# 栖语 (Qiyu) · AI 伴侣 - Codex 项目文档
> 生成时间: 2026-08-29
> 用途: 导入 ChatGPT Codex 开发

---

## 1. 一句话描述

本地 AI 聊天陪伴机器人桌面客户端（Windows .exe），支持自定义虚拟角色、AI 人设生成、长期记忆、RAG 知识库、意图路由，对接本地 llama.cpp（OpenAI 兼容 API）。

---

## 2. 技术架构

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 UI | 原生 HTML/CSS/JS + PyWebView | 毛玻璃 Liquid Glass 风格，1300+ 行单文件 |
| 后端 API | Python + FastAPI + uvicorn | 端口 8765 |
| 记忆存储 | 内置 numpy 向量记忆（Qdrant 可选） | 默认不依赖外部数据库；Qdrant 需本地二进制手动启动 |
| 文本嵌入 | sentence-transformers | 本地小模型，无需联网 |
| 微信接入 | itchat-uos | 可选，未安装 |
| 打包 | PyInstaller | 单文件 .exe，45MB |

---

## 3. 文件清单与职责

### 核心入口
- `demo.py` — 主后端（FastAPI 应用，733 行），包含所有 API 端点
- `client.py` — 桌面启动器（PyWebView 窗口，6596 字节）
- `main.py` — 备用入口

### 模块
| 文件 | 职责 |
|------|------|
| `characters/__init__.py` | 角色 CRUD、人设标签管理、默认角色 |
| `gateway/router.py` | 意图路由引擎（关键词匹配 → 意图类型） |
| `gateway/static/index.html` | 前端 UI（1317 行），所有页面、组件、逻辑 |
| `memory/__init__.py` | 长期记忆：对话历史、事实存储、摘要生成 |
| `rag/__init__.py` | RAG 知识库：文档索引、向量化检索 |
| `rag/indexer.py` | 文档切分、索引逻辑 |
| `rag/tags.py` | 标签系统 |
| `embedding/service.py` | 本地 Embedding 模型服务 |
| `wechat/bot.py` | 微信机器人封装（itchat） |
| `config/__init__.py` | 配置管理（YAML + JSON 运行时设置） |
| `config/settings.yaml` | 应用默认配置 |
| `config/routes.yaml` | 意图路由规则 |
| `installer/diagnose.py` | 安装诊断工具 |

### 构建/部署
- `Qiyu.spec` — PyInstaller 打包配置
- `build.py` — 打包脚本
- `requirements.txt` — Python 依赖
- `start.bat` / `start.sh` — 启动脚本

---

## 4. 关键全局配置（demo.py）

```python
LLM_URL = os.getenv("LLM_BASE_URL", "http://192.168.2.6:8081/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6-35b")
DEMO_PORT = 8765
DEMO_HOST = "0.0.0.0"
```

运行时设置持久化在 `config/_runtime_settings.json`（程序启动时不会自动加载此文件到全局变量，需手动调用或修复）。

---

## 5. API 端点速查

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 首页（返回 index.html） |
| GET | `/v1/characters` | 列出所有角色 |
| POST | `/v1/characters` | 创建角色 |
| POST | `/v1/characters/select` | 切换当前角色 |
| POST | `/v1/characters/generate` | AI 生成结构化角色简历（10 字段，走路由模型） |
| POST | `/v1/characters/{id}/index_resume` | 把角色结构化简历写入 RAG 知识库 |
| DELETE | `/v1/characters/{id}` | 删除角色 |
| POST | `/v1/chat/completions` | 聊天（OpenAI 兼容格式） |
| GET | `/v1/memory/{user_id}` | 获取用户记忆 |
| POST | `/v1/memory/{user_id}` | 添加记忆 |
| POST | `/v1/memory/{user_id}/summary` | 生成记忆摘要 |
| GET | `/v1/rag/search` | RAG 知识搜索 |
| GET | `/v1/rag/documents` | 列出已索引文档 |
| POST | `/v1/rag/index` | 手动索引文档 |
| GET | `/v1/routes` | 获取路由规则 |
| POST | `/v1/routes` | 保存路由规则 |
| GET | `/v1/settings` | 获取设置 |
| POST | `/v1/settings` | 保存设置 |
| GET | `/v1/models` | 获取可用模型列表 |
| POST | `/v1/llm/verify` | 验证 LLM 配置 |
| POST | `/v1/wechat/start` | 启动微信机器人 |
| POST | `/v1/wechat/stop` | 停止微信机器人 |

---

## 6. 前端页面结构（index.html）

```
视图切换（.view-section）:
├── chat        — 聊天主界面（左侧边栏 + 聊天区域 + 输入框）
├── characters  — 角色工坊（标签选择 + AI 生成结构化简历 + 表单 + 简历入RAG）
├── memory      — 记忆管理
├── rag         — 知识库
└── settings    — 设置（LLM / 路由 / 知识库）

设置内标签页（.settings-tab）:
├── llm    — LLM 配置（API地址、模型选择、验证、Temperature）
├── route  — 意图路由规则编辑器
├── rag    — 知识库管理
├── wechat — 微信机器人
├── memory — 记忆标签
└── appearance — 外观（主题切换 + 头像库上传）

全局组件:
├── .toast-container     — 消息提示（成功/错误/警告）
├── .modal-overlay       — 模态框（角色编辑等）
└── 顶部栏               — 角色名称、清空对话、设置入口
```

---

## 7. 数据模型

### CreateCharacterRequest（创建角色）
```json
{
  "id": "可选，不传则自动生成",
  "name": "角色名称",
  "tagline": "一句话描述",
  "description": "人格描述（prompt 风格）",
  "persona": "人设信息卡（AI 生成后填入）",
  "temperature": 0.7,
  "keywords": ["标签1", "标签2"],
  "tone": "说话风格",
  "avatar_color": "#hex",
  "avatar": "头像文件名（默认库或上传库）",
  "resume": {
    "基本信息": "姓名=xxx | 年龄=xx | 职业=xxx",
    "生活环境": "城市=xxx | 居住=xxx",
    "性格": "标签=xxx | 口头禅=xxx",
    "背景": "成长=xxx | 家庭=xxx",
    "爱好日常": "xxx",
    "问题应对": "压力=xxx | 冲突=xxx",
    "关系定位": "与用户=xxx | 规则=xxx",
    "调度标签": "触发词=xxx | 擅长话题=xxx | 回避话题=xxx",
    "对话自我表述": "我是xxx",
    "数据关键词": "character=xxx | tags=xxx | 检索词=xxx"
  }
}
```

> 简历生成链路：用户在角色工坊选择人设标签 → 路由模型生成 10 字段结构化简历（`resume`，不进对话提示词）→ 创建角色时随 `resume` 提交 → 点击「简历入RAG」写入知识库 → 聊天时按意图路由检索注入。对话模型只看到简历字段，标签本身不直接给模型。

### ChatRequest（聊天）
```json
{
  "messages": [{"role": "user", "content": "..."}],
  "temperature": 0.7,
  "stream": false,
  "user": "demo_user",
  "use_memory": true,
  "use_rag": true
}
```

---

## 8. 已知问题清单（按优先级）

| # | 问题 | 位置 | 根因/状态 |
|---|------|------|----------|
| 1 | 启动时 `_runtime_settings.json` 未被加载到全局变量 | `demo.py` startup | `LLM_URL`/`LLM_MODEL` 默认值硬编码，启动未读取持久化设置 |
| 2 | 首次启动无角色时，顶部提示条样式突兀 | `index.html` | 需要改为更优雅的引导状态 |
| 3 | 深色模式切换后部分元素需刷新才生效 | `index.html` CSS | CSS 变量切换逻辑需完善 |
| 4 | Qdrant 为可选组件 | `demo.py` | 内置 numpy RAG 不依赖 Qdrant；如需启用请手动启动本地二进制 |
| 5 | 微信模块 itchat 未安装 | `wechat/bot.py` | 需 `pip install itchat-uos` |
| 6 | `generate_character_card` 超时 120s 对大模型可能不够 | `demo.py` | 可调整为 300s |
| 7 | 路由规则编辑后没有实时热重载反馈 | `index.html` | 保存后应提示生效状态 |
| 8 | 记忆标签的增删改 UI 操作后没有即时刷新 | `index.html` | 需添加前端状态更新 |

---

## 9. 开发环境启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动后端（无需 Docker；PostgreSQL 需本机运行，或修改 .env 的 LETTA_PG_URI）
python demo.py
# 访问 http://localhost:8765

# 3. 打包 exe
python build.py
# 输出: dist/Qiyu.exe
```

---

## 10. 代码风格约定

- 后端: PEP8，使用 `loguru` 日志，`httpx` 异步 HTTP
- 前端: 原生 JS，无框架，CSS 变量命名 `--xxx`，状态管理 `app.state`
- API 错误: FastAPI `HTTPException` + 前端 `this.toast(msg, 'error')`
- 异步: 后端全 async/await，前端 async/await + fetch

---

*此文档用于 Codex 项目上下文导入。所有源文件位于同级目录。*
