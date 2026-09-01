# -*- coding: utf-8 -*-
"""Qiyu Runtime · STTProvider（语音识别，规格§42）。

- 本地 ASR：sherpa-onnx + paraformer-zh（复用 channels.wechat_voice 的能力，
  走统一 Provider 接口，业务层不再直接碰 sherpa 实现）。
- 模型目录：环境变量 QIYU_ASR_MODEL 或 data/asr（encoder.onnx/decoder.onnx/tokens.txt）。
- 不可用时如实上报 unavailable（微信自带 iLink 转写仍是主路径，本 Provider 是显式接口）。
"""
from __future__ import annotations

import time
from typing import Any

from loguru import logger

from runtime.providers import AIProvider, ProviderKind, ProviderStatus


class SherpaOnnxSTTProvider(AIProvider):
    """本地 sherpa-onnx 语音识别（真实执行，失败如实返回空串）。"""

    kind = ProviderKind.STT
    id = "sherpa-onnx"
    name = "STT（sherpa-onnx paraformer-zh 本地识别）"

    def probe(self) -> ProviderStatus:
        try:
            from channels.wechat_voice import local_asr_available
            ok = bool(local_asr_available())
            return ProviderStatus(
                available=ok,
                backend="cpu",
                device="sherpa-onnx",
                reason="" if ok else "未安装 sherpa-onnx 或未找到 ASR 模型目录（可设 QIYU_ASR_MODEL）",
            )
        except Exception as e:
            return ProviderStatus(False, backend="", reason=f"ASR 探测失败: {e}")

    def status(self) -> ProviderStatus:
        return self.probe()

    async def transcribe(self, audio: Any) -> str:
        """audio：音频字节流(bytes) 或文件路径(str)。失败返回 ""（不假装识别成功）。"""
        st = self.probe()
        if not st.available:
            return ""
        try:
            from channels.wechat_voice import transcribe_voice_bytes
        except Exception:
            return ""
        t0 = time.time()
        try:
            text = transcribe_voice_bytes(audio)
        except Exception as e:
            logger.warning(f"[STT] 识别失败: {e}")
            return ""
        finally:
            from runtime.perf import perf_monitor
            perf_monitor.record("stt_latency", value=(time.time() - t0) * 1000.0)
        return (text or "").strip()


stt_provider = SherpaOnnxSTTProvider()

__all__ = ["SherpaOnnxSTTProvider", "stt_provider"]
