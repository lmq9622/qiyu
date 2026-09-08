# P0 进度与实测记录

## 已完成

- 冻结 Quest Protocol v1：
  - `protocol/envelope.schema.json`
  - `protocol/world_state.schema.json`
  - `protocol/avatar_intent.schema.json`
  - `protocol/spatial_action.schema.json`
  - `protocol/common.schema.json`
  - `protocol/message-catalog.md`
- Python Quest WebSocket Gateway：
  - `backend/qiyu_quest_gateway/`
  - `backend/quest_server.py`：在现有 Qiyu `demo.app` 上追加 `/v1/quest/ws`，不改 `demo.py`
  - `client.hello` → `server.hello_ack`
  - `client.heartbeat` → `server.heartbeat`
  - `client.echo` → `server.echo`
  - `client.world_state` → schema 校验 + `server.ack`
  - `client.bye`、错误处理、session 注册与清理
- Unity 端源码骨架：
  - `unity-client/Assets/QiyuQuest/Scripts/Networking/`
  - `unity-client/Assets/QiyuQuest/Scripts/Perception/MrukSceneSummary.cs`
  - `unity-client/Packages/manifest.example.json`
  - `unity-client/README.md`

## 实测结果

在 `quest-mr-client/backend` 执行：

```powershell
python tests/run_tests.py
```

结果：4/4 PASS。

- `test_hello_heartbeat_echo_and_bye`
- `test_world_state_is_stored_and_acked`
- `test_first_message_must_be_hello`
- `test_user_text_without_brain_returns_honest_error`

另已实测：`quest_server.py` 导入现有 Qiyu app 后，`/v1/quest/ws` 路由真实存在；未改动 `demo.py`。

## 尚未完成（真实阻塞）

当前机器：

- 未安装 Unity Editor；
- 未安装 Android SDK / Unity Android Build Support；
- 未连接 Quest 设备。

因此以下 P0/P1 内容只能交付“等待 Unity 打开的源码”，不能声称已在真机完成：

- Unity 工程实际创建与 Meta XR / MRUK / Passthrough 包安装；
- MRUK Scene 真机可视化；
- Passthrough 权限与真机表现；
- APK 构建；
- Quest → Gateway 真实端到端。

## 下一步

1. 在装有 Unity 6.0.66f2（或更高）的机器打开本目录/按 README 建工程；
2. 安装 Meta XR All-in-One SDK + MRUK；
3. 导入现有 C# 源码；
4. 跑通 Quest WS hello/heartbeat/echo；
5. 完成 MRUK Scene 可视化后进入 P1 WorldState 聚合。
