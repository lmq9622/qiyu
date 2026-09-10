# Qiyu Quest MR 客户端 · 实现状态（P0–P6）

> 分支：`quest-mr-client`
> 更新：2026-09-08
> 结论：P0–P6 的**代码骨架与后端闭环已落地并通过本机可执行测试**；
> 真机 MRUK/Passthrough/麦克风/导航部分因当前未连接 Quest 设备，尚未做真机验收，
> 本文严格区分“已实测”与“待真机验证”。

## 2026-09-10 · Character Behavior Runtime 更新

> 真机验收结果、OOD/长时序评估、NavMesh 修复与房间空间推导，
> 见 [docs/P7_ACCEPTANCE_REPORT.md](docs/P7_ACCEPTANCE_REPORT.md)。

本轮在原有 P0–P6 基础上完成：

- Protocol v1.1 兼容扩展：`AvatarIntent` 高层 goal/target/attention、
  `CharacterState`、`BehaviorState`、`InteractionEvent`、`AutonomyRequest`、
  `WorldState delta`、`seq/ack`；
- Quest 本地 Character Behavior Runtime（8 Hz 候选行为仲裁 + Utility + 滞回 + 目标锁定）；
- 60 Hz Reflex Layer（碰撞、突然靠近、遮挡、打断、障碍前向探测）；
- CharacterState（情绪/关系/耐心/精力/社交电量）与 WorldModel；
- Motion Library + Locomotion + Attention + Animation + 程序化低精度兜底；
- 自动仿真数据生成与 x99 CUDA 训练：
  - 2,000 episodes / 24,000 决策组 / 640,600 候选样本；
  - 2×V100，40 epochs 约 30 秒；
  - top-1 0.661 / top-3 0.915 / 硬负样本拒绝率 0.998 / 参数 MAE 0.048；
  - 15 类交互场景自动化测试合理率 1.00；
- 后端测试从 16 项扩展到 22 项，全部通过。

### 2026-09-10 追加：OOD / Long-Horizon / Human Motion

- OOD 泛化：IID 500 episodes、OOD 2,000 episodes、Long-Horizon 500 episodes；
- OOD Top-1 0.965 vs IID 0.971，Δ=−0.006；Top-3 1.000；硬负样本拒绝率 1.000；
- Invalid action rate 0.000；Action contradiction rate 0.000；
- Long-Horizon 抖动：action_oscillation 0.027、walk_stop_walk 0.0005、look_ABA 0.016；
- 结论：当前轻量 Behavior Scorer 不因 OOD 明显崩溃，暂不升级 Transformer/VLA；
- 已新增 Human Motion Capture、Motion Understanding、HumanInteractionEvent、
  SharedAttention、InteractionState、Human→Avatar 互动、HumanMotionSync；
- 已接入真实 Meta API：`OVRHand`、`OVRSkeleton`、`OVRBody.BodyState`、`OVREyeGaze`；
- 验收模型已确认是 aplaybox MMD 模型（原神茜特菈莉），许可禁止二次配布/商业用途，
  本地接入见 `docs/ACCEPTANCE_AVATAR.md`；
- 后端测试扩展到 22 项，全部通过。

仍未完成：

- Quest 真机验收（MRUK/深度/麦克风/动画/NavMesh/性能）；
- 专业 Walk/Run/Idle/手势动作资产导入；
- 真机行为日志回流与增量训练。

详见：

- `docs/character_behavior_architecture.md`
- `docs/protocol_character_v1_1.md`
- `behavior_policy/README.md`

## 1. 实际分支结构

```text
ai-companion/quest-mr-client/
├── protocol/                         # Protocol v1（已冻结）
│   ├── envelope.schema.json
│   ├── common.schema.json
│   ├── world_state.schema.json
│   ├── avatar_intent.schema.json
│   ├── spatial_action.schema.json
│   ├── binary_frame.md               # 二进制音频/视觉帧
│   └── message-catalog.md
├── backend/
│   ├── quest_server.py               # 在现有 demo.app 上追加 /v1/quest/ws
│   ├── qiyu_quest_gateway/
│   │   ├── gateway.py                # 协议/会话/并发回合/barge-in/二进制帧
│   │   ├── protocol.py               # Envelope 编解码
│   │   ├── models.py                 # WorldState/AvatarIntent/SpatialAction
│   │   ├── session.py                # session + 音频缓冲 + 并发回合
│   │   ├── world_state.py            # 空间状态缓存 + LLM 可读渲染
│   │   ├── planner.py                # LLM → 高层 AvatarIntent/SpatialAction
│   │   ├── audio.py                  # PCM16 ↔ WAV，复用 Qiyu STT/TTS
│   │   ├── binary_frame.py           # QY 二进制帧
│   │   └── vision_detector.py        # 复用 Qiyu VisionProvider 做物体识别
│   └── tests/                        # 15 个可执行测试
└── unity-client/Assets/QiyuQuest/
    ├── Editor/QiyuP0Setup.cs         # 一键配置 + 建场景 + 构建 APK
    ├── Scripts/Networking/           # WebSocket 客户端、Envelope、二进制帧
    ├── Scripts/Perception/           # MRUK WorldState、Passthrough、深度投影
    ├── Scripts/Voice/                # 麦克风 VAD、TTS 播放、语音闭环
    ├── Scripts/Avatar/               # AvatarIntent 路由、BlendShape、LookAt
    └── Scripts/Spatial/              # 运行时 NavMesh、SpatialAction 执行
```

