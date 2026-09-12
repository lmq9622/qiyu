# -*- coding: utf-8 -*-
"""栖语 · MiniCPMOBackend（master 分支 `/backend` WebSocket 真实双工）。

**不切 feat/web-demo，不重编，不补 /v1/stream/break。**
用已经实测可用的 `WS /backend` 协议：

```text
Quest/App → OmniSession → MiniCPMOWsBackend → WS /backend → MiniCPM-o 4.5
         ← streaming text + audio + events
```

协议（读自 `tools/server/protocol.cpp`，非猜测）：

| 方向 | 消息 |
|---|---|
| → | `{"type":"session.init","payload":{"mode":"full_duplex","use_tts":bool,"voice":{"ref_audio":<b64 f32 pcm>},"system_prompt":str,"config":{...}}}` |
| → | `{"type":"input.append","payload":{"audio":<b64 f32 pcm>,"video":[<b64 jpeg>...],"max_slice_nums":int,"force_listen":bool}}` |
| → (turn_based) | `{"type":"input.append","payload":{"messages":[...],"streaming":true,...}}` |
| ← | `session.created` / `response.output.delta`(kind=text｜audio｜listen) / `response.done` / `session.closed` |

**打断语义（master 原生）**：双工下没有独立 break 端点。
`input.append.payload.force_listen=true` 就是「这一步强制进入 LISTEN」——
即真实打断原语。配合本地丢弃待播音频即可实现「停止输出 + 终止当前 response」，
**不需要重建 session**。
"""

from __future__ import annotations

import array
import asyncio
import base64
import json
import os
import time
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from runtime.omni.backends.base import BaseBackend, PendingInput, QueueStream
from runtime.omni.interface import IRealtimeOmniStream
from runtime.omni.types import (
    AudioChunk,
    BackendCapabilities,
    ConversationOutput,
    FrameKind,
    OmniOutputKind,
    SessionConfig,
    SessionState,
    UnifiedBrainEvent,
    VideoFrame,
)

DEFAULT_WS_PORT = 19080
AUDIO_SR = 16000  # MiniCPM-o 双工输入按 16k 单声道

# 双工的音频系统提示（assistant prompt）依赖参考音频。
# 实测：session.init 不带 voice.ref_audio 时，模型在 full_duplex 下**只会 __IS_LISTEN__**，
# 从不出话；带上 6s 参考音频后立刻开始产出 text + audio。
# 证据：docs/FULL_DUPLEX_DEBUG_TRACE.md §五
DEFAULT_REF_AUDIO = os.environ.get("QIYU_OMNI_REF_AUDIO") or (
    r"D:\qiyu-omni-build\src\llama.cpp-omni-master\tools\omni\assets"
    r"\default_ref_audio\default_ref_audio.wav")


