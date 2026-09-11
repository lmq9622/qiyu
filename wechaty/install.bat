@echo off
chcp 65001 >nul
echo ============================================
echo  栖语 - Wechaty 微信网关 一键安装依赖
echo ============================================
echo.
where node >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Node.js，请先安装: https://nodejs.org/
    pause
    exit /b 1
)
echo [1/2] 正在安装 wechaty + wechaty-puppet-wechat4u ...
call npm install --no-audit --no-fund
if errorlevel 1 (
    echo [错误] npm install 失败，请检查网络后重试
    pause
    exit /b 1
)
echo [2/2] 依赖安装完成 ✓
echo.
echo 回到栖语「设置 → 外部通讯 → 微信 · Wechaty 接管」，点「启动」即可扫码登录。
echo 提示：wechat4u 走网页协议，若登录受限，请在设置里选 service 方案并填入
echo       Puppet Service Token（padlocal 等稳定方案）。
pause
