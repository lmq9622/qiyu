# Qiyu Quest Gateway 一键启动（Windows PowerShell）
# 用法：右键“使用 PowerShell 运行”，或在终端执行：
#   powershell -ExecutionPolicy Bypass -File .\start_quest_server.ps1

$ErrorActionPreference = "Stop"
$backend = Join-Path $PSScriptRoot "backend"
$port = if ($env:QIYU_QUEST_PORT) { $env:QIYU_QUEST_PORT } else { "8766" }

$ip = (Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Sort-Object -Property SkipAsSource, InterfaceMetric |
    Select-Object -First 1 -ExpandProperty IPAddress)

Write-Host "=============================================="
Write-Host " Qiyu Quest Gateway"
Write-Host " 本机 IP : $ip"
Write-Host " Quest 地址: ws://$ip`:$port/v1/quest/ws"
Write-Host " 现有 Qiyu : http://$ip`:8765"
Write-Host "=============================================="
Write-Host "请确保 Quest 与本机在同一局域网；按 Ctrl+C 停止。"
Write-Host ""

$env:QIYU_QUEST_HOST = "0.0.0.0"
$env:QIYU_QUEST_PORT = $port
Set-Location $backend
python quest_server.py
