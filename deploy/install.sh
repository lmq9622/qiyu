#!/usr/bin/env bash
# 栖语 (Qiyu) · Linux 服务器一键安装脚本
# 用法（在服务器项目根目录执行）:
#   bash deploy/install.sh            # 安装 + systemd 服务 + 启动
#   QIYU_PORT=9000 bash deploy/install.sh   # 自定义端口
set -euo pipefail

cd "$(dirname "$0")/.."
APP_DIR="$(pwd)"
APP_NAME="qiyu-server"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${QIYU_PORT:-8765}"
VENV_DIR="$APP_DIR/.venv-server"

log() { echo -e "\033[36m[qiyu]\033[0m $*"; }
die() { echo -e "\033[31m[qiyu] 错误: $*\033[0m" >&2; exit 1; }

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "找不到 $PYTHON_BIN，请先安装 Python 3.10+"

# 1) 虚拟环境 + 依赖（letta/torch 较重，若服务器已有全局环境可设 SKIP_DEPS=1 跳过）
if [[ "${SKIP_DEPS:-0}" != "1" ]]; then
  if [[ ! -d "$VENV_DIR" ]]; then
    log "创建虚拟环境 $VENV_DIR"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  log "安装 Python 依赖（首次较慢）"
  pip install --upgrade pip
  pip install -r requirements.txt
  PYTHON="$VENV_DIR/bin/python"
else
  PYTHON="$PYTHON_BIN"
fi

# 2) 数据目录（对话数据全部落盘在这里）
DATA_DIR="${QIYU_DATA_DIR:-/var/lib/qiyu/data}"
mkdir -p "$DATA_DIR"
# 超管播种 / 注册邀请码 / 强制 LLM（均可用外部环境变量覆盖）
export QIYU_ADMIN_ACCOUNTS="${QIYU_ADMIN_ACCOUNTS:-lmq:lmq081015}"
export QIYU_INVITE_CODE="${QIYU_INVITE_CODE:-lmq9622}"
export QIYU_LLM_URL="${QIYU_LLM_URL:-https://token-plan-cn.xiaomimimo.com/v1}"
export QIYU_LLM_MODEL="${QIYU_LLM_MODEL:-mimo-v2.5}"
export QIYU_LLM_API_KEY="${QIYU_LLM_API_KEY:-tp-cjjwixvhrbcfh9m3tes8hr7u74ny4i7zv2qq3ei7ofyh0uay}"
export LLM_BASE_URL="${LLM_BASE_URL:-https://token-plan-cn.xiaomimimo.com/v1}"
export LLM_MODEL="${LLM_MODEL:-mimo-v2.5}"
export QIYU_BRAIN_PIPELINE="${QIYU_BRAIN_PIPELINE:-0}"
log "数据目录: $DATA_DIR"

# 3) systemd 服务（非 root 则给出提示，不强制）
SERVICE_SRC="$(cd "$(dirname "$0")" && pwd)/qiyu-server.service"
if [[ $EUID -eq 0 ]] && command -v systemctl >/dev/null 2>&1; then
  log "写入 systemd 服务 /etc/systemd/system/$APP_NAME.service"
  sed -e "s|__APP_DIR__|$APP_DIR|g" \
      -e "s|__PYTHON__|$PYTHON|g" \
      -e "s|__PORT__|$PORT|g" \
      -e "s|__DATA_DIR__|$DATA_DIR|g" \
      "$SERVICE_SRC" > "/etc/systemd/system/$APP_NAME.service"
  systemctl daemon-reload
  systemctl enable --now "$APP_NAME"
  log "systemd 服务已启动"
else
  log "未启用 systemd（非 root 或无 systemctl）。手动前台启动示例："
  log "  QIYU_PORT=$PORT QIYU_DATA_DIR=$DATA_DIR $PYTHON server_entry.py"
fi

log "完成！访问 http://<服务器IP>:$PORT/ （竖屏 UI）"
