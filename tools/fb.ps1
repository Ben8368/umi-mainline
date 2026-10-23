# SPDX-License-Identifier: CC0-1.0
# fb.ps1 — 带超时的 fastboot/adb 状态机（避免"在 Android 里等 fastboot"这类卡死）
#
#   powershell -ExecutionPolicy Bypass -File tools\fb.ps1 -Action state
#   powershell -ExecutionPolicy Bypass -File tools\fb.ps1 -Action tobl
#   powershell -ExecutionPolicy Bypass -File tools\fb.ps1 -Action boot -Image out\boot-umi-p1.img
#   powershell -ExecutionPolicy Bypass -File tools\fb.ps1 -Action boot -Image out\x.img -WatchSec 45
#
# 设计要点（每一条都是从实际踩的坑来的）：
#   * **绝不无限等**：每个 fastboot/adb 调用都有硬超时，超时就 kill。
#   * **先判断状态再动手**：设备可能在 Android(ADB) / fastboot / 都不在。
#     在 Android 里跑 `fastboot xxx` 只会卡住或空转 —— 所以 tobl 会自动二选一。
#   * **一次 fastboot 会话只 boot 一次**：实测这台 ABL 第二次 boot 会返回
#     `Failed to load/authenticate boot image: Load Error`，那是状态残留，不是镜像的问题。
#     所以 boot 之前总是先 tobl，且 boot 完就结束（要再试请重新跑一次）。
#   * `boot` 只下载到内存并跳转，**不写任何分区**。

param(
    [ValidateSet('state', 'tobl', 'boot')]
    [string]$Action = 'state',
    [string]$Image = '',
    [string]$Serial = '',
    [int]$ToBlSec = 75,      # 等它进 fastboot 的最长时间
    [int]$WatchSec = 45,     # boot 之后盯多久
    [int]$CmdSec = 25        # 单条 fastboot/adb 命令的超时
)

$ErrorActionPreference = 'Continue'
$pt = if ($env:ADB_HOME) { $env:ADB_HOME } else { '' }
$adb = if ($env:ADB) { $env:ADB } elseif ($pt) { Join-Path $pt 'adb.exe' } else { 'adb' }
$ft = if ($env:FASTBOOT) { $env:FASTBOOT } elseif ($pt) { Join-Path $pt 'fastboot.exe' } else { 'fastboot' }
$sel = @(); if ($Serial) { $sel = @('-s', $Serial) }
$selPat = if ($Serial) { [regex]::Escape($Serial) } else { '\S+' }

function Run-TO {
    param([string]$Exe, [string[]]$Argv, [int]$TimeoutSec = 25)
    $so = [System.IO.Path]::GetTempFileName()
    try {
        # 关键：用 cmd /c "exe args > 文件 2>&1" 而不是 Start-Process 的管道重定向。
        # adb 会 fork 一个常驻 daemon，如果它继承的是**管道**句柄，父进程读管道就会永远阻塞
        # （这就是"命令会卡住"的根因）。重定向到文件则 daemon 只持有文件句柄，读文件不会阻塞。
        # 路径里可能有空格，直接拼 cmd /c 会被拆开；写成 .bat 最稳。
        $bat = [System.IO.Path]::GetTempFileName() + '.bat'
        $safeArg = $Argv | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_ + '"' } else { $_ } }
        $line = '@echo off' + "`r`n" + '"' + $Exe + '" ' + ($safeArg -join ' ') + ' > "' + $so + '" 2>&1' + "`r`n"
        [System.IO.File]::WriteAllText($bat, $line, (New-Object System.Text.ASCIIEncoding))
        $p = Start-Process -FilePath $bat -NoNewWindow -PassThru
        $ok = $p.WaitForExit($TimeoutSec * 1000)
        if (-not $ok) {
            try { & taskkill /PID $p.Id /T /F | Out-Null } catch { }
            return [pscustomobject]@{ Exit = -999; Out = "<TIMEOUT ${TimeoutSec}s>" }
        }
        $txt = ''
        if (Test-Path -LiteralPath $so) { $txt = [string](Get-Content -LiteralPath $so -Raw -ErrorAction SilentlyContinue) }
        return [pscustomobject]@{ Exit = $p.ExitCode; Out = $txt }
    } finally {
        Remove-Item -LiteralPath $so, $bat -Force -ErrorAction SilentlyContinue
    }
}

function Get-State {
    $r = Run-TO $ft ($sel + @('devices')) 10
    if ($r.Out -match 'fastboot') { return 'FASTBOOT' }
    $r2 = Run-TO $adb @('devices') 10
    if ($r2.Out -match ($selPat + '\s+(device|recovery|sideload)')) { return 'ADB' }
    if ($r2.Out -match ($selPat + '\s+unauthorized')) { return 'ADB_UNAUTH' }
    return 'NONE'
}

