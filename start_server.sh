#!/usr/bin/env bash
# 栖语 (Qiyu) · 快速前台启动（Linux 服务器分支）
# 用法: ./start_server.sh   （端口/数据目录可用环境变量覆盖）
set -euo pipefail
cd "$(dirname "$0")"
export QIYU_HOST="${QIYU_HOST:-0.0.0.0}"
export QIYU_PORT="${QIYU_PORT:-8765}"
echo "栖语服务器分支启动中: http://$QIYU_HOST:$QIYU_PORT/ （竖屏 UI）"
exec python3 server_entry.py
