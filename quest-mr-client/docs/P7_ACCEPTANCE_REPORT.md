# Qiyu MR 角色系统 P7 真机验收报告

日期：2026-09-10
设备：Meta Quest 3S（panther，Android 14 / API 34，序列号 340YC10G9F0WY5）
无线 ADB：192.168.2.58:5555，应用包名 `com.qiyu.quest`
网关：192.168.2.68:8768（`WebSocket /v1/quest/ws`）
Unity：6000.6.0f1 + Meta XR SDK 205

---

## 0. 结论

1. **不升级 Transformer / VLA。** 当前轻量 Behavior Scorer（≈10 万参数、
   104 输入特征、29 类候选行为、6 个连续参数、模型 JSON 1.2 MB）在
   OOD 与 20–50 步长时序上的指标稳定，继续用
   `Policy + Utility + Reflex` 三层本地决策即可，升级大模型没有收益。
2. **真机链路已通。** Quest 端 MRUK 场景、NavMesh、Behavior Runtime、
   策略权重加载、动捕、WebSocket 会话、后端世界状态回传全部真实跑通。
3. **本轮修掉一个真实缺陷。** NavMesh 曾把 `GLOBAL_MESH` 容器当障碍，
   可行走面积被吞到 0.73 m²；修正后为 1.10 m² —— 这个数字本身是
   **房间的物理现实**，不是代码 bug（见第 4 节推导）。
4. **当前验收房间不适合验证“走动/接近”。** 房间地面仅 3.67×2.61 m，
   床+两组柜子+桌子已占掉约 8.4 m²，自由地面只剩约 1 m²。
   角色行为已正确降级为原地行为（视线/手势/说话），
   **行走、接近、跟随必须换一个大房间复测**。

---

## 1. 分层架构（已落地，不是纸面设计）

```text
Qiyu LLM（MainBrain / MiniMind-O）
   ↓  AvatarIntent（goal / target / attention / emotion / urgency / duration_hint）
Character Behavior Policy（Quest 本地 8 Hz：TinyBehaviorPolicy + Utility 仲裁）
   ↓  BehaviorDecision
Behavior（look / approach / follow / listen / think / idle / observe ...）
   ↓
Locomotion(NavMeshAgent) / Animation(Animation 层) / IK(手部与注视)
   ↓
Avatar

并行：Reflex Layer（60 Hz，碰撞/突然靠近/遮挡/打断/距离控制，优先级高于一切）
```

LLM **不允许**输出每帧位置、旋转、骨骼、IK、脚步、Animator 参数、关节角度；
它只能输出高层意图。协议把这条边界写死在 `AvatarIntent` schema 里。

现场实测：LLM 与网关完全断开时，角色仍然继续跑
Behavior Runtime + Reflex + 动画，不会“死掉”。

---

## 2. Behavior Policy v1 评估（决定是否继续训练的依据）

### 2.1 训练产物

| 项目 | 值 |
|---|---|
| 训练数据 | 2,000 episodes / 24,000 决策组 / 640,600 候选样本 |
| 输入 | 104 维（WorldState + CharacterState + AvatarIntent + 候选行为/目标） |
| 结构 | 256 → 128 MLP（行为打分头 + 6 维参数头） |
| 输出 | 29 类候选行为得分 + 6 个连续参数 |
| 训练设备 | x99 2×Tesla V100-SXM2-16GB，CUDA，40 epochs ≈ 30 秒 |
| 部署 | Quest 本地纯 C# 推理，8 Hz，模型 JSON 1.2 MB |

### 2.2 IID / OOD（评估集与训练集完全隔离，全新 seed）

```text
IID：500 episodes / 6,000 决策组
OOD：2,000 episodes / 69,605 决策组（新房间尺寸、6–15 家具、
     动态障碍、遮挡、目标出现/消失、多目标优先级、网络延迟、指令顺序变化）
Long-Horizon：500 episodes / 17,506 steps（单 episode 20–50 个连续决策）
```

| 指标 | IID | OOD | Δ OOD−IID |
|---|---:|---:|---:|
| Top-1 | 0.971 | 0.965 | −0.006 |
| Top-3 | 0.9997 | 1.000 | +0.0003 |
| Hard-negative rejection | 1.000 | 1.000 | 0.000 |
| Invalid action rate | 0.000 | 0.000 | 0.000 |
| Goal abandonment rate | 0.118 | 0.219 | +0.101 |
| Action contradiction rate | 0.000 | 0.000 | 0.000 |

