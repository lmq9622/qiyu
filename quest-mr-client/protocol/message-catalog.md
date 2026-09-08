# Qiyu Quest Protocol v1 · Message Catalog

## Client → Server

| type | 说明 | P0 |
|---|---|---|
| `client.hello` | 握手 | 已实现 |
| `client.heartbeat` | 心跳 | 已实现 |
| `client.echo` | 回显测试 | 已实现 |
| `client.bye` | 主动断开 | 已实现 |
| `client.world_state` | 空间世界状态 | 已实现暂存 |
| `client.scene_delta` | 空间增量 | 后续 |
| `client.vision_frame` | Passthrough 图像 | 后续 |
| `client.object_detection` | 本地识别物体 | 后续 |
| `client.barge_in` | 打断 | 后续 |
| `user.text` | 文本输入 | 后续 |
| `user.voice_transcript` | 语音转写结果 | 后续 |
| `user.voice_partial` | 语音转写中间结果 | 后续 |
| `client.ack` | 本地执行完成确认 | 后续 |

## Server → Client

| type | 说明 | P0 |
|---|---|---|
| `server.hello_ack` | 握手回复 | 已实现 |
| `server.heartbeat` | 心跳回复 | 已实现 |
| `server.echo` | 回显回复 | 已实现 |
| `server.ack` | 通用确认 | 已实现 |
| `server.error` | 错误 | 已实现 |
| `agent.speech` | 台词 | 后续 |
| `audio.tts_chunk` | TTS 音频 | 后续 |
| `avatar.intent` | Avatar 高层意图 | schema 已冻结 |
| `spatial.action` | 空间高层动作 | schema 已冻结 |
| `server.world_query` | 请求场景重传 | 后续 |
