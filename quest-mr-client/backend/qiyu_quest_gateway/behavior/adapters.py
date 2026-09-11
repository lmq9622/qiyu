"""Avatar Adapter：行为层与 3D Avatar 之间的唯一接口。

要求（提示词第十一、十二节）：
- Behavior 系统绝不直接依赖 Unity/VRM；
- 提供 NullAdapter / MockAdapter 以便脱离 Unity 跑完整行为测试；
- QuestAdapter 把动作翻译成项目既有的协议消息，交给 Quest 端执行。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class AvatarAdapter(ABC):
    """动作/表情/视线/移动的统一出口。"""

    @abstractmethod
    def play_action(self, name: str, intensity: float, duration: float,
                    target: str, channel: str) -> None:
        ...

    @abstractmethod
    def stop_action(self, name: str, channel: str) -> None:
        ...

    def set_expression(self, expression: str, intensity: float) -> None:
        """默认退化为一个 expression 通道动作。"""

    def set_gaze_target(self, target: str) -> None:
        """默认空实现；具体适配器覆盖。"""

    def set_head_pose(self, pitch: float, yaw: float, roll: float) -> None:
        """默认空实现。这里只暴露语义化的头部姿态，不接受骨骼。"""

    def move_to(self, target: str, desired_distance: float) -> None:
        """默认空实现。目标是语义目标（user / anchor_id），不是坐标序列。"""

    def rotate_to(self, target: str) -> None:
        """默认空实现。"""

    def get_state(self) -> dict[str, Any]:
        return {}


class NullAdapter(AvatarAdapter):
    """什么都不做；用于纯逻辑测试与容错。"""

    def play_action(self, name: str, intensity: float, duration: float,
                    target: str, channel: str) -> None:
        return None

    def stop_action(self, name: str, channel: str) -> None:
        return None


class MockAdapter(AvatarAdapter):
    """记录所有调用，供自动测试断言（不产生任何副作用）。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_on: set[str] = set()

    def play_action(self, name: str, intensity: float, duration: float,
                    target: str, channel: str) -> None:
        if name in self.fail_on:
            raise RuntimeError(f"mock failure: {name}")
        self.calls.append(("play", name, round(intensity, 3),
                           round(duration, 3), target, channel))

    def stop_action(self, name: str, channel: str) -> None:
        self.calls.append(("stop", name, channel))

    def set_expression(self, expression: str, intensity: float) -> None:
        self.calls.append(("expression", expression, round(intensity, 3)))

    def set_gaze_target(self, target: str) -> None:
        self.calls.append(("gaze", target))

    def move_to(self, target: str, desired_distance: float) -> None:
        self.calls.append(("move", target, round(desired_distance, 3)))

    def names(self) -> list[str]:
        return [c[1] for c in self.calls if c[0] == "play"]

    def started(self) -> list[str]:
        return self.names()


class QuestAdapter(AvatarAdapter):
    """把动作翻译为 Quest 端可消费的协议消息。

    真实的 WebSocket 发送由注入的 `send` 回调完成，因此这里依然不依赖
    FastAPI / Unity，测试时可以注入一个列表收集器。
    """

    def __init__(self, send: Optional[Any] = None,
                 session_id: str = "") -> None:
        self._send = send
        self.session_id = session_id
        self.sent: list[dict] = []

    def _emit(self, message_type: str, payload: dict[str, Any]) -> None:
        envelope = {"type": message_type, "session": self.session_id,
                    "payload": payload}
        self.sent.append(envelope)
        if self._send is not None:
            self._send(envelope)

    def play_action(self, name: str, intensity: float, duration: float,
                    target: str, channel: str) -> None:
        self._emit("server.behavior_action", {
            "action": name,
            "channel": channel,
            "intensity": round(intensity, 3),
            "duration_ms": int(duration * 1000),
            "target": target,
            "state": "start",
        })

    def stop_action(self, name: str, channel: str) -> None:
        self._emit("server.behavior_action", {
            "action": name,
            "channel": channel,
            "state": "stop",
        })

    def set_expression(self, expression: str, intensity: float) -> None:
        self._emit("server.behavior_action", {
            "action": expression, "channel": "facial",
            "intensity": round(intensity, 3), "state": "start",
        })

    def set_gaze_target(self, target: str) -> None:
        self._emit("server.behavior_action", {
            "action": "look_at_target", "channel": "gaze",
            "target": target, "state": "start",
        })

    def move_to(self, target: str, desired_distance: float) -> None:
        self._emit("server.behavior_action", {
            "action": "approach_user", "channel": "locomotion",
            "target": target, "desired_distance_m": desired_distance,
            "state": "start",
        })
