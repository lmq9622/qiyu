# Qiyu Meta Quest MR 客户端 · 第一阶段技术选型

> 状态：调研完成；方案已确认并进入实现（P0–P6 见
> [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)）。
> 当前分支：`quest-mr-client`
> 目标目录：`ai-companion/quest-mr-client/`

## 1. 结论摘要

Qiyu Quest 客户端建议采用 **Unity 6 URP + Meta XR All-in-One SDK + MRUK + Passthrough Camera API + Unity AI Navigation** 作为空间底座，不采用 Meta Spatial SDK 作为主技术栈；Meta Spatial SDK 只作为 Body Tracking、原生 MR 面板和交互语义的参考。

大脑继续复用 Qiyu 现有 `MessageGateway → BrainPipeline → BrainDecision → MiniMind-O / MainBrain / ToolAgent / Vision → Memory / Emotion / Relationship → TTS / Avatar`，新增一个 **Quest WebSocket Gateway** 作为新入口，不改写现有 REST 主链路。

Quest 端只负责：

- 空间感知、Scene Understanding、Depth、Object Detection；
- 本地 Reflex（注视、眨眼、呼吸、打断、避障、寻路执行）；
- Avatar 渲染、LipSync、VRM/Live2D 动作执行；
- 把真实房间状态整理成 `WorldState`，通过 WebSocket 上报；
- 把 `AvatarIntent` / `SpatialAction` 转成本地动画与导航命令。

LLM 不直接控制骨骼。

## 2. 推荐采用与复用方式

### Meta 官方

#### Unity-Phanto

- License：项目主体 MIT，TextMesh Pro 和少量第三方资源另有条款。
- 成熟度：Meta 官方 MR 参考应用，覆盖 Scene API、Scene Model、Scene Mesh、语义家具、碰撞、导航、Haptic。
- 直接复用/参考：
  - `Assets/Phanto/Environment/Scripts/SceneDataLoader.cs`
  - `Assets/Phanto/Environment/Scripts/SceneQuery.cs`
  - `Assets/Phanto/Environment/Scripts/SetupSceneQueries.cs`
  - `Assets/Phanto/Environment/Scripts/SceneBoundsChecker.cs`
  - `Assets/Phanto/Environment/Scripts/PhantoSceneMesh.cs`
  - `Assets/Phanto/Environment/Scripts/JsonSceneBuilder.cs`
  - `Assets/Phanto/Navigation/Scripts/FurnitureNavMeshGenerator.cs`
  - `Assets/Phanto/Navigation/Scripts/NavMeshGenerator.cs`
  - `Assets/Phanto/Navigation/Scripts/NavMeshAgentExtensions.cs`
  - `Assets/Phanto/Utils/Extensions/BoundsExtensions.cs`
  - `Assets/Phanto/Utils/Mesh/MeshExporter*.cs`
  - `Assets/Phanto/Utils/Utility/SceneUtils.cs`
- 判断：**架构参考 + 模块抽取**。不要整体搬游戏玩法，但 Scene/Navigation 层可以直接作为 Quest 空间底座。

#### Unity-MRUtilityKitSample / MRUK SDK

- Sample License：MIT。
- MRUK SDK 包 `com.meta.xr.mrutilitykit`：**Meta License**，属于 SDK 使用条款，不是普通 MIT；应作为 Unity Package 依赖安装和使用，不要重新实现或分发 SDK 本体。
- 直接复用：
  - MRUK room/floor/wall/ceiling/table/chair/sofa/door/window 语义与空间数据；
  - `EffectMesh` 场景可视化；
  - Floor Zone、Multi Spawn、Environment Raycast、Space Map；
  - NavMesh sample 用于基于真实房间生成导航网格。
- 判断：**核心能力直接采用**。Qiyu 不需要自己实现 MRUK、Scene Understanding、语义 anchor 或基础 NavMesh。

#### Unity-SpatialLingo

- License：MIT。
- 用途：Passthrough Camera、物体识别、空间对象理解、LLM、语音、MRUK、Sentis。
- 重点复用：
  - `Packages/com.meta.utilities.cameratracking/`
  - `Packages/com.meta.utilities.imageutilities/`
  - `Packages/com.meta.utilities.objectclassifier/`
  - `Packages/com.meta.utilities.speechandtext/`
  - `Assets/SpatialLingo/Scripts/Gym/GymMRUKController.cs`
  - `Assets/SpatialLingo/Scripts/Gym/GymCameraObjectTrackingController.cs`
  - `Assets/SpatialLingo/Scripts/Utilities/RoomSense.cs`
  - `Assets/SpatialLingo/Scripts/Utilities/WorldAnchorManager.cs`
