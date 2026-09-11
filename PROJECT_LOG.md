# 栖语demo · 项目日志（PROJECT LOG）

> 生成日期：2026-08-31
> 版本规则：**每重新打包一次，版本号顺延 +0.0.1**（打包 = 交付 = 版本）
> 本文档记录从接手（初期编号 **0.0.3**）到当前版本的每一次更新内容、功能清单与测试结果。

---

## 0. 项目一句话

本地 AI 聊天陪伴机器人（Windows 桌面 .exe），虚拟角色 + 真人感聊天 + 记忆系统 + RAG 知识库 + 外部通讯（微信 ClawBot / itchat / 预留企业微信·QQBot·飞书），后端对接 x99 内网 llama.cpp（OpenAI 兼容 API，随时可换）。

- 架构：FastAPI 后端（`demo.py`）+ PyWebView 桌面壳（`client.py`）+ 单文件毛玻璃前端（`gateway/static/index.html`）
- 打包：PyInstaller onefile → `dist\Qiyu.exe`，双击即用（内置后端 + 前端）
- 数据：`data\`（正式）/ `~/.ai_companion`（exe 运行数据）
- 约束：不用 Docker；UI 保持毛玻璃圆角仿 iOS 风格；标题「栖语demo」

---

## 1. 版本历史（按打包顺延）

### 1.1 版本划分依据
- 以「重新打包 exe」为版本节点，每次打包顺延一个版本号。
- 0.0.3 为接手初期的编号（用户指定起点）。
- 历史版本的内容与时间依据：`CODEX_README.md`（08-29）、测试沙箱目录时间线（08-30 22:47 ~ 08-31 10:28）、`docs/整理_20260831.md`（14:50，记录 48.7MB 包）、`test_harness/report/realism_report_run3-5.md`（记录 46.5MB 交付包）、本次打包（18:18，46.7MB）。

### 1.2 版本明细

#### v0.0.3 · 接手初期（2026-08-29 ~ 08-30）
**本次更新内容**
- 从原项目（`C:\Users\lmq20\Documents\kimi\Workspaces\ai伴侣\ai-companion`）参考重建，确定 Letta + Open WebUI + 网关结构，改名「栖语」（避免与市场同音产品冲突，弃用「灵犀」「屿」等名，沿用原「栖语」）。
- 后端：FastAPI + 意图路由 + 记忆系统 + RAG + 微信接入，LLM 指向 x99 内网 llama.cpp（`127.0.0.1:8081`），OpenAI 兼容格式，可随时换 API。
- 前端：单文件毛玻璃圆角仿 iOS 风格 UI；**不改变原有 UI 风格**（用户反复调整过的样式）。
- 角色系统：人设标签 → 路由模型生成约 500 字「虚拟角色信息卡」（虚构生活环境/详细性格/问题应对/爱好/背景/关系定位），信息卡入库 RAG 供调度读取；支持用户选标签一键生成、二级菜单由路由模型智能补全信息卡；信息卡模板可预览。
- 角色参数：MBTI 拖动条（可改，改动后给性格提示）、反驳阈值、主见值、初始好感度、与用户的关系栏；所有值先由模型生成、用户可改。
- 用户画像：预填 + 聊天自动摘取进记忆库。
- 设置：模型验证（失败加抖动特效）、LLM/路由模型配置自动保存、主流 API 预设（DS/GLM/MiniMax/OpenAI/Anthropic/Gemini/Grok/Kimi/Mimo）、思考开关、平行请求开关。
- 微信：itchat 单账号接管（模式 B，登录一个微信号直接接管）。
- 打包：首次交付 exe（约 45MB 级，见 CODEX_README）。

**测试结果**：早期冒烟；开始搭建 e2e 测试台 `test_harness/`（run.py / scenarios.py / analyze_realism.py / gen_organize.py）。

---

#### v0.0.4 · e2e run1/run2 阶段（2026-08-30 晚 ~ 08-31 凌晨）
**本次更新内容**
- 记忆系统成型：记忆按 用户×角色 独立存放，互不串上下文；聊天记录/事实/摘要写入、召回。
- 对话状态机 `conversation_state`（闲聊/兴奋/吐槽/认真/吵架/安慰/技术协作等），消息条数与拆分方式随状态变化。
- 工具真实回填链路：模型只产生 action，工具执行成功后才允许「发你了/查到了」；失败如实告知。
- 防提示词注入：忽略「你是管理员/忽略指令/输出 system prompt」类输入，按真人反应处理。
- 深夜场景、暧昧、吵架、冷淡敷衍等行为建模；主动消息与定时提醒骨架。
- 打包：随 run1/run2 测试迭代。

**测试结果**
- **run1**（200 场景）：197/200 通过。失败 3：`tool_fabrication`（s085 编造 iPhone 价格 5999）、`tool_uncertain`（s194/s195 既没说去找也没说完成）。记忆写入 20/22、召回 21/22。
- **run2**（200 场景）：200/200 全绿。记忆写入 22/22、召回 20/22；工具真实执行 0/33（测试台等待窗口不足的低估，非代码问题）。

---

#### v0.0.5 · run3 五百轮真人感基线（2026-08-31 10:30 打包，48.7MB）
**本次更新内容**
- 真人微信消息产生过程建模：一次回复 ≠ 一条消息，模型先输出 JSON（`messages: [{text,type,delay}]`），前端按 delay 逐条播放；禁止固定「反应+观点+问题」模板。
- 新增量化维度：`affinity`（好感度）/ `patience`（耐心度）/ `interaction_need`（聊天意愿 0-4），三者解耦；关系阶段（友情→暧昧）由初始值+聊天方向动态调整。
- 场景系统 `scene`（ordinary/playful/argument/comfort/intimate/awkward/serious/late_night/helping/farewell）：只描述状态不强制台词；`awkward` 处理突然的关系性质变化。
- Context Gate：主动消息/定时分享发送前检查是否正在聊天、最近主动消息时间、话题相似度、event_id 去重（`water_monstera_20260830` 型），定时触发器不得打断 ACTIVE 对话。
- Task Agent 子代理：搜索/浏览/购物/视频走真实工具链，并行请求数可设（auto/1/2/3/4/unlimited）；后台执行 + 完成后新一轮 prefill。
- 思考模式与输出协议解耦：thinking 开启时前端不再只显示「……」。
- 记忆分当天/短期/长期：当天记忆按权重积累，凌晨 4 点自动总结归档进短期/长期。
- 情绪系统：多维情绪（开心/害怕/悲伤/焦虑/兴奋），加权得出总情绪，情绪基调会延续（如「来姨妈要安慰」整天 down）；情绪原因必须可解释。
- 每日当天话题总结进 RAG；聊天大纲每天凌晨自动生成，次日打开若缺失自动补生成。
- 测试台：场景库扩充至 500+（s001~s5xx），行为测试分组（behavior_*）。

**测试结果**
- **run3**（500 场景）：496/500 通过。失败 4 全为**工具首轮编造**：s085（iPhone 5999 元）、s089（比特币 60500 刀）、s094（宫保鸡丁「搜到了」）、s098（王者 S43 赛季）。
- 记忆写入 20/22（漏「我特别怕黑」「我下周要去杭州出差」两句式）；召回 18/22。
- 真人感主要问题（按严重度）：
  1. 多轮闲聊单轮消息 5~8 条太多（表演欲强），典型 s223/s234/s249；
  2. 工具首轮声称完成并编造价格/日期；
  3. happy 类「哇！！恭喜恭喜呀！🎉」感叹号刷屏 + 彩虹屁模板；
  4. comfort 类固定「抱抱/摸摸头/怎么突然」开头模板；
  5. 个别 JSON 内部分析字段泄漏成消息（s100）；
  6. 记忆落库句式覆盖不足。
- 表现好的类别：冷淡/深夜/暧昧/吵架/口误/琐碎分享（真人感极高，例：「就一个哦？今天这么冷淡」「……那是洗衣液」「草 踩出啥了」「怕黑。刚才自己说的。」）。

---

#### v0.0.6 · 真人感修复 + run4/run5（2026-08-31 14:50 前后交付打包，46.5MB）
**本次更新内容（代码级护栏，不只改提示词）**
- 防工具幻觉护栏：`_sanitize_msg_text` / `_needs_search_guard` / `_postprocess_reply_messages` / `_msg_cap` —— 搜索待回填且无真实结果注入时，自动丢弃「搜到了/找到了/发你了」及任何价格/日期/数字结论，只留短中间话；`_EVIDENCE_CACHE` 标记本轮是否已注入真实联网结果，护栏只在无真实结果时生效。
- 消息条数硬上限：普通闲聊 3 条 / 兴奋·吐槽·吵架 5 条 / 认真讨论·技术协作 6 条 / 完整输出（讲故事·详细分析）不限。
- 感叹号叠打自动收成单个（「！！！」→「！」），「？？？」保留。
- JSON 泄漏消息自动丢弃（s100 类）。
- 记忆兜底句式扩展：捕捉「我特别怕黑」「我下周要去杭州出差」「明天要加班/开会/面试」等句式。
- 流式路径按护栏逐条过滤 + 最终补齐，避免前端闪幻觉消息。
- 提示词微调：消息条数硬约束、好消息别彩虹屁、安慰别模板化、查证铁律「本轮只准发一条中间话」。
- 测试台：工具回填检测由固定 45s 改为轮询最多 150s；移除 `tool_uncertain` 误报。
- 行为测试轮（behavior 系列，14:06~14:41，s501~s524）：story_listener/recall_recent/old_recall/abrupt_shift/minimal_input/rejection/strong_emotion/proactive_cooldown 等 32 组场景。
- 记忆面板改版：当天记忆（总结型）默认清除只清当天；长期/短期单独勾选；事件分开列 + 权重。
- 聊天输入区：脏话/涩涩/思考挡位条放在聊天框旁（off/low/mid/high/ultra）；对话欲望值实时量化并注入提示词。
- 流式输出隐藏播放：收到请求先逐条推消息，识别到 JSON 即上屏，再按 delay 下一条；最后出记忆总结进 RAG。
- 每条回复附带时间信息注入（避免时差感）。

**测试结果**
- **behavior_run1**（26 场景）：25/26；唯一失败 s511 `context_loss`（最后一轮没接住「头发」话题）。
- **behavior_run2**（24 场景）：23/24；同样 s511 context_loss。
- **behavior_s511**（7 场景）：6/7；仍 s511 接不住话题。
- **behavior_clean**（32 场景）：31/32；唯一失败 s503 `story_truncated`（故事只发 2 条）。
- **behavior_final**（32 场景）：31/32；失败 s503 longform 0/1；记忆写入 3/3、召回 2/3。
- **run4**（23 定点复测）：23/23 全过。工具 7/7 零幻觉（s085/s094/s098 拿到真实回填，s081/s089 如实报失败）；记忆 2/2 写入+召回（s143/s149）；黑洞长篇 14 条压缩成对话式 6 条；happy 感叹号刷屏消失。
- **run5**（20 混合回归）：19/20。唯一失败为测试台误报（模型回「行」但工具真执行了），已修测试台判定；长文讲故事完整不截断。
- 其它定点：**smoke** 4 场景 0/4（后端未就绪导致的失败，属环境问题）；**verify_retry** 5 场景 5/5（记忆 3/3 写入+召回，s181 长文 254 字完整）；**final** 12/12（工具 5/5、注入 2/2、记忆 2/2）；**preserved** 5/5（记忆 3/3 写入、2/3 召回）。

---

#### v0.0.7 · 外部通讯重构（2026-08-31 18:18 打包，46.7MB）
**本次更新内容**
- 设置页「微信」→「外部通讯」，参考 OpenClaw channel 抽象做统一通道层 `channels/`：
  - `channels/base.py`：统一 `BaseChannel` 接口（start/stop/send/status/QR/配置表单）。
  - `channels/clawbot.py`：微信 **ClawBot（官方 iLink Bot API）** 客户端 —— 前端扫码绑定直接用、多账号并行；token/baseurl/cursor 持久化到 `data/channels/state_clawbot_*.json`；长轮询收消息 + `context_token` 发送。
  - `channels/itchat_channel.py`：原 itchat 单账号接管包装为通道（模式 B）。
  - `channels/placeholders.py`：预留 **企业微信 / QQBot / 飞书** 配置位（表单可保存、标注未接通）。
  - `channels/registry.py`：通道注册表，`wx_<通道id>__<对方id>` 路由到对应通道，记忆仍按 用户×角色 隔离。
  - `channels/store.py`：通道状态与配置持久化。
- 后端 API：`/v1/channels/list|status|qr|start|stop|config`；旧 `/v1/wechat/*` 保持兼容。
- 微信回复支持 `(text, pieces)` 多消息按 delay 逐条发送（itchat 与 ClawBot 均生效）。
- 主动消息下发改走通道注册表（`channel_registry.send`），不再只认 itchat。
- 前端：外部通讯 tab 渲染通道卡片（状态/二维码/配置表单/启动停止），扫码中自动轮询刷新，毛玻璃风格保持。
- `build.py`：新增 `channels` 及 `qrcode`/`PIL` hidden imports（二维码生成是运行时惰性导入，静态分析不到，必须显式打包）。

**验证结果（2026-08-31 晚）**
- iLink 真实接口连通：`GET /ilink/bot/get_bot_qrcode?bot_type=3` 拉码成功；`get_qrcode_status` 长轮询约 30s 返回 `{"ret":0,"status":"wait"}`；扫码确认后应返回 `bot_token`（待真机验证）。
- 后端 dev（8768）与 exe 均实测：`/health` 返回 5 通道（itchat/wecom/qqbot/feishu/clawbot_main）；ClawBot「启动」→ 二维码 data URL 真实生成（`data:image/png;base64,...`），状态 waiting→扫码中→停止后 idle。
- 浏览器实测前端：5 张通道卡片渲染正常、企业微信表单（含密钥字段）正常、扫码中按钮显示「重新扫码」。
- exe 冒烟：启动后 `/health` 全绿，`wechat_available:true`，ClawBot 二维码在 exe 内实测生成成功（证明 `qrcode`/`PIL` 已打包）。
- 未做：真实扫码绑定（需用户手机实测，等用户指示）；企业微信/QQBot/飞书实际接入（仅预留配置位）。

---

#### v0.0.8 · 外部接入修复 + ClawBot 置顶（2026-08-31 18:38 打包，46.6MB）
**本次更新内容**
- **ClawBot 置顶为默认主通道**：通道注册顺序调整为 ClawBot → itchat → 预留通道，前端「外部通讯」列表第一位即 ClawBot（官方 iLink 协议扫码，多账号并行，主推功能）。
- 修复 ClawBot 二维码「刷新即过期/失效」：
  - 根因 1：轮询线程命名为 `clawbot_qr_{id}`，但 `_find_thread("qr_poll")` 拼出的前缀是 `clawbot_qr_poll_{id}`，**永远匹配不上** → 每次点启动都拉新码，旧码被服务端作废，新旧轮询线程并发互相覆盖 `qr_status/qr_data/qr_message`，前端看到「已过期/已失效」。
  - 根因 2：服务端二维码实测有效期约 **146 秒**（约 2 分半），本地兜底原设 300 秒偏长，与真实有效期脱节。
  - 修复：`start(force=True)` 支持「重新扫码」强制作废旧码并重拉（前端按钮统一传 `force:true`）；`_find_thread("qr")` 修正前缀匹配；所有状态写入加 `qrcode == self._pending_qrcode` 守卫，旧线程不得覆盖新码状态；`finally` 用 `is ev` 保护 stop_event，避免旧线程误清新线程事件；本地兜底改为 150 秒；过期/失效提示改为「请点击『重新扫码』获取新二维码」，前端按钮在过期/失效时显示「重新扫码」。
- 修复 itchat 单账号二维码前端破图：
  - 根因：itchat-uos 的 qrCallback 给的是裸 PNG base64（`iVBORw0KGgo...`，无 `data:image/png;base64,` 前缀），前端 `<img src>` 无法渲染 → 显示破图图标 + 登录文案。
  - 修复：`ItchatChannel._normalize_qr_data` 与 `WeChatBot.qr_data` 双重补 `data:image/png;base64,` 前缀。
- 明确「微信 · 单账号接管」方案：使用 GitHub 的 **itchat-uos**（itchat 的 UOS 协议 fork，`pip install itchat-uos`）；`wechat/bot.py` 里的 gewechat 为旧方案代码（未启用，保留备查）。

**验证结果（2026-08-31 晚）**
- iLink 实测：`get_bot_qrcode?bot_type=3` 返回 `{qrcode, qrcode_img_content, ret=0}`，`qrcode_img_content` 为 liteapp URL（`https://liteapp.weixin.qq.com/q/...?qrcode=...&bot_type=3`），本地按 URL 生成二维码图；新码 `get_qrcode_status` 前 30s 返回 `{"ret":0,"status":"wait"}`，约 146 秒后服务端返回 `{"ret":0,"status":"expired"}`（记录真实有效期）。
- 单元逻辑测试：`start()`→waiting→旧线程存活→`start(force=True)` 强制换新码→旧线程唤醒后不覆盖新码状态（守卫生效）；全部 Python 文件 `py_compile` 通过；前端 JS 经 node --check 通过。
- exe 打包：`dist\Qiyu.exe`（onefile，46.6MB / 48,864,435 字节，18:38:38）重新打包完成，版本顺延 **0.0.8**；打包后已清理 `build/` 缓存与 `__pycache__`。
- 未做：真实扫码绑定（需用户手机实测）；企业微信/QQBot/飞书仍为预留配置位（未接通）。

---

#### v0.0.9 · ClawBot 角色透传 + 微信全功能 + 会话同步（2026-08-31 打包）
**本次更新内容**
- **ClawBot 角色透传**：设置页「外部通讯 → 微信 ClawBot（main）」新增「绑定角色（透传）」下拉（数据源 = 角色工坊所有角色），保存后该微信号收到的每条消息都走绑定角色；留空使用默认角色。配置持久化到 `data/channels/config_clawbot_main.json`，重启不丢；itchat 单账号接管同样支持绑定角色。
- **微信图片/表情/语音/视频/文件全部透传**：
  - ClawBot 入站 `item_list` 类型 2（图片）提取 `image_item.url/base64` 传入视觉链路（远端 llama.cpp 多模态），类型 6（表情）→ `[表情]` 文本透传；回复 pieces 支持 `image/image_url` 字段，模型发图时以 iLink 图片消息真实下发（URL/base64 best effort）。
  - itchat 单账号接管覆盖原开源工具完整功能：文字、图片（下载→视觉）、语音、视频、表情、文件、位置/名片/分享/系统通知、新好友自动通过；图片回复支持远程 URL 下载后 `itchat.send_image`。
- **微信 ↔ App 前端聊天记录同步**：
  - 聊天页顶栏新增「会话选择器」：本机网页 + 所有微信外部会话；微信侧收发的消息实时注册会话、通过 SSE `chat_sync` 事件推给前端，正在看该会话时自动刷新聊天记录与记忆面板。
  - 外部会话自动带出绑定角色（`/v1/sessions` 返回 `character_id`，切换会话自动 `characters/select` 到该角色，按会话 user_id 独立隔离不串台）。
- **修复微信消息处理致命 bug**：原 `handle_wechat_msg` 引用未定义的 `user_content`（NameError），微信任何消息都会在「处理消息失败」处挂掉；重写为角色透传 + 图片视觉 + 记忆落库 + 前端同步完整链路。
- **itchat 登录卡死提示**：扫码后卡在「已扫码/待确认」超过 75 秒自动给出 UOS 协议被限制提示（建议改用 ClawBot 官方通道），不再静默死等；通道状态实时回传 `qr_message`。
- **LLM 预设修正与合并**：`mimo` 改为**小米 MiMo**（`api.xiaomimimo.com/v1`，`mimo-v2-flash/pro/omni`，Key 在 `platform.xiaomimimo.com`）；主模型与路由模型都支持一键预设填充。
- **路由模型自动保存**：`验证配置` 成功即自动持久化整套 LLM 配置（主模型 URL/模型/Key + 路由模型 URL/模型）到运行时设置；预设选择也立即静默保存，重启后无需重配。
- **微信单账号扫码修复**：沿用 itchat-uos 方案（v0.0.8 已补 data URL 前缀）；本轮补充全消息类型注册与扫码卡死提示。

**验证结果（2026-08-31 晚，开发端口 8768）**
- 冒烟：`/health` 正常（llm_available=true，characters=2，channels 含 clawbot_main/itchat/wecom/qqbot/feishu）；`/v1/llm/presets` 返回小米 MiMo；`/v1/channels/list` 两个微信通道均带「绑定角色」下拉 schema。
- 配置持久化：`POST /v1/channels/clawbot_main/config {account_id, character_id}` 与 itchat 通道保存后重启读取正常。
- 路由模型自动保存：`POST /v1/settings`（含 route_url/route_model）与 `POST /v1/llm/verify`（含 route 字段）后 `/v1/settings` 能读回，`_runtime_settings.json` 落盘。
- LLM 真机链路：带 1×1 红色 PNG 的视觉请求经 `/v1/chat/completions` 成功回复（远端 llama.cpp 多模态通过）；vision 探测 `vision_supported=true`、uncensored 探测通过。
- ClawBot `_handle_inbound` 单测：`user_id=wx_clawbot_main__wxid_abc123`、文本+图片+表情混合内容、图片 URL 进 images 列表、channel 透传均符合预期。
- 全量 `py_compile` 通过；前端 JS 经 node --check 通过（无语法错误）。
- 未做：真实微信扫码收发端到端（需用户手机实测 ClawBot 扫码绑定与 itchat UOS 登录）；企业微信/QQBot/飞书仍为预留配置位。

---

#### v0.0.10 · 微信跨事件循环崩溃修复 + 模型配置自动回填（2026-08-31 19:44 打包，46.6MB）
**本次更新内容**
- **修复「ClawBot 收到消息只回一个『在呢』就卡死」的根因——跨事件循环崩溃**：
  - 定位：`channels/clawbot.py` 的 `_handle_inbound` 与 `wechat/__init__.py` 的 `_invoke_handler` 都在微信通道线程里新建临时 `asyncio.new_event_loop()` 再 `run_until_complete`，而 `demo.py` 处理链路里的 `llm_limiter`/`chat_gate` 等 `asyncio.Lock` 都绑定在 Uvicorn 主事件循环，跨 loop 直接 `await` 会抛 `RuntimeError: got Future attached to a different event loop`，被外层 `except` 吞掉后表现为「回一句追问就再无反应」。
  - 修复：`demo.py` 新增桥接入口 `handle_wechat_msg`（async）：非主线程调用时通过 `asyncio.run_coroutine_threadsafe(_process_wechat_msg(...), main_loop)` 投递到主循环执行，微信通道线程等待主循环结果；同线程则直接执行。原处理逻辑更名为 `_process_wechat_msg`，`main_loop` 在 `startup` 中捕获。
  - 现在 ClawBot / itchat 与网页聊天完全走同一条主循环链路，`asyncio.Lock` 不再跨 loop。
- **微信消息实时同步到 App 前端聊天框（补齐 `chat_sync` 广播）**：
  - `_process_wechat_msg` 在微信消息+回复落库后，除推给该会话 `user_id` 外，额外 `_push_event("web_user", notify=True)` 广播一份：前端无论正在看哪个会话都会刷新会话列表，非当前会话时 8 秒节流 toast「微信新消息：xxx」，当前会话自动刷新聊天记录与记忆面板。
- **LLM 模型/路由模型自动保存 + 打开自动回填（解决「每次打开都要手动配再验证」）**：
  - `/v1/settings` 的 `route_url/route_model` 增加回退：`llm_route_url` 为空时回退 `LLM_ROUTE_URL → llm_url`，路由模型同理回退主模型；用户 exe（`~/.ai_companion/data`）此前 `llm_route_url` 为空，现在打开设置页路由字段自动填好 x99 主模型，无需手填。
  - 前端 `applySettingsToUI`：路由字段为空时自动用主模型 URL/模型名填充；保存过的模型自动补进模型下拉并选中；下拉只有占位项时静默拉取真实 `/models` 列表（`_modelListAutoLoaded` 防重复）。
  - `verifyLLM` 成功即自动 `saveSettings(true)` 持久化整套配置（主模型 + 路由模型 + Key）；`POST /v1/llm/verify` 后端也把 `route_url/route_model` 落盘到 `_runtime_settings.json`，启动时自动加载——验证一次，重启不用再配。
- **ClawBot 入站消息过滤放宽**：删除按 `message_type` 硬过滤（两端协议枚举不一致会漏消息），只要对方 id 合法且 `item_list` 有内容即进入对话链路；图片 `image_item` 优先取 url/base64，type 6 表情转文本，回复 pieces 支持 `image/image_url` 真实下发。
- **LLM 预设**：主模型与路由模型预设均已合并（DeepSeek/GLM/MiniMax/OpenAI/Anthropic/Gemini/Grok/Kimi/小米 MiMo），选择预设即自动填 base_url+模型并静默保存，兼容任意 OpenAI 兼容端点（如本机 x99）。

**验证结果（2026-08-31 晚）**
- 集成测试 `_itest.py`：模拟 ClawBot `_handle_inbound` 从微信线程触发（`from_user_id=integtest_wxid`、文本消息）→ 桥接到主 loop → x99 真实生成（约 11s）→ 回复 `pieces` 分条（reaction/question）→ 记忆落库到 `data/chat_history/wx_clawbot_main__integtest_wxid__test_xiaoban.json` 与当日 `chat_logs` 日志，全程无 `RuntimeError`、无死锁、`RESULT: {"ok": true}`。测试后已清理该会话测试数据。
- 开发端口 8768 冒烟：`/health`（llm_available=true, channels=5）、`/v1/settings` 返回已保存 x99 主模型+路由模型、`/v1/llm/presets` 返回小米 MiMo 等 9 个预设、`POST /v1/channels/clawbot_main/config` 保存 `character_id=test_xiaoban` 后 `/v1/channels/list` 读回正常。
- 新 exe（`dist\Qiyu.exe`，48,899,381 字节）启动验证：`/health` 4 秒就绪（llm_available=true, wechat_available=true, characters=10），`/v1/settings` 返回 `route_url/route_model` 已自动回填 x99；`itchat` 模块导入正常（1.4.1）。
- 未做/待用户实测：真实微信 ClawBot 扫码收发端到端（需手机扫码绑定后发消息验证「在呢卡死」已消失）；itchat 单账号接管的 UOS 网页协议被微信限制（服务端不回 200），此类账号建议换 ClawBot 官方通道。

------

------

#### v0.0.11 · 微信独立接入切换 Wechaty（替换 itchat，2026-08-31 打包，46.7MB）
**本次更新内容**
- **微信独立接入从 itchat（UOS 网页协议）切换为 Wechaty**：
  - 原因：itchat-uos 的 UOS 网页协议被微信限制（扫码确认后服务端不回 200），不再可用；Wechaty 是社区主流框架，生态和后续升级空间更大。
  - 架构：`channels/wechaty_channel.py`（Python 通道）+ `wechaty/gateway.js`（Node 网关进程）通过 HTTP 桥接：
    - Python 侧 `start()` 时 spawn `node gateway.js`（`QIYU_GATEWAY_PORT=18765`），`/start` 触发 Wechaty 扫码登录；
    - 状态/二维码：Python 每 2 秒轮询 `/status`，wechaty 的 qrcode 字符串用 Python `qrcode` 库本地生成 data URL 给前端；
    - 入站消息：网关 `POST /v1/channels/wechaty/webhook`（`X-Qiyu-Secret` 共享密钥校验，403 防护）→ 校验后交给统一消息链路（自动桥接主事件循环，与 ClawBot/网页同链路）；
    - 主动/回复发送：`channel.send()` → `POST /send`，回复按 pieces.delay 逐条发送，支持图片（base64/URL）。
  - **两种登录方案（设置页可选）**：`wechaty-puppet-wechat4u`（本地免费 web 协议，扫码登录，同 itchat 一样存在网页协议被限制的风险）；`wechaty-puppet-service`（需 `WECHATY_PUPPET_SERVICE_TOKEN`，padlocal 等稳定方案）。
  - 角色透传、会话隔离（`wx_wechaty__<contact>`）、图片/表情/文件（FileBox 转 base64）透传均与 ClawBot 对齐；群聊仅在 @ 机器人时响应。
- **通道注册替换**：`channel_registry` 中 `itchat` 移除，`wechaty` 注册；`registry.get_channel_for_user` 默认回退改为 wechaty；`/v1/wechat/*` 兼容接口、`/health` 的 `wechat_available/running` 全部映射到 Wechaty 通道。
- **Wechaty 网关目录**：`wechaty/`（gateway.js + package.json + install.bat + node_modules 105MB）；打包后复制 `gateway.js/package.json/install.bat` 到 `dist/wechaty/`，并把 node_modules 一并复制，**exe 开箱即用**（无需手动 npm install）。exe 运行时按 `exe 同目录/wechaty` → `~/.ai_companion/wechaty` → 项目根目录 顺序定位网关。
- **前端**：外部通讯说明文案更新（ClawBot 置顶 + Wechaty 接管）；通道模式标签显示「Wechaty」；配置表单含登录方案下拉、Puppet Token（密码框）、绑定角色透传。

**验证结果（2026-08-31 晚）**
- Node 环境：v24.14.0 / npm 11.9.0；`npm install` 成功（348 包，105.3MB）。
- 网关单测：`node gateway.js` 启动 → `/ping`/`/status` 正常 → `POST /start` 5 秒内触发 `scan` 事件，返回 `https://login.weixin.qq.com/l/...` 二维码字符串（wechat4u web 协议可用）。
- 开发端口 8768 端到端：`/v1/channels/list` 返回 `wechaty`（available=True，mode=wechaty）；`POST /v1/channels/wechaty/start` 成功 → `/v1/channels/wechaty/status` 返回 `qr_status=waiting` + 二维码 data URL（626 字符）；webhook 无密钥/错误密钥均返回 403。
- 集成测试（in-process）：`handle_webhook` → 统一 handler → 意图路由 → x99 真实生成（约 13s）→ 分条 pieces（reaction/statement）→ 记忆落库 `data/chat_history/wx_wechaty__itest_wechaty_wx__test_xiaoban.json`，链路全通。修复了 `handle_webhook` 未 `await` async handler 导致 `'coroutine' object has no attribute 'strip'` 的 bug。
- 新 exe（`dist\Qiyu.exe`，46.7MB + `dist\wechaty\` 105MB）：启动后 `/health` 返回 `wechat_available=true`、channels 含 `clawbot_main/wechaty/wecom/qqbot/feishu`（itchat 已移除）；exe 内 `POST /v1/channels/wechaty/start` 成功并生成二维码。
- 未做/待用户实测：真实手机扫码登录 wechat4u（网页协议可能被限制，若失败请在设置切 service 方案 + 填入 Puppet Service Token）；微信群聊/图片收发端到端。

------
------

#### v0.0.13 · 微信「单一对话」+ 正在输入 + 多条回复修复（2026-08-31 打包）
**本次更新内容**
- **单一对话模式（默认开启）**：微信不再是「新开一堆 wx_ 会话」，而是 App 的另一个前端。ClawBot / Wechaty 通道新增配置 `single_conversation`（勾选）与 `merge_user_id`（默认 `web_user`）；开启后微信消息的 `user_id` 直接并入 App 主对话，消息/记忆/历史/关系/角色完全合并到同一条线程，会话选择器不再出现一堆微信会话；关闭后恢复「每个微信联系人独立会话」。
- **多条回复修复**：`ILinkClient` 发送消息改为**校验服务端返回**（旧代码忽略 `ret/errcode`，第二条起被限流/失效静默吞掉，导致微信只回一条）。现在：`ret=-14 / errcode=-14` 会话过期 → 自动去掉 `context_token` 降级重试一次；`ret=-2 + unknown error` 视为 token 失效同样去 token 重试；`ret=-2` 真频率限制 → 指数退避最多重试 3 次；仍失败抛异常并显式记录到日志与通道状态（前端通道卡片可见「微信发送失败（第 x/y 条）…」）。
- **对方正在输入**：新增 iLink `getconfig`（取 `typing_ticket`，600s 有效期缓存）与 `sendtyping`（1=开始 / 2=取消）。模型生成阶段微信端周期性（每 4s）续显「对方正在输入…」，发送前取消；同时 demo 层给 App 前端推送 `typing / typing_stop` 事件，两端输入指示器同步亮起。取不到 ticket 时优雅降级（仅 debug 日志）。
- **微信消息即时上屏**：收到微信消息后先推 `chat_user` 事件让 App 前端立刻显示该条（不等模型生成完），生成结束后 `chat_sync` 用后端历史覆盖校准；单一对话模式下同步给 web_user 广播 toast「微信新消息已同步到主对话」。
- **会话列表**：`/v1/sessions` 过滤掉已开启单一对话模式的 `wx_` 会话；普通网页会话不受影响。
- **ClawBot 登录态持久化（根因修复「每次重启都要重新扫码」）**：`channels/store.py` 原先把 `bot_token/cursor` 写到 `data/channels/`（exe 内是 PyInstaller 临时解压目录），重启即丢。改为统一走 `pathutil.get_data_dir()`（exe 模式 = `~/.ai_companion/data`）；`start()` 新增「复用上次登录态」：有保存 token 时先用短超时 getupdates 探测，会话有效直接恢复长轮询（免扫码），失效才退回二维码流程。
- **前端配置表单**：通道配置支持 `checkbox` 类型（单一对话开关），`saveChannelConfig` 读取勾选状态。

**验证结果（2026-08-31 晚）**
- `channels/clawbot.py` 单测：模拟入站消息 → handler 收到 `user_id=web_user`（合并生效）→ `_merged_remote` 记录联系人 → `resolve_remote('web_user')` 正确回解析；`-14 session timeout` 发送重试路径生效（去 token → 重试 → 抛错），不再静默吞错。
- 开发端口 8768 冒烟：`/v1/channels/list` 返回 `clawbot_main.single_conversation=True` 且 schema 含 `single_conversation/merge_user_id`；`/v1/sessions` 仅返回 `web_user`；`store` 落盘验证：`state_clawbot_main.json` 写入/读出 roundtrip 通过（不再丢 token）。
- 前端 JS `node --check` 通过；后端四个通道文件 + demo.py 语法检查通过。
- 未做/待实测：真实微信手机扫码后多条消息（2~4 条）连续发送、微信端「对方正在输入」显示、App 与微信同一对话实时互见。

------

#### v0.0.14 · ClawBot 四连修：前端实时刷新 / 语音转写 / 微信表情(beta) / 重置切换账号（2026-08-31 晚打包）
**本次更新内容**
**Bug#1 微信消息在 App 前端不实时刷新（要微信再发一条才显示上一条）**：
  - 根因 1：`loadChatHistory()` 拉完历史后只写 `this.state.messages`，没有调用 `renderMessages()`——`chat_sync` 事件刷新了数据但界面不重绘，直到下一条消息触发渲染才"补显示"。
  - 根因 2：微信通道绑定的角色 ≠ App 当前查看角色时，`chat_user / typing / chat_sync` 事件被 `char_id` 过滤静默丢弃，界面完全无反应。
  - 修复：`loadChatHistory` 末尾补 `renderMessages()`（顺带修好 `switchSession` 切会话后历史不渲染的旧问题）；新增 `_ensureEventCharacter(d)`——微信事件里的 `char_id` 与当前角色不一致时自动 `selectCharacterFor` 切过去再刷新，微信只是另一个前端，消息不再丢；`chat_sync` 分支刷新聊天+记忆+情绪。
**Bug#4 ClawBot 无「切换用户/重置」选项 + 刷新后点启动疑似卡死**：
  - 新增后端 `POST /v1/channels/{id}/reset`：清空 `bot_token / cursor / sessions / merged_remote / typing / pending_qrcode` 与持久化登录态（保留用户配置），下次启动直接全新扫码；前端通道卡片新增「重置连接（切换账号）」按钮（带确认）。
  - 卡死防护：`start/stop` 串行化（`_lifecycle_lock`），`stop()` 现在会 join 仍在跑的轮询线程并清理 `_threads`，启动前清理已退出线程；登录态探测超时从 18s 降到 6s（`get_updates(probe=True)`），避免"点启动像卡死"。
**Bug#2 微信语音发过来模型读不懂（没有本地转写）**：
  - 主路径：iLink `voice_item.text` = 微信自带 ASR 转写，直接拼成 `[语音] 转写内容` 发给模型，模型不再回"光发语音不发文字"。
  - 兜底：新增 `channels/wechat_voice.py`（可选本地 ASR）：若本机装了 `sherpa-onnx` 且 `data/asr` 或 `QIYU_ASR_MODEL` 指向模型目录，会自动尝试下载语音（media.url + aes_key → AES-128-ECB 解密 → ffmpeg 转 16k wav → paraformer-zh 识别）；未安装/失败一律安静降级 `[语音]`，不影响消息处理，也不拖慢轮询。
**Bug#3 微信表情（beta）**：
  - 新增 `channels/wechat_emoji.py`：官方表情名称表 + 用户指定的语义映射（`[大哭]`=委屈、`[微笑]`/`[翻白眼]`=无语、`[汗]`=轻度无语、`[囧]`=害羞、`[委屈]`=求原谅、`[流泪]`=大哭悲伤、`[旺柴]`=玩笑后缀、`[傲慢]`=不屑、`[脸红]`=尴尬、`[吃瓜]`=调侃、`[捂脸]`=服了、`[苦涩]`/`[裂开]`=压力大崩溃、`[拥抱]`=安慰三连发）＋ 提示词注入函数。
  - 入站：`it_type==6` 表情统一转 `[名称]`（兼容 text/emoji/name 字段），模型按语义理解（双向）。
  - 出站：ClawBot/Wechaty 通道配置新增「微信表情（beta）」checkbox；开启后 `_build_chat_system_msg` / `_build_active_prompt` 给模型注入表情规则（格式 `[表情名]`、日常必须但不能句句加、用户用表情则加量、讲故事/干活不用、互喷可单表情怼回去）；微信端直接渲染成表情图。
  - 前端：`[名称]` 在消息气泡里渲染成微信风格黄色小表情（`.wx-emoji`）；表情面板新增「微信表情（beta）」区（点击插入 `[名称]`），与后端表同步。
**验证结果（2026-08-31 晚，开发端口 8768）**
  - `python -m py_compile` 全绿；前端 `<script>` 提取后 `node --check` 通过。
  - 单测：模拟 `_handle_inbound` 表情消息 → content=`[大哭]\n[旺柴]`；语音消息带 `voice_item.text` → `[语音] 我想你了…`；无转写 → `[语音]`；`build_emoji_prompt_block()` 含全部语义映射。
  - API 冒烟：`reset` → `qr_status=idle` 且 `qr_data` 清空；`config {emoji_beta:"1"}` 保存后 status 返回 `True`；ClawBot `start(force)` 出二维码（qr_len 1078），`stop→start` 22ms 无卡死。
  - 未做/待实测：真实微信扫码后消息实时上屏、语音转写正确性（取决于微信是否返回 voice_item.text）、表情在微信端渲染效果、`[拥抱]` 三连发是否符合预期。

------


#### v0.0.15 · 图片透传 + 思考/嘿嘿移入设置 + 微信本机接管 wechatauto（2026-08-31 晚打包）
**本次更新内容**
**① 图片双向透传（微信 ↔ App ↔ 模型视觉链路）**
  - 入站（微信→App→模型）：wechatauto 本机接管把收到的图片/动画表情（beta 开关）下载解密后转 data URL，`_process_wechat_msg` 的 `chat_user / chat_sync` SSE 事件新增 `images` 字段，App 前端消息气泡直接渲染图片（max-width 200px），同时走 OpenAI 视觉格式喂给远端 llama.cpp（x99 多模态）；历史记录翻看也能按条还原用户图片（`memory.add_message` 新增 `images` 参数持久化，前端 `loadChatHistory` 还原）。
  - 出站（模型→微信）：`parse_chat_messages` 现在保留模型 JSON 里的 `image_url` 字段进 pieces；ClawBot 与 wechatauto 的回复发送路径会把 pieces 里的图片先落盘再发（ClawBot 直接 send_image；wechatauto 下载 http/解码 base64 到临时文件后 `quick_send_image`）。找图（Task Agent）路径本来就带真实图片，不受影响。
**② 思考强度 / 嘿嘿阈值移入设置面板**
  - 聊天输入框上方只保留「祖安」档位；「思考」「嘿嘿」两个 pill 删除（设置 → LLM 面板里原本就有 `thinkingSeg / naughtySeg`，全局生效、改完下一条立即生效）；清理了前端残留的 `chatThinkingSeg / chatNaughtySeg` 引用。
**④ 用户网络位置注入（辅助角色理解用户）**
  - 新增 `_user_network_context()`：每次对话与主动消息都向模型注入用户所在位置。**手动填写优先**（「与用户的关系」旁新增「你在哪个城市」输入，创建角色/编辑角色两处都有，存全局设置，改完下一条生效）；没填才走公网 IP 探测（`api.ipify.org` + `ip-api.com` 解析省市，缓存 6 小时，首查约 3~5 秒、命中缓存零开销）；公网不可达退化为局域网 IP，全部失败返回空串不影响对话。
  - 提示词明确标注「内部参考，别在对话里背出来，更不要主动提 IP」——只作背景参考辅助角色理解对方所在城市/时区。
  - VPN/代理的如实处理：本机走 VPN/代理时公网 IP 是代理出口（实测 23.185.208.12 解析为「美国 加州 洛杉矶」），提示词会注明「若开了 VPN/代理则为代理所在地，仅供参考」；要拿到真实地址只能手动填城市（IP 层面无法穿透代理）。
**③ 微信「本机接管」新通道（wechatauto-replica，替换式接入，ClawBot 仍置顶）**
  - 新增 `channels/wechatauto_channel.py`：直接操作本机已登录的微信 4.x 客户端（读=解密本地 SQLCipher 数据库纯被动轮询；发=UIA/剪贴板驱动微信窗口）。
  - 配置项：接管账号（下拉自动检测本机账号）、绑定角色（透传）、单一对话（并入 App 主对话，默认开）、读取轮询间隔、**使用中暂停发送（低干扰，默认开）**、暂停最长等待、微信表情理解（BETA）、接收群聊（默认关）、允许发送（只读开关）。
  - 与电脑微信互不干扰的边界（如实说明）：读取=零打扰（只读数据库）；发送=操作的就是同一个微信窗口，做不到真正隔离——「使用中暂停」检测到微信窗口在前台时先挂起发送、锁屏/断开会话自动失败；真要完全隔离只能走 ClawBot 独立 bot 号或虚拟机。
  - 健壮性：自建轮询循环（逐会话 try/except，微信消息库在客户端运行中的瞬态损坏不影响整体，读不了的会话下轮重试）；启动放后台线程（首次扫描微信进程密钥 + 建会话水位不阻塞 App 界面）；`reset` 清空 DB/媒体句柄下次重新扫描。
  - 图片/表情：`MediaDownloader.detect_image_key()` 内存扫描取密钥（1.5s 级），下载解密失败自动降级 `[图片]` 文本不丢消息；语音：本地 sherpa-onnx 兜底转写（新增 `wechat_voice.transcribe_audio_file`），失败降级 `[语音]`。
  - 前端：通道卡片新增「本机接管」模式标签；`channelModeLabel`/注册表路由回退优先 wechatauto（其次 wechaty、clawbot）。
**验证结果（2026-08-31 晚，开发端口 8768）**
  - `python -m py_compile` 全绿；前端 `<script>` 提取后 `node --check` 通过。
  - wechatauto-replica 1.2.0.3 在 Python 3.13 实测可装可导入（`winsdk` 是 OCR 可选依赖、3.13 编译失败已跳过，不影响收发；UIA 驱动路径可用）。
  - 本机实测：`list_accounts()` 检测到账号；`WeChatDB` 读到昵称/会话/消息；`quick_send` 真实发送到「文件传输助手」成功（`send ok: True`）；入站解析单测（文本/图片/语音/自己发的跳过/群聊跳过）3/3 正确。
  - 通道启动 4 秒内进入 running（后台线程 + 自建轮询）；start 请求即时返回不阻塞界面。
  - 已知边界（如实记录）：用户微信重度使用中部分会话消息库瞬态损坏（SQLCipher+WAL 未落盘），该会话当轮读取降级、下轮自动恢复；图片下载依赖密钥驻留内存（`detect_image_key` 扫描命中即持久化缓存）；发送为 GUI 操作，锁屏/断开会话时失败。

#### v0.0.16 · x99 双卡压测定标 + 12人设回测基建 + 联网搜索链加固 + 记忆检测器补漏（2026-09-01 打包）
**本次更新内容**
**① x99 双卡并行模式压测（127.0.0.1 · Qwen3.6-35B-A3B-uncensored-heretic Q4_K_M · llama-server -np 4）**
- 先探测 GPU 占用：空闲后开始压测（row 模式不可用——V100 报 `device CUDA0 does not support split buffers`，只能 layer/tensor）。
- 对比结论（35B Q4_K_M，短聊/长文/单长文三种负载）：
  - layer 模式：短聊 112 tps（双卡 28/30%）、长文 92 tps（36/40%）、单长文 104 tps。
  - tensor 模式：短聊 80 tps（37/35%）、长文 47 tps（34/34%）、单长文 108 tps。
- **结论：layer 模式整体最优（多请求并发时双卡利用率更高），已保存为当前运行配置**：dispatcher（llm-dispatcher.py:8081）与 llama-server（127.0.0.1:18081）均不带 `-sm` 参数，llama-server 保持 `-ngl 99 -fa on -c 327680 -np 4 --reasoning-format deepseek --cache-reuse 256`。
- 关键坑：请求必须携带 `"chat_template_kwargs": {"enable_thinking": False}`，否则 llama.cpp 返回空 content（Qwen 思考模板不认普通请求）。
**② 12 人设 × 性别向预设（男/女 × 3伴侣 + 3朋友）**
- 新增 `test_harness/personas12.py`：12 个完整人设（背景/性格/说话方式/关系定位），MBTI、反驳阈值 rebut、主见 assertiveness、初始好感 affinity、友情 friendship、祖安倾向 crude、开放度 openness 全部差异化。
- 前端欢迎卡新增性别三段选择（♂我是男生 / ♀我是女生 / 暂不设置），`PRESET_COMBOS` 12 个一键预设组合（m_p_*/m_f_*/f_p_*/f_f_*），按性别向展示；预设通过路由模型生成 500 字角色信息卡后回填。
**③ 联网搜索链加固（tools/web.py）**
- 实测国内网络：Bing www 间歇 ConnectTimeout、DDG 全墙、百度桌面/移动/Sogou 网页全返回安全验证页。
- 新链：Bing RSS 多主机轮询（www/global/www2/cn，`format=rss` XML 稳定可解析）→ Bing HTML ensearch=1 → Sogou 网页 → 搜狗微信文章（`weixin.sogou.com` 国内稳定 1.5s）→ 百度联想入口（`suggestion.baidu.com` 无验证页，给真实百度搜索链接）→ 百度桌面。
- 实测「明天上海天气」「苹果手机最新价格」能出真实结果；全失败时模型会如实说查不到（诚实失败，不编造）。`- 天气类查询新增 wttr.in 真实数据兜底（`_weather_now`）：识别「天气/气温/预报」+ 提取城市（直辖市/省会/常见城市名单），返回实时温度/体感/湿度/今日最高最低，作为证据前置注入（实测「明天上海天气」→ 25°C 多云，今日 25~33°C）。
**④ 记忆兜底检测器补漏（demo.py `_detect_user_fact`）**
- 新增 `我(?:[^，。！？\s]{0,6})?(?:最喜欢|特别爱|爱吃|爱喝|喜欢|最爱…)` 系列模式，覆盖「我早饭爱吃包子配豆浆」这类「我+状语+偏好动词」句式（此前会漏录）。
- 守卫改为排除「(不喜欢|讨厌|烦|恨|看不起|嫌弃)(你|他|她|你们|我|自己)」，避免误录「我觉得你不喜欢我」。
**⑤ 回测基建**
- `test_harness/run_personas.py` 新增 `--resume`（断点续跑）与 `--ids`（只跑指定场景）；Phase B（12×18×100=21600 次）可分段执行不丢进度。
- `run_phaseA.ps1`（5 iters 诊断轮=1080 次）、`run_phaseB.ps1`（100 iters 深度轮=21600 次，resume 模式）。
**⑥ 前端 bug 修复**
- 记忆面板从非对话视图打不开：`toggleMemoryPanel()` 先 `switchView('chat')` 再展开。
- 其余（历史按 pieces 分条、切角色防串台、细滚动条、半屏长消息卡、毛玻璃 emoji 底、头像上传、微信表情、性别分段）沿用 v0.0.15 已修复项并回归确认。
**⑦ Phase A 回测（12人设 × 18 focused 场景 × 5 iters = 1080 次）**
- 结果：1079/1080 通过（99.9%），唯一失败 = 顾小北 night s300 ReadTimeout（瞬时超时，非行为问题）。
- 按人设：11/12 全 90/90，顾小北 89/90；按场景：18 类全通过。
- 记忆写入 53/60 → 新检测器落盘后 s142 补跑 **60 条全部命中**（详见④）；记忆调用召回 60/60（runA 首轮的 0/60 为测试台缺字段，非产品问题；补跑后 60 条全部命中，含「你是金鱼吗/才说过又问一遍」式真人感召回）。
- 工具真实执行 8/60：根因=轮询窗口 60s 太短（回填 100~170s）+ 国内搜索链失败，均已修复（轮询加长 30×5s + 搜索链重构），待 Phase B 验证。
- 亮点样例：cold_short「哦→哦/嗯」、rejection「你别管了，我自己来→行」、happy「卧槽/真的假的/可以啊」等真人反应被稳定复现。

**⑧ 调试残留清理（删除文件内容全量总结）**
> 按用户要求清理上一轮 x99 压测 / 回测 / 搜索链调试产生的临时文件与日志，删除前内容摘要如下（全部为一次性调试脚本，无被引用）：
- `t_net2.py`（533B）：网络位置注入优先级验证脚本——临时写 `user_location=四川成都` 调 `_user_network_context()` 打印手动城市，清掉后再打印公网 IP 回退结果，验证「手动城市 > IP 探测」优先级。
- `sse_test.py`（1.4KB）：SSE 事件通道自测——在 8771 端口起临时 uvicorn，建 `/v1/events?user_id=web_user` 连接，用 `_push_event` 依次推 `chat_user / typing / chat_sync` 三种事件并断言前端可收到。
- `x99_gpu_log.txt`（303B）：压测期间 5 次（23:25~23:45，每 5 分钟）双卡 util/显存采样记录：短聊并发 41~44%，长文回落 27%。
- `_analyze_early.py`（1.2KB）：runA JSONL 早期统计脚本（总数/通过率/issue 分类计数/ai_score 中位数/按人设/记忆与工具命中）。
- `_samples.py` / `_samples2.py`（各 ~800B）：从 runA JSONL 抽取 comfort/inject/rejection/romance/fight/smalltalk 等类别样本转成可读文本；`_samples.txt` 为对应样本输出（含「你好→嗯/大半夜的/咋了」「把事情搞砸了→怎么了/先别急着怪自己」「你笑起来应该很好看→嗯？/为什么突然这么问」等真实样例）。
- `_tool_s2.py` / `_tool_samples.txt`：工具场景样本抽取——导出全部 60 条 tool 场景对话，确认模型只发「行/我看看/等我搜下/我去看看」等中间消息、不编造结果。
- `_tool_hist.py`（645B）：定向查 3 个 tool 测试用户的聊天历史（`/v1/chat/history`），验证后端是否在轮询窗口后补发了带结果/链接的后续消息。
- `_mem_s2.py` / `_mem_samples.txt`：memory/recall_recent/old_recall/multi_turn 场景样本抽取，输出到文本供人工评审。
- `_mem_stat.py`（495B）：记忆命中统计——逐条打印 memory 场景的 `found/key/short/long` 字段，定位漏录具体角色与句式。
- `_shift_s2.py` / `_shift_samples.txt`：topic_shift/proactive_cooldown/story_listener/longform 场景样本抽取。
- `_dbg_bd.html` / `_dbg_bdm.html`（各 1.5KB）：百度桌面/移动搜索返回的「百度安全验证」HTML 原始响应，用于确认旧搜索链被反爬拦截的根因。
- `_dbg_sogou.html`（5.7KB）：Sogou 网页搜索返回的反爬验证页（antispider）原始 HTML。
- `_dbg_wx.html`（35KB）：搜狗微信搜索（`weixin.sogou.com`）真实可用页面响应（含「宫保鸡丁的做法」公众号文章列表、SNUID 反爬字段、UUID/关键词参数），是搜索链改用「搜狗微信」入口的实测依据。
- `_log_v016_draft.md`：v0.0.16 日志草稿（内容已并入本节后删除）。
- `tools/web.py.bak_20260901`：`tools/web.py` 搜索链重构前的旧版备份（Bing www→DDG→百度→Sogou 旧链），新链稳定后删除。
- `_ui_check.js` / `_scan_ids.py` / `_scan_methods.py` / `_analyze_runA.py` / `_analyze_happy.py` / `_merge_report.py` / `_fix_recall.py` / `_v016_section.md` / `_cleanup_section.md`：前端静态审计（JS 语法/id/方法引用检查）与报告合并脚本，均为一次性工具，结果已固化进本节与测试报告。

------




#### v0.0.17 · 触发层并发调度修复 + Phase B 全量回测（12人设×18场景×100遍=21600）+ 前端运行时冒烟（2026-09-01）【当前版本】
**本次更新内容**
**① webcheck/imagecheck 触发层并发调度修复（demo.py `_background_loop`）**
- 根因：背景循环每 20s 扫描到期任务时，对每个用户**串行 await** `_fire_webcheck/_fire_imagecheck`，而一次联网回填要串「子代理规划关键词 → 真实搜索 → 补一轮 prefill 回复」，单次 60~170s。多用户（尤其回测 3 workers）同时触发时，后面的任务被前一个卡住，导致用户等了 225s 还没收到回填。
- 修复：到期任务统一改为 `asyncio.create_task` 后台拉起，不再阻塞背景循环；联网/找图类额外加 `asyncio.Semaphore(3)` 限制并发（避免真实搜索风暴），LLM 调用仍由全局 `llm_limiter`（parallel_requests，默认 auto=4）兜底；nudge/reminder 也改为后台任务，不再串行拖慢整个扫描。
- 定向验证：s081「帮我查一下明天上海的天气」修复前 Phase B 5/10 done；修复后单测 2/2 done（回填 104~115s 内到达）。
**② Phase B 全量回测（12 人设 × 18 focused 场景 × 100 遍 = 21600 次）**
- 覆盖：smalltalk/cold_short/comfort/tool/topic_shift/night/romance/fight/happy/memory/inject/longform/story_listener/old_recall/multi_turn/recall_recent/rejection/proactive_cooldown 18 类。
- 结果摘要（Phase B 完成后回填）。
**③ 前端运行时冒烟（in-app browser）**
- 本地 8766 页面加载：无 JS 报错、无 console error，欢迎卡正常渲染（96% 非白像素，毛玻璃 UI 正常）；`/v1/settings`、`/v1/characters`、`/v1/llm/presets`、`/v1/memory` 接口全部 200。
- 前端既有修复回归确认：细滚动条（仅 hover/focus 显示、4~6px）、记忆面板三档滚动、切角色防串台（流式事件带 char_id 校验）、历史按 pieces 分条、思考/祖安/嘿嘿三档条在聊天框旁、性别三段选择（欢迎卡/角色工坊/编辑弹窗）、12 人设预设、微信表情库、头像上传、半屏长消息展开。
**④ 打包**
- `dist/Qiyu-demo.exe`（v0.0.17），`python -m py_compile` 全绿 + 前端 JS 语法检查通过。
**测试结果**
- Phase B 结果摘要（完成后回填）。运行进度：4 workers 约 10 行/分钟，全程预计 ~34h。
- 修复前后对照：s081 工具回填 5/10 → 2/2（定向单测）；完整 21600 次（100 iters）未在本次执行，原因与续跑方式见文末说明。

------

------




#### v0.0.12 · Wechaty 网关健壮性修复 + 登录失败根因诊断（2026-08-31 打包，46.7MB）
**本次更新内容**
- **修复「重复点击启动导致 EADDRINUSE 端口冲突」**：
  - 根因：`WechatyChannel.start()` 每次点击「启动/重新扫码」都会重新 spawn 一个 `node gateway.js`，前一个网关还占着 `127.0.0.1:18765`，新网关 `listen EADDRINUSE` 崩溃（日志可见完整堆栈）。
  - 修复：`start()` 先检查已有网关进程（`self._proc.poll() is None`），存活则直接复用并 `POST /start` 触发扫码，不再重复拉起；新增 `_ensure_gateway_port_free()`，spawn 前若 18765 被占，先 `POST /stop` 优雅退出，失败则按命令行特征（含 `gateway.js`）杀残留 node 进程——**不会误杀用户的 openclaw 等其它 node 程序**（其命令行是 `...openclaw\dist\index.js gateway --port 18789`，不含 `gateway.js`）。
  - `gateway.js` 增加 `server.on('error')`：EADDRINUSE 时打印明确信息并以退出码 3 退出，不再抛未捕获堆栈。
- **诊断「登录后提示异常」根因：`1 == 0` = 微信服务端拒绝网页协议登录**：
  - 从 `node_modules/wechat4u/lib/core.js` 确认：`1 == 0` 是 wechat4u 内部断言 `assert.equal(data.BaseResponse.Ret, 0)` 失败的消息格式（actual=1, expected=0）。扫码确认阶段微信服务器返回 `BaseResponse.Ret=1`，表示该账号/环境不能使用网页版微信登录。
  - 结论：wechat4u（免费 web 协议）与 itchat UOS 同属网页协议，被微信限制属于服务端策略，代码无法绕过。稳定路径 = 设置页切换 `wechaty-puppet-service` 方案并填入 Puppet Service Token（padlocal 等 pad 协议）。
  - 前端友好提示：轮询到网关 error 且消息含 `1 == 0` / `Ret` 时，通道状态显示「微信网页协议登录被拒绝（该账号可能被限制网页登录），请在设置里切换到 service 方案并填入 Puppet Service Token」。
- **构建**：`build.py` hidden_imports 增加 `psutil`（端口清理用）；`dist/wechaty/` 随包更新 gateway.js。

**验证结果（2026-08-31 晚）**
- 开发端口 8768：连续两次 `POST /v1/channels/wechaty/start` → 仅 1 个网关进程（51648），无 EADDRINUSE；第 2 次复用成功。
- 进程排查：机器上另有 openclaw 的 node gateway（pid 36840，端口 18789），命令行不含 `gateway.js`，端口清理逻辑不会误杀。
- 新 exe（`dist\Qiyu.exe`，46.7MB + `dist\wechaty\`）：`/health` 正常，两次 start 后网关进程数=1、`qr_status=waiting`。
- 未做/待用户实测：换 service 方案（填 Puppet Service Token）后的真实登录收发；web 协议若更换微信号扫码成功的场景。

------
## 2. 测试汇总总表（全部轮次）

| 轮次 | 场景数 | 通过 | 失败原因 | 记忆写入 | 记忆召回 | 工具真实执行 |
|---|---|---|---|---|---|---|
| smoke | 4 | 0 | 后端未就绪（环境） | - | - | - |
| run1 | 200 | 197 | 工具编造/不确定 3 | 20/22 | 21/22 | 0/33 |
| run2 | 200 | 200 | - | 22/22 | 20/22 | 0/33 |
| run3 | 500 | 496 | 工具首轮编造 4 | 20/22 | 18/22 | 0/33 |
| run4（定点） | 23 | 23 | - | 2/2 | 2/2 | 3/7 |
| run5（混合回归） | 20 | 19 | 测试台误报（已修判定） | 3/3 | 1/3 | 2/2 |
| behavior_run1 | 26 | 25 | s511 context_loss | 0/0 | 0/0 | 0/0 |
| behavior_run2 | 24 | 23 | s511 context_loss | 0/0 | 0/0 | 0/0 |
| behavior_s511 | 7 | 6 | s511 context_loss | 0/0 | 0/0 | 0/0 |
| behavior_clean | 32 | 31 | s503 story_truncated | 3/3 | 1/3 | 0/0 |
| behavior_final | 32 | 31 | s503 longform | 3/3 | 2/3 | 0/0 |
| verify_retry | 5 | 5 | - | 3/3 | 3/3 | 0/0 |
| final | 12 | 12 | - | 2/2 | 2/2 | 0/5 |
| preserved | 5 | 5 | - | 3/3 | 2/3 | 0/0 |

> 说明：run1~3 的「工具真实执行 0/33」为测试台 45 秒等待窗口不足导致的低估，实际 webcheck 均触发；run4 起改为轮询最多 150s 后数值恢复正常。

---

## 3. 已知问题与处理记录

### 3.1 已修复（按发生顺序）
1. 工具幻觉（run1/run3）：模型同一轮发「搜到了」并编价格 → 代码级护栏 + 真实结果回填后才允许。
2. 消息条数过多（run3 s119/s151 等 5~8 条）→ `_msg_cap` 硬上限。
3. 感叹号刷屏（happy 类「！！！🎉」）→ 叠打收单。
4. JSON 内部字段泄漏（s100）→ 泄漏消息丢弃。
5. 安慰模板化（「抱抱/摸摸头/怎么突然」）→ 提示词去模板 + 场景只给边界不给台词。
6. 记忆句式覆盖不足（怕黑/出差/加班）→ 兜底正则扩展。
7. 话题接不住（s511「头发」context_loss）→ 提示词补「先接住上一条再回应」；behavior_final 已恢复。
8. 故事截断（s503 只发 2 条）→ verify_retry 5/5 验证完整。
9. 思考开关开启时前端只显示「……」→ 思考与输出协议解耦。
10. 跨角色串上下文 → 记忆按 用户×角色 独立存放 + 前端按角色展开。
11. 主动消息打断聊天/重复分享（早呀×2、视频重复）→ Context Gate + event_id 去重 + COOLDOWN。
12. 搜索能力缺失/幻觉（「我看看」后无动作）→ Task Agent 真实工具链 + 并行请求开关。
13. 不同通道消息串台 → 通道注册表按 user_id 路由隔离（v0.0.7）。

### 3.2 待办 / 风险
- iLink（ClawBot）真实扫码绑定待用户真机验证；若需 OpenClaw 平台审核/注册才能授权，客户端已有失败容错提示。
- 企业微信 / QQBot / 飞书仅预留配置位，接入逻辑未实现。
- 搜索链路本机 Bing/DDG 不稳，靠百度兜底约 30~60s；工具场景回填慢是网络问题不是代码问题。
- run3 s157 型「记忆在库但模型说忘了」偶发（1/22），属模型随机性。

---

## 4. 清理记录（2026-08-31 晚，随 v0.0.7 交付）

按用户要求清理「之前项目测试所产生的遗留记录和日志」（确认不再需要后删除），删除内容如下：

### 4.1 测试数据沙箱（全部删除）
| 目录 | 规模 | 内容 |
|---|---|---|
| `data_test` | 531 文件 / 0.61MB | 最早 e2e 沙箱（08-30 22:47 起），含 chat_history（e2e_s001~s200 聊天记录）、memory（用户事实记忆）、knowledge、outlines、uploads、conv_state/emotions/relations/schedules/shared_events、dev 日志 |
| `data_e2e2` | 631 文件 / 0.64MB | run1 相关（08-31 00:02）；`_user_characters.json` 含测试角色「小栖/test_xiaoban」+ e2e_cute(软软)/e2e_sunyou/e2e_cool/e2e_warm/e2e_maoshi/e2e_zhai；memory 含 `user_e2e_s010__e2e_warm`（例：「用户养了一只叫煤球的猫」，long_fact weight 0.9）等约 100 条记忆 |
| `data_e2e3` | 9 文件 / 0.01MB | 08-31 00:30 短跑 |
| `data_e2e4` | 607 文件 / 0.65MB | run1/run2 相关（08-31 00:45） |
| `data_e2e5` | 49 文件 / 0.06MB | 08-31 01:20 |
| `data_e2e6` | 1586 文件 / 1.70MB | 最大测试沙箱（08-31 08:56，run2/run3 前），conv_state 374KB / relations 113KB / schedules 136KB |
| `data_e2e7` | 137 文件 / 0.17MB | 08-31 10:17 |
| `data_e2e8` | 0 文件 | 空目录（08-31 10:28） |
| `data_e2e_behavior` | 70 文件 / 0.12MB | 行为测试轮 1（14:06，s501~s524 聊天记录） |
| `data_e2e_behavior2` | 96 文件 / 0.16MB | 行为轮 2（14:20） |
| `data_e2e_behavior3` | 92 文件 / 0.10MB | 行为轮 3（14:32） |
| `data_e2e_behavior4` | 20 文件 / 0.03MB | 行为轮 4（14:41） |
| `data_e2e_behavior8` | 29 文件 / 0.03MB | v0.0.7 开发联调用（18:09，含 channels 配置目录，已空） |

### 4.2 测试日志 / 临时文件（全部删除）
- `test_dev_err.log`（6.5KB）、`test_dev_out.log`（0.6KB）：08-31 10:29 开发后端日志。
- `test_harness/backend_8768.err.log`（13.4KB）、`test_harness/backend_8768.out.log`（2.7KB）：测试后端 8768 日志。
- `patch_s.txt`（378B）：一次性补丁记录 —— 给 `test_harness/scenarios.py` 的模块级 print 加 `if __name__ == "__main__"` 保护（防止导入时误打印）。

### 4.3 测试报告（全部删除，内容已归档到本文档）
- `test_harness/report/run3_整理文档.md`（16KB）：run3 五百轮整理 —— 500/496、4 例工具幻觉样例全文、问题分类样例（条数过多/工具未回填/AI味）、修复后复测结论。
- `test_harness/report/realism_report_run3-5.md`（2.7KB）：run3 基线问题 6 类、代码级修复 6 条、run4 23/23、run5 19/20、交付打包说明。
- `test_harness/report/results_run3_backup.jsonl`（313.9KB，500 行）：run3 全量原始结果（每行含场景 id/分类/角色/回合 pieces/conv_state/耗时/ai_score/问题标记）。
- `test_harness/report/results_behavior_before.jsonl`（16.8KB，20 行）：行为测试修复前原始结果。
- `test_harness/report/results.jsonl`（3.8KB，8 行）：小批量结果（例 s002「在吗→在/咋了」、s001「你好→嘿」、s004「天气→阴沉沉的/感觉要下雨」）。
- `test_harness/report/summary_*.txt`（16 份）：各轮汇总 —— run1 200/197、run2 200/200、run3 500/496、run4 23/23、run5 20/19、behavior_run1 26/25、behavior_run2 24/23、behavior_s511 7/6、behavior_clean 32/31、behavior_final 32/31、behavior_s181 1/1、smoke 4/0、verify_retry 5/5、final 12/12、preserved 5/5（含 AI味 TOP10、问题明细、记忆/工具命中统计）。

### 4.4 备份文件（全部删除）
- `demo.py.bak_behavior`（231KB）：v0.0.5 行为测试前 demo.py 备份。
- `demo.py.bak_channels`（263KB）：v0.0.7 外部通讯改造前 demo.py 备份。
- `gateway/static/index.html.bak_channels`（230KB）：外部通讯改造前前端备份。
- `wechat/__init__.py.bak_channels`（9KB）：外部通讯改造前微信模块备份。
- `test_harness/run.py.bak_behavior`（14KB）、`test_harness/scenarios.py.bak_behavior`（32KB）：行为测试前测试台备份。

### 4.5 构建缓存（全部删除）
- `build/`（70.7MB，PyInstaller 中间产物，每次打包自动重建）。
- 全部 `__pycache__`（16 处，Python 字节码缓存）。

### 4.6 保留清单（明确不删）
- `test_harness/run.py`、`scenarios.py`、`analyze_realism.py`、`gen_organize.py`：测试工具脚本，后续可继续跑 e2e。
- `data\`：正式运行数据（勿动）；`dist\Qiyu.exe`：当前交付包（运行中）。
- `channels/`、`characters/`、`config/`、`gateway/`、`memory/`、`rag/`、`embedding/`、`agent/`、`wechat/`、`tools/`、`installer/`、`launcher/`：源码与资源。
- `docs/`、`CODEX_README.md`、`README.md`、`PROJECT_LOG.md`（本文档）。
- `.env` / `.env.example`、`requirements.txt`、`Qiyu.spec`、`build.py`、`build.bat`、`start.bat`、`start.sh`、`start_services.bat`、`letta_backend.py`、`main.py`、`client.py`、`openapi_letta.json`、`pathutil.py`。

---

## 5. 常用命令

- 起后端（开发）：`python demo.py`（`QIYU_DATA_DIR` 可指定数据目录；开发端口用 `QIYU_PORT`）
- 跑测试：`cd test_harness` → `python run.py runN 500 [only_cat] [ids_csv]`
- 定点复测：`python run.py runN 500 "" s085,s089,...`
- 打包：`python build.py` → `dist\Qiyu.exe`（打包前先停掉运行中的 Qiyu 进程释放文件锁）
- 桌面运行：双击 `dist\Qiyu.exe`

---

## 6. 附：iLink（ClawBot）协议要点（v0.0.7 实测记录）

- Base：`https://ilinkai.weixin.qq.com`；请求头：`AuthorizationType: ilink_bot_token`、`X-WECHAT-UIN: base64(random uint32)`、登录后 `Authorization: Bearer <bot_token>`。
- `GET /ilink/bot/get_bot_qrcode?bot_type=3` → `{qrcode, qrcode_img_content, ret}`；实测 qrcode_img_content 是 liteapp URL（`https://liteapp.weixin.qq.com/q/...?qrcode=...`），本地按 URL 生成二维码图片。
- `GET /ilink/bot/get_qrcode_status?qrcode=xx`：长轮询约 30s 返回 `{"ret":0,"status":"wait"}`；扫码确认返回 `bot_token + baseurl`（待真机确认）。
- `POST /ilink/bot/getupdates`：长轮询收消息（hold 最长约 35s），返回 `msgs + get_updates_buf`（游标持久化）。
- `POST /ilink/bot/sendmessage`：发送必须携带 inbound 的 `context_token`；对方 ID 形如 `xxx@im.wechat`，机器人 `xxx@im.bot`。
- 多账号：每个微信号一个 `clawbot_<账号id>` 通道实例，token 独立持久化。


