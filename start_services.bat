@echo off
chcp 65001 >nul
title 栖语 - 服务一键启动
echo ============================================
echo   栖语 Qiyu - 本地服务启动 (Postgres + Letta + 主程序)
echo ============================================
echo.

set "PY=C:\Users\lmq20\AppData\Local\Programs\Python\Python313\python.exe"
set "LETTA_EXE=C:\Users\lmq20\AppData\Local\Programs\Python\Python313\Scripts\letta.exe"
set "PGBIN=C:\Users\lmq20\.ai-companion\runtime\pgsql\bin"
set "PGDATA=C:\Users\lmq20\.ai-companion\data\letta-pg"
set "ROOT=%~dp0"

REM ---- 1) PostgreSQL ----
netstat -an | findstr ":5432 " | findstr "LISTENING" >nul
if errorlevel 1 (
    echo [1/3] 启动 PostgreSQL...
    start "栖语-PostgreSQL" "%PGBIN%\postgres.exe" -D "%PGDATA%" -p 5432
    timeout /t 3 /nobreak >nul
) else (
    echo [1/3] PostgreSQL 已在运行 (5432)
)

REM ---- 2) Letta Agent Server ----
netstat -an | findstr ":8283 " | findstr "LISTENING" >nul
if errorlevel 1 (
    echo [2/3] 启动 Letta Agent Server...
    set "LETTA_PG_URI=postgresql+pg8000://letta:letta@127.0.0.1:5432/letta"
    start "栖语-Letta" "%LETTA_EXE%" server --port 8283 --host 127.0.0.1
    timeout /t 6 /nobreak >nul
) else (
    echo [2/3] Letta Server 已在运行 (8283)
)

REM ---- 3) 主程序 demo.py ----
netstat -an | findstr ":8765 " | findstr "LISTENING" >nul
if errorlevel 1 (
    echo [3/3] 启动栖语主程序 (8765)...
    start "栖语-Demo" "%PY%" "%ROOT%demo.py"
) else (
    echo [3/3] 主程序已在运行 (8765)
)

echo.
echo 访问: http://127.0.0.1:8765
pause