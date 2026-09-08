"""Qiyu + Quest Gateway 启动器。

在现有 Qiyu FastAPI app 上追加 /v1/quest/ws，不修改 demo.py 源文件。

用法：
    cd ai-companion/quest-mr-client/backend
    python quest_server.py

环境变量：
    QIYU_QUEST_HOST=0.0.0.0
    QIYU_QUEST_PORT=8766
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from demo import app  # noqa: E402  加载现有 Qiyu FastAPI app
from qiyu_quest_gateway.gateway import QuestWebSocketGateway  # noqa: E402

quest_gateway = QuestWebSocketGateway()
app.add_api_websocket_route("/v1/quest/ws", quest_gateway.handle_ws)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("QIYU_QUEST_HOST", "0.0.0.0"),
        port=int(os.getenv("QIYU_QUEST_PORT", "8766")),
        log_level="info",
    )
