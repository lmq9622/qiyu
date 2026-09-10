# Qiyu MR 角色实时行为系统架构（P0 冻结版）

> 日期：2026-09-09
> 目标：Quest 3/3S 上的角色能够持续感知真实房间、理解用户状态，并像“有自主行为的角色”一样自然行动。
> 原则：LLM 只表达“想做什么”，本地实时层决定“具体怎么做”。

## 1. 当前代码审计

### 1.1 已存在且可复用

| 模块 | 位置 | 现状 | 结论 |
|---|---|---|---|
| Quest WebSocket 协议 | `quest-mr-client/backend/qiyu_quest_gateway/protocol.py`、`unity-client/.../Networking/QiyuQuestWebSocketClient.cs` | hello/heartbeat/重连/二进制帧/barge-in 已实现 | 保留，增量扩展 |
| WorldState | `MrukWorldStatePublisher.cs`、`world_state.py` | MRUK 锚点、用户头手、NavMesh、视觉物体已上报 | 保留，扩展 delta 与交互事件 |
| 房间语义与 NavMesh | `MrukSceneSummary.cs`、`RoomNavMeshBuilder.cs` | MRUK 语义 → 运行时 NavMesh 已实现 | 保留，由行为层调用 |
| 高层意图规划 | `planner.py` | 已有 LLM → AvatarIntent/SpatialAction 的结构化桥 | 重构成 AvatarIntent v1.1，只输出目标/关注/情绪/风格 |
| 表情与视线 | `BlendShapeAvatarDriver.cs`、`AvatarLookController.cs` | 情绪 BlendShape、音频口型、限幅注视已实现 | 保留，接入注意力层 |
| 空间执行 | `SpatialActionExecutor.cs`、`QuestObjectRegistry.cs` | NavMesh 路径、目标解析、避障已实现 | 保留为低层执行器，行为层不再直接下发逐动作 |
| 语音 | `QuestMicrophoneCapture.cs`、`QuestTtsPlayer.cs`、`QuestVoiceLoop.cs` | VAD、PCM 上行、流式 TTS、口型、打断已实现 | 保留，向行为层提供 speaking/listening/barge-in 事件 |
| Qiyu 大脑 | `quest_server.py` → `demo._pipeline_web_chat_payload` → MiniMind-O/MainBrain | 原有链路完整 | 保持 Gateway → MiniMind-O → BrainDecision → MainBrain → Memory/Emotion/Relationship |

### 1.2 缺失且必须新增

| 缺口 | 影响 | 本方案处理 |
|---|---|---|
| 无 CharacterState | 无法表达耐心、精力、社交电量、压力、当前行为 | 新增持久化状态与本地估计器 |
| 无 Behavior Runtime | 角色只能执行 LLM 单次动作，不能自主维持行为 | 新增 10 Hz 行为运行时 |
| 无 Reflex Layer | 碰撞、突然靠近、遮挡、打断不能立即响应 | 新增 60 Hz 反射覆盖层 |
| 无行为优先级/中断/滞回 | 会出现抽搐、频繁切换、机械重复 | 新增优先级、最小驻留、切换惩罚、硬中断 |
| 无目标选择器 | 多目标竞争时容易盯错或反复切换 | 新增候选目标评分与锁定机制 |
| 无动作库与合成器 | 只有零散 Animator Trigger | 新增 Motion Library、过渡、打断、分层手势 |
| 无自主行为 | 用户沉默时角色静止 | 新增 patience/energy/curiosity/social 驱动 |
| 无训练数据系统 | 无法学习自然行为 | 新增仿真器、专家策略、硬负样本、偏好排序 |
| 无行为策略模型 | 规则容易僵化 | 训练轻量 Behavior Scorer（不是 VLA） |
| 无自动行为验收 | 只能看 loss | 新增场景级、指标级、时序级测试 |

## 2. 最终分层

```text
MainBrain（低频，复杂理解/记忆/关系）
        ↓
MiniMind-O（中低频，即时反应/意图）
        ↓
AvatarIntent v1.1（目标 / 关注 / 情绪 / 风格 / 紧急度）
        ↓
Quest 本地 Character Behavior Runtime（5–10 Hz）
  ├─ CharacterState（情绪、关系、记忆、耐心、精力、社交电量）
  ├─ Candidate Generator（行为 × 目标 × 参数）
  ├─ Tiny Behavior Policy（学习型候选打分器）
  ├─ Utility / Safety Arbitration（约束与兜底）
  └─ Behavior Decision（高层行为）
        ↓
Motion Composer（30–60 Hz）
  ├─ Motion Library / 动画选择
  ├─ Blend / Transition / Interrupt
  └─ 手势 / 表情 / 口型 / 视线分层
        ↓
Locomotion + IK + Animator + BlendShape
        ↓
Avatar

独立并行：
Reflex Layer（60 Hz）
  ├─ 碰撞 / 卡住 / 危险
  ├─ 用户突然靠近 / 远离
  ├─ 遮挡 / 目标丢失
  ├─ barge-in / TTS 中断
  └─ 个人空间与距离控制
```