- 判断：**Passthrough Camera 与 Object Detection 的主要参考来源**。`llamaapi` 只参考“空间对象上下文 + LLM 结构化输出”的接口模式，Qiyu 的 LLM 仍走 MiniMind-O/MainBrain，不接 Meta Llama API。

#### Meta Spatial SDK Samples

- License：项目主体 MIT；sample 中的 Meta SDK 和资源适用 Meta Platform Technologies SDK license。
- 用途：Kotlin/Android 原生 MR、Panels、Spatial Anchor、Scene Understanding、Body Tracking、Interaction。
- 复用：
  - `BodyTrackingSample`：骨骼关节数据参考；
  - `MixedRealitySample` / `MrukSample`：物理世界交互参考；
  - `CustomComponentsSample`：组件化数据模型参考。
- 判断：**非主技术栈，只作架构/交互参考**。除非未来决定完全走 Android 原生路线，否则不引入 Kotlin 分支。Unity 更适合 Qiyu 的 VRM/Live2D Avatar 和 NavMesh 需求。

### 开源项目

#### JarvisVR

- 仓库：`sumitaich1998/jarvisvr`
- License：MIT。
- 用途：Quest 3 MR + LLM Agent + WebSocket + 多模态感知 + holograms。
- 直接复用/参考：
  - `shared-protocol/`：Python/C#/TypeScript 三端协议绑定；
  - `shared-protocol/schema/`：envelope、scene、perception、speech、holo 等 JSON Schema；
  - `docs/PROTOCOL.md`：版本化 WebSocket envelope、heartbeat、barge-in、vision/audio 并行通道设计；
  - `unity-client/`：WebSocket client、Hologram Manager、输入/相机/麦克风捕获结构；
  - `agent-backend/`：**只参考**，不采用其 Agent 系统。
- 判断：**协议与客户端骨架优先参考**。JarvisVR 的 Agent 后端与 Qiyu 的 `MessageGateway/BrainPipeline` 冲突，必须保留 Qiyu 大脑，只抽取协议层和 Quest 端渲染/连接层。

#### Conversational-AI-npc-Unity

- 仓库：`Viid21/Conversational-AI-npc-Unity`
- License：MIT。
- 用途：Unity NPC 的 STT → LLM → TTS → LipSync 全链路。
- 直接复用/参考：
  - `ConversationEventSystem.cs`
  - `ConversationStateMachine.cs` / `ConversationStates.cs`
  - `STT/`, `LLM/`, `TTS/`, `NPC/LipSyncHelper.cs`
  - `CharacterData.cs`
- 判断：**事件驱动状态机参考**，不要把它的 Whisper/Ollama/ElevenLabs 作为后端；Qiyu 已有 STT/TTS/Brain。LipSync 也优先用 Meta 提供的 OVR LipSync 或 VRM viseme。

#### Quest MR Assistant

- 仓库：`Vtestcode/quest-mr-assistant`
- License：README 声明 MIT，但仓库根目录没有 LICENSE 文件。Qiyu 商用前应要求作者补充或保存许可声明，只抽取模式风险最低。
- 用途：Quest Passthrough 截图 → 云端 GPT-4o → 返回文本 + 2D overlay。
- 直接复用/参考：
  - `client-unity/Assets/Scripts/AssistantClient.cs`
  - `client-unity/Assets/Scripts/OverlayRenderer.cs`
  - `client-unity/Assets/Scripts/PassthroughManager.cs`
  - `backend/app/main.py`、`models.py`、`openai_client.py`、`utils.py`
- 判断：**云端视觉回退模式参考**。Qiyu 应优先本地 Object Detection，必要时再走 Qiyu 自己的 Vision/MainBrain 云端通道；不要引入 OpenAI 作为新后端。

#### Incarna

- 仓库：`andrewsegas/incarna`
- License：源码 MIT；VRM 模型和第三方资产自带许可。
- 用途：OpenClaw Agent 通过 WebXR / Quest 3 以 VRM Avatar 呈现，含语音、LipSync、表情、动作。
- 直接复用/参考：
  - `js/components/vrm-actor.js`
  - `js/components/vrm-model.js`
  - `js/components/vrm-anim-utils.js`
  - `js/components/look-at-camera.js`
  - `js/voice-chat.js`
  - `actions.json`
  - `[action:tag]` / `<<<incarna:panel ...>>>` 标记协议
- 判断：**Avatar 意图与 VRM 动作绑定参考**，尤其是“LLM 输出高层动作标记，Avatar Runtime 解释执行”。Qiyu 是 Unity 原生，不是 WebXR/A-Frame；抽取思想，不搬 JS。VRM 加载用 UniVRM。

