#### v0.0.17 · 触发层并发调度修复 + Phase B 深度回测（12×18×10=2160）+ 前端运行时冒烟（2026-09-01 打包）【当前版本】
**本次更新内容**
**① webcheck/imagecheck 触发层并发调度修复（demo.py `_background_loop`）**
- 根因：背景循环每 20s 扫描到期任务时，对每个用户**串行 await** `_fire_webcheck/_fire_imagecheck`，而一次联网回填要串「子代理规划关键词 → 真实搜索 → 补一轮 prefill 回复」，单次 60~170s。多用户（尤其回测 3 workers）同时触发时，后面的任务被前一个卡住，导致用户等了 225s 还没收到回填。
- 修复：到期任务统一改为 `asyncio.create_task` 后台拉起，不再阻塞背景循环；联网/找图类额外加 `asyncio.Semaphore(3)` 限制并发（避免真实搜索风暴），LLM 调用仍由全局 `llm_limiter`（parallel_requests，默认 auto=4）兜底；nudge/reminder 也改为后台任务，不再串行拖慢整个扫描。
- 定向验证：s081「帮我查一下明天上海的天气」修复前 Phase B 5/10 done；修复后单测 2/2 done（回填 104~115s 内到达）。
**② Phase B 深度回测（12 人设 × 18 focused 场景 × 10 iters = 2160 次）**
- 覆盖：smalltalk/cold_short/comfort/tool/topic_shift/night/romance/fight/happy/memory/inject/longform/story_listener/old_recall/multi_turn/recall_recent/rejection/proactive_cooldown 18 类。
- 结果摘要（Phase B 完成后回填）。
**③ 前端运行时冒烟（in-app browser）**
- 本地 8766 页面加载：无 JS 报错、无 console error，欢迎卡正常渲染（96% 非白像素，毛玻璃 UI 正常）；`/v1/settings`、`/v1/characters`、`/v1/llm/presets`、`/v1/memory` 接口全部 200。
- 前端既有修复回归确认：细滚动条（仅 hover/focus 显示、4~6px）、记忆面板三档滚动、切角色防串台（流式事件带 char_id 校验）、历史按 pieces 分条、思考/祖安/嘿嘿三档条在聊天框旁、性别三段选择（欢迎卡/角色工坊/编辑弹窗）、12 人设预设、微信表情库、头像上传、半屏长消息展开。
**④ 打包**
- `dist/Qiyu-demo.exe`（v0.0.17），`python -m py_compile` 全绿 + 前端 JS 语法检查通过。
**测试结果**
- Phase B 结果摘要（完成后回填）。
- 修复前后对照：s081 工具回填 5/10 → 2/2（定向单测）；完整 21600 次（100 iters）未在本次执行，原因与续跑方式见文末说明。

------