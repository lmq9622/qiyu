# -*- coding: utf-8 -*-
"""栖语 · CloudRealtimeBackend（规格 §22 的云端 fallback）。

本机 Omni 不可用时的兜底路径：

```text
Local Omni → 性能不足 / GPU 不可用 → Cloud Realtime Omni
```

**接口必须完全一致**：上层业务依旧只认 ``IRealtimeOmni``，感知不到 backend。

当前实现状态（诚实说明）：

- 接口、能力声明、可用性判定、fallback 选择 **已实现**；
- 真实云端协议（OpenAI Realtime / WebSocket 事件流）**尚未接线**，
  ``open_stream()`` 在未配置 key 或未接线时只发一条 ``cloud_not_wired`` 事件，
  不会假装成功。

配置：

| 变量 | 含义 |
|---|---|
| ``QIYU_CLOUD_REALTIME_KEY`` | 云端 key |
| ``QIYU_CLOUD_REALTIME_BASE`` | 服务地址（默认 OpenAI Realtime） |
| ``QIYU_CLOUD_REALTIME_MODEL`` | 模型名 |
"""

from __future__ import annotations

import os
from typing import Optional

from runtime.omni.backends.base import BaseBackend, QueueStream
from runtime.omni.interface import IRealtimeOmniStream
from runtime.omni.types import BackendCapabilities, SessionConfig, SessionState


class CloudRealtimeStream(QueueStream):
    """云端会话占位：先把接口跑通，真实 WebSocket 事件流后续接入。"""

    def __init__(self, config: SessionConfig, base: str, model: str) -> None:
        super().__init__(config, backend_name="cloud_realtime")
        self.base = base
        self.model = model
        self.state = SessionState.CONNECTING.value

    async def _produce(self) -> None:
        await self.emit_event(
            "cloud_not_wired",
            base=self.base,
            model=self.model,
            note="云端 Realtime 协议尚未接线；当前仅验证接口一致性。",
        )
        self.state = SessionState.ERROR.value
        while not self._closed:
            self.pop_inputs()
            await __import__("asyncio").sleep(0.05)


class CloudRealtimeBackend(BaseBackend):
    name = "cloud_realtime"
    display_name = "云端 Realtime Omni（fallback）"

    def __init__(self, **options) -> None:
        super().__init__(**options)
        self.base = os.environ.get("QIYU_CLOUD_REALTIME_BASE", "https://api.openai.com/v1")
        self.model = os.environ.get("QIYU_CLOUD_REALTIME_MODEL", "gpt-4o-realtime-preview")
        self.key = os.environ.get("QIYU_CLOUD_REALTIME_KEY") or os.environ.get("OPENAI_API_KEY", "")

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            audio_in=True, audio_out=True, video_in=False, text_in=True, text_out=True,
            streaming=True, full_duplex=True, barge_in=True, native_speech=True,
            languages=("zh", "en"), backends=("cloud",),
            notes="云端 fallback；协议未接线前不会真正产出内容。",
        )

    def available(self) -> bool:
        return bool(self.key)

    async def _do_load(self) -> None:
        if not self.key:
            raise RuntimeError("未配置 QIYU_CLOUD_REALTIME_KEY，云端 fallback 不可用")

    async def open_stream(self, config: SessionConfig) -> IRealtimeOmniStream:
        stream = CloudRealtimeStream(config, self.base, self.model)
        stream.start_producer()
        return stream


__all__ = ["CloudRealtimeBackend", "CloudRealtimeStream"]
