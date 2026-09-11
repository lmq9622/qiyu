# 栖语 Qiyu · 本地 AI 陪伴桌面应用

> **本仓库发布的是 `0.0.x` 历史线的最后一版：`v0.0.17`（2026-09-01）。**
> 这一版**不包含 MiniMind / 小脑模块**。项目在此之后转向「内置小脑」的 `0.05.x`
> 实验专线（该专线后来被判定为废案、不再演进），因此本仓库作为
> **「不带小脑」的可运行历史版本**归档发布，不再跟进后续开发。

## 一、项目目标

把「AI 伴侣」做成本地可跑、可自建、数据留在自己机器上的桌面应用：角色有自己的生活和人设，
聊天像真人微信（短、快、有态度，不端着、不说教），能记住长期发生的事，能读自己的资料库，
并且把微信当成真正的聊天入口，而不是又一个网页对话框。

## 二、项目简介

「栖语」是一个 Windows 桌面应用：Python + FastAPI 后端 + pywebview（Edge WebView2）桌面窗口，
打包成单文件 exe，双击即用。v0.0.17 时的构成如下。

| 模块 | 作用 |
|---|---|
| `client.py` | 桌面客户端入口：自动拉起后端子进程（默认 `127.0.0.1:8765`）并打开窗口 |
| `demo.py` | FastAPI 单文件后端：聊天链路、角色、记忆、RAG、联网、设置、外部通道 |
| `gateway/` | OpenAI 兼容适配网关（`/v1/chat/completions` 等），可接 Open WebUI |
| `letta_backend.py`、`agent/` | 可选：走 Letta Agent 做记忆/工具链，需要 PostgreSQL |
| `memory/` | 分层记忆：用户档案 / 长期记忆 / 每日摘要 + 记忆标签 |
| `rag/`、`embedding/` | 文档索引（`.txt/.md/.pdf/.docx/.doc`）+ 本地 bge-small-zh 向量检索 |
| `characters/` | 角色卡（人设、语气、标签、头像），支持 AI 生成人设 |
| `channels/`、`wechat/`、`wechaty/` | 微信通道：ClawBot / Wechaty / itchat / 本机微信自动化 |
| `build.py`、`Qiyu.spec` | PyInstaller 打包成单文件 exe |
| `test_harness/` | 自建「真人感」回测：12 人设 × 场景 × 多轮 |

### v0.0.17 能做什么

- **桌面客户端**：双击 `Qiyu.exe` 或运行 `python client.py`，自动起后端并开窗口。
- **角色工坊**：多角色人设（人设 / 用户设定 / 记忆提示 / 语气 / 标签 / 头像），可流式「AI 生成人设」，可切换角色。
- **聊天链路**：意图路由（直答 / 思考 / 联网 / 工具）、话题与情绪状态、记忆注入、回复分条（`reaction` / `statement` / `question` / `follow_up` 等）。
- **长期记忆**：聊天自动落库 + 分层摘要，记忆面板可查看、增删、按标签管理。
- **RAG 知识库**：把文档丢进上传目录，自动切块、Embedding、检索，回答时引用自己的资料。
- **联网工具**：搜索、打开链接、看热点、找图/找视频；**真实执行**后才交给模型回复，失败会如实说明，不假装成功。
- **主动消息**：09:00–22:00 随机主动找你，好感度越高越频繁；你长时间不回，下次聊天角色会自然带出来。
- **外部通讯**：ClawBot（官方扫码置顶）、Wechaty、itchat 单账号接管、本机微信自动化；支持多账号并行、不同联系人映射到不同角色。
- **模型可换**：内置 9 个 OpenAI 兼容预设（DeepSeek / 智谱 GLM / MiniMax / OpenAI / Anthropic Claude / Gemini / Grok / Kimi / 小米 MiMo），也可以指向本机 llama.cpp 之类的任意 OpenAI 兼容端点。

## 三、未来规划（简要）

- 让整条对话链路更彻底地留在本机，减少对外部服务的依赖；
- 把交互从「一问一答」推向更接近真人的即时反应：能接话、能被打断、边听边想；
- 让角色的存在感不止于一个窗口——声音、表情、动作，以及空间里的呈现；
- 记忆和关系继续往长期走，让相处是连续的而不是一遍遍重新认识；
- 工程上保持克制：只留下真正改善体验的部分，不为架构好看而堆叠层级。

（以上是方向，不是承诺。后续版本的实现、训练与回归记录不放在本仓库。）

## 四、环境要求

