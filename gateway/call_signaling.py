# -*- coding: utf-8 -*-
"""网关 · 视频通话信令 WebSocket 路由。

把浏览器 / Quest 的 WebSocket 信令接到 ``runtime.media`` 的 MediaSession：

    ws://<gateway>/v1/call/signal

协议见 ``runtime/media/gateway_bridge.py`` 头部注释。
媒体永远是 WebRTC（这里**只**传信令，绝不传视频帧）。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from runtime.media.gateway_bridge import CallSignalingBridge

router = APIRouter(tags=["call"])
_bridge = CallSignalingBridge()


@router.websocket("/v1/call/signal")
async def call_signal(ws: WebSocket) -> None:
    await ws.accept()

    async def send_json(text: str) -> None:
        await ws.send_text(text)

    async def recv_json():
        try:
            return json.loads(await ws.receive_text())
        except WebSocketDisconnect:
            return None
        except Exception:
            return None

    try:
        stats = await _bridge.run(send_json, recv_json)
        logger.info(f"[call] 会话结束: {stats.get('session_id')} "
                    f"state={stats.get('state')} reconnects={stats.get('reconnects')}")
    except Exception as e:
        logger.warning(f"[call] 信令通道异常: {type(e).__name__}: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@router.get("/v1/call/stats")
async def call_stats() -> dict:
    """呼叫层只读状态：最近一次会话统计 + 服务累计。"""
    return {"last_session": _bridge.last_close_stats,
            "connections": _bridge.connections,
            "service": _bridge.service.summary()}
