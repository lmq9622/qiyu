"""Behavior Plan：计划节点构造、校验、遍历与描述。

支持 Sequence / Parallel / Selector / Conditional / Repeat 五种组合。
刻意保持轻量：不引入行为树/GOAP 框架，但结构上可扩展。
"""
from __future__ import annotations

from typing import Iterator

from .models import ActionRef, PlanNode
from .registry import ActionRegistry


def action(name: str, intensity: float = 0.6, duration: float | None = None,
           target: str = "") -> PlanNode:
    return PlanNode(type="action",
                    action=ActionRef(name=name, intensity=intensity,
                                     duration=duration, target=target))


def sequence(*nodes: PlanNode, label: str = "") -> PlanNode:
    return PlanNode(type="sequence", children=list(nodes), label=label)


def parallel(*nodes: PlanNode, label: str = "") -> PlanNode:
    return PlanNode(type="parallel", children=list(nodes), label=label)


def selector(*nodes: PlanNode, label: str = "") -> PlanNode:
    return PlanNode(type="selector", children=list(nodes), label=label)


def conditional(condition: str, then: PlanNode, otherwise: PlanNode | None = None,
                label: str = "") -> PlanNode:
    return PlanNode(type="conditional", condition=condition,
                    children=[then],
                    else_children=[otherwise] if otherwise is not None else [],
                    label=label)


def repeat(node: PlanNode, times: int = 2, label: str = "") -> PlanNode:
    return PlanNode(type="repeat", children=[node], repeat=times, label=label)


def iter_actions(root: PlanNode) -> Iterator[ActionRef]:
    """按深度优先顺序遍历计划里的所有动作引用。"""
    if root.type == "action" and root.action is not None:
        yield root.action
        return
    for child in root.children:
        yield from iter_actions(child)
    for child in root.else_children:
        yield from iter_actions(child)


def collect_unknown_actions(root: PlanNode, registry: ActionRegistry) -> list[str]:
    """返回计划中未注册的动作名（空列表表示计划合法）。"""
    seen: list[str] = []
    for ref in iter_actions(root):
        if not registry.has(ref.name) and ref.name not in seen:
            seen.append(ref.name)
    return seen


def describe(root: PlanNode, indent: int = 0) -> str:
    """人类可读的计划描述，用于日志与验收报告。"""
    pad = "  " * indent
    if root.type == "action" and root.action is not None:
        return f"{pad}- {root.action.name}({root.action.intensity:.2f})"
    head = root.type if not root.label else f"{root.type}:{root.label}"
    if root.type == "repeat":
        head += f" x{root.repeat}"
    if root.type == "conditional":
        head += f" if {root.condition}"
    lines = [f"{pad}{head}"]
    for child in root.children:
        lines.append(describe(child, indent + 1))
    for child in root.else_children:
        lines.append(f"{pad}else")
        lines.append(describe(child, indent + 1))
    return "\n".join(lines)


def to_dict(root: PlanNode) -> dict:
    return root.model_dump(exclude_none=True)
