@echo off
chcp 65001 >nul
title 栖语 - 打包工具
echo ==========================================
echo   栖语 - Windows 打包工具
echo ==========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

REM 检查依赖
echo [1/3] 检查依赖...
python -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo   正在安装 PyInstaller...
    pip install pyinstaller
)

python -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo   正在安装 pywebview...
    pip install pywebview
)

echo [2/3] 运行环境检查...
python build.py --check-only
if errorlevel 1 (
    echo.
    echo [错误] 环境检查未通过，请修复上述问题
    pause
    exit /b 1
)

echo.
echo [3/3] 开始打包...
python build.py

echo.
echo ==========================================
if exist "dist\Qiyu.exe" (
    echo 打包完成！
    echo 输出文件: dist\Qiyu.exe
    echo.
    echo 直接双击 dist\Qiyu.exe 即可运行
) else (
    echo 打包完成（文件夹模式）
    echo 输出目录: dist\Qiyu\
    echo.
    echo 双击 dist\Qiyu\Qiyu.exe 运行
)
echo ==========================================
pause
