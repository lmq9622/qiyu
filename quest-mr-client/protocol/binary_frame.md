# Quest Protocol v1 · Binary Frame

JSON Text Frame 负责控制流（hello / 回合 / TTS 起止），Binary Frame 只承载大块负载。

## 帧布局（小端）

| 偏移 | 长度 | 字段 | 说明 |
|---|---|---|---|
| 0 | 2 | magic | 固定 `"QY"` (0x51 0x59) |
| 2 | 1 | version | 固定 `1` |
| 3 | 1 | kind | 见下表 |
| 4 | 4 | seq | uint32 序号，同一 kind 内递增 |
| 8 | N | payload | 裸数据 |

## kind

| kind | 方向 | 名称 | payload |
|---|---|---|---|
| 1 | Quest → Gateway | `audio_in_pcm16` | PCM signed 16-bit little-endian，默认 16kHz 单声道 |
| 2 | Gateway → Quest | `tts_out_pcm16` | PCM signed 16-bit little-endian，16kHz 单声道 |
| 3 | Quest → Gateway | `vision_jpeg` | JPEG 图像 |

## 语音回合时序

```
Quest                                    Gateway
  |-- binary(kind=1) xN  ----------------->|  累积 PCM
  |-- user.audio_end {sample_rate} ------->|  STT
  |<-- server.voice_transcript ------------|
  |<-- agent.speech -----------------------|
  |<-- avatar.intent ----------------------|
  |<-- audio.tts_start --------------------|
  |<-- binary(kind=2) xN ------------------|  边合成边推流
  |<-- audio.tts_end ----------------------|

打断：
  |-- client.barge_in -------------------->|  取消当前回合，停止 TTS
  |<-- server.ack {barge_in: true} --------|
  |<-- audio.tts_end {interrupted: true} --|
```

## 约束

- 单次上行音频上限 30 秒，超限丢弃并返回 `audio_too_long`。
- TTS 分片默认 8192 字节（16kHz 单声道约 256ms），客户端按 `seq` 顺序播放。
- 二进制帧与文本帧共用同一 WebSocket 连接，`session` 由连接态确定。
