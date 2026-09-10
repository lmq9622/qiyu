<#
.SYNOPSIS
  Qiyu Quest P7 真机验收采集脚本。

.DESCRIPTION
  安装/启动 APK，按时间轴提示佩戴者做动作，采集应用日志并统计关键事件。
  自动部分只负责“取证”；自然度、打断手感等主观项仍需人工确认
  （见 docs/P7_quest_acceptance.md）。

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\quest_p7_acceptance.ps1
#>
param(
    [string]$Apk = "D:\UnityProjects\QiyuQuestProject\Builds\QiyuQuestP0.apk",
    [string]$Package = "com.qiyu.quest",
    [string]$Serial = "192.168.2.58:5555",
    [int]$DurationSeconds = 180,
    [switch]$SkipInstall,
    [string]$OutputDir = "D:\Codex projects\ai-companion-codex\quest_p7_logs"
)

$ErrorActionPreference = "Stop"
# Unity/adb 输出是 UTF-8；不设这两项中文日志会被按 ANSI 解码成乱码。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$adb = Get-Command adb -ErrorAction SilentlyContinue
if ($null -eq $adb) {
    $candidate = "D:\Unity\Hub\Editor\6000.6.0f1\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools\adb.exe"
    if (Test-Path $candidate) {
        $adbPath = $candidate
    } else {
        throw "未找到 adb。请安装 Android Platform Tools 或把 adb 加入 PATH。"
    }
} else {
    $adbPath = $adb.Source
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logPath = Join-Path $OutputDir "quest_p7_$stamp.log"
$summaryPath = Join-Path $OutputDir "quest_p7_$stamp.summary.json"

Write-Host "[P7] adb=$adbPath"
if ($Serial -like "*:*") {
    & $adbPath connect $Serial | Out-Null
}
$devices = & $adbPath devices
Write-Host ($devices -join "`n")
$readyPattern = if ($Serial) {
    "(^|\s)$([regex]::Escape($Serial))\s+device"
} else {
    "\tdevice$"
}
if (-not ($devices | Select-String -Pattern $readyPattern)) {
    throw "没有已授权的 Quest 设备：请开启开发者模式 / 无线调试，或改用 -Serial 指定设备。"
}
$serialArgs = if ($Serial) { @("-s", $Serial) } else { @() }

if (-not $SkipInstall) {
    if (-not (Test-Path $Apk)) {
        throw "APK 不存在: $Apk"
    }
    Write-Host "[P7] install $Apk"
    & $adbPath @serialArgs install -r -d $Apk
}

Write-Host "[P7] launch $Package"
& $adbPath @serialArgs shell monkey -p $Package -c android.intent.category.LAUNCHER 1 |
    Out-Null

# 佩戴者动作时间轴：每个条目 (秒, 提示)
$timeline = @(
    @(10, "站着不动，看角色 5 秒（观察 idle / 自然视线）"),
    @(20, "叫角色名字，说：你好，你能看到我吗？"),
    @(35, "说：跟我来（等 8 秒看它是否跟随）"),
    @(50, "说：坐到那边去（看是否只对真实椅子执行）"),
    @(62, "说：别过来，站远一点（看是否保持距离）"),
    @(74, "说话中途打断它：等一下！（看 TTS 与行为是否立即切换）"),
    @(86, "对角色挥手（看是否识别并挥手回应）"),
    @(98, "用手指指向房间里的一个物体（看是否共同注意）"),
    @(110, "走近角色，看它是否后退/让位而不是穿模"),
    @(122, "保持沉默 30 秒（观察自主行为，不应呆站不动）")
)
Write-Host "[P7] 佩戴后请按下面时间轴做动作："
foreach ($item in $timeline) {
    Write-Host ("  T+{0,3}s  {1}" -f $item[0], $item[1])
}

Write-Host "[P7] clear logcat and capture $DurationSeconds s"
& $adbPath @serialArgs logcat -c
# 加大缓冲区，避免长时间交互把开头日志挤掉（失败不影响后续流程）。
& $adbPath @serialArgs logcat -G 16M 2>&1 | Out-Null
$appPid = (& $adbPath @serialArgs shell pidof $Package).Trim()
Write-Host "[P7] app pid=$appPid"

Start-Sleep -Seconds $DurationSeconds

# 用 cmd 重定向直接落盘，保证 Unity 的 UTF-8 中文日志原样保存，不经 PowerShell 转码。
$pidFilter = if ($appPid) { " --pid=$appPid" } else { "" }
$dumpCmd = "`"$adbPath`" -s $Serial logcat -d -v time$pidFilter > `"$logPath`""
cmd /c $dumpCmd | Out-Null
if (-not (Test-Path $logPath)) {
    throw "日志导出失败: $logPath"
}
Write-Host ("[P7] 采集到 {0:N0} 字节日志" -f (Get-Item $logPath).Length)

$content = Get-Content -LiteralPath $logPath -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
$patterns = [ordered]@{
    behavior_start = "\[QiyuBehavior\].*启动"
    behavior_directive = "Human→Avatar directive"
    policy_loaded = "QiyuBehaviorPolicy.*behavior-policy-v1"
    reflex_active = "\[Reflex"
    motion_capture = "\[QiyuMotionCapture\]"
    motion_gesture = "gesture="
    motion_library_missing = "缺少动作资产"
    motion_library = "\[QiyuMotionLibrary\]"
    navmesh = "\[QuestNavMesh\]"
    navmesh_selftest = "可达性自检|可行走图"
    navmesh_tiny = "可行走面积仅"
    avatar_placed = "角色已放到用户前方|角色已吸附到最近可行走点"
    mruk = "\[QiyuReconstruction\]"
    websocket = "\[QuestWS\]"
    mic = "\[QuestMic\]"
    tts = "\[QuestTTS\]"
    server_error = "server\.error|server.error"
    exception = "Exception|NullReferenceException|MissingReferenceException"
}
$summary = [ordered]@{}
foreach ($key in $patterns.Keys) {
    $summary[$key] = ([regex]::Matches($content, $patterns[$key])).Count
}
$summary | ConvertTo-Json | Tee-Object -FilePath $summaryPath
Write-Host "[P7] log=$logPath"
Write-Host "[P7] summary=$summaryPath"

if ($summary["exception"] -gt 0 -or $summary["server_error"] -gt 0) {
    Write-Warning "检测到异常或 server.error，请查看日志。"
    exit 2
}
Write-Host "[P7] automatic capture complete; 请按 docs/P7_quest_acceptance.md 做人工验收。"
