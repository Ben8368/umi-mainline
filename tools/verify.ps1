# SPDX-License-Identifier: CC0-1.0
# verify.ps1 — 上机前的静态自检（一条命令跑完所有「编译看着成功、上机必挂」的检查）
#
#   powershell -ExecutionPolicy Bypass -File tools\verify.ps1
#
# 检查项：
#   1. out/config-effective —— 配置片段是否真的生效（写法陷阱 / 必须项 / 必须不要项）
#   2. out/Image.gz        —— ABL 会不会把它当 64 位内核（gzip + ARM\x64）+ arm64 Image 头
#   3. out/boot-umi-*.img  —— 头部字段、dtb_size、FDT 魔数
#   4. out/initramfs.cpio.gz —— 体积（会不会盖掉 ramoops）
#
# 退出码：0 = 全通过；1 = 有问题（每条都会告诉你为什么）

$ErrorActionPreference = "Continue"
$ws = Split-Path -Parent $PSScriptRoot
Set-Location $ws

$fail = 0
function Section($t) { Write-Host ""; Write-Host "==================== $t ====================" -ForegroundColor Cyan }
function Warn($t)    { Write-Host "  [!!] $t" -ForegroundColor Red; $script:fail = 1 }
function Ok($t)      { Write-Host "  [OK] $t" -ForegroundColor Green }
function Note($t)    { Write-Host "  [..] $t" -ForegroundColor DarkGray }

function Run-Py($script, $args) {
    $out = & python $script @args 2>&1
    $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Host $_ }
    return $code
}

# ---------------------------------------------------------------- 1 配置
Section "1/4 配置审计 (tools/config-audit.py)"
if (-not (Test-Path "out\config-effective")) {
    Warn "缺 out/config-effective（先跑 scripts/build.sh）"
} else {
    $c = Run-Py "tools\config-audit.py" @("out\config-effective")
    if ($c -ne 0) { Warn "配置有问题（见上面 [1]~[6] 各节）" } else { Ok "配置全部通过" }
}

# ---------------------------------------------------------------- 2 内核
Section "2/4 内核负载审计 (tools/img-audit.py)"
if (-not (Test-Path "out\Image.gz")) {
    Warn "缺 out/Image.gz"
} else {
    $c = Run-Py "tools\img-audit.py" @("out\Image.gz")
    if ($c -ne 0) { Warn "内核负载有问题（最要紧的是 ABL 的 32/64 位判别）" } else { Ok "内核负载可以引导" }
}

# ---------------------------------------------------------------- 3 boot.img
Section "3/4 boot.img 头"
$imgs = @(Get-ChildItem "out\boot-umi-*.img" -ErrorAction SilentlyContinue)
if ($imgs.Count -eq 0) {
    Warn "out/ 里没有 boot-umi-*.img（先跑 python tools\pack-umi.py）"
} else {
    $py = @"
import sys
sys.path.insert(0, r'$ws\tools')
from bootimg import BootImg
bad = 0
for p in sys.argv[1:]:
    b = BootImg.load(p)
    import os
    name = os.path.basename(p)
    v2 = b.header_version >= 2
    dtbok = (b.dtb[:4] == b'\xd0\x0d\xfe\xed') if b.dtb_size else None
    print('  %-34s hdr=%d kernel=%d ramdisk=%d dtb=%d' % (name, b.header_version, b.kernel_size, b.ramdisk_size, b.dtb_size))
    if v2 and b.dtb_size == 0:
        print('     [!!] header v2 但 dtb_size=0 -> ABL 会 EFI_NOT_FOUND 掉回 fastboot'); bad = 1
    if v2 and dtbok is False:
        print('     [!!] dtb 段不是 FDT'); bad = 1
    is_gz = b.kernel[:2] == b'\x1f\x8b'
    is_raw = b.kernel[56:60] == b'ARM\x64'
    if not is_gz and not is_raw:
        print('     [!!] kernel 既不是 gzip 也不带 offset 56 的 ARM\\x64 -> ABL 会走 32 位路径'); bad = 1
    if is_raw:
        print('     [..] 裸 arm64 Image（magic 在 offset 56，不是 offset 0）')
    if b.ramdisk_size == 0:
        print('     [..] 没有 ramdisk（只有 fbtest 这类裸 payload 才应该这样）')
sys.exit(bad)
"@
    $tmp = Join-Path $env:TEMP "umi-chk-bootimg.py"
    [System.IO.File]::WriteAllText($tmp, $py, (New-Object System.Text.UTF8Encoding($false)))
    $paths = $imgs | ForEach-Object { $_.FullName }
    & python $tmp @paths
    if ($LASTEXITCODE -ne 0) { Warn "有 boot.img 不合格" } else { Ok "boot.img 全部合格" }
}

# ---------------------------------------------------------------- 4 initramfs
Section "4/4 initramfs 体积"
if (-not (Test-Path "out\initramfs.cpio.gz")) {
    Warn "缺 out/initramfs.cpio.gz"
} else {
    $sz = (Get-Item "out\initramfs.cpio.gz").Length
    $limit = 1350 * 1024
    Note ("{0} 字节（上限 {1}，占 {2}%）" -f $sz, $limit, [int]($sz * 100 / $limit))
    if ($sz -ge $limit) {
        Warn "超过上限：ABL 可能把它摆到 0xafe9f000 一路往上，会盖掉 0xb0000000 的 ramoops"
    } else {
        Ok "体积安全"
    }
}

# ---------------------------------------------------------------- 汇总
Section "结论"
if ($fail -ne 0) {
    Write-Host "  有检查没通过，先修再上机（详见 RISK-AUDIT-2.md）" -ForegroundColor Red
    exit 1
}
Write-Host "  全部通过。上机顺序见 RISK-AUDIT-2.md §4（第 0 步是先用原厂 boot.img 做对照）" -ForegroundColor Green
exit 0
