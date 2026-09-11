#!/bin/bash
set -e

echo "============================================"
echo "  栖语 - 本地 AI 陪伴机器人"
echo "============================================"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请安装 Python 3.10+"
    exit 1
fi

# 检查 .env
if [ ! -f .env ]; then
    echo "[提示] 未找到 .env 文件，从 .env.example 复制..."
    cp .env.example .env
    echo "请编辑 .env 文件配置你的 LLM 地址，然后重新运行。"
    exit 1
fi

# 检查依赖
echo "[检查依赖...]"
if ! python3 -c "import fastapi" 2>/dev/null; then
    echo "[安装依赖...]"
    pip3 install -r gateway/requirements.txt
    pip3 install -r agent/requirements.txt
    pip3 install -r embedding/requirements.txt
    pip3 install -r rag/requirements.txt
fi

echo ""
echo "[启动服务...]"
echo ""

# 启动主程序
python3 main.py
