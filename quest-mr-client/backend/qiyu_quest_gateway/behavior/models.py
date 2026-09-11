"""Behavior 层数据模型（Avatar 无关）。

边界（与项目既定原则一致）：
- LLM 只能产 `BehaviorIntent`：行为语义 + 强度（+ 可选动作名）；
- 动作名必须来自 `ActionRegistry`，未知动作直接拒绝，不会传给 Unity；
- `BehaviorPlan` 由 BehaviorBrain 生成，LLM 不直接产出计划；
- 本层不出现坐标、骨骼、Animator 参数、BlendShape 数值、IK 参数。
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ActionCategory = Literal[
    "expression", "gaze", "head", "gesture", "upper_body", "lower_body",
    "locomotion", "interaction", "audio", "system",
]

Channel = Literal[
    "facial", "gaze", "head", "gesture", "upper_body", "lower_body",
    "locomotion", "interaction", "audio", "system",
]

#: 类别 → 通道。不同通道可以并行，同通道默认互斥。
CATEGORY_TO_CHANNEL: dict[str, str] = {
    "expression": "facial",
    "gaze": "gaze",
    "head": "head",
    "gesture": "gesture",
    "upper_body": "upper_body",
    "lower_body": "lower_body",
    "locomotion": "locomotion",
    "interaction": "interaction",
    "audio": "audio",
    "system": "system",
}

#: 优先级基线（提示词第十节）。具体动作可在注册表里覆盖。
PRIORITY_BASELINE: dict[str, int] = {
    "emergency": 100,
    "interaction": 80,
    "locomotion": 70,
    "gesture": 50,
    "expression": 40,
    "idle": 10,
}


class ActionState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ActionDefinition(BaseModel):
    """注册表里的一条动作定义。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    category: ActionCategory
    description: str = ""
    default_duration: float = Field(default=1.0, gt=0.0, le=60.0)
    priority: int = Field(default=30, ge=0, le=100)
    interruptible: bool = True
    cooldown: float = Field(default=0.0, ge=0.0, le=120.0)
    loop: bool = False
    requires: list[str] = Field(default_factory=list)

    @property
    def channel(self) -> str:
        return CATEGORY_TO_CHANNEL[self.category]


class ActionRef(BaseModel):
    """计划里对一个动作的引用（不是坐标/参数）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    intensity: float = Field(default=0.6, ge=0.0, le=1.0)
    duration: Optional[float] = Field(default=None, gt=0.0, le=60.0)
    target: str = ""


class BehaviorIntent(BaseModel):
    """LLM 唯一被允许产出的行为层结构。"""

    model_config = ConfigDict(extra="ignore")

    intent: str = ""
    intensity: float = Field(default=0.6, ge=0.0, le=1.0)
    actions: list[ActionRef] = Field(default_factory=list)
    reason: str = ""
    relevance: float = Field(default=1.0, ge=0.0, le=1.0)
    duration_hint: float = Field(default=0.0, ge=0.0, le=120.0)

    @property
    def is_empty(self) -> bool:
        return not self.intent and not self.actions


class PlanNode(BaseModel):
    """计划节点：action / sequence / parallel / selector / conditional / repeat。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "action", "sequence", "parallel", "selector", "conditional", "repeat"
    ]
    action: Optional[ActionRef] = None
    children: list["PlanNode"] = Field(default_factory=list)
    else_children: list["PlanNode"] = Field(default_factory=list)
    condition: str = ""
    repeat: int = Field(default=1, ge=1, le=20)
    label: str = ""


class BehaviorPlan(BaseModel):
    """可以直接序列化、也可以脱离 Unity 回放的行为计划。"""

    model_config = ConfigDict(extra="ignore")

    version: str = "1"
    request_id: str = ""
    intent: str = ""
    intensity: float = Field(default=0.6, ge=0.0, le=1.0)
    reason: str = ""
    root: PlanNode
    created_at: float = Field(default_factory=time.time)


class ActionRecord(BaseModel):
    """运行时的动作实例状态（用于遥测与测试）。"""

    model_config = ConfigDict(extra="ignore")

    action_id: str
    name: str
    channel: str
    priority: int
    state: ActionState = ActionState.PENDING
    interruptible: bool = True
    intensity: float = 0.6
    target: str = ""
    duration: float = 1.0
    elapsed: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    cancel_reason: str = ""
