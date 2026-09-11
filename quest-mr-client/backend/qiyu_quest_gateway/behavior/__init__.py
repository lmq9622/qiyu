"""Qiyu Behavior 层：Behavior Intent → Behavior Brain → Behavior Plan → Action Runtime。

对外只用这几个名字：
    BehaviorIntent, BehaviorPlan, ActionRegistry, BehaviorBrain,
    ActionRuntime, BehaviorBridge, AvatarAdapter(+Null/Mock/Quest)
"""
from .adapters import AvatarAdapter, MockAdapter, NullAdapter, QuestAdapter
from .brain import BrainContext, BehaviorBrain
from .bridge import BehaviorBridge, build_context
from .models import (
    ActionCategory,
    ActionDefinition,
    ActionRecord,
    ActionRef,
    ActionState,
    BehaviorIntent,
    BehaviorPlan,
    CATEGORY_TO_CHANNEL,
    PlanNode,
)
from .plan import (
    action,
    collect_unknown_actions,
    conditional,
    describe,
    iter_actions,
    parallel,
    repeat,
    selector,
    sequence,
)
from .registry import ACTION_DEFINITIONS, ActionRegistry, default_registry
from .runtime import ActionRuntime

__all__ = [
    "ACTION_DEFINITIONS",
    "ActionCategory",
    "ActionDefinition",
    "ActionRecord",
    "ActionRef",
    "ActionRegistry",
    "ActionRuntime",
    "ActionState",
    "AvatarAdapter",
    "BehaviorBrain",
    "BehaviorBridge",
    "BehaviorIntent",
    "BehaviorPlan",
    "BrainContext",
    "CATEGORY_TO_CHANNEL",
    "MockAdapter",
    "NullAdapter",
    "PlanNode",
    "QuestAdapter",
    "action",
    "build_context",
    "collect_unknown_actions",
    "conditional",
    "default_registry",
    "describe",
    "iter_actions",
    "parallel",
    "repeat",
    "selector",
    "sequence",
]
