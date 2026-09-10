# Quest ↔ Qiyu Character Protocol v1.1（冻结）

> 基线：Protocol v1.0.0 保持兼容。
> v1.1 只做向后兼容的字段与消息类型扩展。
> 高频身体控制仍由 Quest 本地完成，协议只传高层意图和可观测状态。

## 1. Envelope

```json
{
  "v": "1.0.0",
  "id": "event-id",
  "type": "avatar.intent",
  "ts": 1788870000000,
  "session": "session-id",
  "reply_to": "optional-event-id",
  "seq": 12,
  "ack": 11,
  "payload": {}
}
```

- `id`：全局唯一事件 ID。
- `seq`：会话内单调递增序号；缺失时按 0 处理。
- `ack`：已确认收到的对端最大连续序号；用于检测丢包/重放。
- `reply_to`：请求/响应关联。
- 断线重连后 Quest 必须立即上报完整 `client.world_state` 和 `client.behavior_state`。
- `session` 是连接会话；用户/角色长期状态仍由 `user_id + char_id` 持久化。

## 2. 下行：AvatarIntent v1.1

LLM 只允许表达“想做什么”，不允许表达关节、脚步、路径或 Animator 参数。

```json
{
  "schema_version": "1.1",
  "intent_id": "intent-001",
  "goal": "observe_object",
  "target": "cup_01",
  "attention": "cup_01",
  "emotion": "curious",
  "emotion_intensity": 0.45,
  "behavior_style": "casual",
  "urgency": 0.1,
  "social_priority": 0.5,
  "duration_hint_ms": 3000,
  "speech_act": "comment",
  "speaking": false,
  "response_id": "",
  "cancel_on_barge_in": true,
  "priority": 2,
  "expression_hint": "",
  "gesture_hint": "",
  "prosody": {
    "rate": 1.0,
    "pitch": 1.0,
    "volume": 1.0
  },
  "spatial_hint": null
}
```

### 允许的 goal

```text
idle
listen_user
think
speak
observe_user
observe_object
approach_user
maintain_distance
retreat
follow_user
go_to_object
point_at_object
inspect_object
invite_to_object
sit
stand
reposition
wave
nod
shake_head
laugh
sigh
surprised
comfort_user
```

`spatial_hint` 只允许包含 `target_id`、`desired_distance_m`、`face_target`，
不得包含坐标序列、路径点、速度曲线、关节角度。

## 3. 下行：CharacterState

```json
{
  "schema_version": "1.1",
  "character_id": "qiyu",
  "emotion": {
    "label": "curious",
    "intensity": 0.45,
    "valence": 0.2,
    "arousal": 0.5
  },
  "relationship": {
    "tier": "close_friend",
    "affinity": 72,
    "trust": 68,
    "familiarity": 61
  },
  "drives": {
    "patience": 0.7,
    "energy": 0.8,
    "curiosity": 0.6,
    "social_battery": 0.75,
    "stress": 0.1
  },
  "memory_context": {
    "salient_count": 3,
    "last_interaction_age_s": 42,
    "has_unfinished_topic": true
  },
  "attention": {
    "target_id": "cup_01",
    "focus": 0.6
  },
  "speech": {
    "state": "idle",
    "response_id": ""
  }
}
```

## 4. 上行：BehaviorState

Quest 本地实时行为状态，2 Hz 上报，用于可观测性、断线恢复和训练日志。

```json
{
  "schema_version": "1.1",
  "active_behavior": "observe_object",
  "goal": "observe_object",
  "target_id": "cup_01",
  "priority": 2,
  "confidence": 0.78,
  "policy_source": "learned+utility",
  "since_ms": 1788870000000,
  "interruptible": true,
  "locomotion": {
    "moving": false,
    "speed_mps": 0.0,
    "distance_to_user_m": 1.4,
    "stuck": false
  },
  "attention": {
    "target_id": "cup_01",
    "gaze_weight": 0.65
  },
  "motion": {
    "motion_id": "idle_curious",
    "gesture": "",
    "blend": 0.2
  },
  "reflex": {
    "active": false,
    "kind": ""
  },
  "latency_ms": {
    "policy": 0.08,
    "intent_age": 420
  }
}
```