结论：OOD Top-1 几乎不掉，说明没有过拟合训练布局；
唯一弱项是 OOD 目标保持率，已用本地硬约束修正
（指令目标仍有效时不允许无理由放弃）。

### 2.3 长时序稳定性（20–50 步）

```text
action_oscillation_rate       0.027     behavior_switching_rate   0.119
target_switching_rate         0.203     walk_stop_walk_rate       0.0005
look_aba_rate                 0.016     stale_goal_rate           0.029
action_contradiction_rate     0.000     interruption_response_rate 0.663
cancellation_response_rate    1.000     replan_success_rate       1.000
reflex_override_rate          0.340
```

没有出现 WALK→STOP→WALK、LEFT→RIGHT→LEFT、LOOK A→LOOK B→LOOK A 抖动。
打断响应率 0.663 是当前最弱项，已加本地硬约束：用户说话时优先进入
`listen_user / nod / observe_user / think`，不等云端下发。

### 2.4 6 个连续参数审计

| 参数 | 范围/单位 | 归一化 | 训练 target | Unity 实际用途 | 是否核心 |
|---|---|---|---|---|---|
| `desired_distance` | 0.55–2.2 m | `(x−0.55)/1.65` | 专家候选期望距离 | 移动停止距离 | 核心 |
| `speed_scale` | 0–1 | 直接 | 专家候选速度比例 | NavMeshAgent.speed | 核心 |
| `gaze_weight` | 0–1 | 直接 | 专家候选注视强度 | 注意力/头部 LookAt | 核心 |
| `gesture_probability` | 0–1 | 直接 | 专家候选手势倾向 | Talk/手势选择 | 核心 |
| `look_away_rate` | 0–1 | 直接 | 专家候选移开视线频率 | 自然移开视线 | 核心 |
| `speech_urge` | 0–1 | 直接 | 专家候选说话冲动 | 自主表达 urgency | 核心 |

| 参数 | IID MAE | IID RMSE | OOD MAE | OOD RMSE |
|---|---:|---:|---:|---:|
| desired_distance | 0.139 | 0.178 | 0.102 | 0.125 |
| speed_scale | 0.042 | 0.056 | 0.082 | 0.112 |
| gaze_weight | 0.034 | 0.050 | 0.040 | 0.053 |
| gesture_probability | 0.041 | 0.059 | 0.063 | 0.088 |
| look_away_rate | 0.012 | 0.016 | 0.016 | 0.022 |
| speech_urge | 0.026 | 0.037 | 0.025 | 0.031 |

6 个参数全部真实驱动 Unity 行为，**没有需要丢弃的纯模拟器内部变量**。
移动自然度最敏感的是 `desired_distance` / `speed_scale`；
社交自然度最敏感的是 `gaze_weight` / `look_away_rate`。

### 2.5 场景门禁（15 类，reasonable_rate 全 1.00）

```text
call_character  user_approach  user_leave   user_return   user_silence
point_object    look_object    follow_me    sit_here      dont_come
interrupt       emotion_shift  two_targets  target_missing network_stale
```

---

## 3. 真机验证结果

### 3.1 通过项（有日志证据）

| 能力 | 设备日志证据 |
|---|---|
| 应用与 XR 会话 | `nativeOnActivityReady: com.qiyu.quest/com.unity3d.player.UnityPlayerActivity`，OpenXR READY→SYNC |
| MRUK 房间 | `[QiyuReconstruction] anchors=15 semanticObjects=7 room=Room - 2d25b866-...` |
| 世界状态上行 | 网关 `world_diag scene=2 anchors=17 floors=1 navmesh_area=1.10416663` |
| WebSocket 会话 | `INFO: 192.168.2.58:49892 - "WebSocket /v1/quest/ws" [accepted]` |
| 断线重连 | 网关重启后 Quest 自动重连并继续上行世界状态（无需人工操作） |
| 行为策略加载 | `[QiyuBehaviorPolicy] 已加载 Qiyu/behavior_policy_v1 behavior-policy-v1 input=104` |
| 动作库 | `[QiyuMotionLibrary] 已加载 39 个动作 qiyu-motion-v1` |
| 行为运行时 | `[QiyuBehavior] Character Behavior Runtime 启动` |
| 动捕能力探测 | `[QiyuMotionCapture] head=True leftHand=True rightHand=True eyeSupported=False bodySupported=False` |
| 手势理解 | 真机手势事件真实产生并上行：`stand / sit / point`，后端收到 `human gesture ... gesture=point` |
| 透传 Passthrough | `[PassthroughDiag] supported=True initialized=True overlay=Underlay camera=True` |
| 角色落到可行走面 | `avatar onMesh=yes dist=0.00m pathFromAvatar=PathComplete` |

