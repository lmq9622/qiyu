# Qiyu MR Character Behavior Policy

## 结论

这里训练的不是完整 VLA，而是 **轻量 Behavior Scorer**：

```text
WorldState + CharacterState + AvatarIntent + 候选行为/目标
→ 行为得分 + 连续参数
→ Quest 本地 Utility 仲裁
→ BehaviorDecision
→ Motion / Locomotion / IK / Animator
```

模型约 10 万参数，JSON 权重约 1.2 MB，Quest 本地 8 Hz 纯 C# 推理。

## 为什么不是完整 VLA

- Quest 端无法承受高频大模型推理；
- 房间语义、NavMesh、动画、IK 已由 MRUK/Unity 提供；
- 完整 VLA 数据与算力成本远高于本项目收益；
- 当前第一版采用“学习型候选打分 + 确定性安全/自然度约束”，更适合真机落地。

## x99 CUDA 训练

连接信息来自仓库既有 x99 脚本：

```text
host: 192.168.2.6
user: lmq
GPU: 2 × Tesla V100-SXM2-16GB
python: /home/lmq/ComfyUI/.venv/bin/python
torch: 2.9.1+cu128
```

同步代码：

```powershell
pscp -pw <password> -hostkey <hostkey> `
  'D:\Codex projects\ai-companion-codex\ai-companion\quest-mr-client\behavior_policy\*.py' `
  lmq@192.168.2.6:/home/lmq/qiyu-mr-behavior/behavior_policy/
```

生成数据 + CUDA 训练 + 场景测试：

```bash
cd /home/lmq/qiyu-mr-behavior
PY=/home/lmq/ComfyUI/.venv/bin/python

$PY -m behavior_policy.generate_data \
  --episodes 2000 --steps 12 \
  --output behavior_policy/data/behavior_train_large.npz

$PY -m behavior_policy.train \
  --data behavior_policy/data/behavior_train_large.npz \
  --out behavior_policy/artifacts/behavior_policy_v1.json \
  --epochs 40 --batch-groups 1024 --device cuda \
  --unity-resources /home/lmq/qiyu-mr-behavior/artifacts/behavior_policy_v1.json

$PY -m behavior_policy.scenario_tests \
  --weights behavior_policy/artifacts/behavior_policy_v1.json \
  --device cuda --seeds 30
```

## 当前训练结果

数据：

```text
2,000 episodes
24,000 决策组
640,600 候选样本
15 类真实交互场景
自动硬负样本
```

模型：

```text
104 输入特征
256 → 128 两层 MLP
29 类行为候选
6 个连续参数
```

CUDA 训练结果：

```text
device: Tesla V100-SXM2-16GB
40 epochs ≈ 30 秒
top-1: 0.661
top-3: 0.915
硬负样本拒绝率: 0.998
连续参数 MAE: 0.048
```

场景测试：

```text
call_character        1.00
user_approach         1.00
user_leave            1.00
user_return           1.00
user_silence          1.00
point_object          1.00
look_object           1.00
follow_me             1.00
sit_here              1.00
dont_come             1.00
interrupt             1.00
emotion_shift         1.00
two_targets           1.00
target_missing        1.00
network_stale         1.00
```

top-1 不是唯一指标：top-3 约 90%，且 Quest 运行时会用 Utility 对“用户不可见时不该社交/不该移动”等约束做修正，学习策略只占 35% 权重。

## OOD 泛化 + 长时序 + 参数分析（2026-09-10）

评估集与训练集完全隔离：

```text
IID：500 episodes / 6,000 决策组（全新 seed，不参与训练）
OOD：2,000 episodes / 69,605 决策组（新房间尺寸、6–15 家具、动态障碍、
     遮挡、目标出现/消失、多目标优先级、网络延迟、指令顺序变化）
Long-Horizon：500 episodes / 17,506 steps（20–50 连续决策）
```

### IID / OOD / Δ

| 指标 | IID | OOD | Δ OOD−IID |
|---|---:|---:|---:|
| Top-1 | 0.971 | 0.965 | −0.006 |
| Top-3 | 0.9997 | 1.000 | +0.0003 |
| Hard-negative rejection | 1.000 | 1.000 | 0.000 |
| Invalid action rate | 0.000 | 0.000 | 0.000 |
| Goal abandonment rate | 0.118 | 0.219 | +0.101 |
| Action contradiction rate | 0.000 | 0.000 | 0.000 |

结论：**OOD Top-1 几乎不下降**，说明当前小模型没有明显过拟合训练布局；
主要弱项是 OOD 的目标保持率，已通过本地“指令目标仍有效时不允许无理由放弃”约束修正，
不需要立即升级 Transformer/VLA。

### 长时序稳定性

```text
action_oscillation_rate       0.027
behavior_switching_rate       0.119
target_switching_rate         0.203
walk_stop_walk_rate           0.0005
look_aba_rate                 0.016
stale_goal_rate               0.029
action_contradiction_rate     0.000
interruption_response_rate    0.663
cancellation_response_rate    1.000
replan_success_rate           1.000
reflex_override_rate          0.340
```

