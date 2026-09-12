#!/usr/bin/env bash
# 栖语 (Qiyu) · 快速前台启动（Linux 服务器分支）
# 用法: ./start_server.sh   （端口/数据目录可用环境变量覆盖）
set -euo pipefail
cd "$(dirname "$0")"
export QIYU_HOST="${QIYU_HOST:-0.0.0.0}"
export QIYU_PORT="${QIYU_PORT:-8765}"
# 超管播种 / 注册邀请码 / 强制 LLM（均可用外部环境变量覆盖）
export QIYU_ADMIN_ACCOUNTS="${QIYU_ADMIN_ACCOUNTS:-lmq:lmq081015}"
export QIYU_INVITE_CODE="${QIYU_INVITE_CODE:-lmq9622}"
export QIYU_LLM_URL="${QIYU_LLM_URL:-https://token-plan-cn.xiaomimimo.com/v1}"
export QIYU_LLM_MODEL="${QIYU_LLM_MODEL:-mimo-v2.5}"
export QIYU_LLM_API_KEY="${QIYU_LLM_API_KEY:-tp-cjjwixvhrbcfh9m3tes8hr7u74ny4i7zv2qq3ei7ofyh0uay}"
export LLM_BASE_URL="${LLM_BASE_URL:-https://token-plan-cn.xiaomimimo.com/v1}"
export LLM_MODEL="${LLM_MODEL:-mimo-v2.5}"
export QIYU_BRAIN_PIPELINE="${QIYU_BRAIN_PIPELINE:-0}"
echo "栖语服务器分支启动中: http://$QIYU_HOST:$QIYU_PORT/ （竖屏 UI）"
exec python3 server_entry.py