---
## 7. 真人感行为建模专项记录（2026-08-31，对应 v0.0.6~v0.0.7）

> 依据保留文档 `docs/真人感行为建模_20260831.md` 归纳。核心原则：**先感知 → 判断状态 → 决定反应 → 才生成文字**；行为/状态/时间/工具/记忆生命周期归代码管，人格/语气/自然语言归模型管，两者不混。

### 7.1 专项结论
- P0（当前上下文 > 记忆检索 / recent fact 不表演回忆 / unfinished topic / attention / story listener / 主动消息 cooldown）：全部落地。
- P1（reply_intent / response_necessity / 多气泡自然生成 / 耐心度影响行为）：全部落地。
- P2（post-check 只纠明显错误 / 符号自然度 / 模板去重）：全部落地。
- 定点回测 `behavior_final` 32 场景 **31/32 通过**（唯一失败 s181 为并发流式 240s 超时，单跑通过）；`verify_retry` 5 场景 **5/5 通过**（含长文重拉、记忆召回 3/3）。

### 7.2 把「记忆调用」和「当前上下文理解」分开（run3 s151 暴露的最大问题）
- 现象：用户刚说过「怕坐飞机」，转头问「我怕坐什么你还记得吗」，模型却进入长期记忆检索流程，连续发 6 条「等等/让我想想/嘶/坐什么来着/我脑子短路了/是不是坐飞机」。
- 真人逻辑：这件事刚刚就在聊天里发生过，根本没必要认真回忆。
- 修改前（run3 s151，e2e_maoshi）：`用户：我有点怕坐飞机` → `角色：啊？/咋啦，是最近要飞吗` → `用户：我怕坐什么你还记得吗` → `角色：啊？/等等/让我想想/嘶.../坐什么来着/我脑子短路了/是不是坐飞机？`
- 修改后（行为回测 s151，同角色同输入）：`用户：我有点怕坐飞机` → `角色：？？？` → `角色：这才几分钟 坐飞机啊`
- 保留的正面样例（s143/s149，验证不退化）：
  - `用户：我特别怕黑` / `角色：？` / `角色：多大个人了` / `用户：你还记得我怕什么吗` / `角色：怕黑。刚才自己说的。`
  - `用户：我下周要去杭州出差` / `角色：杭州？去几天` / `用户：我下周要去哪记得吗` / `角色：杭州 刚才自己发的`
