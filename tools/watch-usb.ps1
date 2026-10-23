# SPDX-License-Identifier: CC0-1.0
# watch-usb.ps1 — 上机时的「不看屏幕的眼睛」
#
#   powershell -ExecutionPolicy Bypass -File tools\watch-usb.ps1
#   powershell -ExecutionPolicy Bypass -File tools\watch-usb.ps1 -TimeoutSec 600 -Log out\usb-console.log
#
# 干三件事：
#   1. 一直盯 USB，只要出现 VID_1D6B&PID_0104（我们 initramfs 里 gadget 的 ID）
#      就打印带秒数的时间戳 —— 这一条就证明「内核跑到用户态了」，不需要看屏幕
#   2. 出现串口设备后自动打开，把控制台内容同时打到屏幕和日志文件
#   3. 设备消失也记一笔（说明重启/复位了），这样能看出「黑屏几秒」到底几秒
#
# 用法：先启动它，再 fastboot boot。

param(
    [int]$TimeoutSec = 300,
    [string]$Vid = '1D6B',
    [string]$Pid = '0104',
    [string]$Log = '',
    [int]$Baud = 115200
)

$ErrorActionPreference = 'SilentlyContinue'
$start = Get-Date
$pattern = "VID_$Vid&PID_$Pid"

if ($Log -eq '') {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $Log = Join-Path (Split-Path -Parent $here) 'out\usb-console.log'
}
$logDir = Split-Path -Parent $Log
if ($logDir -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Elapsed { '{0,6:N1}s' -f ((Get-Date) - $start).TotalSeconds }

function Say([string]$msg) {
    $line = "[$(Elapsed)] $msg"
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

function Get-GadgetDevices {
    # PS 5.1: Get-PnpDevice 比 Get-WmiObject 快很多
    if (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue) {
        return @(Get-PnpDevice | Where-Object { $_.InstanceId -match $pattern })
    }
    return @(Get-WmiObject Win32_PnPEntity | Where-Object { $_.DeviceID -match $pattern })
}

function Get-ComPorts {
    if (Get-Command Get-PnpDevice -ErrorAction SilentlyContinue) {
        return @(Get-PnpDevice -Class Ports | Where-Object { $_.Status -eq 'OK' -and $_.FriendlyName -match 'COM\d+' })
    }
    return @(Get-WmiObject Win32_SerialPort)
}

Write-Host ""
Write-Host "================================================================"
Write-Host " 盯 USB：$pattern     超时 ${TimeoutSec}s     日志 $Log"
Write-Host " 现在去执行：  fastboot boot out\boot-umi-p1.img"
Write-Host "================================================================"
Write-Host ""
Say "watcher 启动"

$seen = $false
$port = $null
$sp = $null

while (((Get-Date) - $start).TotalSeconds -lt $TimeoutSec) {

    $devs = Get-GadgetDevices
    if ($devs.Count -gt 0 -and -not $seen) {
        $seen = $true
        Say "*** 检测到 USB gadget $Vid`:$Pid —— 内核已经跑到 initramfs/用户态了！ ***"
        foreach ($d in $devs) { Say ("    " + $d.FriendlyName) }
    }
    elseif ($devs.Count -eq 0 -and $seen) {
        $seen = $false
        Say "!!! gadget 消失 —— 设备重启/复位了（如果刚才黑屏，这就是复位点）"
    }

    if ($seen -and -not $sp) {
        $ports = Get-ComPorts
        if ($ports.Count -gt 0) {
            $port = ($ports[0].FriendlyName -replace '.*\((COM\d+)\).*', '$1')
            if ($port -match '^COM\d+$') {
                Say "打开串口 $port @ ${Baud}（Ctrl+C 退出）"
                try {
                    $sp = New-Object System.IO.Ports.SerialPort $port, $Baud, 'None', 8, 'One'
                    $sp.ReadTimeout = 1000
                    $sp.Open()
                } catch {
                    Say ("打开 $port 失败：" + $_.Exception.Message)
                    $sp = $null
                }
            }
        }
    }

    if ($sp -and $sp.IsOpen) {
        try {
            $data = $sp.ReadExisting()
            if ($data) {
                Write-Host -NoNewline $data
                Add-Content -Path $Log -Value $data -NoNewline -Encoding UTF8
            }
        } catch { }
    }

    Start-Sleep -Milliseconds 500
}

if ($sp -and $sp.IsOpen) { $sp.Close() }

Say ""
Say "超时结束。"
if (-not $seen) {
    Say "整个过程没看到 $pattern —— 说明内核从来没跑到 initramfs。"
    Say "  结合秒表：<5s 回 fastboot → ABL 层拒绝镜像；>8s → 内核早期挂了。"
}
