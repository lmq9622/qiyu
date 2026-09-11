"""Action Runtime：行为计划 → 分通道调度执行。

职责（提示词第八、九、十、十七节）：
- Channel 模型：facial/gaze/head/gesture/upper_body/lower_body/locomotion/...
  不同通道可并行，同通道默认互斥；
- 优先级：高优先级可打断低优先级（按动作的 interruptible 判断）；
- 队列：同通道排队等待；
- 冷却：动作执行后进入冷却，冷却期内重复请求被忽略；
- 状态机：pending / running / completed / cancelled / failed；
- 事件：started / completed / cancelled / failed，便于遥测与测试。

运行时只调用 AvatarAdapter，不接触任何 Unity/VRM 细节。
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Callable, Optional

from .adapters import AvatarAdapter, NullAdapter
from .models import (
    ActionDefinition,
    ActionRecord,
    ActionRef,
    ActionState,
    BehaviorPlan,
    PlanNode,
)
from .registry import ActionRegistry, default_registry

EventCallback = Callable[[ActionRecord, str], None]


class _Channel:
    """单个通道：一个正在执行的动作 + 一个等待队列。"""

    def __init__(self) -> None:
        self.current: Optional[ActionRecord] = None
        self.queue: deque[ActionRecord] = deque()


class ActionRuntime:
    def __init__(self, adapter: AvatarAdapter | None = None,
                 registry: ActionRegistry | None = None,
                 on_event: EventCallback | None = None) -> None:
        self.adapter = adapter or NullAdapter()
        self.registry = registry or default_registry
        self.on_event = on_event
        self._channels: dict[str, _Channel] = {}
        self._cooldowns: dict[str, float] = {}
        self._history: list[ActionRecord] = []
        self.now: float = 0.0
        self.active_plan: Optional[BehaviorPlan] = None

    # ------------------------------------------------------------------ 查询
    def channel_locks(self) -> list[str]:
        """返回被"不可打断动作"占用的通道（供 Brain 做冲突消解）。"""
        locks: list[str] = []
        for name, channel in self._channels.items():
            cur = channel.current
            if cur is not None and cur.state == ActionState.RUNNING and \
                    not cur.interruptible:
                locks.append(name)
        return locks

    def snapshot(self) -> dict:
        """行为状态快照（提示词第十七节的结构）。"""
        actions = []
        for name, channel in self._channels.items():
            for record in ([channel.current] if channel.current else []) + \
                    list(channel.queue):
                if record is None:
                    continue
                actions.append({
                    "id": record.name,
                    "action_id": record.action_id,
                    "channel": name,
                    "state": record.state.value,
                    "priority": record.priority,
                    "progress": round(
                        min(1.0, record.elapsed / record.duration), 3)
                    if record.duration else 0.0,
                })
        return {
            "current_behavior": self.active_plan.intent if self.active_plan else "idle",
            "intent": self.active_plan.intent if self.active_plan else "",
            "actions": actions,
            "cooldowns": {k: round(v, 2) for k, v in self._cooldowns.items()},
        }

    def history(self) -> list[ActionRecord]:
        return list(self._history)

    # ------------------------------------------------------------------ 提交
    def submit_plan(self, plan: BehaviorPlan) -> list[ActionRecord]:
        """把计划展开成动作序列提交。返回本次被接受的动作记录。

        Sequence 语义：按顺序提交（后续动作在运行时推进中入队）；
        简化实现：先全部入对应通道队列，通道内 FIFO 保证顺序。
        Parallel：直接各自入队，天然并行。
        Conditional：按条件常量（True/False/1/0）选支。
        Repeat：重复 n 次该节点。
        """
        self.active_plan = plan
        accepted: list[ActionRecord] = []
        self._submit_node(plan.root, accepted)
        return accepted

    def _submit_node(self, node: PlanNode, accepted: list[ActionRecord]) -> None:
        if node.type == "action" and node.action is not None:
            record = self._enqueue(node.action)
            if record is not None:
                accepted.append(record)
            return
        if node.type == "conditional":
            take_then = str(node.condition).strip().lower() in {
                "has_seat", "true", "1", "yes"}
            branch = node.children if take_then else node.else_children
            for child in branch:
                self._submit_node(child, accepted)
            return
        if node.type == "selector":
            # 选择器：提交第一个能入队的子节点
            for child in node.children:
                before = len(accepted)
                self._submit_node(child, accepted)
                if len(accepted) > before:
                    return
            return
        if node.type == "repeat":
            for _ in range(node.repeat):
                for child in node.children:
                    self._submit_node(child, accepted)
            return
        # sequence / parallel：逐子提交（通道队列负责串行）
        for child in node.children:
            self._submit_node(child, accepted)

    def _enqueue(self, ref: ActionRef) -> Optional[ActionRecord]:
        definition = self.registry.get(ref.name)
        if definition is None:
            # 未知动作：明确失败，不静默丢弃也不转发
            self._emit_unknown(ref.name)
            return None
        if self._cooldowns.get(ref.name, 0.0) > self.now:
            return None
        channel_name = definition.channel
        channel = self._channels.setdefault(channel_name, _Channel())
        record = self._make_record(ref, definition)
        current = channel.current
        if current is None:
            self._start(record, channel)
            return record
        # 同通道已有动作：高优先级且可打断 → 抢占；否则排队
        if record.priority > current.priority and current.interruptible:
            self._cancel(current, reason=f"preempted_by:{record.name}")
            self._start(record, channel)
            return record
        channel.queue.append(record)
        self._emit(record, "queued")
        return record

    # ------------------------------------------------------------------ 推进
    def update(self, dt: float) -> None:
        """推进运行时。dt 为秒。测试里可以直接喂时间，不依赖真实时钟。"""
        if dt > 0:
            self.now += dt
        for name, channel in self._channels.items():
            current = channel.current
            if current is not None and current.state == ActionState.RUNNING:
                current.elapsed += dt
                if current.elapsed >= current.duration:
                    self._complete(current)
                    channel.current = None
            if channel.current is None and channel.queue:
                nxt = channel.queue.popleft()
                self._start(nxt, channel)

    def complete_action(self, action_id: str) -> None:
        """外部（Avatar Adapter 回调）通知动作已完成。"""
        for channel in self._channels.values():
            cur = channel.current
            if cur is not None and cur.action_id == action_id:
                self._complete(cur)
                channel.current = None
                return

    def fail_action(self, action_id: str, reason: str = "") -> None:
        for channel in self._channels.values():
            cur = channel.current
            if cur is not None and cur.action_id == action_id:
                cur.state = ActionState.FAILED
                cur.cancel_reason = reason
                cur.finished_at = self.now
                self._history.append(cur)
                self._emit(cur, "failed")
                channel.current = None
                return

    def cancel_channel(self, channel_name: str, reason: str = "cancelled") -> None:
        channel = self._channels.get(channel_name)
        if channel is None:
            return
        if channel.current is not None:
            self._cancel(channel.current, reason)
            channel.current = None
        for record in list(channel.queue):
            record.state = ActionState.CANCELLED
            record.cancel_reason = reason
            self._history.append(record)
            self._emit(record, "cancelled")
        channel.queue.clear()

    def cancel_all(self, reason: str = "cancelled") -> None:
        for name in list(self._channels):
            self.cancel_channel(name, reason)

    # ------------------------------------------------------------------ 内部
    def _make_record(self, ref: ActionRef, definition: ActionDefinition) -> ActionRecord:
        duration = ref.duration or definition.default_duration
        return ActionRecord(
            action_id=uuid.uuid4().hex[:12],
            name=definition.name,
            channel=definition.channel,
            priority=definition.priority,
            state=ActionState.PENDING,
            interruptible=definition.interruptible,
            intensity=ref.intensity,
            target=ref.target,
            duration=duration,
        )

    def _start(self, record: ActionRecord, channel: _Channel) -> None:
        record.state = ActionState.RUNNING
        record.started_at = self.now
        record.elapsed = 0.0
        channel.current = record
        definition = self.registry.get(record.name)
        if definition is not None and definition.cooldown > 0:
            self._cooldowns[record.name] = self.now + definition.cooldown
        self._history.append(record)
        self._emit(record, "started")
        try:
            self.adapter.play_action(record.name, record.intensity,
                                     record.duration, record.target,
                                     record.channel)
        except Exception as exc:  # noqa: BLE001 - 适配器失败必须显式失败
            record.state = ActionState.FAILED
            record.cancel_reason = f"adapter_error:{exc}"
            self._emit(record, "failed")

    def _complete(self, record: ActionRecord) -> None:
        record.state = ActionState.COMPLETED
        record.elapsed = record.duration
        record.finished_at = self.now
        self._emit(record, "completed")
        try:
            self.adapter.stop_action(record.name, record.channel)
        except Exception:  # noqa: BLE001
            pass

    def _cancel(self, record: ActionRecord, reason: str) -> None:
        record.state = ActionState.CANCELLED
        record.cancel_reason = reason
        record.finished_at = self.now
        self._emit(record, "cancelled")
        try:
            self.adapter.stop_action(record.name, record.channel)
        except Exception:  # noqa: BLE001
            pass

    def _emit_unknown(self, name: str) -> None:
        record = ActionRecord(action_id=uuid.uuid4().hex[:12], name=name,
                              channel="system", priority=0,
                              state=ActionState.FAILED,
                              cancel_reason="unknown_action")
        self._history.append(record)
        self._emit(record, "failed")

    def _emit(self, record: ActionRecord, event: str) -> None:
        if self.on_event is not None:
            try:
                self.on_event(record, event)
            except Exception:  # noqa: BLE001 - 遥测失败不能影响执行
                pass

