@echo off
chcp 65001 >nul
title 栖语 - 本地 AI 陪伴机器人

echo ============================================
echo   栖语 - 本地 AI 陪伴机器人
echo ============================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查 .env 文件
if not exist .env (
    echo [提示] 未找到 .env 文件，从 .env.example 复制...
    copy .env.example .env
    echo 请编辑 .env 文件配置你的 LLM 地址，然后重新运行。
    pause
    exit /b 1
)

REM 检查依赖
echo [检查依赖...]
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo [安装依赖...]
    pip install -r gateway/requirements.txt
    pip install -r agent/requirements.txt
    pip install -r embedding/requirements.txt
    pip install -r rag/requirements.txt
)

echo.
echo [启动服务...]
echo.

REM 启动主程序
python main.py

echo.
echo [服务已停止]
pause