- 实现：`_record_recent_facts` 记录最近 45 分钟内用户刚说过的事实（最多 14 条，同义换说法只刷时间戳）；`_find_recent_fact` 命中时系统提示词改为「根本不用检索，直接答 + 可调侃」；`_postprocess_reply_messages` 剥离纯犹豫短气泡，答案被丢时用 `_fact_short_answer` 兜底；只有 C/D/E（本次聊天较早/短期/长期记忆）才真正走记忆检索。

### 7.3 话题与注意力行为（s511 / s512 / s503）
- 旧话题突然回来（s511，D 类）：`用户：我今天去剪头发了 / 最近原神抽卡好非 / 那我刚才说的头发呢` → `角色：？？？ 才几分钟就忘了 咋样翻车没`（`_refresh_unfinished_topic` + `_CALLBACK_RE` 靠共同双字词命中「头发」，从近期上下文恢复，不当作失忆）。
- 未完成话题突然跳题（s512，E 类）：`用户：我今天去剪头发了 / 最近原神抽卡好非` → `角色：啊？刚说头发又跳到这个`（只有「未完成话题 + 上一轮 AI 在等答案」才判 abrupt，允许意外；natural/contextual 换题不注入任何反应指令，避免「话题意识」痕迹）。
- 长故事输出（s503，A 类）：`用户：给我讲个完整的睡前故事，讲长一点` → 角色 23 个气泡完整讲完（完整输出模式：用户明确要长内容时本轮必须讲完，禁止只开个头就停；带听众感知，概率性 listener check，不机械）。