Unity 实际工程：`D:\UnityProjects\QiyuQuestProject`（源码与仓库内 `unity-client/Assets/QiyuQuest` 同步）。

## 2. 运行时架构（已实现）

```text
Quest 3/3S
├─ MRUK / Scene Understanding ──► MrukSceneSummary ──► MrukWorldStatePublisher
├─ Passthrough Camera Access ───► PassthroughFrameSource ──► vision_query
├─ Environment Depth / MRUK 射线 ► ObjectDetectionProjector（2D→3D）
├─ Microphone + VAD ────────────► 二进制 PCM16 ──► user.audio_end
└─ TTS PCM 播放 + RMS 口型 ◄──── 二进制 TTS 帧
                │
                ▼  WebSocket JSON + Binary（Protocol v1）
        QuestWebSocketGateway
                │
                ▼
    demo._pipeline_web_chat_payload（现有链路，未改写）
                │
                ▼
        MessageGateway → BrainPipeline
                │
                ├─ MiniMind-O（永远第一入口）
                ├─ BrainDecision
                ├─ MainBrain（需要时）
                ├─ ToolAgent / Vision（需要时）
                └─ Memory / Emotion / Relationship
                │
                ▼
    QuestResponsePlanner（复用同一 LLMClient）
                │
        ┌───────┼──────────────┬─────────────────┐
        ▼       ▼              ▼                 ▼
   agent.speech  avatar.intent  spatial.action  audio.tts_*
        │
        ▼
Quest 执行层
├─ AvatarIntentRouter → BlendShape / LookAt / Animator
├─ SpatialActionExecutor → NavMeshAgent 路径/避障/朝向
└─ QuestMicrophoneCapture → barge_in 打断
```

关键边界：

- LLM 只输出 `AvatarIntent` / `SpatialAction` 高层意图，**不输出骨骼或逐帧坐标**；
- `SpatialAction` 的 `target_id` 必须存在于 Quest 上报的 WorldState，否则后端直接丢弃；
- Quest 本地负责实时空间计算、碰撞、导航、动画与低延迟打断；
- 后端继续使用现有 Qiyu 架构，只新增 Quest WebSocket 入口。

对现有 Qiyu 代码的三处最小 hook（`runtime/brain/pipeline.py`、`demo.py`、
`companion/llm.py`）已单独导出到
[patches/qiyu-brain-quest-hooks.patch](patches/qiyu-brain-quest-hooks.patch)，
便于审查；不传 Quest 上下文字段时现有链路行为完全不变。

## 3. 复用清单（直接复用 / 架构参考）

| 项目 | License | 采用方式 | 具体复用 |
|---|---|---|---|
| Meta MRUK `com.meta.xr.mrutilitykit` | Meta SDK License | 直接依赖 | 房间扫描、Floor/Wall/Ceiling/Table/Chair/Sofa/Storage 语义、`EffectMesh`、`GetRoomBounds`、`Raycast`、`PassthroughCameraAccess` |
| Meta XR Core `com.meta.xr.sdk.core` | Meta SDK License | 直接依赖 | `OVRCameraRig`、`OVRManager`、`OVRPassthroughLayer`、`OVRPermissionsRequester`、`EnvironmentDepthManager`、`DepthTextureAccess` |
| Meta OpenXR `com.unity.xr.meta-openxr` | Unity 包许可 | 直接依赖 | OpenXR Loader + Meta Quest Feature Set |
| Unity AI Navigation | Unity 包许可 | 直接依赖 | `NavMeshAgent`、`NavMeshBuilder`、避障 |
| NativeWebSocket | MIT | 直接依赖 | Quest WebSocket 底层收发 |
| Unity-Phanto | MIT（部分资源除外） | 架构参考 | Scene Mesh、NavMesh、家具碰撞/空间关系设计 |
| Unity-SpatialLingo | MIT | 架构参考 | Passthrough Camera、2D 框→3D 投影、空间对象+LLM 交互模式 |
| JarvisVR | MIT | 协议参考 | 版本化 Envelope、heartbeat、barge-in、音频/视觉并行通道 |
| Conversational-AI-npc-Unity | MIT | 架构参考 | STT→LLM→TTS→LipSync 事件状态机 |
| Quest MR Assistant | README 声明 MIT（无 LICENSE 文件） | 模式参考 | Passthrough→云端视觉→MR overlay；未复制代码 |
| Incarna | 需按仓库实际许可复核 | 架构参考 | VRM Avatar 与 Agent 的连接方式 |

