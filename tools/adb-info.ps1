# SPDX-License-Identifier: CC0-1.0
# adb-info.ps1 - second, targeted identification round against a booted MIUI.
#   powershell -ExecutionPolicy Bypass -File tools\adb-info.ps1
# ASCII only.
param([string]$Out = '')

$ErrorActionPreference = 'Continue'
$adb = if ($env:ADB) { $env:ADB } else { 'adb' }
if (-not $Out) { $Out = Join-Path (Split-Path -Parent $PSScriptRoot) 'out\touch-identify2.txt' }
$log = New-Object System.Text.StringBuilder
function Add-Line([string]$s) { [void]$log.AppendLine($s) }
function Run([string]$c) {
    Add-Line "--- $c"
    $r = & $adb shell $c 2>&1 | Out-String
    Add-Line $r.TrimEnd()
    Add-Line ''
}

Add-Line "=== adb-info $(Get-Date -Format s) ==="

Run 'dumpsys input'
Run 'ls -l /vendor/firmware/'
Run 'ls -l /vendor/lib/firmware/'
Run 'ls -l /proc/device-tree/soc/i2c@a94000/'
Run 'cat /proc/device-tree/soc/i2c@a94000/fts@49/compatible'
Run 'cat /proc/device-tree/soc/i2c@a94000/fts@49/reg'
Run 'cat /proc/device-tree/soc/i2c@a94000/qcom,i2c-touch-active'
Run 'getprop | grep -i -e fts -e touch'
Run 'cat /sys/class/input/event5/device/name'
Run 'ls -l /sys/class/input/event5/device/'
Run 'cat /proc/touchpanel/panel_id'
Run 'ls /proc/touchpanel/'

Set-Content -LiteralPath $Out -Value $log.ToString() -Encoding UTF8
Write-Output "written $Out"
