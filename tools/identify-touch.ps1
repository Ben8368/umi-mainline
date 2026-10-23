# SPDX-License-Identifier: CC0-1.0
# identify-touch.ps1 - reboot the phone out of the RAM-booted mainline image
# back into Android and collect every hint about the touch controller.
#
#   powershell -ExecutionPolicy Bypass -File tools\identify-touch.ps1
#
# Writes out\touch-identify.txt.  ASCII only (PS 5.1 ansi codepage).
param(
    [string]$Out  = '',
    [int]$Timeout = 240
)

$ErrorActionPreference = 'Continue'
$adb = if ($env:ADB) { $env:ADB } else { 'adb' }
$root = Split-Path -Parent $PSScriptRoot
if (-not $Out) { $Out = Join-Path $root 'out\touch-identify.txt' }
$log  = New-Object System.Text.StringBuilder

function Add-Line([string]$s) { [void]$log.AppendLine($s) }
function Run([string]$cmd) {
    $r = & $adb shell $cmd 2>&1 | Out-String
    return $r.TrimEnd()
}

Add-Line "=== identify-touch $(Get-Date -Format s) ==="

# --- 1. leave the mainline image ------------------------------------------------
$ser = & powershell -ExecutionPolicy Bypass -File "$root\tools\serial-cmd.ps1" `
          -Cmd 'reboot -f' -Wait 600 2>&1 | Out-String
Add-Line "serial reboot sent (first 200 chars): $($ser.Substring(0, [Math]::Min(200, $ser.Length)))"

# --- 2. wait for Android --------------------------------------------------------
& $adb kill-server 2>&1 | Out-Null
Start-Sleep -Seconds 3
$ok = $false
$waited = 0
while ($waited -lt $Timeout) {
    Start-Sleep -Seconds 4
    $waited += 4
    $st = (& $adb get-state 2>$null | Out-String).Trim()
    if ($st -eq 'device') { $ok = $true; break }
}
Add-Line "adb state: $st after ${waited}s"

if ($ok) {
    & $adb wait-for-device 2>&1 | Out-Null
    # boot may still be finishing; give the input stack a moment
    Start-Sleep -Seconds 8

    Add-Line ''
    Add-Line '=== getprop (touch-ish) ==='
    Add-Line (Run "getprop | grep -i -E 'touch|tp_|goodix|focal|synaptics|novatek|himax'")

    Add-Line ''
    Add-Line '=== /proc/bus/input/devices ==='
    Add-Line (Run 'cat /proc/bus/input/devices')

    Add-Line ''
    Add-Line '=== /sys/class/input/*/name ==='
    Add-Line (Run 'for f in /sys/class/input/input*/name; do echo "$f = $(cat $f)"; done')

    Add-Line ''
    Add-Line '=== i2c devices ==='
    Add-Line (Run 'ls -l /sys/bus/i2c/devices/ 2>/dev/null')
    Add-Line (Run 'for f in /sys/bus/i2c/devices/*/name; do echo "$f = $(cat $f 2>/dev/null)"; done')

    Add-Line ''
    Add-Line '=== getevent -pl ==='
    Add-Line (Run 'getevent -pl 2>&1')

    Add-Line ''
    Add-Line '=== video/drm connectors ==='
    Add-Line (Run 'ls /sys/class/drm/ 2>/dev/null')
    Add-Line (Run 'for f in /sys/class/drm/*/status; do echo "$f = $(cat $f)"; done')

    Add-Line ''
    Add-Line '=== touch firmware files in vendor ==='
    Add-Line (Run 'ls -l /vendor/firmware/ 2>/dev/null | grep -i -E "goodix|gt9|fts"')
    Add-Line (Run 'ls -l /vendor/lib/firmware/ 2>/dev/null | grep -i -E "goodix|gt9|fts"')
    Add-Line (Run 'ls -l /mnt/vendor/persist/ 2>/dev/null | grep -i -E "goodix|gt9|fts|tp"')

    Add-Line ''
    Add-Line '=== ps (touch daemons) ==='
    Add-Line (Run 'ps -A 2>/dev/null | grep -i -E "touch|goodix|fts|tp_"')
}

Set-Content -LiteralPath $Out -Value $log.ToString() -Encoding UTF8
Write-Output "written: $Out (adb=$ok)"