### 其他必要组件

- VRM：`vrm-c/UniVRM`，MIT，直接用于 VRM 导入、表情、LookAt、Humanoid。
- LipSync：Meta OVR LipSync / Voice SDK，具体条款随 Meta SDK。
- Live2D：Live2D Cubism SDK 为 Live2D 专有许可，不是开源；需要按 Live2D 授权接入，不能自行重实现。Qiyu 现有 `Live2DAvatarProvider` 输出命令，Unity 端只做适配器。
- TTS/STT：继续 Qiyu 现有 `runtime/stt.py`、`runtime/tts.py`，Quest 端负责音频采集、播放和流式传输，不重复实现推理引擎。

## 3. 最终 MR 客户端技术栈

### 引擎与 SDK

- Unity 6 LTS，URP，Android 构建，目标 Meta Quest 3 / 3S。
- Meta XR All-in-One SDK。
- MRUK（`com.meta.xr.mrutilitykit`）。
- Passthrough Camera API。
- Depth API / Scene API（由 Meta SDK 提供）。
- Unity AI Navigation（NavMesh 生成、NavMeshAgent）。
- XR Interaction Toolkit / Meta Interaction SDK。
- UniVRM（VRM 1.0）。
- Live2D Cubism SDK（可选，VRM 优先）。
- Sentis 或 Meta object classifier，用于本地物体识别。

### 运行时分层

1. `Spatial Perception`：Passthrough、MRUK、Scene Mesh、Depth、Object Detection。
2. `WorldState Service`：房间、语义 anchor、物体、用户姿态、Avatar 姿态、导航信息。
3. `Reflex Controller`：LookAt、眨眼、呼吸、打断、避障、紧急停止等低延迟本地行为。
4. `Avatar Runtime`：VRM / Live2D 适配器，消费 `AvatarIntent`。
5. `Spatial Action Runtime`：NavMesh 移动、靠近/远离、面朝用户/物体、动画播放。
6. `WebSocket Client`：协议封包、重连、心跳、音频/视觉二进制通道。
7. `Audio I/O`：麦克风采集、TTS 播放、barge-in。

### Qiyu 后端新增

- 新增 `QuestGateway`（FastAPI WebSocket route）或独立 `runtime/quest_gateway.py`。
- 复用 `MessageGateway`、`BrainPipeline`、`MemoryProvider`、Emotion、Relationship、`VoicePipeline`、`AvatarProvider`。
- 不改写现有 `/v1/chat/completions`、`/v1/events` 等 REST/SSE 主链路。

## 4. 通信协议建议

### 传输

- 主通道：WebSocket JSON text frames。
- 音频上行：建议 16 kHz mono PCM16，可分帧；后续可升级 Opus。
- 音频下行：TTS 音频 chunk，建议独立 binary channel 或 `audio.tts_chunk`。
- 视觉上行：pull-based，1–3 fps，JPEG q≈70，最长边 ≤1024；低帧率可 base64，高帧率用二进制分帧。
- 心跳：客户端每 5 秒发一次，服务端回显。
- 断线重连：指数退避 + session resume。

### Envelope

```json
{
  "v": "1.0.0",
  "id": "uuid-v4",
  "type": "namespace.name",
  "ts": 1733397600000,
  "session": "uuid-v4",
  "reply_to": "uuid-or-null",
  "payload": {}
}
```

### 客户端 → Qiyu Gateway

- `client.hello`：设备、SDK 版本、能力、`user_id`、`char_id`。
- `client.bye`、`client.heartbeat`、`client.error`。
- `client.world_state`：房间、surfaces/anchors、objects、user/avatar pose、navmesh 版本。
- `client.scene_delta`：只发送变化，降低带宽。
- `client.vision_frame`：Passthrough 图像或本地识别结果。
- `client.object_detection`：label、confidence、2D bbox、3D position、anchor。
- `user.text`、`user.voice_transcript`、`user.voice_partial`。
- `client.barge_in`：打断当前回合。
- `client.interaction`：用户抓取/点击/手势/空间交互。
- `client.ack`：确认已执行某条命令。

### Qiyu Gateway → Quest

- `server.hello_ack`：session、能力、协议版本。
- `server.heartbeat`、`server.error`。
- `agent.thinking`：内部状态提示，不泄露 BrainDecision 原样。
- `agent.transcript`：回显用户语音/文本。
- `agent.speech`：最终或流式台词。
- `audio.tts_chunk`：TTS 音频块。
- `avatar.intent`：`AvatarIntent`。
- `spatial.action`：`SpatialAction`。
- `server.world_query`：请求重新上报场景或确认锚点。

