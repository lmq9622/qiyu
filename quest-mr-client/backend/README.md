# Qiyu Quest Gateway

Python 侧 P0 Gateway，负责 Quest WebSocket 入口。

运行测试：

```powershell
cd D:\Codex projects\ai-companion-codex\ai-companion\quest-mr-client\backend
python tests/run_tests.py
```

启动完整 Qiyu + Quest 服务（不改 `demo.py`，启动时给现有 app 追加路由）：

```powershell
cd D:\Codex projects\ai-companion-codex\ai-companion\quest-mr-client\backend
python quest_server.py
```

默认端口：

- 现有 Qiyu：8765
- Quest Gateway：8766

实测结果以 `tests/test_gateway.py` 为准，禁止用 Mock 替代。