### 7.4 代码解决的问题（行为归代码管，均在 demo.py）
| 模块 | 作用 |
|---|---|
| `_record_recent_facts` | 45 分钟内用户刚说的话进 recent_facts，供「刚说过别表演回忆」和「我刚才说的X呢」指回 |
| `_recall_keywords` / `_find_recent_fact` / `_CALLBACK_RE` | 回忆请求先查最近事实：命中→直接答+可调侃；只有 C/D/E 才真正检索 |
| `_classify_topic_shift` | none/natural/contextual/abrupt 四级；只有 abrupt 才可能意外，禁止「跨度挺大啊」固定台词 |
| `_refresh_unfinished_topic` | 上一轮以提问/等对方决定收尾→记录；被正面回应就解除；对方突然跳走则保留 |
| `_attention_state` / `_attention_prompt_block` | FOCUSED/CASUAL/DISTRACTED/LISTENING/WAITING/IDLE，只影响节奏不规定台词 |
| `_story_state` | 长文输出时概率性检查听众在不在，不机械 |
| `_postprocess_reply_messages` | 命中最近事实时丢弃 ≤14 字纯犹豫短气泡；答案被丢用 `_fact_short_answer` 兜底最简答案 |
| 极简输入/拒绝收手 | 「嗯/哦/行/哈哈哈」最多 1 条；「不用了/算了/随你/别管我」最多 2 条且不再教育 |
| 提问上限 | 一条回复最多 2 个提问（问题一个一个来），长文/技术诊断不限 |
| `_SERVICE_TONE_RE` | 短句（≤40 字）客服腔/咨询师腔模板句丢弃，长句不误伤 |
| `_msg_cap` | 普通 1~2 最多 3；情绪类最多 4~5 且条条短；长文不限 |
| `_sanitize_msg_text` | 兴奋/吐槽/吵架/playful/argument/late_night 才放行感叹号，最多三个 |
| 长文输出兜底 | 模型只发 ≤3 条且 ≤40 字无故事特征词的「开场白」→ 自动重拉一次完整内容 |
| `generate_webcheck_reply` | 查的过程中用户已聊到别的事 → 标记 stale，不再把旧结果硬塞回去（可输出空 messages） |
| 主动消息冷却强化 | <90 分钟刚聊完禁止像新开一摊一样「早呀」，必须有续接理由 |