### AvatarIntent

```json
{
  "id": "uuid-v4",
  "emotion": "happy",
  "intensity": 0.8,
  "expression": "smile",
  "gesture": "wave",
  "action": "look_at_user",
  "speaking": true,
  "prosody": {
    "speed": 1.1,
    "pitch": 1.05,
    "energy": 1.1
  },
  "text": "同步台词",
  "duration_ms": 1200,
  "cancel_on_barge_in": true
}
```

### SpatialAction

```json
{
  "id": "uuid-v4",
  "action": "move_to",
  "target": {
    "anchor": "object:cup_01",
    "position": [0.0, 0.0, 0.0],
    "rotation": [0.0, 0.0, 0.0, 1.0]
  },
  "speed": 1.2,
  "stop_distance_m": 0.6,
  "face_target": true,
  "avoid_obstacles": true,
  "cancel_on_barge_in": true
}
```

坐标系：右手系、米、Y 轴向上，与 Unity 一致。

## 5. 复用/自研边界

### 不复实现

- MRUK、Scene Understanding、Scene Mesh、语义 anchor。
- Depth API、Passthrough 渲染。
- 基础 NavMesh 烘焙和 NavMeshAgent。
- UniVRM、OVR LipSync / Meta Voice SDK 基础能力。
- 基础 WebSocket JSON envelope 和重连机制，可参考 JarvisVR。
- Qiyu 已有 STT、TTS、Memory、Emotion、Relationship、BrainPipeline。

### 必须自研

- Qiyu Quest 专用 `WorldState` schema 与聚合器。
- Quest 端 WebSocket client、音频/视觉二进制通道和 session resume。
- Qiyu Gateway 的 WebSocket 入口，接入现有 BrainPipeline。
- `AvatarIntent` / `SpatialAction` 到 Unity Animator/NavMesh/VRM/Live2D 的执行层。
- 2D 检测结果到 3D anchor 的融合：相机内参 + Depth/Raycast + MRUK surface。
- 本地 Reflex 与安全层：个人空间、避障、barge-in、紧急停止。
- 长期空间记忆：场景锚点持久化并与 Qiyu Memory 对齐。

## 6. 推荐开发顺序

1. **工程骨架**：Unity 6 URP + Meta XR All-in-One + Passthrough + MRUK 场景可视化 + 最小 WebSocket 客户端 + Qiyu Gateway WS echo。
2. **WorldState v0**：MRUK room/floor/wall/table/chair 等语义信息、用户头/手姿态、Avatar 姿态、增量上报。
3. **语音闭环**：Quest 麦克风 → Qiyu STT → BrainPipeline → TTS 音频 → Quest 播放 + LipSync。
4. **AvatarIntent**：情绪/表情/手势/动作，VRM 优先，Live2D 适配器后接；本地 LookAt/眨眼/呼吸/Idle Reflex。
5. **SpatialAction**：基于 MRUK 的 NavMesh，`move_to`、`look_at`、`approach`、`face_user`、避障。
6. **物体识别**：本地 Passthrough Object Detection，支持桌子/椅子/杯子；2D bbox → 3D anchor；云端 Vision 回退。
7. **记忆与人格接入**：WorldState 注入 BrainPipeline context，Memory/Emotion/Relationship 继续服务端管理；空间记忆可选落地。
8. **实时体验**：barge-in、TTS 流式、场景 delta、低延迟 Reflex、性能与耗电调优。
9. **高级交互**：Body Tracking / 手势 / 多物体交互，按 Meta Spatial SDK 或 Movement SDK 参考。
10. **设备 QA**：Quest 3 / 3S 真机、不同房间、弱网、重连、打断、导航碰撞。

## 7. 需要确认的风险

- MRUK SDK 是 Meta License，不是 MIT；只能作为 Meta SDK 依赖使用，不能直接复制或重新分发 SDK 源码。
- `Vtestcode/quest-mr-assistant` 缺少 LICENSE 文件，直接复制代码前应确认或保留 README 中的 MIT 声明。
- Live2D Cubism SDK 是专有授权，Qiyu 使用 Live2D 模型/运行时需遵守 Live2D 许可。
- Passthrough Camera API 在 Quest 真机才能完整验证；Editor/Link 只能做降级开发。
- 本地 Object Detection 的模型许可与功耗需单独评估，不能为了“像完成”而用假检测。
- Qiyu 现有后端没有 WebSocket 入口，需要新增网关，但必须保持 REST/SSE 旧路径不回归。