## 5. 上行：InteractionEvent

```json
{
  "schema_version": "1.1",
  "event_type": "user_near",
  "target_id": "user",
  "value": 0.72,
  "data": {
    "distance_m": 0.65
  }
}
```

允许的 `event_type`：

```text
user_near
user_far
user_left
user_returned
user_speech_start
user_speech_end
barge_in
gaze_target
point_target
object_appeared
object_lost
collision
danger
occlusion
stuck
```

手势事件使用 `event_type="gesture"`，并附带：

```json
{
  "gesture": "wave",
  "intent": "wave_response",
  "target_id": "user",
  "direction": {"x": 0.2, "y": 0.5, "z": 0.8},
  "distance_m": 1.2,
  "confidence": 0.86,
  "emotion_hint": "挥手",
  "source": "local_motion_understanding"
}
```

## 5.1 上行：HumanMotionState（压缩）

5–15Hz 同步，仅传低维状态，不传原始骨骼：

```json
{
  "schema_version": "1.1",
  "ts": 1788870000000,
  "sequence": 128,
  "head_pose": {
    "position": {"x": 0, "y": 1.6, "z": 0},
    "rotation": {"x": 0, "y": 0, "z": 0, "w": 1}
  },
  "left_hand_position": {"x": -0.2, "y": 1.2, "z": 0.3},
  "right_hand_position": {"x": 0.2, "y": 1.3, "z": 0.4},
  "left_hand_tracked": true,
  "right_hand_tracked": true,
  "body_tracked": false,
  "body_confidence": 0.0,
  "gaze_direction": {"x": 0, "y": 0, "z": 1},
  "gaze_target_id": "cup_01",
  "gesture": "point",
  "facing_direction": {"x": 0, "y": 0, "z": 1},
  "velocity": {"x": 0.1, "y": 0, "z": 0},
  "confidence": 0.82,
  "source": "meta_xr"
}
```

## 6. 上行：AutonomyRequest

Quest 本地自主行为需要主动说话时，只请求“是否值得说”，不传台词。

```json
{
  "schema_version": "1.1",
  "reason": "silence_with_high_affinity",
  "urgency": 0.25,
  "social_priority": 0.6,
  "cooldown_s": 90,
  "world_scene_version": 14
}
```

服务端可以由 MiniMind-O/MainBrain 决定保持沉默或生成一句主动内容。

## 7. WorldState v1.1 增量

原有 `client.world_state` 保持兼容，新增可选字段：

```json
{
  "schema_version": "1.1",
  "world_epoch": 3,
  "user": {
    "velocity": {"x": 0, "y": 0, "z": 0},
    "is_speaking": false,
    "gaze_target_id": "",
    "pointing_target_id": "",
    "last_spoke_at_ms": 0
  },
  "objects": [
    {
      "id": "cup_01",
      "label": "cup",
      "confidence": 0.91,
      "position": {"x": 0, "y": 0, "z": 0},
      "velocity": {"x": 0, "y": 0, "z": 0},
      "last_seen_at_ms": 1788870000000,
      "affordances": ["small_object", "movable"],
      "state": "visible"
    }
  ],
  "interaction": {
    "user_distance_m": 1.2,
    "user_approach_speed_mps": 0.0,
    "occluded": false
  }
}
```

Delta 使用 `client.world_state_delta`：

```json
{
  "base_scene_version": 12,
  "scene_version": 13,
  "changed": {
    "objects_upsert": [],
    "objects_remove": ["cup_01"],
    "user": {},
    "avatar": {},
    "interaction": {}
  }
}
```

## 8. 降级与容错

1. LLM 超时：本地行为继续运行，`AvatarIntent` 保持最后有效值直到过期。
2. WorldState 过期：进入保守模式，不追目标、不靠近用户、不做快速移动。
3. 目标消失：立即取消目标行为，重新选目标。
4. 断网：本地 idle/reflex/基础行为继续；重连后上报完整状态。
5. barge-in：停止 TTS、取消当前说话行为、取消可中断动作、进入 listening/attention。
6. 序号缺口：接受新状态但标记 `degraded`，必要时请求全量 WorldState。