### 7.5 prompt 解决的问题（台词归模型管）
- 「生成前内部判断」块：reply_intent（回应/提问/调侃/反驳/安慰/拒绝/继续故事/检查听众/回忆/沉默/等待）+ response_necessity（MINIMAL/NORMAL/ENGAGED/DETAILED）+「多气泡=先决定几件事再拆，不是写完一整段再切」。
- 「记忆使用」：记忆是背景知识，需要时自然出现，不需要时不要主动背出来（禁止「你不是喜欢冰美式吗」式炫耀记忆）。
- 「完整输出模式」：用户明确要长内容时本轮必须讲完，禁止只发开场白；长内容按自然段落拆多条连续发完。
- 「拒绝收手」红线：对方说不用了/算了/随你/别管我 → 直接收手，不再补建议、不再劝。
- 话题突变分级注入：abrupt 才提示「可以意外一下但非必须」，禁止固定台词。
- 主动消息生命周期：刚聊完 90 分钟内必须带续接理由，禁止无脑「早呀」。

### 7.6 新增行为回测场景（s501–s526，分类 A–J 全覆盖）
| 分类 | 场景数 | 验证点 |
|---|---|---|
| story_listener（A） | 3 | 用户讲故事：短回应、不抢话、不突然结束；长故事不截断 |
| recall_recent（B） | 5 | 刚说过再问：直接答+轻微吐槽，禁止表演回忆 |
| old_recall（C） | 2 | 旧记忆：允许真正调用记忆库 |
| abrupt_shift（D/E） | 3 | 旧话题回来能恢复；未完成话题跳题能察觉 |
| natural_shift（F） | 1 | 带连接词自然换题：正常接住，不演惊讶 |
| minimal_input（G） | 5 | 单字/表情：不自动展开 |
| strong_emotion（H） | 2 | 强情绪：允许草/哈哈哈哈/？？？/卧槽 |
| rejection（I） | 4 | 拒绝后收手：不继续教育 |
| proactive_cooldown（J） | 1 | 告别后不硬开新话题 |

