# SPDX-License-Identifier: CC0-1.0
# serial-cmd.ps1 - talk to the umi initramfs shell over the USB CDC-ACM port.
#
#   powershell -ExecutionPolicy Bypass -File tools\serial-cmd.ps1 -Cmd 'uname -a'
#   powershell -ExecutionPolicy Bypass -File tools\serial-cmd.ps1 -Cmd 'ls /sys/class/drm' -Wait 2000
#
# Notes (ASCII only on purpose: Windows PowerShell 5.1 reads .ps1 without a BOM
# as the system ANSI codepage, and non-ASCII comments get mangled into the code):
#   * default COM3 / 115200 8N1, override with -Port / -Baud
#   * every command gets a trailing CR (the tty has ICRNL, so CR == newline)
#   * if another program holds the port we fail immediately instead of hanging
param(
    [string[]]$Cmd = @(),
    [string]$CmdFile = '',
    [string]$Port = 'COM3',
    [int]$Baud = 115200,
    [int]$Wait = 1500,
    [int]$FirstWait = 800
)

$ErrorActionPreference = 'Continue'

# Reading the commands from a file avoids every layer of quoting hell when this
# script is launched from another shell. One command per line, blank/leading-# ok.
if ($CmdFile -ne '') {
    $Cmd = @(Get-Content -LiteralPath $CmdFile |
             ForEach-Object { $_.Trim() } |
             Where-Object { $_ -ne '' -and -not $_.StartsWith('#') })
}

$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, 'None', 8, 'One'
$sp.ReadTimeout = 200
$sp.WriteTimeout = 2000

try {
    $sp.Open()
} catch {
    Write-Output "OPEN-FAILED: $($_.Exception.Message)"
    exit 2
}

$sp.DtrEnable = $true
$sp.RtsEnable = $true

function Read-Window([int]$ms) {
    $sb = New-Object System.Text.StringBuilder
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt $ms) {
        try {
            if ($sp.BytesToRead -gt 0) { [void]$sb.Append($sp.ReadExisting()) }
        } catch { break }
        Start-Sleep -Milliseconds 40
    }
    return $sb.ToString()
}

try { $sp.Write("`r") } catch {}
$out = Read-Window $FirstWait

foreach ($c in $Cmd) {
    try {
        $sp.Write($c + "`r")
    } catch {
        $out += "`r`n[WRITE-FAILED: $($_.Exception.Message)]`r`n"
        break
    }
    $out += Read-Window $Wait
}

try { $sp.Close() } catch {}
Write-Output $out
