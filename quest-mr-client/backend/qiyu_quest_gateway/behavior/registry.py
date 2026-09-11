"""Action Registry：有限动作集合 + 校验。

LLM 不允许创造动作（例如 "super_cute_head_turn_93"）。
所有动作必须在这里注册，未注册的动作在执行前就会被拒绝。
"""
from __future__ import annotations

from .models import ActionDefinition, ActionRef

# 类别优先级基线（提示词第十节，可按项目微调）
_P = {
    "idle": 10,
    "expression": 40,
    "gaze": 45,
    "head": 45,
    "gesture": 50,
    "upper_body": 55,
    "lower_body": 60,
    "locomotion": 70,
    "interaction": 80,
    "audio": 35,
    "system": 10,
}


def _d(name: str, category: str, description: str, duration: float = 1.0,
       priority: int | None = None, cooldown: float = 0.0,
       interruptible: bool = True, loop: bool = False,
       requires: list[str] | None = None) -> ActionDefinition:
    return ActionDefinition(
        name=name,
        category=category,  # type: ignore[arg-type]
        description=description,
        default_duration=duration,
        priority=_P[category] if priority is None else priority,
        cooldown=cooldown,
        interruptible=interruptible,
        loop=loop,
        requires=requires or [],
    )


ACTION_DEFINITIONS: list[ActionDefinition] = [
    # ---- expression / facial ----
    _d("neutral", "expression", "回到中性表情", 0.3),
    _d("blink", "expression", "眨眼", 0.18, cooldown=2.0),
    _d("smile", "expression", "微笑", 1.6),
    _d("laugh", "expression", "笑", 2.0),
    _d("sad", "expression", "难过", 2.5),
    _d("angry", "expression", "生气", 2.5),
    _d("surprised", "expression", "惊讶", 1.2),
    _d("embarrassed", "expression", "害羞表情", 2.5),
    _d("blush", "expression", "脸红", 2.5),
    _d("pout", "expression", "撇嘴", 1.8),
    _d("shy", "expression", "害羞神态（配合 look_away/head_down）", 2.5),
    _d("confused", "expression", "困惑", 2.0),
    _d("tired", "expression", "疲惫", 2.5),
    # ---- gaze ----
    _d("look_at_user", "gaze", "看向用户", 1.5),
    _d("look_at_target", "gaze", "看向指定目标", 1.5),
    _d("look_away", "gaze", "移开视线", 1.5),
    _d("look_down", "gaze", "向下看", 1.5),
    _d("look_up", "gaze", "向上看", 1.2),
    _d("random_idle_gaze", "gaze", "自然的随机视线游移", 2.5, loop=True),
    # ---- head ----
    _d("nod", "head", "点头", 1.0, cooldown=0.4),
    _d("shake_head", "head", "摇头", 1.2, cooldown=0.6),
    _d("head_tilt", "head", "歪头", 1.5),
    _d("head_down", "head", "低头", 1.8),
    # ---- gesture ----
    _d("wave", "gesture", "挥手", 1.6, cooldown=1.0),
    _d("point", "gesture", "指向", 1.2),
    _d("clap", "gesture", "拍手", 1.6),
    _d("fidget", "gesture", "小幅摆弄手指/小动作", 2.0),
    _d("stretch", "gesture", "伸展", 2.5),
    _d("yawn", "gesture", "打哈欠", 2.5),
    _d("thumbs_up", "gesture", "竖大拇指", 1.2),
    # ---- upper body ----
    _d("lean_in", "upper_body", "身体前倾", 1.5),
    _d("lean_back", "upper_body", "身体后仰", 1.5),
    _d("subtle_shift", "upper_body", "轻微身体晃动", 2.0, loop=True),
    _d("shrug", "upper_body", "耸肩", 1.2),
    _d("dance", "upper_body", "跳舞（占满全身，移动会被阻塞）", 6.0, priority=60),
    # ---- lower body ----
    _d("weight_shift", "lower_body", "重心转移", 1.5, loop=True),
    _d("crouch", "lower_body", "下蹲", 1.2),
    # ---- locomotion ----
    _d("walk", "locomotion", "行走", 2.0, loop=True),
    _d("run", "locomotion", "跑动", 2.0, loop=True, priority=75),
    _d("stop", "locomotion", "停下", 0.4),
    _d("turn", "locomotion", "转身", 1.0),
    _d("sit_down", "locomotion", "坐下（需要真实座位）", 2.5, requires=["seat"]),
    _d("stand_up", "locomotion", "站起", 2.0),
    _d("approach_user", "locomotion", "走向用户", 3.0, loop=True, priority=72),
    _d("move_away", "locomotion", "远离用户", 3.0, loop=True, priority=72),
    # ---- interaction ----
    _d("offer_hand", "interaction", "伸手", 2.0),
    _d("high_five", "interaction", "击掌", 2.0),
    _d("handshake", "interaction", "握手", 2.5),
    _d("comfort_touch", "interaction", "安抚性靠近/轻拍", 2.5),
    _d("give_object", "interaction", "递东西", 2.0),
    _d("take_object", "interaction", "接东西", 2.0),
    # ---- audio ----
    _d("speak", "audio", "说话（由语音链路驱动，这里只占位）", 2.0, loop=True),
    _d("barge_in_listen", "audio", "被打断后转入倾听", 1.0, priority=90),
    # ---- system ----
    _d("idle", "system", "回到自然待机", 2.0, loop=True),
    _d("relaxed_idle", "system", "放松待机（呼吸/微视线/重心）", 4.0, loop=True),
]


class ActionRegistry:
    """动作注册表。线程内共享，只读。"""

    def __init__(self, definitions: list[ActionDefinition] | None = None) -> None:
        self._defs: dict[str, ActionDefinition] = {}
        for definition in (definitions or ACTION_DEFINITIONS):
            self.register(definition)

    def register(self, definition: ActionDefinition) -> None:
        self._defs[definition.name] = definition

    def get(self, name: str) -> ActionDefinition | None:
        return self._defs.get(name)

    def has(self, name: str) -> bool:
        return name in self._defs

    def names(self) -> list[str]:
        return sorted(self._defs)

    def by_category(self, category: str) -> list[ActionDefinition]:
        return [d for d in self._defs.values() if d.category == category]

    def split_known(self, refs: list[ActionRef]) -> tuple[list[ActionRef], list[str]]:
        """返回 (合法动作, 未知动作名)。未知动作必须被拒绝而不是转发。"""
        known: list[ActionRef] = []
        unknown: list[str] = []
        for ref in refs:
            if self.has(ref.name):
                known.append(ref)
            else:
                unknown.append(ref.name)
        return known, unknown


default_registry = ActionRegistry()