## 3. 频率与算力边界

| 层 | 频率 | 运行位置 | 职责 |
|---|---:|---|---|
| MainBrain | 事件触发，秒级 | 云端/主机 | 复杂推理、长期记忆、关系 |
| MiniMind-O | 事件触发，百毫秒级 | 主机/边缘 | 即时反应、高层意图 |
| Behavior Policy | 5–10 Hz | Quest 本地 CPU | 选行为、选目标、给连续参数 |
| Reflex | 60 Hz | Quest 本地 | 硬中断与安全覆盖 |
| Animation/Locomotion/IK | 30–90 Hz | Unity | 骨骼、脚步、朝向、口型 |

LLM 绝不输出逐帧位置、旋转、骨骼、IK、脚步、Animator 参数或关节角度。

## 4. 技术选型结论

### 4.1 不训练完整 VLA

当前项目不需要、也不适合在 Quest 上跑完整 VLA：

- VLA 通常依赖大规模视觉-语言-动作数据与较强算力；
- Quest 端无法承受高频大模型推理；
- 房间语义、导航、动画、IK 已由 Unity/Meta SDK 提供；
- 训练完整 VLA 会显著增加不可控性和调试成本。

### 4.2 训练轻量 Behavior Scorer

第一版训练一个约 2–5 万参数的候选行为打分网络：

- 输入：CharacterState + WorldState + AvatarIntent + 候选行为/目标特征；
- 输出：候选行为得分 + 连续控制参数；
- 模型：2 层 MLP + 候选/目标嵌入（可理解为轻量行为策略，不是 VLA）；
- 推理：Quest 本地 C# 纯矩阵运算，5–10 Hz，预计小于 0.2 ms/次；
- 权重：JSON 可热更新，约 200–500 KB；
- 训练：行为克隆 + 偏好排序 + 硬负样本，不先做强化学习。

训练目标不是“完成任务”，而是：

> 自然、稳定、连贯、符合情绪、符合关系、符合上下文。

### 4.3 为什么不是纯状态机

行为运行时不是 `if/else` 串联：

1. 每 tick 生成多个候选行为 × 目标组合；
2. 学习型策略和确定性效用共同打分；
3. 加入最小驻留、切换成本、重复惩罚、目标锁定；
4. 反射层可以硬中断；
5. 连续参数由策略头输出，而不是固定模板；
6. 相同状态下会根据关系、情绪、记忆、历史产生不同选择。

## 5. 训练数据策略

### 5.1 数据来源

优先级从高到低：

1. Unity 自动仿真生成的专家轨迹；
2. 人工脚本化的少量关键场景演示；
3. 真机录制的高层行为日志；
4. 公共人体动作数据只用于动作库/动画，不用于行为策略输入。

### 5.2 数据格式

每条样本包含：

```text
world_features
+ character_features
+ intent_features
+ candidate_behavior_features
+ candidate_target_features
+ history_features
→ behavior_score
→ continuous_parameters
→ hard_negative_label
```

### 5.3 硬负样本

自动注入并强制降分：

- 不必要走动、突然停走、来回转圈；
- 重复动作、高频切换、抽搐；
- 用户说话时背对用户；
- 用户离开后继续追；
- 对不存在/已消失目标动作；
- 语言与动作不一致、情绪与行为不一致；
- 碰撞、路径不自然、行为延迟。

### 5.4 第一版实际数据规模

| 数据 | 第一版实际 |
|---|---:|
| 仿真 episode | 2,000 |
| 行为决策组 | 24,000 |
| 候选样本 | 640,600 |
| 自动硬负样本 | 每决策组强制包含 |
| 自动化场景 | 15 类 × 30 seeds |
| 真机录制 | P7 后补充 |

第一版已在 x99 的 2×V100 上用 CUDA 训练 40 epochs（约 30 秒）：

```text
top-1: 0.661
top-3: 0.915
硬负样本拒绝率: 0.998
连续参数 MAE: 0.048
15 类场景合理率: 1.00
```