没有引入的新依赖：Meta Spatial SDK（Kotlin 原生路线）、llamaapi（Qiyu 自有 LLM）、OpenAI/ElevenLabs/Whisper（Qiyu 已有 STT/TTS/LLM）。

## 4. 最终技术栈

| 层 | 选型 |
|---|---|
| Quest 引擎 | Unity 6000.6.0f1 + URP + IL2CPP + ARM64 |
| XR | Meta XR Core 205.0.0 + Meta OpenXR 2.6.1 + OpenXR 1.18.0 |
| 空间理解 | MRUK 205.0.0（Scene API + EffectMesh + Raycast + RoomBounds） |
| 视觉 | Passthrough Camera Access + Environment Depth + Qiyu VisionProvider |
| 导航 | Unity AI Navigation（运行时 NavMeshBuilder） |
| 网络 | NativeWebSocket（MIT）+ Protocol v1 JSON/Binary |
| 语音 | Quest 麦克风 VAD + Qiyu STT（sherpa-onnx）+ Qiyu TTS（System.Speech/edge-tts） |
| Avatar | 高层 AvatarIntent → BlendShape/Animator/LookAt；VRM 通过 UniVRM 接入（待安装模型资源） |
| 大脑 | 现有 Qiyu MessageGateway → BrainPipeline → MiniMind-O → MainBrain |

## 5. 协议 v1 摘要

- 主通道：WebSocket。
- 控制流：JSON Text Frame（`envelope.schema.json`）。
- 大块负载：Binary Frame（`binary_frame.md`，magic `QY`，kind 1=上行 PCM、2=下行 TTS PCM、3=上行 JPEG）。
- 已实现消息：
  - 上行：`client.hello/heartbeat/echo/bye/world_state/barge_in/tts_config/vision_frame_meta/vision_query`、`user.text/voice_transcript/audio_end`。
  - 下行：`server.hello_ack/heartbeat/echo/ack/error/voice_transcript/object_detection`、`agent.speech`、`audio.tts_start/tts_end`、`avatar.intent`、`spatial.action`。
- 并发语义：同一 session 同时只跑一轮；新输入或 `barge_in` 会取消旧回合与正在推送的 TTS。

## 6. P0–P6 完成情况

| 阶段 | 完成内容 | 实测结果 | 剩余问题 |
|---|---|---|---|
| P0 基础骨架 | Protocol v1 冻结；Gateway；Unity 工程；Meta XR/MRUK/Passthrough；APK 构建 | `QiyuQuestP0.apk` 构建成功（41.8 MB，Build result=Succeeded） | 未安装到真机 |
| P1 WorldState | MRUK 语义锚点/房间边界/用户头手/Avatar 姿态；后端空间渲染注入 MainBrain；`_extra_brain_context` 钩子 | 后端 15/15 测试通过；空间渲染测试通过 | 真机 MRUK 场景未验收 |
| P2 语音 | 麦克风 48k→16k + 能量 VAD；二进制上行；Qiyu STT；TTS PCM 流式下行；预缓冲播放；RMS 口型；barge-in | 真实 TTS→PCM→真实 STT 往返测试通过；TTS 二进制帧测试通过 | 真机麦克风/回声/时延未验收；无 AEC |
| P3 AvatarIntent | LLM 规划器（含关系/情绪）；AvatarIntent 路由；BlendShape 表情；口型；头部 LookAt；Animator 触发 | 规划器 fallback 与 schema 校验测试通过 | 未导入 VRM 模型；未接 UniVRM 标准表情代理 |
| P4 物体识别 | Passthrough 取帧→JPEG→后端 VisionProvider→2D 框；深度/MRUK 射线投影 3D；写入 WorldState；`need_vision` 时后端主动 `server.vision_request`，识别后自动重跑同一问题 | 视觉 JSON/bbox 归一化 + 视觉闭环重跑测试通过 | 通用 VLM 框精度有限；未接 Meta AI Blocks + Sentis YOLO；未真机验证深度 |
| P5 空间动作 | LLM → SpatialAction；目标校验；运行时 NavMesh（Floor 可行走/家具障碍）；NavMeshAgent 执行；避障/朝向/动画 | 目标不存在时后端丢弃动作（测试通过） | 未真机验收 NavMesh 与避障；未做动态障碍/个人空间 |
| P6 记忆/情绪/关系 | 复用 `_pipeline_web_chat_payload` 写入 Memory/Emotion/Relationship；规划器读取情绪与关系 | 链路与现有 Qiyu 测试一致 | 空间锚点长期持久化未做；未做跨设备记忆同步 |

