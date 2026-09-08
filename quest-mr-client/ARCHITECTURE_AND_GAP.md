# Qiyu Quest MR 客户端 · 分支架构与差距分析

> 当前阶段：方案确认后的架构细化，尚未开始 Unity/后端实现。

## 1. 分支结构建议

```text
quest-mr-client/
├── docs/
│   ├── PHASE1_TECH_SELECTION.md
│   ├── ARCHITECTURE_AND_GAP.md
│   ├── PROTOCOL.md
│   ├── WORLD_STATE.md
│   ├── AVATAR_INTENT.md
│   ├── SPATIAL_ACTION.md
│   └── TEST_PLAN.md
├── protocol/
│   ├── schemas/                 # JSON Schema：envelope、world_state、voice、avatar、spatial
│   ├── python/                  # Python dataclass / pydantic 模型
│   └── unity/                   # C# 消息类与序列化
├── unity-client/
│   ├── Assets/QiyuQuest/
│   │   ├── Core/                # AppBootstrap、Session、Config
│   │   ├── Perception/          # Passthrough、MRUK、Depth、ObjectDetector
│   │   ├── WorldState/          # 世界状态聚合与增量编码
│   │   ├── Networking/          # WebSocket、AudioChannel、VisionChannel
│   │   ├── Avatar/              # VRM、Live2D、LipSync、Expression
│   │   ├── SpatialAction/       # NavMesh、Mover、Approach、FaceTarget
│   │   ├── Reflex/              # LookAt、Blink、PersonalSpace、BargeIn、EmergencyStop
│   │   └── UI/                  # 调试面板、权限提示、连接状态
│   └── Packages/                # Meta SDK、UniVRM、AI Navigation 等
└── backend/
    ├── qiyu_quest_gateway/      # 参考实现；实际生产代码可挂到 ai-companion/runtime/
    │   ├── ws_app.py
    │   ├── session.py
    │   ├── schema.py
    │   ├── context_builder.py
    │   └── response_composer.py
    └── tests/
```

注意：`backend/qiyu_quest_gateway/` 是隔离参考包；生产接入时会在 Qiyu 现有 `ai-companion/runtime/` 下增加一个薄入口，复用 `MessageGateway`、`BrainPipeline`、`MemoryProvider`、`VoicePipeline`、`AvatarProvider`，避免形成第二套 Agent 系统。

## 2. 运行时架构

```text
Meta Quest 3 / 3S
├── Passthrough Camera
├── MRUK / Scene Understanding
├── Depth API
├── Object Detector（本地优先）
├── Microphone / Speaker
├── Hand / Controller Input
└── Avatar Runtime（VRM / Live2D）
          │
          ▼
   WorldStateBuilder
          │
          ▼
   QuestWebSocketClient ──────────────┐
                                      │ WebSocket + Audio/Vision binary
                                      ▼
                              Qiyu Quest Gateway
                                      │
                                      ▼
                              MessageGateway
                                      │
                                      ▼
                              BrainPipeline
                                      │
                                      ├── MiniMind-O（永远第一入口）
                                      ├── BrainDecision
                                      ├── MainBrain（需要时）
                                      ├── ToolAgent（需要时）
                                      └── Vision（需要时）
                                      │
                                      ├── Memory
                                      ├── Emotion
                                      └── Relationship
                                      │
                                      ▼
                              ResponseComposer
                                      │
                          ┌───────────┼───────────────┐
                          ▼           ▼               ▼
                    agent.speech   audio.tts       avatar.intent
                                      │               spatial.action
                                      └───────────────┬───────────────┘
                                                      ▼
                                              Quest 执行层
                                              ├── Reflex Controller
                                              ├── Avatar Runtime
                                              └── Spatial Action Runtime
```

## 3. 关键数据流

### 3.1 语音对话

```text
Quest 麦克风
→ 16 kHz PCM 音频帧
→ Qiyu STT
→ user.voice_transcript
→ BrainPipeline
→ ResponseEvent
→ agent.speech + audio.tts_chunk + avatar.intent
→ Quest 播放音频 + LipSync + Avatar 表情/动作
```

### 3.2 空间理解与视觉

```text
MRUK / Scene / Depth / ObjectDetector
→ WorldStateBuilder
→ client.world_state 或 client.scene_delta
→ Qiyu Gateway 缓存/注入

需要复杂视觉理解时：
Quest Passthrough JPEG
→ client.vision_frame
→ BrainPipeline.images
→ Vision / MainBrain
→ avatar.intent + spatial.action + agent.speech
```

### 3.3 空间动作

```text
MainBrain 输出高层 SpatialAction
→ Qiyu Gateway 校验并封装
→ spatial.action
→ Quest Spatial Action Runtime
→ NavMesh 路径规划
→ NavMeshAgent 执行
→ 本地避障 / 靠近 / 远离 / 面朝用户 / 面朝物体
→ client.ack 或 client.error
```

