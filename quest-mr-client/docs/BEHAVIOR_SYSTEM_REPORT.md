# Behavior 系统实现报告（LLM 意图 → 行为规划 → 动作执行 → 3D Avatar）

日期：2026-09-11　分支：`quest-mr-client`
配套审计：[BEHAVIOR_SYSTEM_AUDIT.md](BEHAVIOR_SYSTEM_AUDIT.md)

---

## 1. 当前 VR 后端原架构（未改动）

```text
quest-mr-client/backend/quest_server.py         # 入口，复用 demo.app，追加 /v1/quest/ws
quest-mr-client/backend/qiyu_quest_gateway/
├── gateway.py     QuestWebSocketGateway：30+ 消息处理方法、回合编排、TTS 流
├── planner.py     QuestResponsePlanner：LLM → AvatarIntent + SpatialAction
├── models.py      Pydantic：WorldState / AvatarIntent / CharacterState / BehaviorState ...
├── protocol.py    Envelope、seq/ack、版本协商
├── session.py     QuestSession 会话状态
├── world_state.py 世界状态存储与 LLM 渲染
├── audio.py / binary_frame.py / vision_detector.py
└── tests/         stdlib 测试运行器（原 23 项）
```

Unity 侧已有：`CharacterBehaviorRuntime`(8Hz 候选仲裁)、`CharacterLocomotionController`(NavMesh)、
`CharacterAttentionController`、`MotionLibrary` + `ProceduralMotionFallback`、`CharacterReflexLayer`(60Hz)、
`HumanMotionCapture/Understanding`、`SharedAttentionController`、`InteractionStateController`。

## 2. 新增 Behavior 架构

```text
LLM
 ↓  {"behavior": {"intent": "shy", "intensity": 0.7}}      ← 唯一允许的 LLM 输出
BehaviorIntent            backend/.../behavior/models.py
 ↓
BehaviorBrain             behavior/brain.py    意图 → 组合（含冲突消解、相关性门控）
 ↓
BehaviorPlan              behavior/plan.py     Sequence / Parallel / Selector / Conditional / Repeat
 ↓
ActionRuntime             behavior/runtime.py  Channel / 优先级 / 打断 / 取消 / 冷却 / 队列 / 状态机
 ↓
AvatarAdapter             behavior/adapters.py Null / Mock / Quest（协议消息）
 ↓
Quest 端 BehaviorActionBridge.cs  →  Locomotion / 表情 / 本地行为运行时
 ↓
Unity Humanoid Avatar
```

关键设计：
- **动作名有限集合**：`ActionRegistry` 注册 55 个动作、10 个类别；
  未注册动作在 Brain 与 Runtime 两处都会被拒绝，绝不转发。
- **Channel 并行**：facial / gaze / head / gesture / upper_body / lower_body /
  locomotion / interaction / audio / system，同通道默认互斥、异通道并行。
- **优先级**：emergency 100 / interaction 80 / locomotion 70 / gesture 50 / expression 40 / idle 10；
  高优先级可抢占同通道的低优先级可打断动作。
- **相关性门控**：`relevance < 0.35` 或意图为空 → **不出行为**（允许 behavior=null），
  避免"说一句播一个动作"。

## 3. 修改的文件

| 文件 | 改动 |
|---|---|
| `qiyu_quest_gateway/planner.py` | LLM 输出新增 `behavior` 字段；新增关键词相关性门控 `_build_behavior`（11 组行为提示词） |
| `qiyu_quest_gateway/session.py` | `QuestSession` 增加 `behavior_bridge` / `behavior_task` |
| `qiyu_quest_gateway/gateway.py` | 能力协商 `behavior_v1`；`_start_behavior_ticker` / `_ensure_behavior_ticker` / `_stop_behavior_ticker` / `_apply_behavior`；barge-in 取消行为；断线回收 |
| `quest_server.py` | 回合结果透传 `behavior`（对话回合 + autonomy 回合） |
| Unity `Networking/QiyuQuestWebSocketClient.cs` | hello 声明 `behavior_v1`/`behavior_plan_v1`；新增 4 个事件与 4 个消息分发 |
| Unity `Behavior/CharacterBehaviorRuntime.cs` | 新增 `ApplyExternalIntent`（外部注入高层指令的唯一入口）；自动挂载 Bridge |
| `tests/run_tests.py` | 注册 24 个新测试 |

## 4. 新增的文件

| 文件 | 作用 |
|---|---|
| `qiyu_quest_gateway/behavior/models.py` | BehaviorIntent / ActionDefinition / ActionRef / PlanNode / BehaviorPlan / ActionRecord |
| `qiyu_quest_gateway/behavior/registry.py` | 55 个动作定义 + 校验 |
| `qiyu_quest_gateway/behavior/plan.py` | 计划构造/遍历/校验/描述 |
| `qiyu_quest_gateway/behavior/brain.py` | 意图→计划，15 个预设（greeting/shy/tease/comfort/sit_with_user/...）+ 冲突规则 |
| `qiyu_quest_gateway/behavior/runtime.py` | 分通道调度器（优先级/打断/取消/冷却/队列/状态机/事件） |
| `qiyu_quest_gateway/behavior/adapters.py` | AvatarAdapter 抽象 + Null/Mock/Quest |
| `qiyu_quest_gateway/behavior/bridge.py` | 会话级行为桥 + `build_context` |
| `tests/test_behavior.py` | 24 个行为层测试 |
| Unity `Behavior/BehaviorActionBridge.cs` | 接收计划/动作并映射到本地执行层 |
| `docs/BEHAVIOR_SYSTEM_AUDIT.md`、本报告 | 审计与报告 |

