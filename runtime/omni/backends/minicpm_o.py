# -*- coding: utf-8 -*-
"""栖语 · MiniCPMOBackend（规格 §19 / §20 / §23）。

首选模型：**MiniCPM-o 4.5 Q4_K_M**，跑在 App 所在机器本地。

设计原则（照抄规格里最容易自欺欺人的那几条）：

1. **不默认 AMD 一定支持。** ``available()`` 只检查「运行时二进制 + 权重文件」
   是否存在；真正的可用性必须由 ``verify_amd_backend.py`` 在目标机器上实测
   （编译 → 加载 → vision → audio in → audio out → streaming → full duplex）。
2. **不用普通 llama.cpp 支持 AMD 就声称 Omni 支持。** Omni 需要
   vision/audio/双工，这是 ``llama.cpp-omni`` 级别的能力，普通文本推理通过不算。
3. 运行时后端选型和端口都从环境变量读，不写死。

环境变量：

| 变量 | 含义 |
|---|---|
| ``QIYU_OMNI_SERVER`` | llama.cpp-omni 服务端可执行文件路径 |
| ``QIYU_OMNI_GGUF`` | MiniCPM-o 4.5 Q4_K_M 权重路径 |
| ``QIYU_OMNI_MMPROJ`` | 视觉/音频投影文件（如需要） |
| ``QIYU_OMNI_PORT`` | 服务端口（默认 8199） |
| ``QIYU_OMNI_BACKEND`` | vulkan / rocm / hip / cpu |
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from runtime.omni.backends.base import BaseBackend, PendingInput, QueueStream
from runtime.omni.interface import IRealtimeOmniStream
from runtime.omni.types import (
    AudioChunk,
    AvatarIntent,
    BackendCapabilities,
    ConversationOutput,
    OmniOutputKind,
    SessionConfig,
    SessionState,
    UnifiedBrainEvent,
    VideoFrame,
)

DEFAULT_PORT = 8199
WEIGHT_GLOBS = ("*MiniCPM-o*4_5*Q4_K_M*.gguf", "*MiniCPM-o*Q4_K_M*.gguf", "*minicpm-o*.gguf")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def find_server() -> Optional[Path]:
    env = os.environ.get("QIYU_OMNI_SERVER")
    if env and Path(env).exists():
        return Path(env)
    root = _project_root()
    for cand in (
        root / "backends" / "omni" / "llama-server-omni.exe",
        root / "backends" / "omni" / "llama-server.exe",
        root / "backends" / "omni" / "llama-server",
    ):
        if cand.exists():
            return cand
    return None


def find_weights() -> Optional[Path]:
    env = os.environ.get("QIYU_OMNI_GGUF")
    if env and Path(env).exists():
        return Path(env)
    root = _project_root()
    for base in (root / "models" / "omni", root / "models" / "realtime"):
        if not base.is_dir():
            continue
        for pattern in WEIGHT_GLOBS:
            hits = sorted(base.rglob(pattern))
            if hits:
                return hits[0]
    return None


def probe_amd_backends() -> dict:
    """探测本机可用的 AMD 后端线索。**只是线索，不是可用性结论。**"""
    out = {"vulkan": False, "rocm": False, "hip": False, "cpu": True, "gpus": []}
    # Vulkan：查注册表/驱动 DLL
    for dll in ("vulkan-1.dll",):
        for base in (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32",):
            if (base / dll).exists():
                out["vulkan"] = True
    # ROCm/HIP：查常见安装位置
    for p in (r"C:\Program Files\AMD\ROCm", r"C:\Program Files\AMD\ROCm\bin", os.environ.get("HIP_PATH", "")):
        if p and Path(p).exists():
            out["rocm"] = True
            out["hip"] = True
            out["gpus"].append(p)
    # 显卡名（wmic 已废弃，用 CIM）
    try:
        ps = ("Get-CimInstance Win32_VideoController | "
              "Select-Object -ExpandProperty Name")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            out["gpus"] = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    except Exception:
        pass
    return out


class MiniCPMOStream(QueueStream):
    """通过本地 llama.cpp-omni HTTP 服务做流式双工。"""

    def __init__(self, config: SessionConfig, base_url: str, model_name: str = "minicpm-o") -> None:
        super().__init__(config, backend_name="minicpm_o")
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self._pending_text: list = []
        self._abort = False
        self.state = SessionState.LISTENING.value

    async def _on_interrupt(self, reason: str) -> None:
        self._abort = True

    async def _produce(self) -> None:
        while not self._closed:
            items = self.pop_inputs()
            if not items:
                await asyncio.sleep(0.01)
                continue
            texts = [i for i in items if i.kind == "text"]
            if texts:
                self._abort = False
                await self._stream_reply("\n".join(str(t.payload) for t in texts))
            # 音频/视频：由 backend 的音/视接口处理（此处暂存，供未来 turn 拼装）
            for i in items:
                if i.kind == "event":
                    await self._handle_event(i.payload)

    async def _handle_event(self, payload: dict) -> None:
        name = str((payload or {}).get("name") or "")
        if name in ("stop", "reject"):
            await self.interrupt("human_interaction:stop")

    async def _stream_reply(self, user_text: str) -> None:
        self.state = SessionState.THINKING.value
        body = {
            "model": self.model_name,
            "stream": True,
            "messages": [
                {"role": "system", "content": self.config.system_prompt or self.config.personality},
                {"role": "user", "content": user_text},
            ],
            "modalities": ["text", "audio"],
        }
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        self.state = SessionState.SPEAKING.value
        try:
            raw = await asyncio.to_thread(self._read_sse, req)
        except Exception as e:
            await self.emit_event("backend_error", error=repr(e))
            return
        for chunk in raw:
            if self._abort or self._closed:
                self._abort = False
                return
            await self.emit(chunk)
        await self.emit_text("", final=True)
        self.state = SessionState.LISTENING.value

    @staticmethod
    def _read_sse(req) -> list:
        """同步读 SSE；在 to_thread 里跑，避免阻塞事件循环。"""
        events: list = []
        with urllib.request.urlopen(req, timeout=120) as resp:
            for line in resp:
                line = line.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except Exception:
                    continue
                delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                text = delta.get("content")
                if text:
                    events.append(UnifiedBrainEvent(
                        kind=OmniOutputKind.CONVERSATION.value,
                        conversation=ConversationOutput(text=text, is_final=False),
                    ))
                audio = delta.get("audio") or {}
                if audio:
                    events.append(UnifiedBrainEvent(
                        kind=OmniOutputKind.CONVERSATION.value,
                        conversation=ConversationOutput(
                            audio=audio.get("data"),
                            audio_format=audio.get("format", "pcm_s16"),
                            sample_rate=int(audio.get("sample_rate") or 24000),
                        ),
                    ))
        return events


class MiniCPMOBackend(BaseBackend):
    name = "minicpm_o"
    display_name = "MiniCPM-o 4.5 Q4_K_M（llama.cpp-omni）"

    def __init__(self, port: Optional[int] = None, **options) -> None:
        super().__init__(**options)
        self.port = int(port or os.environ.get("QIYU_OMNI_PORT") or DEFAULT_PORT)
        self.server: Optional[Path] = None
        self.weights: Optional[Path] = None
        self.proc: Optional[subprocess.Popen] = None
        self.backend_kind = os.environ.get("QIYU_OMNI_BACKEND", "")

    # ---------- 能力 / 可用性 ----------

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            audio_in=True, audio_out=True, video_in=True, text_in=True, text_out=True,
            streaming=True, full_duplex=True, barge_in=True, native_speech=True,
            languages=("zh", "en"),
            backends=(self.backend_kind or "auto",),
            notes="原生全双工 omni；AMD 支持需实测，未实测前不宣称可用。",
        )

    def available(self) -> bool:
        self.server = find_server()
        self.weights = find_weights()
        return bool(self.server and self.weights)

    def health(self) -> dict:
        base = super().health()
        base.update({
            "server": str(self.server) if self.server else "",
            "weights": str(self.weights) if self.weights else "",
            "port": self.port,
            "weights_gb": round(self.weights.stat().st_size / 1073741824, 2) if self.weights else 0,
            "notes": "available() 只代表『文件和二进制存在』；AMD 可用性必须跑 verify_amd_backend.py。",
        })
        return base

    # ---------- 生命周期 ----------

    async def _do_load(self) -> None:
        if not self.available():
            raise RuntimeError(
                "MiniCPM-o 运行时或权重缺失：请设置 QIYU_OMNI_SERVER / QIYU_OMNI_GGUF，"
                "或把 llama-server-omni 放到 backends/omni/、权重放到 models/omni/"
            )
        assert self.server and self.weights
        args = [
            str(self.server), "-m", str(self.weights),
            "--host", "127.0.0.1", "--port", str(self.port),
            "--no-webui",
        ]
        mmproj = os.environ.get("QIYU_OMNI_MMPROJ")
        if mmproj:
            args += ["--mmproj", mmproj]
        if self.backend_kind:
            args += ["--device", self.backend_kind]
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 180
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama.cpp-omni 进程提前退出（返回码 {self.proc.returncode}）")
            if await self._ping():
                return
            await asyncio.sleep(1.0)
        raise RuntimeError("等待 llama.cpp-omni 就绪超时（180s）")

    async def _ping(self) -> bool:
        def _do() -> bool:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/health", timeout=2) as r:
                    return r.status == 200
            except Exception:
                return False
        return await asyncio.to_thread(_do)

    async def unload(self) -> dict:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except Exception:
                self.proc.kill()
        self.proc = None
        return await super().unload()

    async def open_stream(self, config: SessionConfig) -> IRealtimeOmniStream:
        stream = MiniCPMOStream(config, f"http://127.0.0.1:{self.port}")
        stream.start_producer()
        return stream


__all__ = [
    "DEFAULT_PORT",
    "MiniCPMOBackend",
    "MiniCPMOStream",
    "find_server",
    "find_weights",
    "probe_amd_backends",
]
