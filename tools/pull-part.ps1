# SPDX-License-Identifier: CC0-1.0
# pull-part.ps1 - dump one partition through adb, READ ONLY, never writes one.
#
#   powershell -ExecutionPolicy Bypass -File tools\pull-part.ps1 -Action state
#   powershell -ExecutionPolicy Bypass -File tools\pull-part.ps1 -Part dtbo
#   powershell -ExecutionPolicy Bypass -File tools\pull-part.ps1 -Part dtbo -RebootFirst
#
# Flow:
#   1. adb reboot recovery                     (a reboot, nothing is written)
#   2. wait for the recovery adb endpoint
#   3. adb shell dd if=/dev/block/by-name/<part> of=/tmp/<part>.img  (/tmp is a ramdisk)
#   4. adb pull into dump\
#   5. remove the temporary file under /tmp
#   6. adb kill-server on the way out (the daemon inherits handles and would
#      otherwise keep the caller waiting for EOF)
#
# Set $env:ADB to an explicit adb.exe path if adb is not on %PATH%.
# Set $env:ANDROID_SERIAL to pick one device when several are attached.

param(
    [ValidateSet('state', 'recovery', 'pull')]
    [string]$Action = 'state',
    [string]$Part = 'dtbo',
    [string]$OutDir = 'dump',
    [int]$WaitSec = 150,
    [string]$Serial = ''
)

$ErrorActionPreference = 'Continue'

$ws = Split-Path -Parent $PSScriptRoot
Set-Location $ws

$adb = if ($env:ADB) { $env:ADB } else { 'adb' }
$sel = @()
$serialValue = if ($Serial) { $Serial } elseif ($env:ANDROID_SERIAL) { $env:ANDROID_SERIAL } else { '' }
if ($serialValue) { $sel = @('-s', $serialValue) }

New-Item -ItemType Directory -Force (Join-Path $ws $OutDir) | Out-Null
New-Item -ItemType Directory -Force (Join-Path $ws 'out') | Out-Null
$log = Join-Path $ws 'out\fb.log'

function Say([string]$m) {
    Write-Host $m
    try { Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m) -Encoding UTF8 } catch { }
}

# Every adb call gets a hard timeout: adb happily blocks forever when the
# device is not in the state we assumed.
function Run-TO {
    param([string[]]$Argv, [int]$TimeoutSec = 60)
    $so = [System.IO.Path]::GetTempFileName()
    $bat = $so + '.bat'
    $quoted = $Argv | ForEach-Object { if ($_ -match '[\s"]') { '"' + $_ + '"' } else { $_ } }
    $line = '@echo off' + "`r`n" + '"' + $adb + '" ' + ($quoted -join ' ') + ' > "' + $so + '" 2>&1' + "`r`n"
    [System.IO.File]::WriteAllText($bat, $line, (New-Object System.Text.ASCIIEncoding))
    $p = Start-Process -FilePath $bat -NoNewWindow -PassThru
    $done = $p.WaitForExit($TimeoutSec * 1000)
    if (-not $done) { try { $p.Kill() } catch { } }
    Start-Sleep -Milliseconds 150
    $out = ''
    try { $out = Get-Content -LiteralPath $so -Raw -ErrorAction Stop } catch { }
    Remove-Item -LiteralPath $so, $bat -Force -ErrorAction SilentlyContinue
    [pscustomobject]@{ Ok = ($done -and $p.ExitCode -eq 0); TimedOut = (-not $done); Out = "$out" }
}

function Get-DevState {
    $r = Run-TO ($sel + @('get-state')) 12
    if ($r.TimedOut) { return 'TIMEOUT' }
    $s = ($r.Out -replace '\s', '')
    if ($s -match 'device') { return 'DEVICE' }
    if ($s -match 'recovery') { return 'RECOVERY' }
    return 'OFFLINE'
}

switch ($Action) {
    'state' {
        Say "adb: $adb"
        Say 'adb devices:'
        Say ((Run-TO ($sel + @('devices')) 15).Out.Trim())
        Say "state: $(Get-DevState)"
    }
    'recovery' {
        Say 'rebooting to recovery (no partition is touched)'
        $r = Run-TO ($sel + @('reboot', 'recovery')) 25
        if (-not $r.Ok) { Say "reboot failed: $($r.Out)"; break }
        $deadline = (Get-Date).AddSeconds($WaitSec)
        $ok = $false
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 3
            $st = Get-DevState
            Say "  ... $st"
            if ($st -eq 'DEVICE' -or $st -eq 'RECOVERY') { $ok = $true; break }
        }
        if ($ok) { Say 'recovery adb is up' } else { Say 'recovery adb did not come up in time' }
    }
    'pull' {
        $st = Get-DevState
        if ($st -ne 'DEVICE' -and $st -ne 'RECOVERY') {
            Say "device not reachable over adb (state: $st); run -Action recovery first"
            break
        }
        $remote = "/tmp/$Part.img"
        Say "dumping /dev/block/by-name/$Part -> $remote"
        $r = Run-TO ($sel + @('shell', 'dd', "if=/dev/block/by-name/$Part", "of=$remote")) 300
        if (-not $r.Ok) { Say "dd failed: $($r.Out)"; break }
        $dst = Join-Path (Join-Path $ws $OutDir) "$Part.img"
        Say "pulling -> $dst"
        $r = Run-TO ($sel + @('pull', $remote, $dst)) 600
        if ($r.Ok) {
            $len = (Get-Item $dst).Length
            Say "saved $dst ($len bytes)"
        } else {
            Say "pull failed: $($r.Out)"
        }
        Run-TO ($sel + @('shell', 'rm', '-f', $remote)) 20 | Out-Null
    }
}

Run-TO @('kill-server') 15 | Out-Null