LLM 不直接控制骨骼。所有动作必须经过 Quest 本地 Runtime 校验。

## 4. 关键模块职责

| 模块 | 职责 | 现有基础 | 缺口 |
|---|---|---|---|
| `WorldStateBuilder` | 聚合房间、家具、物体、用户和 Avatar 姿态 | 无 | 需要从 MRUK、Scene、Vision 组合 |
| `QuestWebSocketClient` | 连接、重连、心跳、JSON + 二进制收发 | 无 | 需要参考 JarvisVR 自研 |
| `Qiyu Quest Gateway` | 新 WebSocket 入口 | 现有 REST/SSE | 需新增 WS，不改旧路径 |
| `ContextBuilder` | WorldState → BrainPipeline 上下文 | 无 | 需定义 schema 和注入策略 |
| `ResponseComposer` | 生成 speech/TTS/avatar/spatial 事件 | 已有部分 Avatar/TTS | 需新增 SpatialAction 与流式组合 |
| `Avatar Runtime` | 消费 AvatarIntent | `runtime/avatar.py` 有抽象 | 无 Unity VRM/Live2D 执行器 |
| `Spatial Action Runtime` | 消费 SpatialAction | 无 | 需 NavMesh 执行层 |
| `Reflex Controller` | 低延迟反应与安全 | 无 | 需自研 |
| `ObjectDetector` | 本地物体识别与 3D 定位 | 无 | 需结合 SpatialLingo 方案 |

## 5. 距离“完美目标”还差什么

### 已具备

- MiniMind-O 永远第一入口的 `BrainPipeline`
- `BrainDecision`
- MainBrain / ToolAgent / Vision 结构
- Memory、Emotion、Relationship 系统
- TTS、STT、VoicePipeline
- AvatarProvider 抽象与 Live2D/VRC/JSON 命令输出
- 现有 REST、SSE 事件通道

### 尚缺

1. Quest Unity 工程不存在。
2. MRUK / Scene Understanding / Depth 未接入。
3. Passthrough Camera 未接入。
4. 本地 Object Detection 与 2D→3D anchor 融合未实现。
5. WorldState schema 和聚合器未实现。
6. WebSocket 客户端和 Qiyu WebSocket Gateway 未实现。
7. 音频/视觉二进制通道、session、重连、barge-in 未实现。
8. AvatarIntent 的 Unity 执行层未实现，VRM/Live2D 未接入。
9. SpatialAction 的 NavMesh 执行层未实现。
10. 本地 Reflex 与安全层未实现。
11. Memory/Emotion/Relationship 尚未注入 Quest 空间上下文。
12. 空间记忆和场景锚点持久化未实现。
13. 真机性能、弱网、耗电、导航碰撞、权限、安全测试未做。

## 6. 要做什么

### P0：基础骨架

- 创建 Unity 6 URP 工程。
- 接入 Meta XR All-in-One、MRUK、Passthrough、AI Navigation。
- 建立 Quest WebSocket 客户端。
- 建立 Qiyu WebSocket Gateway。
- 完成 `client.hello` / `server.hello_ack` / heartbeat / echo。

### P1：WorldState

- 定义并冻结 v1 WorldState schema。
- 从 MRUK 生成 room、floor、wall、table、chair 等语义数据。
- 上报用户头/手姿态、Avatar 姿态、房间边界。
- 实现增量 `client.scene_delta`。

### P2：语音 + Avatar

- 接入 Quest 麦克风，Qiyu STT。
- 接入 `BrainPipeline`，流式返回 `agent.speech`。
- TTS 音频下发与播放。
- VRM 优先，LipSync + 表情 + LookAt。
- 本地 Reflex：眨眼、呼吸、Idle。

### P3：空间动作

- 基于 MRUK 生成 NavMesh。
- 实现 `move_to`、`look_at`、`approach`、`face_user`、`face_object`。
- 实现避障、个人空间、barge-in 紧急停止。

### P4：物体识别

- 本地检测桌子、椅子、杯子等。
- 2D bbox → Depth/Raycast/MRUK surface → 3D anchor。
- 复杂场景走 Qiyu Vision/MainBrain 回退。
- 检测结果写入 WorldState 和空间记忆。

### P5：人格与记忆

- 将 WorldState 注入 BrainPipeline 上下文。
- Memory / Emotion / Relationship 保持服务端管理。
- 增加场景锚点持久化和空间长期记忆。

### P6：体验与 QA

- 流式 TTS、低延迟 Reflex、弱网重连。
- Quest 3 / 3S 真机测试。
- 权限、隐私、耗电、导航碰撞和异常恢复。

## 7. 下一步可直接启动的任务

1. 冻结协议 v1 schema。
2. 创建 Unity 工程并完成 Passthrough + MRUK 可视化。
3. 实现最小 Qiyu WebSocket Gateway 和 Unity echo client。
4. 完成 WorldState v0 数据模型。

这些任务不破坏现有 Qiyu REST/SSE 主链路，可以在独立分支上并行推进。