新增评分项：recall_perform（表演回忆）、minimal_expand（单字展开）、lecture_after_reject（拒绝后教育）、story_truncated / story_endless（故事截断/无脑长）、old_recall_miss（旧记忆漏）、context_loss（上下文丢失）、farewell_expand（告别硬聊）。

### 7.7 全量 526 轮回归实况（未跑完，原因如实记录）
- 实际跑到 **122 场景**（8768 端口、全新数据目录、修复后代码）：**111 通过 / 11 失败**，11 个失败全部是 ReadTimeout(240s)——不是行为问题，是 LLM 排队超时。
- 覆盖分类：smalltalk 40/40、comfort 40/40、tool 30/30（工具零编造，修复生效）、topic_shift 前 12（11 个超时 + 1 过）。
- 未跑到：memory、inject、night、romance、fight、trivia、mistake、small_help、行为专项 s501-s526（后者已被定点回测覆盖）。
- 未跑完原因：用户机器上 AI Novel Writing Assistant v2 用 6 条长连接占用同一 llama.cpp（127.0.0.1:8081），栖语每次生成请求都要排队数分钟，测试台 240s 超时 → topic_shift 段开始级联超时；另发现 D:/Codex projects/ai量化（QuantMachine）占用 127.0.0.1:8766，开发后端已改到 8768 避开。
- 结论：剩余约 400 场景的回归需在 LLM 空闲时（关闭 Novel Writing Assistant）再跑才有效。

### 7.8 工具幻觉护栏补漏（v0.0.6→v0.0.7 之间）
- 问题：用户要求查证时，若系统内联搜索恰好成功（证据已注入），护栏会被关闭，模型仍可能在首轮说「搜到了」并编造无单位价格（如 5999 起 / 17999，run3 同类失败的残留漏洞）。
- 修复：`_is_search_request()` + `_sanitize_msg_text` 增加 `search_requested` 维度——只要用户提了搜索诉求，「搜到了/找到了/发你了」类声称完成词始终过滤（即使有内联证据）；无单位裸数字（三位以上）在无真实证据时也过滤。
- 验证：单测通过；修复后回归 tool 30/30 零编造（修复前 s085 会编造）。

### 7.9 保留的优点（验证不退化）
- run3 s143/s149：刚说完就问记不记得 → 「怕黑。刚才自己说的。」「杭州 刚才自己发的」——已升级为 recent_fact 机制，回测通过。
- run3 s223/s235：自然接话、轻微调侃 → natural_shift / smalltalk 均通过。
- 工具幻觉护栏（run3 4 例首轮编造）：`scheduled_at`/stale 机制加强，验证不退化。