### 进程级真实联调（已通过）

`python tests/smoke_live_gateway.py` 启动真实 `quest_server.py`（uvicorn + 现有
Qiyu app），用 `websockets` 客户端跑完整协议：

```text
hello_ack: True
world_state_ack: True
turn_type: agent.speech
turn_text: 又啥呢
SMOKE PASS
```

同一次日志中 MiniMind-O 真实加载（113.1M 参数，device=cpu）并执行，
`mode=direct mini_ran=True`；由于外部 LLM 服务返回 502，
Quest 规划器按设计降级为确定性 AvatarIntent，且不编造 SpatialAction。

## 7. 距离“完美目标”还差什么

### A. 代码已完成，但必须真机验收

1. MRUK 房间扫描与 EffectMesh 在 Quest 3/3S 上的真实显示。
2. Passthrough Camera Access 权限与取帧。
3. Environment Depth 可用性、2D 框→3D 位置误差。
4. 麦克风权限、VAD 阈值、端到端语音时延与回声。
5. 运行时 NavMesh 在真实家具上的可行走区域与避障。
6. APK 安装、连接 Qiyu Gateway 的 hello/heartbeat/world_state。

### B. 需要额外资源/依赖

1. **VRM Avatar 模型 + UniVRM 包**：当前 Avatar 执行层已就绪，但场景里还没有真实角色模型。
2. **高精度物体检测**：当前走 Qiyu VisionProvider（语义强、框精度一般）。要稳定识别杯子/手机并定位，建议接入 Meta AI Blocks `ObjectDetectionAgent` + Unity Inference Engine（Sentis）+ YOLO 模型，或专用检测服务。
3. **高质量 TTS 音色与 viseme**：当前 System.Speech 真实可用但音色一般；viseme 级口型需 uLipSync/OVRLipSync。
4. **真机自动化测试设备**：ADB 连接 Quest + logcat 采集。

### C. 需要继续开发的功能

1. `client.scene_delta` 增量 WorldState，降低带宽。
2. 空间锚点持久化与跨会话空间记忆（“上次杯子放在桌子左边”）。
3. 本地 Reflex：眨眼/呼吸/注视优先级、个人空间、紧急停止。
4. 动态障碍与移动家具处理。
5. 多角色/多设备 session 隔离与冲突处理。
6. 弱网重连、离线队列、隐私开关（相机/麦克风指示灯与用户同意）。
7. Quest 3S 与 Quest 3 的性能分级（分辨率、检测频率、LOD）。

## 8. 推荐开发顺序（下一步）

1. 连接 Quest 3/3S，`adb install` P0 APK，验证 hello/heartbeat/world_state。
2. 真机打开 MRUK 扫描，确认 Floor/Wall/Table/Chair 语义与房间边界。
3. 导入一个 VRM 角色，挂 `BlendShapeAvatarDriver` + `AvatarLookController` + `NavMeshAgent`，验证 AvatarIntent。
4. 真机验证语音闭环与 barge-in 时延。
5. 真机验证 Passthrough 取帧与 2D→3D 投影，再决定是否接入 Sentis YOLO。
6. 真机验证 NavMesh 行走、靠近桌子/椅子、避障。
7. 最后做空间长期记忆与性能/隐私 QA。

## 9. 本机已验证命令

