# -*- coding: utf-8 -*-
"""Qiyu Runtime · TTSProvider（语音合成，规格§42/§43）。

- 统一接口 synthesize(text, **params)，params 支持 emotion/intensity/speed/pitch/
  pause_style/voice（规格§42：TTS 不只收到 text）。
- 实现：
  1) WindowsSapiTTSProvider —— Windows 自带 System.Speech（零依赖，真实可用）；
  2) EdgeTTSProvider —— 若安装 edge-tts（云端神经音色，更好的人声人格，可选）。
- 角色 voice profile（§43）：从角色 persona_params 读取 voice_profile（speed/pitch/
  voice），情绪平滑变化由调用方控制，本层只接受参数。
- 不可用如实上报，绝不假装发声。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from runtime.providers import AIProvider, ProviderKind, ProviderStatus

TTS_DIR_NAME = "tts"


def _tts_dir() -> Path:
    try:
        from companion.state import get_data_dir
        d = get_data_dir() / TTS_DIR_NAME
    except Exception:
        d = Path("data") / TTS_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


class WindowsSapiTTSProvider(AIProvider):
    """Windows System.Speech 本地 TTS（零依赖，真实合成 WAV）。"""

    kind = ProviderKind.TTS
    id = "windows-sapi"
    name = "TTS（Windows System.Speech 本地合成）"

    def probe(self) -> ProviderStatus:
        import platform
        if platform.system() != "Windows":
            return ProviderStatus(False, backend="", reason="仅支持 Windows")
        return ProviderStatus(True, backend="local", device="System.Speech")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def synthesize(self, text: str, **kwargs) -> Optional[dict]:
        """合成语音，返回 {"path": str, "format": "wav", "duration_ms": int}；失败返回 None。"""
        text = (text or "").strip()
        if not text:
            return None
        if not self.probe().available:
            return None
        speed = _clamp_float(kwargs.get("speed"), 0.5, 2.0, 1.0)      # 语速倍率
        pitch = _clamp_float(kwargs.get("pitch"), 0.5, 2.0, 1.0)      # 音调倍率
        voice = (kwargs.get("voice") or "").strip()
        rate = int((speed - 1.0) * 10)                                # System.Speech Rate: -10..10
        out_name = f"tts_{int(time.time() * 1000)}.wav"
        out_path = _tts_dir() / out_name
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            f"$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Rate = {max(-10, min(10, rate))}; "
            + (f"$s.SelectVoice('{voice}'); " if voice else "")
            + f"$s.SetOutputToWaveFile('{out_path}'); "
            f"$s.Speak('{_ps_escape(text)}'); $s.Dispose()"
        )
        t0 = time.time()
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, timeout=120,
            )
            if r.returncode != 0 or not out_path.exists():
                logger.warning(f"[TTS] System.Speech 合成失败: {r.stderr[:200]}")
                return None
            dur = _wav_duration(out_path)
            from runtime.perf import perf_monitor
            perf_monitor.record("tts_first_packet", value=(time.time() - t0) * 1000.0)
            return {"path": str(out_path), "format": "wav", "duration_ms": int(dur), "engine": "windows-sapi"}
        except Exception as e:
            logger.warning(f"[TTS] 合成异常: {e}")
            return None


class EdgeTTSProvider(AIProvider):
    """edge-tts 神经音色（可选，需安装 edge-tts 并有网络）。"""

    kind = ProviderKind.TTS
    id = "edge-tts"
    name = "TTS（edge-tts 神经音色，可选）"

    def _import(self):
        try:
            import edge_tts  # noqa: F401
            return edge_tts
        except Exception:
            return None

    def probe(self) -> ProviderStatus:
        if self._import() is None:
            return ProviderStatus(False, backend="", reason="未安装 edge-tts（可选依赖）")
        return ProviderStatus(True, backend="cloud", device="edge-tts")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def synthesize(self, text: str, **kwargs) -> Optional[dict]:
        et = self._import()
        if et is None or not self.probe().available:
            return None
        voice = (kwargs.get("voice") or "zh-CN-XiaoxiaoNeural").strip()
        speed = _clamp_float(kwargs.get("speed"), 0.5, 2.0, 1.0)
        rate = f"+{int((speed - 1.0) * 100)}%" if speed >= 1.0 else f"{int((speed - 1.0) * 100)}%"
        out_path = _tts_dir() / f"tts_{int(time.time() * 1000)}.mp3"
        t0 = time.time()
        try:
            com = et.Communicate((text or "").strip(), voice=voice, rate=rate)
            await com.save(str(out_path))
            if not out_path.exists():
                return None
            from runtime.perf import perf_monitor
            perf_monitor.record("tts_first_packet", value=(time.time() - t0) * 1000.0)
            return {"path": str(out_path), "format": "mp3", "duration_ms": 0, "engine": "edge-tts"}
        except Exception as e:
            logger.warning(f"[TTS] edge-tts 合成失败: {e}")
            return None


def _clamp_float(v, lo, hi, default) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except Exception:
        return default


def _ps_escape(text: str) -> str:
    return (text or "").replace("'", "''").replace("\r", " ").replace("\n", " ")[:2000]


def _wav_duration(path: Path) -> float:
    try:
        import wave
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def resolve_tts_provider():
    """按优先级返回可用 TTS Provider：edge-tts（人声更好）→ Windows SAPI。"""
    edge = EdgeTTSProvider()
    if edge.probe().available:
        return edge
    return WindowsSapiTTSProvider()


tts_provider = resolve_tts_provider()

__all__ = [
    "EdgeTTSProvider",
    "WindowsSapiTTSProvider",
    "resolve_tts_provider",
    "tts_provider",
]
