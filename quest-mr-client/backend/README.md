# Qiyu Quest Gateway

在现有 Qiyu FastAPI app 上追加 `/v1/quest/ws`，不改写现有 REST/SSE 主链路。

## 启动

```powershell
cd D:\Codex projects\ai-companion-codex\ai-companion\quest-mr-client\backend
python quest_server.py
```

- 现有 Qiyu：`http://<host>:8765`
- Quest Gateway：`ws://<host>:8766/v1/quest/ws`

环境变量：

- `QIYU_QUEST_HOST`（默认 `0.0.0.0`）
- `QIYU_QUEST_PORT`（默认 `8766`）
- `QIYU_QUEST_TEMPERATURE`（默认 `0.7`）

## 测试

```powershell
# 协议/WorldState/规划器/真实 TTS→STT/视觉闭环/Character/HumanMotion：22 项
python tests/run_tests.py

# 真实进程级联调：启动 uvicorn + 现有 Qiyu app + MiniMind-O
python tests/smoke_live_gateway.py
```

## 模块

| 文件 | 职责 |
|---|---|
| `quest_server.py` | 复用 `demo._pipeline_web_chat_payload`，注入 Quest 空间/视觉上下文 |
| `qiyu_quest_gateway/gateway.py` | 协议、session、并发回合、barge-in、二进制帧、视觉请求闭环 |
| `qiyu_quest_gateway/world_state.py` | WorldState 缓存 + LLM 可读空间关系渲染 |
| `qiyu_quest_gateway/planner.py` | 同一 LLM → 高层 AvatarIntent/SpatialAction，目标不存在则丢弃 |
| `qiyu_quest_gateway/models.py` | AvatarIntent v1.1 / CharacterState / BehaviorState / InteractionEvent / AutonomyRequest |
| `qiyu_quest_gateway/audio.py` | PCM16↔WAV，复用 `runtime.stt` / `runtime.tts` |
| `qiyu_quest_gateway/vision_detector.py` | 复用 `runtime.vision` VisionProvider 做物体识别 |

## 对现有 Qiyu 的最小改动

三处 hook 见 [../patches/qiyu-brain-quest-hooks.patch](../patches/qiyu-brain-quest-hooks.patch)：

1. `runtime/brain/pipeline.py`：可选追加 `_extra_brain_context`；
2. `demo.py`：`_pipeline_web_chat_payload` 增加可选 `extra_context`；
3. `companion/llm.py`：新增 `complete_json` 方法。

不传 Quest 上下文字段时，现有 Web/微信/主动消息行为完全不变。

## v1.1 Character 扩展

- `client.character_state`：Quest 本地情绪/关系/耐心/精力/社交电量；
- `client.behavior_state`：本地行为运行时遥测；
- `client.interaction_event`：靠近/远离/离开/回来/说话/打断/指向/目标消失等；
- `client.human_motion_state`：5–15Hz 压缩头/手/身体/视线状态，不含原始骨骼；
- `client.interaction_event(gesture)`：wave/point/come_here/stop/high_five 等高层手势事件；
- `client.autonomy_request`：低频自主表达请求，服务端有权保持沉默；
- `client.world_state_delta`：带 revision 校验的 WorldState 增量；
- Envelope 新增可选 `seq` / `ack`，重复/乱序事件不会重复执行。

测试：

```powershell
python tests/run_tests.py
```

当前 22 项协议/规划/语音/视觉/Character/HumanMotion 测试全部通过。