```powershell
# 后端协议/语音/规划器测试
cd D:\Codex projects\ai-companion-codex\ai-companion\quest-mr-client\backend
python tests/run_tests.py
# → ALL PASS (22)

# 真实进程级联调（uvicorn + 现有 Qiyu app + MiniMind-O）
python tests/smoke_live_gateway.py
# → SMOKE PASS

# APK 构建
$env:JAVA_HOME='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\OpenJDK'
$env:ANDROID_SDK_ROOT='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\SDK'
$env:ANDROID_NDK_ROOT='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\NDK'
& 'D:\Unity\Hub\Editor\6000.6.0f1\Editor\Unity.exe' -batchmode -nographics -quit `
  -projectPath 'D:\UnityProjects\QiyuQuestProject' `
  -executeMethod Qiyu.Quest.Editor.QiyuP0Setup.BuildP0Apk `
  -logFile 'D:\UnityProjects\QiyuQuestProject\Logs\p0_build7.log'
# → Build result=Succeeded
```

## 10. 真机根因修复记录（2026-09-10 晚，UI + 输入）

这一轮不再靠猜，全部先读真机日志 / 离线布局转储定位根因，再改代码。

### 10.1 UI 白块盖住一切、圆角被切（根因两条）

用新增的编辑器离屏预览工具（`Qiyu/渲染 UI 预览图`、`Qiyu/转储 UI 布局树`）
把真实界面渲染成 PNG 并导出每个节点的 rect，量出两条硬 bug：

1. `QiyuUI.ScrollView` 里新建的 `Content` 没有清零 `sizeDelta`。
   Unity 新建 RectTransform 默认 `sizeDelta=(100,100)`，配合左右拉伸锚点
   会让内容比视口宽 100px，卡片左右各被 Viewport 的 Mask 切掉约 30px —— 
   **正好把 30px 的圆角整个切没了**，看起来就是“方形白块、圆角被遮住”。
2. `VerticalLayoutGroup.childControlHeight = false` 时，纵向布局用子级当前
   `sizeDelta` 堆叠，而卡片高度是同一帧稍后才由 `ContentSizeFitter` 算出来的。
   结果三张卡片全部按默认 100px 高叠在同一位置：
   **白卡互相覆盖、文字全部重叠**，最后一张卡的白底盖住了整片内容区。

修复：
- `ScrollView` 显式 `content.sizeDelta = Vector2.zero`；
- `ScrollView.Content` 与 `Card` 的 `VerticalLayoutGroup` 改为
  `childControlHeight = true`（由父级按 `LayoutElement.preferredHeight` 排版）；
- `Card` 不再自己挂 `ContentSizeFitter`，避免父子同时驱动同一个 rect；
- 白色磨砂叠加层 `WhiteTint/Frost` 与 `Body` 使用相同圆角半径并铺满整张卡片。

真机验证：`[QiyuUIDiag] card=Hero cardSize=(1544.00, 462.00)`（修复前是
`1644x536` 且互相重叠），Divider=2px，卡片之间恢复 24px 间距。

### 10.2 裸手完全不出现（根因：OpenXR 手部追踪子系统特性没开）

真机日志：

```
[QiyuInput] connected=Hands ... RightHand valid=True tracked=False conf=Low
            bones=26 skelPos=(0.00,0.00,0.00) tipPos=(0.00,0.00,0.00)
[QiyuHand]  subsystem=False running=False
```

项目里只勾了 `HandInteractionProfile`（手势交互 profile），
**没勾 `com.unity.openxr.feature.input.handtrackingsubsystem`
（XR_EXT_hand_tracking 手部追踪子系统）**：

- `XRHandSubsystem` 根本不会运行；
- Meta 旧接口 `OVRHand/OVRSkeleton` 也只给 PointerPose，26 个关节位置全是 0
  （整条骨骼链塌在世界原点），所以手网格退化成一个点、指尖激光无从谈起。

修复：
- `QiyuP0Setup.ConfigureOpenXR` 显式启用
  `...input.handtrackingsubsystem` 与 `...input.handtrackingdatasource`，
  并在构建日志里回读确认；
- 新增 `QiyuHandRig`：走 Unity XR Hands（OpenXR 原生关节）画可见手部骨架
  （关节球 + 骨链线），同时对外提供食指尖射线与拇指↔食指捏合距离；
- `QiyuPointerVisuals` 改为「手柄/裸手互斥 + 优先 XR Hands 指尖射线」，
  骨骼退化时退回 PointerPose，杜绝激光从世界原点射出；
- `QiyuInputVisibilityGuard` 在关节链塌缩时隐藏退化的 OVR 手网格；
- 手柄：`m_showState = Always` 且 `showWhenHandsArePoweredByNaturalControllerPoses = true`，
  修掉「自然手柄手势模式下 Meta 把手柄模型藏掉、而手又不显示」的空白状态。

真机验证：`[QiyuHand] subsystem=True running=True`（修复前 subsystem=False）。

