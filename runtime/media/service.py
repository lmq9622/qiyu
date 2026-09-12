# -*- coding: utf-8 -*-
"""VideoCallService：视频通话服务（媒体面的入口）。

它管理多个 :class:`MediaSession`，提供：
  - 建立（offerer/answerer 两种角色）
  - 本机回环（两个真 WebRTC peer，进程内信令）
  - 静音 / 摄像头开关 / 重连 / 关闭
  - 会话列表与汇总统计

**不接 Omni**。要接 AI 请用 ``runtime/media/ai_adapter.py``。
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional

from .session import MediaSession, MediaSessionConfig
from .signaling import InProcessSignaling, SignalingTransport


class VideoCallService:
    def __init__(self, ice_servers: Optional[list] = None):
        self.ice_servers = list(ice_servers or [])
        self._sessions: Dict[str, MediaSession] = {}
        self.started_at = time.time()

    # ---------- 创建会话 ----------
    async def create_session(self, role: str = "offerer",
                             signaling: Optional[SignalingTransport] = None,
                             session_id: str = "", **cfg) -> MediaSession:
        cfg.setdefault("ice_servers", self.ice_servers)
        if session_id:
            cfg["session_id"] = session_id
        config = MediaSessionConfig(role=role, **cfg)
        if signaling is None:
            from .signaling import QueueSignaling
            signaling = QueueSignaling(identity=f"{role}-{config.session_id[:6]}")
        session = MediaSession(config, signaling)
        self._sessions[session.session_id] = session
        return session

    async def connect_loopback(self, video_fps: float = 10.0,
                               audio_sample_rate: int = 48000) -> tuple:
        """本机回环：两个**真实** WebRTC peer 互联（真 ICE/DTLS/SRTP）。

        返回 ``(session_a, session_b)``，两者都已完成协商。
        """
        sig_a, sig_b = InProcessSignaling.pair()
        a = await self.create_session("offerer", sig_a, video_fps=video_fps,
                                      audio_sample_rate=audio_sample_rate)
        b = await self.create_session("answerer", sig_b, video_fps=video_fps,
                                      audio_sample_rate=audio_sample_rate)
        await asyncio.gather(a.start(), b.start())
        await asyncio.gather(a.wait_live(15.0), b.wait_live(15.0))
        return a, b

    # ---------- 汇总 ----------
    def list_sessions(self) -> List[dict]:
        return [s.stats().to_dict() for s in self._sessions.values()]

    def get(self, session_id: str) -> Optional[MediaSession]:
        return self._sessions.get(session_id)

    def summary(self) -> dict:
        states: Dict[str, int] = {}
        for s in self._sessions.values():
            states[s.state] = states.get(s.state, 0) + 1
        return {"sessions": len(self._sessions), "states": states,
                "uptime_s": round(time.time() - self.started_at, 1)}

    async def close_session(self, session_id: str) -> bool:
        s = self._sessions.pop(session_id, None)
        if s is None:
            return False
        await s.close()
        return True

    async def close_all(self) -> None:
        sessions = list(self._sessions.values())
        self._sessions.clear()
        for s in sessions:
            try:
                await s.close()
            except Exception:
                pass

    async def aclose(self) -> None:
        await self.close_all()