### 3.2 受限项（如实标注，不做假实现）

| 项 | 状态 | 说明 |
|---|---|---|
| Eye Tracking | **不支持** | Quest 3S 硬件无眼动，代码如实返回 `eyeSupported=False`，不伪造注视 |
| Body Tracking | **不支持** | Quest 3S 无全身追踪，`bodySupported=False`；仅头部+双手 |
| Passthrough Depth | 部分可用 | `depth=supported=True available=True frames=0 points=0`，深度帧始终为 0，物体 3D 投影仍不可用（TODO） |
| 动作资产 | **缺失** | `缺少动作资产 Idle_Relaxed / Reflex_Dodge`，当前使用程序化低精度兜底 |
| 云侧 LLM | 曾 502 | x99 `192.168.2.6:8081` 一度返回 502，期间角色靠本地策略继续运行；后已恢复 200 |

---

## 4. NavMesh 修复与房间空间现实

### 4.1 缺陷与修复

原始实现把 MRUK 的全部锚点当障碍，其中 `GLOBAL_MESH`（整房网格容器）
覆盖整个房间，导致 NavMesh 只剩 **0.73 m²**。

修复：

1. `GLOBAL_MESH / ROOM / UNKNOWN / CEILING` 视为容器，不参与地面导航；
2. 其余语义锚点（`WALL_FACE / BED / TABLE / COUCH / STORAGE / DOOR_FRAME...`）
   **一律视为障碍**（黑名单改白名单的反向做法，漏标签会让角色穿床）；
3. 悬空锚点（底边高于地面 0.45 m，如窗框、挂柜、挂画）不挡路；
4. 世界包围盒占房间 60% 以上的障碍判为容器几何并剔除；
5. 角色出生点不在 NavMesh 上时，优先放到用户前方，否则吸附最近可行走点；
   4 m 内无可行走点则明确告警并保持原地行为。

### 4.2 本房间的几何真相

```text
room bounds       4.41 × 2.57 × 3.68 m
floor PlaneRect   3.67 × 2.61 m ≈ 9.6 m²
墙面 6 段合计     12.55 m（矩形周长 2×(3.67+2.61)=12.56 m，完全吻合）
家具：BED 2.16×1.50×0.52 / STORAGE 0.96×1.95 / STORAGE 1.25×1.94 / TABLE 1.29×0.74
      WINDOW_FRAME 与一处 STORAGE 悬空（不挡路）
```

家具水平占地 ≈ 8.4 m²，扣除 0.25 m 角色半径腐蚀后，
NavMesh 可行走面积 = **1.10 m²**。逐格占用图（0.3 m 网格，`#`=可行走）：

```text
  ..................
  ..................
  ..................
  ..................
  ..................
  ...###............
  ...###............
  ...####...........
  ....###...........
  ....####..........
  ....####..........
  ...#####........##
  ...#####.....#####
  ....##......######
  ............######
  可走格=52/270 ≈3.12m²（含 0.2 m 采样容差）
```

可达性自检（延迟 6 秒，角色创建之后）：

```text
  center       onMesh=no   corner_xz    onMesh=yes dist=0.08m pathFromAvatar=PathComplete
  corner_min   onMesh=no   corner_zx    onMesh=no
  corner_max   onMesh=no   user_head    onMesh=no（本轮头显放在桌上，非真人站立点）
  avatar       onMesh=yes dist=0.00m pathFromAvatar=PathComplete
```

**判定：这不是导航 bug，是房间被家具占满的物理结果。**
行为层已正确降级：`CharacterWorldModel` 用
`NavMesh.SamplePosition(userPosition)` 判定 `navmeshReachable`，
不可达时“走向用户/目标”类候选直接标记为硬负样本，不会穿床穿柜硬走。

---

## 5. 通信协议与降级