没有出现明显的 WALK→STOP→WALK、LEFT→RIGHT→LEFT、LOOK A→LOOK B→LOOK A 抖动。
打断响应仍有提升空间，已加本地硬约束：用户说话时优先进入
`listen_user / nod / observe_user / think`，不依赖 LLM 下发。

### 6 个连续参数

| 参数 | 范围/单位 | 归一化 | 训练 target | Unity 用途 | 是否核心 |
|---|---|---|---|---|---|
| `desired_distance` | 0.55–2.2 m | `(x-0.55)/1.65` | 专家候选期望距离 | Locomotion stop distance | 核心 |
| `speed_scale` | 0–1 比例 | 直接 | 专家候选速度比例 | NavMeshAgent speed | 核心 |
| `gaze_weight` | 0–1 | 直接 | 专家候选注视强度 | 注意力/头部 LookAt | 核心 |
| `gesture_probability` | 0–1 | 直接 | 专家候选手势倾向 | Talk/gesture 选择 | 核心 |
| `look_away_rate` | 0–1 | 直接 | 专家候选移开视线频率 | CharacterAttention 自然移开 | 核心（已接入） |
| `speech_urge` | 0–1 | 直接 | 专家候选说话冲动 | 自主表达请求 urgency | 核心（已接入） |

参数误差（策略头在专家正样本位置）：

| 参数 | IID MAE | IID RMSE | IID p90 | OOD MAE | OOD RMSE | OOD p90 |
|---|---:|---:|---:|---:|---:|---:|
| desired_distance | 0.139 | 0.178 | 0.312 | 0.102 | 0.125 | 0.209 |
| speed_scale | 0.042 | 0.056 | 0.096 | 0.082 | 0.112 | 0.161 |
| gaze_weight | 0.034 | 0.050 | 0.077 | 0.040 | 0.053 | 0.086 |
| gesture_probability | 0.041 | 0.059 | 0.097 | 0.063 | 0.088 | 0.152 |
| look_away_rate | 0.012 | 0.016 | 0.026 | 0.016 | 0.022 | 0.038 |
| speech_urge | 0.026 | 0.037 | 0.049 | 0.025 | 0.031 | 0.041 |

结论：6 个参数都真实影响 Unity 行为，没有需要丢弃的纯模拟器内部变量。
其中 `desired_distance`、`speed_scale` 对移动自然度最敏感；
`gaze_weight`、`look_away_rate` 对社交自然度最敏感；
`gesture_probability`、`speech_urge` 对表达欲/合作感最敏感。

### 重新跑 OOD / Long-Horizon

```bash
cd /home/lmq/qiyu-mr-behavior
PY=/home/lmq/ComfyUI/.venv/bin/python

# IID 对照
$PY -m behavior_policy.generalization_eval \
  --weights behavior_policy/artifacts/behavior_policy_v1_large.json \
  --out behavior_policy/artifacts/gen_iid.json --device cuda \
  --iid-episodes 500 --ood-episodes 0 --long-episodes 0 --seed 9009

# OOD（可并行 500/episode 分块）
$PY -m behavior_policy.generalization_eval \
  --weights behavior_policy/artifacts/behavior_policy_v1_large.json \
  --out behavior_policy/artifacts/gen_ood_1.json --device cuda \
  --iid-episodes 0 --ood-episodes 500 --long-episodes 0 --seed 1001

# Long-Horizon
$PY -m behavior_policy.generalization_eval \
  --weights behavior_policy/artifacts/behavior_policy_v1_large.json \
  --out behavior_policy/artifacts/gen_long_1.json --device cuda \
  --iid-episodes 0 --ood-episodes 0 --long-episodes 250 --long-seed 7001

# 合并
$PY -m behavior_policy.aggregate_generalization \
  behavior_policy/artifacts/gen_iid.json \
  behavior_policy/artifacts/gen_ood_*.json \
  behavior_policy/artifacts/gen_long_*.json \
  --out behavior_policy/artifacts/generalization_report_v1.json
```

## 文件

| 文件 | 作用 |
|---|---|
| `schema.py` | 与 Unity 完全一致的特征/行为/参数顺序 |
| `simulator.py` | 自动仿真、专家策略、硬负样本 |
| `generate_data.py` | 生成 npz 训练集 |
| `model.py` | PyTorch 模型与 Unity JSON 导出/加载 |
| `train.py` | CUDA 整批训练 |
| `evaluate.py` | top-1 / top-3 / 硬负样本 / 参数误差 |
| `scenario_tests.py` | 15 类真实交互场景门禁 |
| `generalization_eval.py` | OOD / Long-Horizon / 参数统计 / 仲裁参数搜索 |
| `aggregate_generalization.py` | 合并并行分块评估报告 |
| `artifacts/behavior_policy_v1.json` | Quest 最终加载权重 |
| `artifacts/generalization_report_v1.json` | IID/OOD/长时序完整评估报告 |

## 诚实边界

- 第一版策略来自自动仿真专家数据，不是真机人类行为数据；
- 真机接入后必须录制真实失败案例，做增量训练/偏好校正；
- 当前仓库没有专业 Walk/Run/Idle 动作资产，Motion Library 槽位已就绪，最终自然度仍依赖 P7 导入授权动作并真机验收；
- 未连接 Quest 真机前，场景测试只能证明决策层逻辑，不等于最终观感。
