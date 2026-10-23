# SPDX-License-Identifier: CC0-1.0
<#
    setup-wsl.ps1 — 重建一个可用的 WSL2 编译环境（不破坏你现有的 Alpine 注册）

    背景：原来的环境在 D:\WSL\alpine\ext4.vhdx，
          该文件已丢失 → `wsl -l -v` 里 Alpine 处于 Stopped，
          任何 `wsl -d Alpine` 都会报 ERROR_PATH_NOT_FOUND（WSL2 挂载磁盘失败）。
          所以 /tmp/mainline-kernel 里的源码树也一起没了。

    做法：新建一个叫 umi 的发行版（Alpine minirootfs + import），
          装好 clang/lld + 内核构建依赖，用 LLVM=1 交叉编译 arm64。

    用法：
        pwsh -File scripts\setup-wsl.ps1
        pwsh -File scripts\setup-wsl.ps1 -Distro umi -InstallDir D:\WSL\umi
#>
param(
    [string]$Distro     = "umi",
    [string]$InstallDir = "D:\WSL\umi",
    [string]$CacheDir   = "D:\WSL\cache",
    [string]$AlpineBranch = "latest-stable",   # 或 v3.20 / edge
    [switch]$Force
)

$ErrorActionPreference = "Stop"
function Say($m) { Write-Host "[*] $m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "[+] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[!] $m" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 0. 前置检查
Say "WSL 版本"
wsl --version | Out-String | Write-Host

$existing = (wsl -l -q) -split "`r?`n" | Where-Object { $_.Trim() -ne "" }
$rootfsVhdx = Join-Path $InstallDir "ext4.vhdx"
if ($existing -contains $Distro -and -not $Force) {
    if (Test-Path $rootfsVhdx) {
        Ok "发行版 $Distro 已存在且磁盘完好，跳过 import（要重建请加 -Force）"
        $skipImport = $true
    } else {
        Warn "$Distro 已注册但 $rootfsVhdx 不存在 → 注销后重建"
        wsl --unregister $Distro | Out-Null
        $skipImport = $false
    }
} else {
    if ($existing -contains $Distro -and $Force) {
        Warn "-Force：注销已存在的 $Distro"
        wsl --unregister $Distro | Out-Null
    }
    $skipImport = $false
}

# ---------------------------------------------------------------- 1. 下载 rootfs
if (-not $skipImport) {
    New-Item -ItemType Directory -Force -Path $CacheDir, $InstallDir | Out-Null
    $base = "https://dl-cdn.alpinelinux.org/alpine/$AlpineBranch/releases/x86_64/"
    Say "读取 $base"
    $idx = (Invoke-WebRequest -Uri $base -UseBasicParsing -TimeoutSec 60).Content
    $name = ([regex]::Matches($idx, 'alpine-minirootfs-[\d\.]+-x86_64\.tar\.gz') |
             ForEach-Object { $_.Value } | Sort-Object -Unique | Select-Object -Last 1)
    if (-not $name) { throw "在 $base 找不到 alpine-minirootfs-*-x86_64.tar.gz" }

    $tar = Join-Path $CacheDir $name
    if (-not (Test-Path $tar)) {
        Say "下载 $name"
        Invoke-WebRequest -Uri ($base + $name) -OutFile $tar -UseBasicParsing -TimeoutSec 600
    } else { Ok "使用缓存 $tar" }
    Ok ("rootfs {0:N1} MB" -f ((Get-Item $tar).Length / 1MB))

    Say "wsl --import $Distro $InstallDir"
    wsl --import $Distro $InstallDir $tar --version 2 | Out-String | Write-Host
    if (-not (Test-Path $rootfsVhdx)) { throw "import 失败：$rootfsVhdx 不存在" }
    Ok "import 完成"
}

# ---------------------------------------------------------------- 2. 安装依赖
Say "更新 apk 索引"
wsl -d $Distro -u root -- sh -c "apk update" | Out-String | Write-Host

$pkgs = @(
    "bash","bc","bison","flex","gcc","musl-dev","make","openssl-dev","perl",
    "python3","dtc","cpio","coreutils","findutils","diffutils","ncurses-dev",
    "clang","lld","llvm","binutils","tar","xz","zip","gzip","git","rsync","file","elfutils-dev"
)
Say "安装构建依赖 ($($pkgs -join ' '))"
wsl -d $Distro -u root -- sh -c "apk add --no-cache $($pkgs -join ' ')" | Out-String | Write-Host

# 可选：GNU 交叉工具链（Alpine 有的分支里叫 gcc-aarch64-none-elf / gcc-cross-aarch64）
Say "探测 GNU aarch64 交叉工具链包名（有就用，没有就靠 clang）"
$probe = wsl -d $Distro -u root -- sh -c "apk search -q 'aarch64*' 2>/dev/null | grep -Ei 'gcc|cross' | head -20" 
$probe | Out-String | Write-Host
foreach ($cand in @("gcc-aarch64-none-elf","aarch64-none-elf-gcc","gcc-cross-aarch64","aarch64-linux-gnu-gcc")) {
    $r = wsl -d $Distro -u root -- sh -c "apk add --no-cache $cand >/dev/null 2>&1 && echo OK-$cand" 
    if ($r -match "OK-") { Ok "GNU 交叉编译器可用：$cand" ; break }
}

# ---------------------------------------------------------------- 3. 验证
Say "验证工具链"
wsl -d $Distro -u root -- sh -c @'
echo "--- clang ---"; clang --version | head -2
echo "--- ld.lld ---"; ld.lld --version
echo "--- dtc ---"; dtc --version
echo "--- make/bc/python3 ---"; make --version | head -1; bc --version | head -1; python3 -V
echo "--- gcc (host) ---"; gcc --version | head -1
echo "--- aarch64 gcc (optional) ---"; (aarch64-none-elf-gcc --version 2>/dev/null | head -1) || echo none
echo "--- cpu/mem ---"; nproc; free -g | head -2
'@ | Out-String | Write-Host

Ok "完成。进入环境： wsl -d $Distro -u root"
Write-Host @"

下一步（在 WSL 里）：
    cp -a /mnt/d/project/linux-src ~/linux      # 复制到 ext4，编译快很多
    cd ~/linux
    scripts/build.sh                            # 见工作区 scripts/build.sh

"@ -ForegroundColor Yellow
