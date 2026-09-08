# Qiyu Quest Protocol v1

本目录冻结 Quest ↔ Qiyu Gateway 之间的协议 v1。

协议约定：

- 主通道：WebSocket JSON Text Frame。
- 音频/视觉：后续使用独立二进制 channel 或 base64 内联；v1 schema 已预留。
- 坐标系：右手系、米、Y 轴向上，与 Unity 一致。
- 每次消息都必须带 Envelope。

冻结文件：

- `envelope.schema.json`
- `common.schema.json`
- `world_state.schema.json`
- `avatar_intent.schema.json`
- `spatial_action.schema.json`

P0 Gateway 已实现：

- `client.hello` → `server.hello_ack`
- `client.heartbeat` → `server.heartbeat`
- `client.echo` → `server.echo`
- `client.bye`
- `client.world_state` → `server.ack`（暂存 session，不接 LLM）

后续消息类型见 `message-catalog.md`。