$script:LogPath = Join-Path (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)) 'out\fb.log'
function Say([string]$m) {
    Write-Host $m
    try {
        $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
        Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch { }
}

function Done([int]$code) {
    # adb 会 fork 一个常驻 daemon。如果它继承了调用方的 stdout/stderr 句柄，
    # 调用方（比如 DSH 的工具封装）就会一直等 EOF —— 表现就是"命令卡住"。
    # 所以每次退出前把它收掉；下次 adb 用的时候会自动重启。
    try { Run-TO $adb @('kill-server') 8 | Out-Null } catch { }
    exit $code
}

# ------------------------------------------------------------------ state
if ($Action -eq 'state') {
    $s = Get-State
    Say ("fastboot/adb 状态: {0}" -f $s)
    if ($s -eq 'FASTBOOT') {
        Say '  -> bootloader 就绪，可以直接 -Action boot'
        Say ((Run-TO $ft ($sel + @('devices')) 10).Out.Trim())
    } elseif ($s -eq 'ADB') {
        Say '  -> Android / TWRP 里，-Action tobl 会用 adb reboot bootloader'
        Say ((Run-TO $adb @('shell', 'getprop ro.build.version.release') 10).Out.Trim())
    } else {
        # ★ 这里不能只说「NONE」：设备最可能是「内核在跑，停在 panic 屏 / 卡死」，
        #   那种状态下 USB 什么都不枚举，fastboot/adb 当然都看不到。
        #   以前这句只提示「请手动进 fastboot」，会让人误以为手机重启了。
        Say '  -> 既不在 fastboot 也不在 adb。'
        Say '     最可能：内核正在跑，停在 panic 屏（或卡死）。此时 USB 不枚举任何设备，'
        Say '     所以 fastboot/adb 都看不到 —— 这【不代表】它重启了。'
        $usb = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
            Where-Object { $_.InstanceId -match 'VID_18D1|VID_05C6|VID_2717|VID_1D6B' }
        if ($usb) {
            Say '     当前能看到的安卓相关 USB：'
            $usb | ForEach-Object { Say ("       {0}  [{1}]" -f $_.FriendlyName, $_.InstanceId) }
        } else {
            Say '     USB 上没有任何安卓设备 -> 符合「内核已接管但没起 USB」的特征'
        }
        Say '     下一步：看一眼屏幕。若是 panic 二维码，拍照/扫码把日志拿走；'
        Say '     想重新 boot 就长按电源键 10~15 秒强制重启，再跑 -Action boot。'
    }
    Done 0
}

# ------------------------------------------------------------------ tobl
function To-Bootloader {
    $s = Get-State
    Say ("  [tobl] 当前状态: {0}" -f $s)
    if ($s -eq 'FASTBOOT') {
        Say "  [tobl] 已经在 fastboot，做一次 reboot-bootloader 清掉上次 boot 的残留状态"
        $r = Run-TO $ft ($sel + @('reboot-bootloader')) $CmdSec
        Say ("  [tobl] {0}" -f ([string]$r.Out).Trim())
    }
    elseif ($s -eq 'ADB') {
        Say "  [tobl] 在 Android 里 -> adb reboot bootloader"
        $r = Run-TO $adb ($sel + @('reboot','bootloader')) $CmdSec
        Say ("  [tobl] {0}" -f ([string]$r.Out).Trim())
    }
    elseif ($s -eq 'ADB_UNAUTH') {
        Say "  !! adb 未授权：请在手机上点「允许 USB 调试」，或者手动长按 电源+音量下 进 fastboot"
        return $false
    }
    else {
        Say "  !! 既不在 fastboot 也不在 adb。请手动长按 电源+音量下 进 fastboot 后重跑。"
        return $false
    }
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $ToBlSec) {
        Start-Sleep -Milliseconds 500
        if ((Get-State) -eq 'FASTBOOT') {
            Say ("  [tobl] 已进 fastboot（{0:N1}s）" -f ((Get-Date) - $t0).TotalSeconds)
            return $true
        }
    }
    Say ("  !! {0}s 内没进 fastboot" -f $ToBlSec)
    return $false
}

if ($Action -eq 'tobl') {
    if (To-Bootloader) { exit 0 } else { exit 1 }
}

# ------------------------------------------------------------------ boot
if ($Action -eq 'boot') {
    if (-not $Image) { Say '!! -Action boot 需要 -Image'; exit 2 }
    if (-not (Test-Path $Image)) { Say "!! 找不到 $Image"; exit 2 }
    if (-not (To-Bootloader)) { exit 3 }

    Say ("`n  [boot] {0} ({1:N0} 字节) —— 本次会话唯一一次" -f (Split-Path -Leaf $Image), (Get-Item $Image).Length)
    $t1 = Get-Date
    $r = Run-TO $ft ($sel + @('boot', (Resolve-Path $Image).Path)) 90
    ($r.Out.Trim() -split "`r?`n") | ForEach-Object { Say ("    {0}" -f $_) }
    Say ("  [boot] 命令返回 +{0:N2}s" -f ((Get-Date) - $t1).TotalSeconds)

    Say "  [boot] 盯 ${WatchSec}s（只看它离不离开 fastboot）"
    $last = $null; $left = $false
    while (((Get-Date) - $t1).TotalSeconds -lt $WatchSec) {
        $s = Get-State
        $now = if ($s -eq 'FASTBOOT') { 'IN_FASTBOOT' } elseif ($s -eq 'NONE') { 'GONE' } else { $s }
        if ($now -ne $last) {
            Say ("    [{0,6:N2}s] {1}" -f ((Get-Date) - $t1).TotalSeconds, $now)
            $last = $now
            if ($now -ne 'IN_FASTBOOT') { $left = $true }
        }
        if ($left -and ((Get-Date) - $t1).TotalSeconds -gt 4) { break }
        Start-Sleep -Milliseconds 150
    }
    Say ""
    if ($left) { Say "  结论: 离开了 fastboot -> ABL 真的跳转了" ; exit 0 }
    Say "  结论: 一直没离开 fastboot -> ABL 静默拒了这个镜像"
    Done 4
}
