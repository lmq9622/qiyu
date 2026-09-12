<#
.SYNOPSIS
  跑 Ambient Life 策略层的自动测试（用 Unity 自己的编译器，无需 .NET SDK）。

.DESCRIPTION
  AmbientLifeCore 是纯 C# 策略层，测试放在 Assets/QiyuQuest/Editor/AmbientLifeTests.cs，
  由 Unity batchmode 执行。失败时返回码非 0。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\run_ambient_life_tests.ps1
#>
param(
    [string]$Unity = "D:\Unity\Hub\Editor\6000.6.0f1\Editor\Unity.exe",
    [string]$Project = "D:\UnityProjects\QiyuQuestProject",
    [string]$LogFile = "D:\UnityProjects\QiyuQuestProject\Logs\ambient_tests.log"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

& $Unity -batchmode -quit -projectPath $Project `
    -executeMethod Qiyu.Quest.Editor.AmbientLifeTests.RunAll `
    -logFile $LogFile -nographics | Out-Null
$exit = $LASTEXITCODE

$lines = Select-String -Path $LogFile -Pattern 'RUN |PASS |FAIL |AMBIENT ALL PASS|AMBIENT TESTS FAILED|error CS' |
    ForEach-Object { $_.Line }
$lines | Where-Object { $_ -match 'FAIL|AMBIENT|error CS' } | ForEach-Object { Write-Host $_ }
if ($exit -ne 0) {
    Write-Warning "Ambient Life 测试失败（exit=$exit），详见 $LogFile"
    exit $exit
}
Write-Host "Ambient Life 测试通过（exit=0）"
