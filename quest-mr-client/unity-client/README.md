# Qiyu Quest Unity Client（P0 源码骨架）

本目录保存可直接导入 Unity 的 Quest 端源码。

## 当前状态

真实开发机器上已安装 Unity 6000.6.0f1、Android Build Support、Android SDK/NDK 和 OpenJDK，
并已在 `D:\UnityProjects\QiyuQuestProject` 用官方 URP 模板创建工程。

当前阻塞点：

- Unity 尚未登录/激活 Personal 许可证；
- Meta XR All-in-One / MRUK 需从 Unity Asset Store 授权安装；
- 没有连接 Quest 设备。

因此本目录目前仍是：

- 可被 Unity 工程直接引用的 C# 源码；
- 建议的 `Packages/manifest.json`；
- 打开 Unity 后需要完成的 Meta SDK / 场景搭建步骤。

不允许把该状态描述为“已在真机验证”。

## 首次打开 Unity 后的步骤

1. 新建 Unity 6 URP 空工程。
2. 将本目录 `Assets/QiyuQuest/` 复制进工程。
3. 按 `manifest.example.json` 安装 NativeWebSocket、Newtonsoft JSON、Unity AI Navigation 等包。
4. 从 Unity Asset Store 安装 **Meta XR All-in-One SDK**，再按官方指引安装 MRUK / Passthrough Camera API。
5. 在场景中放 `QiyuQuestWebSocketClient`，配置 `serverUrl = ws://<Qiyu主机IP>:8766/v1/quest/ws`。
6. 运行 `python quest_server.py` 启动 Qiyu Gateway。
7. Quest 与 PC 同局域网，Build & Run 后验证 hello/heartbeat/echo。

MRUK Scene 可视化、WorldState v1 聚合、Passthrough 权限验证属于 P1，必须在 Unity 编辑器可用后真实完成。
