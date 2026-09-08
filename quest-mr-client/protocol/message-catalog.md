# Qiyu Quest Protocol v1 · Message Catalog

控制流走 JSON Text Frame；音频/图像等大块负载走 Binary Frame（见 `binary_frame.md`）。

## Client → Server

| type | 说明 | P0 |
|---|---|---|
| `client.hello` | 握手 | 已实现 |
| `client.heartbeat` | 心跳 | 已实现 |
| `client.echo` | 回显测试 | 已实现 |
| `client.bye` | 主动断开 | 已实现 |
| `client.world_state` | 空间世界状态 | 已实现暂存 |
| `client.scene_delta` | 空间增量 | 后续 |
| `client.vision_frame_meta` | Passthrough 帧元数据（分辨率/相机位姿/内参） | 已实现 |
| `client.vision_query` | 请求后端识别最近一帧 | 已实现 |
| `client.object_detection` | 本地识别物体（Meta AI Blocks 路径预留） | 后续 |
| `client.barge_in` | 打断（取消当前回合与 TTS） | 已实现 |
| `user.text` | 文本输入 | 已实现 |
| `user.voice_transcript` | 客户端侧语音转写结果 | 已实现 |
| `user.voice_partial` | 语音转写中间结果 | 后续 |
| `user.audio_end` | 上行 PCM 音频结束，请求服务端 STT | 已实现 |
| `client.tts_config` | 开关服务端 TTS | 已实现 |
| `client.ack` | 本地执行完成确认 | 后续 |

## Server → Client

| type | 说明 | P0 |
|---|---|---|
| `server.hello_ack` | 握手回复 | 已实现 |
| `server.heartbeat` | 心跳回复 | 已实现 |
| `server.echo` | 回显回复 | 已实现 |
| `server.ack` | 通用确认 | 已实现 |
| `server.error` | 错误 | 已实现 |
| `agent.speech` | 台词（pieces） | 已实现 |
| `audio.tts_start` | TTS 音频段开始（随后为二进制 PCM 帧） | 已实现 |
| `audio.tts_end` | TTS 音频段结束/被打断 | 已实现 |
| `server.voice_transcript` | 服务端 STT 转写结果 | 已实现 |
| `server.object_detection` | 后端物体识别结果（label + 2D 框） | 已实现 |
| `server.vision_request` | 后端请求 Quest 抓一帧 Passthrough 图像 | 已实现 |
| `avatar.intent` | Avatar 高层意图 | 已实现 |
| `spatial.action` | 空间高层动作 | 已实现 |
| `server.world_query` | 请求场景重传 | 后续 |