## 5. 完整数据流（真实可跑）

```text
用户说话/打字
 → Quest 上行 user.text / user.audio_end
 → Gateway 走既有 Qiyu 大脑链路得到台词
 → QuestResponsePlanner 产出 AvatarIntent + behavior{intent,intensity}
 → Gateway._apply_behavior：build_context(WorldState/CharacterState/被锁通道)
 → BehaviorBrain.plan → BehaviorPlan
 → ActionRuntime.submit_plan → 按通道启动动作
 → QuestAdapter 生成 server.behavior_action
 → 8Hz ticker：推进时长、发 server.behavior_event / server.behavior_state
 → Unity BehaviorActionBridge：表情 → BlendShapeAvatarDriver；移动 → NavMeshAgent；
   视线/头部/手势 → CharacterBehaviorRuntime（最终落到动画/IK/程序化动作）
```

协议消息（版本化，不绑定 Unity 内部实现）：
`server.behavior_plan` / `server.behavior_action` / `server.behavior_event` / `server.behavior_state`。

## 6. 当前真实可运行的功能

- LLM（或关键词兜底）产出 `behavior.intent` → 计划 → 调度全链路，**47 个后端测试全绿**；
- 内置行为：greeting、shy、tease、comfort、laugh、happy、angry、sad、surprised、
  embarrassed、confused、tired、apologize、think、acknowledge、agree、disagree、
  sit_with_user、come_here；
- 通道并行：`greeting` 实测同时启动 gaze+facial+gesture 三个通道；
- 优先级/打断：同通道高优先级抢占；barge-in 立即 `cancel_all`；
- 冷却：wave 1.0s、blink 2.0s 等，冷却期内重复请求被忽略；
- 冲突消解：无座位时 `sit_down` 自动退化为"走近+看向用户"；`dance` 会剥掉同时的移动；
- 能力协商：只有声明 `behavior_v1` 的客户端才启用，老客户端/协议测试不受影响。

## 7. 仍是 Stub / 未接入（明确标注，不假装完成）

| 项 | 现状 |
|---|---|
| 动作资产 | 项目缺 Walk/Run/Idle/手势 动画资产，Unity 侧靠程序化兜底；行为语义已能下发，观感受限于资产 |
| interaction 通道 | `high_five`/`give_object` 等需要 IK 与手部判定，Unity 侧目前只记录"暂未接入" |
| sit_down / stand_up | 缺动作资产与座位判定（后端会按 has_seat 退化，不会凭空坐下） |
| 表情丰富度 | 只有模型自带的 BlendShape；`ApplyEmotion(action, intensity)` 按已有映射生效 |
| 视线分级 | 现有实现是"头+身体"级，眼睛独立转动需要模型带眼骨/眼 BlendShape |
| LLM 直接产出 behavior | 已支持 schema 与校验，但当前 x99 上的 LLM 未强制输出该字段，实际多走关键词门控 |

## 8. 如何连接实际 VRM / Unity Avatar

1. 后端：`QuestAdapter(send=...)` 已在网关里接好，动作会走 WebSocket 下发；
2. Unity：场景中挂 `BehaviorActionBridge`（`EnsureRuntimeComponents` 会自动补），
   在 Inspector 里指定 `webSocketClient`；其余引用会自动查找；
3. 模型：把 Humanoid 模型放进 `Assets/QiyuQuest/Resources/Qiyu/Avatar/`，
   运行时由 `CharacterBehaviorRuntime.EnsureAvatarModel()` 载入（MMD→FBX 流程见
   [AVATAR_PMX_TO_UNITY.md](AVATAR_PMX_TO_UNITY.md)）；
4. 换成 VRM 时只需替换模型与动画本体，行为层与协议完全不用改。

## 9. 如何添加新的 Action

```python
# qiyu_quest_gateway/behavior/registry.py
_d("stretch_up", "upper_body", "举手伸展", 2.0, cooldown=1.0)
```
注册后即可被计划引用；未注册的动作会被拒绝执行。

## 10. 如何添加新的 Behavior Intent

```python
# qiyu_quest_gateway/behavior/brain.py 的 _preset 里加一条
"goodbye": sequence(
    action("look_at_user", intensity),
    action("wave", intensity),
    action("smile", intensity * 0.7)),
```
复杂行为可以用 `conditional` / `repeat` / `selector` 组合；
需要新上下文条件时，在 `BrainContext` 里加字段并在 `build_context` 中填充。

## 11. 测试结果

```text
python tests/run_tests.py  →  ALL PASS (47)
  原有协议/网关/音频/视觉测试   23
  行为层测试（意图/计划/冲突/运行时） 19
  网关桥集成测试                5
```

覆盖：greeting/happy/angry/shy/embarrassed/tease/comfort/idle、
priority/interrupt/cancel/cooldown/parallel/channel conflict/sequence/conditional/
unknown action/invalid behavior/adapter failure、walk+look_at+smile 并行、walk→sit 切换。

## 12. 下一阶段建议

1. **导入动作资产**（Walk/Run/Idle/手势）→ 行为观感提升最大的一步；
2. 让 LLM 强制输出 `behavior` 字段并做离线偏好评估（用真实对话样本回归）；
3. interaction 通道接 IK：击掌/递物需要手部目标与可达性判定；
4. 把 `server.behavior_state` 接进 Unity HUD，实时看到当前 intent/通道/冷却；
5. 真机长时运行采集失败案例，回流为硬负样本与新的预设行为。
