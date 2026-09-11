# Phase 1 · 现有 VR 后端审计（Behavior 系统落地前）

日期：2026-09-11　分支：`quest-mr-client`
结论先说：**现有系统已经有一半架构，而且方向一致**（LLM 只出高层意图、
本地运行时负责具体动作）。缺的是提示词里那套「Behavior Intent → Behavior Brain →
Behavior Plan → Action Runtime → Channel/优先级/冷却」的**显式行为层**。
因此本轮是"补一层 + 接线"，不是重写。

---

## 1. 现有数据流（代码实测，不是猜的）

```text
Quest(Unity)                          Python VR 后端
-----------                           ---------------
MrukWorldStatePublisher ──world_state──▶ gateway._handle_world_state
CharacterStateStore     ──client.character_state──▶ _handle_character_state
CharacterBehaviorRuntime──client.behavior_state───▶ _handle_behavior_state
HumanMotionCapture      ──client.human_motion_state▶ _handle_human_motion_state
QiyuUserBodyTracker     ──client.user_body────────▶ _handle_user_body
InteractionStateController─client.interaction_event▶ _handle_interaction_event
QuestVoiceLoop          ──client.user_text/audio──▶ _handle_user_text / _handle_audio_end
                                     ◀─ agent.speech / avatar.intent / spatial.action ──
AvatarIntentRouter ──▶ CharacterBehaviorRuntime ──▶ Locomotion/Animation/Attention
```

入口：`quest-mr-client/backend/quest_server.py`（复用 `demo.app`，追加 `/v1/quest/ws`）。
网关：`qiyu_quest_gateway/gateway.py`（`QuestWebSocketGateway`，30+ 处理方法）。

---

## 2. 已有能力清单（可直接复用）

| 层 | 现有实现 | 位置 |
|---|---|---|
| 协议/信封 | `Envelope`、`seq/ack`、版本化、二进制帧 | `protocol.py`、`binary_frame.py` |
| 世界状态 | `WorldState`、`WorldStateDelta`、NavMesh、锚点、用户姿态 | `models.py`、`world_state.py` |
| 高层意图 | `AvatarIntent(goal/target/attention/emotion/urgency/spatial_hint)` | `models.py:182` |
| 角色内部状态 | `CharacterState(emotion/relationship/drives/memory/attention/speech)` | `models.py:266` |
| 行为遥测 | `BehaviorState(active_behavior/goal/priority/locomotion/attention/reflex/latency)` | `models.py:284` |
| 交互事件 | `InteractionEvent`、`HumanMotionSnapshot`、`AutonomyRequest` | `models.py:305+` |
| LLM 规划 | `QuestResponsePlanner.plan()` → AvatarIntent + SpatialAction | `planner.py:114` |
| 会话/取消 | `QuestSession`、`_cancel_turn`、barge-in | `session.py`、`gateway.py` |
| 本地行为运行时 | 8 Hz 候选行为仲裁 + Utility + 学习策略 + 滞回 | Unity `Behavior/CharacterBehaviorRuntime.cs` |
| 表情/视线/动作 | `BlendShapeAvatarDriver`、`AvatarLookController`、`MotionLibrary`、`ProceduralMotionFallback` | Unity `Avatar/`、`Behavior/` |
| 移动 | NavMesh + `CharacterLocomotionController`（避障/到达/距离控制） | Unity `Behavior/`、`Spatial/` |
| 反射层 | 60 Hz `CharacterReflexLayer`（碰撞/靠近/遮挡/打断） | Unity `Behavior/` |
| 动捕理解 | `HumanMotionCapture` + `MotionUnderstanding` + `SharedAttention` | Unity `Behavior/` |

---

## 3. 缺失能力（提示词要求、当前没有）

| 缺口 | 说明 | 严重度 |
|---|---|---|
| **Behavior Intent 层** | 现在 LLM 直接给 `goal`（去靠近用户/看物体），没有 `intent=shy/tease/greeting/comfort` 这种"行为语义"层 | 高 |
| **Action Registry** | 没有有限动作集合与 `ActionDefinition(category/priority/cooldown/...)`；LLM 可能编出不存在的动作 | 高 |
| **Behavior Plan** | 没有 Sequence/Parallel/Selector/Conditional/Repeat 的组合结构 | 高 |
| **Behavior Brain** | 没有"intent → 动作组合"的展开与冲突消解 | 高 |
| **Action Runtime（Python 侧）** | 没有 queue/priority/interrupt/cancel/cooldown/start-update-complete 调度 | 高 |
| **Channel 模型** | 现有 Unity 侧是"候选行为竞争"，没有 facial/gaze/head/upper_body/locomotion/gesture 分通道并行 | 高 |
| **behavior relevance 门控** | 当前每轮对话都会产出意图；缺少"这句话是否需要触发特殊行为"的判断 | 中 |
| **AvatarAdapter 抽象** | Python 侧没有 `AvatarAdapter`（Null/Mock/Quest）以便脱离 Unity 测试 | 中 |
| **行为自动测试** | 现有 23 个后端测试偏协议；缺 greeting/shy/tease/并行/打断/冷却等行为测试 | 高 |

---

## 4. 复用点（明确不改的东西）

1. **不改网关入口**：新行为层挂在 `QuestWebSocketGateway` 之后，作为"意图→计划→调度"的一段。
2. **不改协议主结构**：复用 `Envelope` 与 `seq/ack`；新增消息类型 `behavior.execute` / `behavior.plan` / `behavior.event`。
3. **不重复实现移动/动画**：动作最终仍落到 Unity 的 `CharacterBehaviorRuntime` + `CharacterLocomotionController` + `CharacterAnimationController`。
4. **不重复实现情绪/关系/记忆**：继续用 `CharacterState` 里的 `EmotionState/RelationshipState/MemoryContext`。
5. **保留 LLM 边界**：LLM 只出 `behavior.intent + intensity (+ 可选 actions)`，禁止输出骨骼/Animator/BlendShape/坐标。

---

## 5. 需要新增的模块

```text
quest-mr-client/backend/qiyu_quest_gateway/behavior/
├── __init__.py
├── models.py       # BehaviorIntent / ActionDefinition / ActionRef / PlanNode / BehaviorPlan
├── registry.py     # ActionRegistry：有限动作集合 + 校验（未知动作直接拒绝）
├── plan.py         # Sequence / Parallel / Selector / Conditional / Repeat
├── brain.py        # BehaviorBrain：intent → BehaviorPlan（含 relevance 门控、冲突消解）
├── runtime.py      # ActionRuntime：Channel / 优先级 / 打断 / 取消 / 冷却 / 状态机
├── adapters.py     # AvatarAdapter 抽象 + NullAdapter / MockAdapter / QuestAdapter
└── scenarios.py    # greeting / shy / tease / comfort / sit_with_user 等预设

tests/test_behavior_*.py   # 行为层自动测试
```

Unity 侧只需**增量**接收新计划并映射到既有能力，不新增执行层。

---

## 6. 下一步（Phase 2 起）

1. Phase 2：`models.py` + `registry.py` + `plan.py`
2. Phase 3：`brain.py` + `runtime.py`
3. Phase 4/5：`adapters.py` 接现有网关与 Unity
4. Phase 6：greeting / shy / tease / sit_with_user 四个完整行为打通
5. 自动测试 + 最终报告（按提示词第 27 节的 12 项）