- Windows 10 / 11（本版只在 Windows 上开发、打包、验证过）
- Python 3.10+（源码运行方式需要）
- 一个 OpenAI 兼容的 LLM 服务（本机 llama.cpp / Ollama 网关，或任一云端 API）
- 可选：PostgreSQL（仅 Letta 链路需要，端口 5432）
- 可选：Qdrant（默认不启用；内置 numpy 记忆与检索不需要它）

## 五、快速开始（源码）

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 配置
copy .env.example .env
#    编辑 .env：LLM_BASE_URL / LLM_MODEL / LLM_API_KEY

# 3) 启动桌面客户端（会自动起后端）
python client.py
```

其它启动方式：

```bash
python demo.py            # 只起后端，浏览器访问 http://127.0.0.1:8765/
python main.py            # 全自动服务启动器：Letta / 网关 / RAG 监控 / 微信（按需）
python gateway/main.py    # 只起 OpenAI 兼容适配网关（端口 8000）
python installer/diagnose.py   # 环境诊断
```

端口被占用时（例如本机已有别的服务占了 8765）：

```bash
set QIYU_PORT=8888
python client.py
```

## 六、从源码打包 exe

```bash
pip install pyinstaller pywebview
python build.py                 # 产物：dist/Qiyu.exe
set QIYU_OUTPUT_NAME=Qiyu-0.0.17 && python build.py    # 自定义输出名
```

> Release 里的 `Qiyu-0.0.17-win64.exe` 由本仓库这份源码打包，并在打包之外额外做了一层
> **防反编译加固**：应用自身模块不在包内以明文/明文字节码形式出现，而是加密后随包分发，
> 运行时在内存中解密执行（详见 `RELEASE_NOTES_v0.0.17.md`）。该加固工具不随仓库发布。

## 七、目录结构

```text
client.py            桌面客户端入口（打包入口）
demo.py              后端主体（FastAPI，聊天/角色/记忆/RAG/设置/通道）
main.py              服务启动器
gateway/             OpenAI 兼容网关 + 前端页面（gateway/static/index.html）
agent/               Letta Agent 初始化
channels/            外部通讯通道（ClawBot / Wechaty / itchat / 本机接管 / 预留）
tools/web.py         联网工具：搜索、热点、商品、视频、图片
wechat/、wechaty/     微信接入的两套实现
memory/  rag/  embedding/   记忆、知识库、向量服务
characters/          角色卡与头像
config/              运行时配置 yaml
installer/ launcher/ 诊断与启动器
test_harness/        回测脚本与报告
build.py Qiyu.spec   PyInstaller 打包
PROJECT_LOG.md       项目日志（截止 0.0.x）
docs/用户手册.md      用户手册
```

## 八、关于这一份源码的说明（如实记录）

1. **它是历史版本的归档，不是当前开发版。** 小脑专线（`0.05.x`）与之后的架构改造不在本仓库。
2. **`tools/` 是从同期备份恢复的。** 原始 v0.0.17 快照的 `.gitignore` 把整个 `tools/` 目录排除了，
   导致 `tools/web.py`（联网工具）从未进入版本库；本仓库用 2026-08-31 的备份补回该模块，
   它与 `demo.py` 调用的函数完全对得上。
3. **客户端端口改为可配置。** `client.py` 现在读取环境变量 `QIYU_PORT`（默认仍是 8765），
   否则端口被占用时 exe 会直接起不来。
4. **已做最小脱敏**：开发期内网地址 `192.168.2.6` 已替换为 `127.0.0.1`，并移除若干含本机绝对路径的开发期补丁脚本。

## 九、已知限制（如实说明）

- **不内置任何模型权重**，必须自备 LLM 后端；聊天质量取决于你接的模型。
- Letta 链路需要自己装 PostgreSQL；`python main.py` 会检测端口，但不会替你安装数据库。
- 首次使用本地 Embedding 会下载 `BAAI/bge-small-zh-v1.5`（需要联网）。
- **微信通道有风险**：itchat 早已停止维护；本机接管走微信 UI 自动化，锁屏/断网/微信改版都会失败；Wechaty 免费协议也不稳定。存在账号被限制的风险，请用小号自测。
- 「真人感」结论来自自建回测（12 人设 × 场景 × 多轮），不是公开基准，换模型后不一定成立。
- v0.0.17 的 Phase B 全量 21600 次回测**没有跑完**（受限于本地推理耗时约 40–60 小时），日志里如实记录为未完成，没有写成通过。

## 十、文档与许可

- 用户手册：[`docs/用户手册.md`](docs/用户手册.md)
- 项目日志（截止 0.0.x）：[`PROJECT_LOG.md`](PROJECT_LOG.md)
- 版本说明：[`RELEASE_NOTES_v0.0.17.md`](RELEASE_NOTES_v0.0.17.md)
- 许可证：MIT，见 [`LICENSE`](LICENSE)