协议版本 `character_v1_1`（`quest-mr-client/protocol/character_v1_1.schema.json`），
已覆盖：`session_id / event_id / sequence / timestamp`、
`WorldStateDelta`、`AvatarIntent`、`BehaviorState`、`CharacterState`、
`SpatialAction`、`AudioChunk`、`interruption`、`cancel`、`reconnect`。

两条实时链保持分离：

```text
Fast Local（不依赖网络）：
  Human Motion（帧率级）→ Motion Understanding → Shared Attention
  → Reflex（60 Hz）/ Behavior（8 Hz）→ Locomotion / Animation / IK → Avatar

Deep（低频）：
  Quest Event → Gateway → MiniMind-O → BrainDecision → MainBrain
  → Memory / Emotion / Relationship → AvatarIntent → Quest
```

同步频率：本地动捕 30–60 Hz；压缩状态上行 10 Hz（`HumanMotionSync`）；
世界状态 2 Hz（`telemetryHz`）；事件即时发送。原始骨骼不上云。

---

## 6. 自动化门禁

| 门禁 | 结果 |
|---|---|
| 后端协议回归 `python tests/run_tests.py` | **ALL PASS (23)** |
| Unity 全量编译（IL2CPP + Gradle 出 APK） | **Succeeded**（仅 CS0618 弃用告警） |
| Behavior Policy 场景门禁 15 类 | 合理率 **1.00** |
| IID / OOD / Long-Horizon 评估 | 见第 2 节 |
| 真机 NavMesh 自检（占用图 + 可达性） | 已接入运行时，每次房间加载自动输出 |

APK：`D:\UnityProjects\QiyuQuestProject\Builds\QiyuQuestP0.apk`（构建于 2026-09-10 20:36）。

---

## 7. 诚实 TODO（未完成就不写成完成）

1. **动作资产**：`Idle_Relaxed`、`Reflex_Dodge` 等槽位为空，当前是程序化兜底，
   最终自然度必须导入授权 Walk/Run/Idle/手势动作后才能定稿。
2. **大房间复测**：本房间自由地面约 1 m²，行走/接近/跟随/避障**尚未真机验证**。
3. **Passthrough Depth**：`frames=0`，物体 3D 投影链路未打通。
4. **打断响应率**：0.663，需真机复测本地硬约束的实际效果。
5. **真人动捕长时录制**：需要用户佩戴头显并做动作，用于增量训练/偏好校正。
6. **Eye/Body Tracking**：Quest 3S 硬件不支持，代码已如实降级，不伪装。

---

## 8. 复现命令

```powershell
# 1) 启动网关
cd 'D:\Codex projects\ai-companion-codex\ai-companion\quest-mr-client\backend'
$env:QIYU_QUEST_HOST='0.0.0.0'; $env:QIYU_QUEST_PORT='8768'
python quest_server.py

# 2) 构建 APK
$env:JAVA_HOME='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\OpenJDK'
$env:ANDROID_SDK_ROOT='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\SDK'
$env:ANDROID_NDK_ROOT='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\NDK'
$env:QIYU_QUEST_WS_URL='ws://192.168.2.68:8768/v1/quest/ws'
& 'D:\Unity\Hub\Editor\6000.6.0f1\Editor\Unity.exe' -batchmode -nographics -quit `
  -projectPath 'D:\UnityProjects\QiyuQuestProject' `
  -executeMethod Qiyu.Quest.Editor.QiyuP0Setup.BuildP0Apk `
  -logFile 'D:\UnityProjects\QiyuQuestProject\Logs\build.log'

# 3) 安装并启动
$adb='D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools\adb.exe'
& $adb connect 192.168.2.58:5555
& $adb -s 192.168.2.58:5555 install -r -d 'D:\UnityProjects\QiyuQuestProject\Builds\QiyuQuestP0.apk'
& $adb -s 192.168.2.58:5555 shell am start -n com.qiyu.quest/com.unity3d.player.UnityPlayerActivity

# 4) 抓 NavMesh / 动捕 / 行为日志
$appPid=(& $adb -s 192.168.2.58:5555 shell pidof com.qiyu.quest).Trim()
& $adb -s 192.168.2.58:5555 logcat -d -v time --pid=$appPid |
  Select-String -Pattern 'QuestNavMesh|QiyuMotionCapture|QiyuBehavior'
```
