# -*- coding: utf-8 -*-
"""MediaSession：一次视频通话的媒体会话（独立于 AI 认知层）。

职责边界（很重要）：
- 只管媒体：轨道、协商、静音、摄像头开关、连接状态、重连、统计、关闭；
- **不含**任何 Omni / Avatar / 行为语义；
- 想接 AI 的，走 ``runtime/media/ai_adapter.py`` 的桥。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from .peer import PeerConfig, PeerLink
from .signaling import SignalKind, SignalMessage, SignalingTransport
from .tracks import QueueAudioTrack, SyntheticVideoTrack, ToneAudioTrack
from .types import ConnectionState, MediaSessionState, MediaSessionStats, TrackKind


@dataclass
class MediaSessionConfig:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    role: str = "offerer"                  # offerer / answerer
    ice_servers: list = field(default_factory=list)
    audio: bool = True
    video: bool = True
    video_fps: float = 10.0
    video_size: tuple = (320, 240)
    audio_sample_rate: int = 48000
    connect_timeout: float = 15.0


class MediaSession:
    def __init__(self, config: MediaSessionConfig, signaling: SignalingTransport):
        self.config = config
        self.signaling = signaling
        self.session_id = config.session_id
        self.state = MediaSessionState.IDLE.value
        self.muted = False
        self.camera_enabled = True
        self.reconnects = 0
        self.error = ""

        self.link: Optional[PeerLink] = None
        # 轨道在 _new_link() 里创建：RTCPeerConnection.close() 会把轨道置为 stopped，
        # 重连必须换新对象，否则新连接上再也发不出媒体（实测踩过）。
        self.local_audio: Optional[QueueAudioTrack] = None
        self.local_video: Optional[SyntheticVideoTrack] = None
        self.remote_audio = None
        self.remote_video = None
        self._answer_ready = asyncio.Event()
        self._offer_ready = asyncio.Event()
        self._pending_offer: Optional[dict] = None
        self._created = time.time()
        self._closed = False
        self._on_remote_track = None
        self._seq = 0
        self._reconnect_in_progress = False

    # ---------- 内部：信令 ----------
    async def _handle_signal(self, msg: SignalMessage) -> None:
        if msg.kind == SignalKind.OFFER.value:
            self._pending_offer = msg.payload
            self._offer_ready.set()
            # 已经在通话中又收到 offer = 对端重连/重协商，此时没人等在 start() 里，
            # 需要就地应答（否则对端会一直等不到 answer）。
            if (not self._reconnect_in_progress) and self.state in (
                    MediaSessionState.LIVE.value, MediaSessionState.ERROR.value):
                asyncio.create_task(self._answer_renegotiation(msg.payload))
        elif msg.kind == SignalKind.HELLO.value:
            # 对端（answerer）请求重协商 → 由 offerer 重新发 offer
            if msg.payload.get("renegotiate") and self.config.role == "offerer" \
                    and self.state != MediaSessionState.CLOSED.value:
                asyncio.create_task(self.reconnect())
        elif msg.kind == SignalKind.ANSWER.value:
            if self.link is not None:
                await self.link.set_remote("answer", msg.payload.get("sdp", ""))
            self._answer_ready.set()
        elif msg.kind == SignalKind.TRACK_STATE.value:
            # 对端状态镜像（只记状态，不反向控制对端）
            pass
        elif msg.kind == SignalKind.BYE.value:
            self.state = MediaSessionState.CLOSED.value
            self._closed = True

    async def _answer_renegotiation(self, payload: dict) -> None:
        """就地处理对端的新 offer（重连路径）。"""
        try:
            # 对端重建了 PeerConnection：本端也要重建，否则旧 DTLS 会话对不上。
            if self.link is not None:
                await self.link.close()
            self.remote_audio = None
            self.remote_video = None
            await self._new_link()
            await self.link.set_remote(payload.get("type", "offer"), payload.get("sdp", ""))
            await self.link.create_answer()
            await self.link.wait_ice_gathering(5.0)
            await self._send(SignalKind.ANSWER.value,
                             {"sdp": self.link.pc.localDescription.sdp, "type": "answer"})
            ok = await self.link.wait_connected(10.0)
            self.state = MediaSessionState.LIVE.value if ok else MediaSessionState.ERROR.value
            if ok:
                self.reconnects += 1
        except Exception as e:
            self.error = f"renegotiate:{type(e).__name__}"
            self.state = MediaSessionState.ERROR.value

    async def _send(self, kind: str, payload: dict) -> None:
        self._seq += 1
        await self.signaling.send(SignalMessage(
            kind=kind, session_id=self.session_id,
            from_id=self.signaling.identity, payload=payload, seq=self._seq))

    def on_remote_track(self, cb) -> None:
        self._on_remote_track = cb

    # ---------- 生命周期 ----------
    async def start(self) -> "MediaSession":
        await self.signaling.open()
        self.signaling.on_message(self._handle_signal)
        self.state = (MediaSessionState.OFFERING.value if self.config.role == "offerer"
                      else MediaSessionState.ANSWERING.value)
        await self._new_link()
        if self.config.role == "offerer":
            sdp = await self.link.create_offer()
            await self.link.wait_ice_gathering(5.0)
            sdp = self.link.pc.localDescription.sdp
            await self._send(SignalKind.OFFER.value, {"sdp": sdp, "type": "offer"})
            if not await self._wait_event(self._answer_ready, self.config.connect_timeout):
                self.state = MediaSessionState.ERROR.value
                self.error = "answer_timeout"
                return self
        else:
            if not await self._wait_event(self._offer_ready, self.config.connect_timeout):
                self.state = MediaSessionState.ERROR.value
                self.error = "offer_timeout"
                return self
            payload = self._pending_offer or {}
            await self.link.set_remote(payload.get("type", "offer"), payload.get("sdp", ""))
            sdp = await self.link.create_answer()
            await self.link.wait_ice_gathering(5.0)
            sdp = self.link.pc.localDescription.sdp
            await self._send(SignalKind.ANSWER.value, {"sdp": sdp, "type": "answer"})

        ok = await self.link.wait_connected(self.config.connect_timeout)
        self.state = MediaSessionState.LIVE.value if ok else MediaSessionState.ERROR.value
        if not ok:
            self.error = self.error or "connect_timeout"
        return self

    async def _new_link(self) -> None:
        old_audio = self.local_audio
        if self.config.audio:
            self.local_audio = QueueAudioTrack(sample_rate=self.config.audio_sample_rate)
            self.local_audio.enabled = not self.muted
            if old_audio is not None:
                # 把还没播完的本地音频搬到新轨道，重连不丢话
                while True:
                    try:
                        self.local_audio.push(old_audio.queue.get_nowait())
                    except Exception:
                        break
        else:
            self.local_audio = None
        if self.config.video:
            self.local_video = SyntheticVideoTrack(fps=self.config.video_fps,
                                                   width=self.config.video_size[0],
                                                   height=self.config.video_size[1])
            self.local_video.enabled = self.camera_enabled
        else:
            self.local_video = None
        self.link = PeerLink(PeerConfig(role=self.config.role, ice_servers=self.config.ice_servers))
        if self.local_audio is not None:
            self.link.add_track(self.local_audio)
        if self.local_video is not None:
            self.link.add_track(self.local_video)

        def _got(track):
            if track.kind == TrackKind.AUDIO.value:
                self.remote_audio = track
            elif track.kind == TrackKind.VIDEO.value:
                self.remote_video = track
            if self._on_remote_track is not None:
                self._on_remote_track(track)

        self.link.on_track(_got)

    @staticmethod
    async def _wait_event(ev: asyncio.Event, timeout: float) -> bool:
        try:
            await asyncio.wait_for(ev.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def wait_live(self, timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.state == MediaSessionState.LIVE.value and self.link is not None \
                    and self.link.connection_state == "connected":
                return True
            await asyncio.sleep(0.05)
        return False

    # ---------- 控制 ----------
    def set_muted(self, muted: bool) -> dict:
        self.muted = bool(muted)
        if self.local_audio is not None:
            self.local_audio.enabled = not self.muted
        return {"muted": self.muted}

    def set_camera_enabled(self, enabled: bool) -> dict:
        self.camera_enabled = bool(enabled)
        if self.local_video is not None:
            self.local_video.enabled = self.camera_enabled
        return {"camera_enabled": self.camera_enabled}

    def push_local_audio(self, pcm) -> None:
        if self.local_audio is not None:
            self.local_audio.push(pcm)

    async def notify_track_state(self) -> None:
        await self._send(SignalKind.TRACK_STATE.value, {
            "muted": self.muted, "camera_enabled": self.camera_enabled})

    # ---------- 统计 ----------
    async def sample_quality(self) -> dict:
        if self.link is None:
            return {}
        sample = await self.link.stats()
        return sample.to_dict()

    def stats(self) -> MediaSessionStats:
        st = MediaSessionStats(
            session_id=self.session_id, state=self.state,
            connection=(self.link.connection_state if self.link else ConnectionState.IDLE.value),
            peer_role=self.config.role,
            audio_track_out=self.local_audio is not None,
            video_track_out=self.local_video is not None,
            audio_track_in=self.remote_audio is not None,
            video_track_in=self.remote_video is not None,
            muted=self.muted, camera_enabled=self.camera_enabled,
            created_at=self._created,
            connected_at=(self.link.connected_at if self.link else 0.0),
            reconnects=self.reconnects, error=self.error)
        if self.local_audio is not None:
            st.audio_frames_sent = self.local_audio.frames_sent
        if self.local_video is not None:
            st.video_frames_sent = self.local_video.frames_sent
        return st

    # ---------- 重连 / 关闭 ----------
    async def reconnect(self, timeout: float = 15.0) -> bool:
        """断线重连：重建 PeerConnection，复用同一个信令通道。"""
        self._reconnect_in_progress = True
        self.state = MediaSessionState.RECONNECTING.value
        self._answer_ready = asyncio.Event()
        self._offer_ready = asyncio.Event()
        self._pending_offer = None
        if self.link is not None:
            await self.link.close()
        self.remote_audio = None
        self.remote_video = None
        await self._new_link()
        if self.config.role != "offerer":
            # answerer 自己重连：请 offerer 重新发 offer，然后就地应答
            await self._send(SignalKind.HELLO.value, {"renegotiate": True})
            ok = await self._wait_event(self._offer_ready, timeout)
            if ok:
                payload = self._pending_offer or {}
                await self.link.set_remote(payload.get("type", "offer"), payload.get("sdp", ""))
                await self.link.create_answer()
                await self.link.wait_ice_gathering(5.0)
                await self._send(SignalKind.ANSWER.value,
                                 {"sdp": self.link.pc.localDescription.sdp, "type": "answer"})
        else:
            await self.link.create_offer()
            await self.link.wait_ice_gathering(5.0)
            await self._send(SignalKind.OFFER.value,
                             {"sdp": self.link.pc.localDescription.sdp, "type": "offer"})
            await self._wait_event(self._answer_ready, timeout)
        ok = await self.link.wait_connected(timeout)
        self._reconnect_in_progress = False
        self.reconnects += 1
        self.state = MediaSessionState.LIVE.value if ok else MediaSessionState.ERROR.value
        return ok

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._send(SignalKind.BYE.value, {"reason": "local_close"})
        except Exception:
            pass
        if self.link is not None:
            await self.link.close()
        await self.signaling.close()
        self.state = MediaSessionState.CLOSED.value
