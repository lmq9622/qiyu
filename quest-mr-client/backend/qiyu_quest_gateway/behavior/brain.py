"""Behavior Brain：BehaviorIntent → BehaviorPlan。

职责（提示词第四节）：
- 分析当前角色状态与上下文；
- 选择行为组合（不是"播一个动画"）；
- 处理冲突（座位不存在、通道被占用、舞蹈阻塞移动等）；
- 生成可执行、可测试的 BehaviorPlan。

这一层完全不接触 Unity：输出只有动作语义 + 强度。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    ActionRef,
    BehaviorIntent,
    BehaviorPlan,
    PlanNode,
)
from .plan import (
    action,
    collect_unknown_actions,
    conditional,
    describe,
    parallel,
    sequence,
)
from .registry import ActionRegistry, default_registry

#: 相关性低于该阈值就不触发特殊行为（避免"说一句话播一个动作"）。
DEFAULT_RELEVANCE_THRESHOLD = 0.35

#: 这些意图不影响行为（自然保持当前状态）。
NOOP_INTENTS = {"", "none", "null", "neutral", "idle_only"}

#: 行为通道锁：这些通道已有不可打断动作时，新计划不再往该通道塞动作。
CHANNEL_LOCKABLE = {"interaction", "locomotion", "gesture", "audio"}


class BrainContext(BaseModel):
    """行为决策所需的最小上下文，可由 CharacterState + WorldState 组装。"""

    model_config = ConfigDict(extra="ignore")

    user_visible: bool = True
    user_distance_m: float = 1.2
    has_seat: bool = False
    is_moving: bool = False
    is_speaking: bool = False
    emotion: str = "neutral"
    emotion_intensity: float = 0.0
    relationship_tier: str = "acquaintance"
    #: 当前被占用且不可打断的通道（由 ActionRuntime 提供）
    locked_channels: list[str] = Field(default_factory=list)


class BehaviorBrain:
    """意图 → 计划。轻量查表 + 少量冲突规则，不做通用规划搜索。"""

    def __init__(self, registry: ActionRegistry | None = None,
                 relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD) -> None:
        self.registry = registry or default_registry
        self.relevance_threshold = relevance_threshold
        self.last_rejection: str = ""

    # ------------------------------------------------------------------ 主入口
    def plan(self, intent: BehaviorIntent,
             context: BrainContext | None = None) -> BehaviorPlan | None:
        """返回 None 表示"本轮不触发特殊行为"，这是合法结果。"""
        context = context or BrainContext()
        self.last_rejection = ""
        if intent is None or intent.is_empty:
            self.last_rejection = "empty_intent"
            return None
        if intent.intent.strip().lower() in NOOP_INTENTS and not intent.actions:
            self.last_rejection = "noop_intent"
            return None
        if intent.relevance < self.relevance_threshold:
            self.last_rejection = f"low_relevance({intent.relevance:.2f})"
            return None

        root = self._build_root(intent, context)
        if root is None:
            self.last_rejection = f"unknown_intent({intent.intent})"
            return None

        unknown = collect_unknown_actions(root, self.registry)
        if unknown:
            # 未知动作一律拒绝：宁可不出行为，也不让 Unity 收到野动作
            self.last_rejection = "unknown_action:" + ",".join(unknown)
            return None

        root = self._resolve_conflicts(root, context)
        return BehaviorPlan(
            intent=intent.intent,
            intensity=intent.intensity,
            reason=intent.reason,
            root=root,
        )

    # ------------------------------------------------------------------ 组合表
    def _build_root(self, intent: BehaviorIntent,
                    context: BrainContext) -> PlanNode | None:
        key = intent.intent.strip().lower()
        intensity = intent.intensity
        preset = self._preset(key, intensity, context)
        if preset is not None:
            return preset
        if intent.actions:
            # LLM 直接点名动作：必须已注册（上面已校验）
            return sequence(*[action(ref.name, ref.intensity or intensity, ref.duration,
                                     ref.target) for ref in intent.actions],
                            label=f"explicit:{key}")
        return None

    def _preset(self, key: str, intensity: float,
                context: BrainContext) -> PlanNode | None:
        presets: dict[str, PlanNode] = {
            # 打招呼：看 + 笑 + 挥手，三者并行（不同通道）
            "greeting": parallel(
                action("look_at_user", intensity),
                action("smile", intensity),
                action("wave", intensity), label="greeting"),

            # 害羞：视线移开 → 低头 → 脸红 → 小动作（顺序）
            "shy": sequence(
                action("look_away", intensity),
                action("head_down", intensity),
                action("blush", intensity),
                action("fidget", intensity), label="shy"),

            # 逗弄：笑 + 歪头 + 看用户，再补一个小手势
            "tease": sequence(
                parallel(action("smile", intensity),
                         action("head_tilt", intensity),
                         action("look_at_user", intensity), label="tease_core"),
                action("point", intensity * 0.7, duration=0.8), label="tease"),

            # 安慰：看向用户 + 前倾，然后伸手安抚
            "comfort": sequence(
                parallel(action("look_at_user", intensity),
                         action("lean_in", intensity * 0.8), label="comfort_attend"),
                action("comfort_touch", intensity * 0.8), label="comfort"),

            "laugh": parallel(action("laugh", intensity),
                              action("head_tilt", intensity * 0.7), label="laugh"),

            "happy": parallel(action("smile", intensity),
                              action("look_at_user", intensity * 0.8), label="happy"),

            "angry": parallel(action("angry", intensity),
                              action("look_at_user", intensity), label="angry"),

            "sad": parallel(action("sad", intensity),
                            action("look_down", intensity * 0.8), label="sad"),

            "surprised": parallel(action("surprised", intensity),
                                  action("look_at_user", intensity), label="surprised"),

            "embarrassed": sequence(action("look_away", intensity),
                                    action("blush", intensity),
                                    action("head_down", intensity * 0.8),
                                    label="embarrassed"),

            "confused": parallel(action("confused", intensity),
                                 action("head_tilt", intensity),
                                 action("look_at_user", intensity), label="confused"),

            "tired": parallel(action("tired", intensity),
                              action("yawn", intensity * 0.8), label="tired"),

            "apologize": sequence(action("head_down", intensity),
                                  action("sad", intensity * 0.8),
                                  action("look_up", intensity), label="apologize"),

            "think": parallel(action("look_up", intensity),
                              action("head_tilt", intensity * 0.8), label="think"),

            "acknowledge": sequence(action("look_at_user", intensity),
                                    action("nod", intensity), label="acknowledge"),

            "agree": sequence(action("look_at_user", intensity),
                              action("nod", intensity), label="agree"),

            "disagree": sequence(action("look_at_user", intensity),
                                 action("shake_head", intensity), label="disagree"),

            # 复杂的"坐过去陪你"：看 → 走 → 停 → 转身 → 坐下 → 看 → 放松待机
            # 没有真实座位时退化为"走近 + 看向用户"，不会凭空坐下
            "sit_with_user": conditional(
                "has_seat",
                sequence(action("look_at_user", intensity),
                         action("approach_user", intensity, duration=3.0,
                                target="user"),
                         action("stop", 0.5),
                         action("turn", 0.8),
                         action("sit_down", intensity),
                         action("look_at_user", intensity),
                         action("relaxed_idle", intensity, duration=4.0),
                         label="sit_with_user"),
                sequence(action("look_at_user", intensity),
                         action("approach_user", intensity, duration=3.0,
                                target="user"),
                         action("stop", 0.5),
                         action("relaxed_idle", intensity, duration=4.0),
                         label="sit_with_user_no_seat"),
                label="choose_seat"),

            "come_here": sequence(action("look_at_user", intensity),
                                  action("approach_user", intensity, duration=3.0,
                                         target="user"),
                                  action("stop", 0.5),
                                  action("look_at_user", intensity),
                                  label="come_here"),
        }
        return presets.get(key)

    # ------------------------------------------------------------------ 冲突消解
    def _resolve_conflicts(self, root: PlanNode, context: BrainContext) -> PlanNode:
        """按上下文修剪计划。规则少而明确，便于测试与解释。"""
        names = {ref.name for ref in self._iter(root)}

        # 1) 跳舞占满全身，去掉同时的移动，避免"边走边跳"的诡异画面
        if "dance" in names:
            root = self._strip_channels(root, {"locomotion"})

        # 2) 没有真实座位时不允许 sit_down（由 conditional 分支处理，
        #    这里兜底处理 LLM 直接点名 sit_down 的情况）
        if "sit_down" in names and not context.has_seat:
            root = self._replace_action(root, "sit_down", "relaxed_idle")

        # 3) 用户不可见时，社交类动作退化为最小动作（看向最后已知方向由运行时处理）
        if not context.user_visible:
            root = self._replace_action(root, "wave", "neutral")
            root = self._replace_action(root, "point", "neutral")

        # 4) 通道被占用（不可打断）时，不再往该通道塞新动作
        if context.locked_channels:
            blocked = set(context.locked_channels) & CHANNEL_LOCKABLE
            if blocked:
                root = self._strip_channels(root, blocked)

        return root

    def _strip_channels(self, node: PlanNode, channels: set[str]) -> PlanNode:
        def keep(child: PlanNode) -> bool:
            if child.type == "action" and child.action is not None:
                definition = self.registry.get(child.action.name)
                return definition is None or definition.channel not in channels
            return True

        children = [self._strip_channels(c, channels) for c in node.children if keep(c)]
        else_children = [self._strip_channels(c, channels)
                         for c in node.else_children if keep(c)]
        node = node.model_copy(update={"children": children,
                                       "else_children": else_children})
        return node

    def _replace_action(self, node: PlanNode, old: str, new: str) -> PlanNode:
        if node.type == "action" and node.action is not None:
            if node.action.name == old and self.registry.has(new):
                return node.model_copy(
                    update={"action": ActionRef(name=new,
                                                intensity=node.action.intensity)})
            return node
        return node.model_copy(update={
            "children": [self._replace_action(c, old, new) for c in node.children],
            "else_children": [self._replace_action(c, old, new)
                              for c in node.else_children],
        })

    @staticmethod
    def _iter(node: PlanNode):
        if node.type == "action" and node.action is not None:
            yield node.action
            return
        for child in node.children:
            yield from BehaviorBrain._iter(child)
        for child in node.else_children:
            yield from BehaviorBrain._iter(child)

    @staticmethod
    def explain(plan: BehaviorPlan) -> str:
        return f"intent={plan.intent} intensity={plan.intensity:.2f}\n" + \
               describe(plan.root)
