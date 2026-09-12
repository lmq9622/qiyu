# -*- coding: utf-8 -*-
"""网关 · Omni 统一协议 WebSocket 路由（规格 §二）。

    ws://<gateway>/v1/omni/session

App / Quest 用统一信封跟 Omni 会话通信；媒体永远走 WebRTC，这里只走信令与事件。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from runtime.omni.session_hub import OmniGatewayHub

router = APIRouter(tags=["omni"])
_hub = OmniGatewayHub()


@router.websocket("/v1/omni/session")
async def omni_session(ws: WebSocket) -> None:
    await ws.accept()

    async def send_json(payload: dict) -> None:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))

    async def recv_json():
        try:
            return json.loads(await ws.receive_text())
        except WebSocketDisconnect:
            return None
        except Exception:
            return None

    try:
        snap = await _hub.handle(send_json, recv_json)
        logger.info(f"[omni] 连接结束: session={snap.get('session_id')} "
                    f"in={((snap.get('counters') or {}).get('in'))} "
                    f"out={((snap.get('counters') or {}).get('out'))}")
    except Exception as e:
        logger.warning(f"[omni] 会话异常: {type(e).__name__}: {e}")
    finally:
        try:
            await ws.close()
        except Exception:
            pass


@router.get("/v1/omni/stats")
async def omni_stats() -> dict:
    return _hub.stats()