后续真机日志回流后，再把数据规模扩到 5,000 episodes / 150,000+ 决策组。

### 5.5 OOD 与长时序验收结论（2026-09-10）

```text
IID:          500 episodes / 6,000 决策组
OOD:          2,000 episodes / 69,605 决策组
Long-Horizon: 500 episodes / 17,506 steps
```

| 指标 | IID | OOD | Δ |
|---|---:|---:|---:|
| Top-1 | 0.971 | 0.965 | −0.006 |
| Top-3 | 0.9997 | 1.000 | +0.0003 |
| Hard-negative rejection | 1.000 | 1.000 | 0.000 |
| Invalid action rate | 0.000 | 0.000 | 0.000 |
| Goal abandonment rate | 0.118 | 0.219 | +0.101 |
| Action contradiction rate | 0.000 | 0.000 | 0.000 |

长时序：

```text
action_oscillation_rate    0.027
stale_goal_rate            0.029
action_contradiction_rate  0.000
replan_success_rate        1.000
cancellation_response_rate 1.000
interruption_response_rate 0.663
```

结论：**不需要立即升级 Transformer/VLA**。OOD Top-1 几乎不下降；
主要问题是 OOD 目标保持与打断响应，已通过运行时硬约束修正，而不是增加训练轮数。

## 6. 验收原则

不只看 loss。每次策略迭代必须同时通过：

1. 场景测试：叫角色、靠近、远离、打断、沉默、指向、命令、情绪变化、目标竞争；
2. 时序测试：行为连续性、中断延迟、重复率、抽搐率；
3. 空间测试：可达性、避障、个人空间、目标存在性；
4. 社交测试：说话时看用户、倾听时不抢话、离开/回来反应；
5. 降级测试：断网、LLM 超时、WorldState 过期、目标消失。

## 6.1 Human Motion Capture（2026-09-10 新增）

已扫描当前 Meta XR SDK 205 的实际 API，并使用真实类名：

| 能力 | Meta API | 使用方式 |
|---|---|---|
| 手部追踪 | `OVRHand` | `IsDataValid/IsTracked/HandConfidence/GetFingerIsPinching/PointerPose` |
| 手部骨骼 | `OVRSkeleton` | 需要时扩展手指/关节，不持续上传 |
| Body Tracking | `OVRBody.BodyState` | `JointLocations`、`Confidence`、`BodyJointSet` |
| 眼动 | `OVREyeGaze` | 支持且授权时使用；否则回退头部朝向 |
| 权限 | `OVRPermissionsRequester` | Body/Eye Tracking 权限 |

数据流：

```text
用户动作
→ HumanMotionCapture（30–60Hz，本地）
→ HumanMotionState
→ MotionUnderstanding（本地几何/时序识别）
→ HumanInteractionEvent
→ CharacterWorldModel.UserState
→ SharedAttention
→ Behavior Policy / Reflex
→ Avatar
```

- 原始骨骼只保留在 Quest 本地内存；
- 5–15Hz 只上传压缩状态 `client.human_motion_state`；
- 事件发生立即上传 `client.interaction_event`；
- LLM 只看到事件与压缩语义，不接触原始骨骼。

支持手势：`wave / point / come_here / stop / reach / give / sit / stand /
turn / look / nod / shake_head / high_five / push`。

`InteractionState` 支持：

```text
idle / approaching / following / watching / responding / playing /
cooperating / waiting / avoiding / interrupted
```

并显式支持 `interrupt / cancel / resume / replan`。

## 6.2 策略实现边界

Quest Runtime 只依赖：

```text
ICharacterBehaviorPolicy
```

当前实现：

```text
BehaviorPolicyV1 = 轻量 MLP Scorer + Utility + Reflex
```

已预留但不假装可用：

```text
BehaviorPolicyTransformer
ImitationPolicy
VLAAdapter
```

占位实现 `IsReady=false` 且 `Load()` 明确 TODO；只有真实权重/推理接入后才允许启用。

## 7. 诚实边界

- 当前仓库没有角色动画 FBX/Animator Controller，Motion Library 的资产槽位已建立，但真实自然动作必须导入授权动作资源后才能在真机达到最终效果；
- 真机 Quest 尚未连接，MRUK/NavMesh/动画的真实表现必须在 P7 验收；
- 第一版 Behavior Policy 先使用仿真专家数据训练，后续用真机日志持续校正；
- 在未通过场景验收前，不把“模型已训练”等同于“角色已经自然”。