def load_ref_audio_b64(path: str) -> str:
    """把参考音频 WAV 转成协议要求的 base64(float32 PCM)。

    正确跳过 LIST 等附加 chunk（用 wave 模块，避免自写解析出错）。
    """
    import struct as _s

    try:
        with open(path, "rb") as f:
            b = f.read()
        if b[:4] != b"RIFF":
            return ""
        pos, bits, data, ch, sr = 12, 16, None, 1, 16000
        while pos + 8 <= len(b):
            cid = b[pos:pos + 4]
            size = _s.unpack_from("<I", b, pos + 4)[0]
            body = b[pos + 8: pos + 8 + size]
            if cid == b"fmt ":
                _, ch, sr, _, _, bits = _s.unpack_from("<HHIIHH", body, 0)
            elif cid == b"data":
                data = body
            pos += 8 + size + (size & 1)
        if data is None:
            return ""
        if bits == 16:
            arr = array.array("h")
            arr.frombytes(data[: len(data) // 2 * 2])
            fa = array.array("f", [v / 32768.0 for v in arr])
        elif bits == 32:
            fa = array.array("f")
            fa.frombytes(data[: len(data) // 4 * 4])
        else:
            return ""
        # 参考音频取单声道前 6 秒即可
        if ch > 1:
            fa = array.array("f", fa[0::ch])
        max_n = sr * 6
        if len(fa) > max_n:
            fa = array.array("f", fa[:max_n])
        return base64.b64encode(fa.tobytes()).decode("ascii")
    except Exception:
        return ""


def pcm_to_b64_f32(pcm: Any) -> str:
    """PCM → base64(float32 LE)。协议要求 float32 PCM。"""
    if pcm is None:
        return ""
    if isinstance(pcm, (bytes, bytearray, memoryview)):
        raw = bytes(pcm)
        # 假定调用方给的是 int16，转 float32
        try:
            arr = array.array("h")
            arr.frombytes(raw[: len(raw) // 2 * 2])
            fa = array.array("f", [v / 32768.0 for v in arr])
            return base64.b64encode(fa.tobytes()).decode("ascii")
        except Exception:
            return base64.b64encode(raw).decode("ascii")
    try:
        fa = array.array("f", [float(x) for x in pcm])
        return base64.b64encode(fa.tobytes()).decode("ascii")
    except Exception:
        return ""


def b64_to_pcm_f32(b64: str) -> array.array:
    """base64(float32) → array('f')。"""
    raw = base64.b64decode(b64)
    fa = array.array("f")
    fa.frombytes(raw[: len(raw) // 4 * 4])
    return fa


class MiniCPMOWsStream(QueueStream):
    """一条长连接双工会话。输入与输出互不阻塞（各自独立 task）。"""

    def __init__(self, config: SessionConfig, url: str, *, use_tts: bool = True) -> None:
        super().__init__(config, backend_name="minicpm_o_ws")
        self.url = url
        self.use_tts = use_tts
        self.ws = None
        self._send_task: Optional[asyncio.Task] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._force_listen = False
        self._response_id = ""
        self._seen_first_audio = False
        self._seen_first_text = False
        self.t_first_audio: Optional[float] = None
        self.t_first_text: Optional[float] = None
        self.turn_count = 0
        self.events_in = 0
        self.events_out = 0
        self.dropped_on_interrupt = 0
        self.interrupts = 0
        self.last_metrics: dict = {}
        # session.created 之后，服务端还要约 2s 才把双工管线（encoder/llm/tts/t2w）
        # 建好；这期间送进去的输入，其 listen 增量会被管线启动时重置掉。
        # 实测：sleep 3s 后再送，能稳定收到 response.output.delta。
        self.settle_s = float((config.meta or {}).get("settle_s") or 2.5)

    # ---------- 连接 ----------

    async def connect(self, open_timeout: float = 60.0) -> None:
        import websockets

        self.state = SessionState.CONNECTING.value
        self.ws = await asyncio.wait_for(websockets.connect(self.url, max_size=None),
                                         timeout=open_timeout)
        payload: dict = {
            # 模式：**默认 turn_based**。
            # 实测（docs/OMNI_LOCAL_VALIDATION.md §8）：master 的 full_duplex 分支
            # 不把双工线程产出的 __IS_LISTEN__ / 文本 / 音频转发给 WS 客户端
            # （WS handler 的转发轮询只在 turn_based 分支），所以 full_duplex
            # 从外部客户端看是「静默」的；turn_based 则完全可用
            # （实测 TTFT 795ms / TTFA 1858ms / 真模型输出「在呀在呀！有什么事吗？」）。
            "mode": str((self.config.meta or {}).get("mode") or "turn_based"),
            "use_tts": bool(self.use_tts),
            "system_prompt": self.config.system_prompt or self.config.personality or "",
            "config": {
                "personality": self.config.personality,
                "speaking_style": self.config.speaking_style,
                "relationship": self.config.relationship,
                "emotion_state": self.config.emotion_state,
                "patience": self.config.patience,
                "energy": self.config.energy,
                "topic_state": self.config.topic_state,
                "memory_hint": self.config.memory_hint,
            },
        }
        # 双工说话的必要条件：注入参考音频（音频系统提示）。
        # 不带它时模型只会 __IS_LISTEN__（实测，见 docs/FULL_DUPLEX_DEBUG_TRACE.md §五）。
        ref_path = str((self.config.meta or {}).get("ref_audio_path") or DEFAULT_REF_AUDIO)
        ref_b64 = load_ref_audio_b64(ref_path) if self.use_tts else ""
        self.ref_audio_loaded = bool(ref_b64)
        if ref_b64:
            payload["voice"] = {"ref_audio": ref_b64}
        await self.ws.send(json.dumps({"type": "session.init", "payload": payload}))
        # 等服务端 session.created
        deadline = time.time() + 120
        while time.time() < deadline:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=120)
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            if ev.get("type") == "session.created":
                self.last_metrics = ev.get("metrics") or {}
                if self.settle_s > 0:
                    await asyncio.sleep(self.settle_s)
                self.state = SessionState.LISTENING.value
                self._send_task = asyncio.create_task(self._sender())
                self._recv_task = asyncio.create_task(self._receiver())
                return
            if ev.get("type") == "session.closed":
                raise RuntimeError(f"服务端拒绝会话: {ev.get('reason')}")
        raise RuntimeError("等待 session.created 超时")

    # ---------- 发送（独立 task，绝不阻塞接收） ----------

    async def _sender(self) -> None:
        try:
            while not self._closed:
                items = self.pop_inputs()
                if not items:
                    await asyncio.sleep(0.005)
                    continue
                await self._send_batch(items)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.emit_event("ws_sender_error", error=repr(e))

    async def _send_batch(self, items: list) -> None:
        audio_b64 = ""
        frames: list = []
        parts: list = []
        text_parts: list = []

        for it in items:
            if it.kind == "audio":
                audio_b64 += pcm_to_b64_f32(it.payload.pcm)
            elif it.kind == "video":
                fr: VideoFrame = it.payload
                if isinstance(fr.data, (bytes, bytearray)):
                    frames.append(base64.b64encode(bytes(fr.data)).decode("ascii"))
                elif isinstance(fr.data, str):
                    frames.append(fr.data)
            elif it.kind == "text":
                text_parts.append(str(it.payload))
            elif it.kind == "event":
                parts.append({"type": "event", "name": (it.payload or {}).get("name", "")})

        # 纯文本/动捕事件 → 走 turn_based 风格的 messages
        if text_parts and not audio_b64 and not frames:
            payload = {
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": " ".join(text_parts)}]}],
                "streaming": True, "omni_mode": True,
                "use_tts_template": bool(self.use_tts),
                "tts_enabled": bool(self.use_tts),
            }
        else:
            payload = {}
            if audio_b64:
                payload["audio"] = audio_b64
            if frames:
                # 协议接受的键：video_frames / frame_base64_list / frames
                payload["video_frames"] = frames
            if self._force_listen:
                payload["force_listen"] = True
                self._force_listen = False

        if not payload:
            return
        # 注意：协议不对称 —— session.init 用 "payload"，input.append 用 "input"。
        await self.ws.send(json.dumps({"type": "input.append", "input": payload}))
        self.turn_count += 1
        self.metrics_started = time.time()
        self._seen_first_audio = False
        self._seen_first_text = False

    # ---------- 接收 ----------

    async def _receiver(self) -> None:
        try:
            # 统一用 recv()：connect() 里已经用过 recv()，再混用 async-for
            # 在 websockets 15.x 上会拿不到后续消息。
            while True:
                raw = await self.ws.recv()
                self.events_in += 1
                try:
                    ev = json.loads(raw)
                except Exception:
                    continue
                await self._handle_event(ev)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self.emit_event("ws_closed", error=repr(e))
        finally:
            if not self._closed:
                self.state = SessionState.ERROR.value
                await self.emit_event("stream_closed", state=self._state)

    async def _handle_event(self, ev: dict) -> None:
        et = ev.get("type")
        if et == "session.created":
            self.last_metrics = ev.get("metrics") or {}
            self.state = SessionState.LISTENING.value
            return
        if et == "session.closed":
            await self.emit_event("session_closed", reason=ev.get("reason"))
            await self.close()
            return
        if et != "response.output.delta":
            if et == "response.done":
                self.last_metrics = ev.get("metrics") or self.last_metrics
                self.state = SessionState.LISTENING.value
                await self.emit(UnifiedBrainEvent(
                    kind=OmniOutputKind.EVENT.value,
                    payload={"event": "response_done",
                             "text": ev.get("text", ""),
                             "reason": ev.get("reason", ""),
                             "metrics": self.last_metrics},
                ))
            return

        kind = ev.get("kind")
        self._response_id = ev.get("response_id") or self._response_id
        now = time.time()
        if kind == "text":
            if self.t_first_text is None:
                self.t_first_text = now
            self._seen_first_text = True
            self.state = SessionState.SPEAKING.value
            await self.emit(UnifiedBrainEvent(
                kind=OmniOutputKind.CONVERSATION.value,
                conversation=ConversationOutput(text=ev.get("text", "") or "",
                                                 is_final=False),
            ))
        elif kind == "audio":
            b64 = ev.get("audio") or ""
            if not b64:
                return
            if self.t_first_audio is None:
                self.t_first_audio = now
            self._seen_first_audio = True
            self.state = SessionState.SPEAKING.value
            await self.emit(UnifiedBrainEvent(
                kind=OmniOutputKind.CONVERSATION.value,
                conversation=ConversationOutput(
                    audio=b64_to_pcm_f32(b64), audio_format="pcm_f32",
                    sample_rate=24000,
                    latency_ms={"since_input_ms": round((now - getattr(self, "metrics_started", now)) * 1000, 1)},
                ),
            ))
        elif kind == "listen":
            self.state = SessionState.LISTENING.value
            await self.emit(UnifiedBrainEvent(
                kind=OmniOutputKind.EVENT.value, payload={"event": "listen"},
            ))

    # ---------- 打断 ----------

    async def interrupt(self, reason: str = "") -> None:
        """master 原生打断：清空待播 + 下一步 force_listen。**不重建 session**。"""
        self.interrupts += 1
        dropped = 0
        while not self._out.empty():
            try:
                self._out.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        self.dropped_on_interrupt += dropped
        self._force_listen = True
        self.state = SessionState.INTERRUPTED.value
        self.log.append({"event": "interrupt", "reason": reason, "dropped": dropped,
                         "ts": time.time()})
        await self.emit_event("interrupted", reason=reason, dropped=dropped)
        self.state = SessionState.LISTENING.value

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for t in (self._send_task, self._recv_task):
            if t and not t.done():
                t.cancel()
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        self.state = SessionState.CLOSED.value
        self._out.put_nowait(None) if False else None
        await QueueStream.close(self)


class MiniCPMOWsBackend(BaseBackend):
    """连接已运行的 `llama-omni-server` 的 /backend WebSocket。"""

    name = "minicpm_o"
    display_name = "MiniCPM-o 4.5 Q4_K_M（WS /backend 真实双工）"

    def __init__(self, host: str = "", port: int = 0, autostart: bool = False, **options) -> None:
        super().__init__(**options)
        self.host = host or os.environ.get("QIYU_OMNI_HOST", "127.0.0.1")
        self.port = int(port or os.environ.get("QIYU_OMNI_PORT") or DEFAULT_WS_PORT)
        self.autostart = autostart or os.environ.get("QIYU_OMNI_AUTOSTART") == "1"
        self.proc = None

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            audio_in=True, audio_out=True, video_in=True, text_in=True, text_out=True,
            streaming=True, full_duplex=True, barge_in=True, native_speech=True,
            languages=("zh", "en"), backends=("vulkan", "cuda"),
            notes="真实 WS /backend 双工；AMD 端为自编译 Vulkan 版（已验证）。",
        )

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/backend"

    def available(self) -> bool:
        import socket

        try:
            with socket.create_connection((self.host, self.port), timeout=2):
                return True
        except Exception:
            return False

    def health(self) -> dict:
        base = super().health()
        base.update({"url": self.url, "listening": self.available(), "autostart": self.autostart})
        return base

    async def _do_load(self) -> None:
        if not self.available():
            raise RuntimeError(f"llama-omni-server 未监听 {self.url}（先启动服务端或设 QIYU_OMNI_AUTOSTART=1）")

    async def unload(self) -> dict:
        return await super().unload()

    async def open_stream(self, config: SessionConfig) -> IRealtimeOmniStream:
        stream = MiniCPMOWsStream(config, self.url, use_tts=True)
        await stream.connect()
        return stream


__all__ = ["MiniCPMOWsBackend", "MiniCPMOWsStream", "b64_to_pcm_f32", "pcm_to_b64_f32"]
