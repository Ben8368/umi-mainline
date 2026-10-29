#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# install-modules.sh — 把编好的内核模块塞进 rootfs 镜像
#
#   wsl -d umi -u root -- sh <repo>/scripts/install-modules.sh [镜像路径]
#
# 默认镜像 /root/arch/umi-rootfs.img。装完会在镜像里得到
#   /usr/lib/modules/<kver>/   （kver 形如 6.12.94-umi-dirty）
# 并且 modules.dep / modules.alias 等索引都由 kbuild 自己生成。
#
# 为什么要专门一个脚本：本内核把 rtc-pm8xxx / overlay / veth / fuse /
# pinctrl-lpass-lpi 都编成了 =m，没有这些 .ko 的话 Arch 里
# 没有 RTC（时间回到 1970，pacman 签名全挂）、没有 overlayfs。
set -e

WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
# shellcheck source=../config/kernel.env
. "$WS/config/kernel.env"
TREE=${TREE:-/root/linux-$UMI_KERNEL_VERSION}
OUT=${OUT:-$TREE/out}
IMG=${1:-/root/arch/umi-rootfs.img}
MNT=/mnt/umirootfs
TC="ARCH=arm64 CROSS_COMPILE=aarch64-none-elf-"

[ -f "$IMG" ] || { echo "!! 找不到镜像 $IMG"; exit 1; }
[ -f "$OUT/.config" ] || { echo "!! 没有 $OUT/.config，先 build.sh"; exit 1; }

KVER=$(make -s -C "$TREE" $TC O="$OUT" kernelrelease 2>/dev/null | tail -1)
[ -n "$KVER" ] || { echo "!! 拿不到 kernelrelease"; exit 1; }
echo "== kernel release: $KVER"

NKO=$(find "$OUT" -name '*.ko' | wc -l)
echo "== 编好的模块数: $NKO"
[ "$NKO" -gt 0 ] || { echo "!! 一个 .ko 都没有，先 make modules"; exit 2; }

mkdir -p "$MNT"
if mountpoint -q "$MNT"; then
	echo "== $MNT 已经挂着，直接用"
	MOUNTED_BY_US=0
else
	mount -o loop "$IMG" "$MNT"
	MOUNTED_BY_US=1
fi
trap '[ "$MOUNTED_BY_US" = 1 ] && umount "$MNT" 2>/dev/null; true' EXIT INT TERM

# 老版本先清掉，避免装了两份不同 kver 的模块
rm -rf "$MNT/usr/lib/modules/"*

# ARCH/INSTALL_MOD_PATH 决定落点：$MNT/usr/lib/modules/$KVER
# INSTALL_MOD_STRIP=1 会剥掉调试符号，体积能小一大截
make -C "$TREE" $TC O="$OUT" \
	INSTALL_MOD_PATH="$MNT" \
	INSTALL_MOD_STRIP=1 \
	modules_install 2>&1 | tail -5

echo "== 镜像里的模块："
ls "$MNT/usr/lib/modules/"
du -sh "$MNT/usr/lib/modules/"*

# build/ 和 source/ 是 kbuild 建的两个指向源码树的符号链接，
# 在手机上它们指向不存在的路径，删掉，免得某些工具报警。
rm -f "$MNT/usr/lib/modules/$KVER/build" "$MNT/usr/lib/modules/$KVER/source"

sync
if [ "$MOUNTED_BY_US" = 1 ]; then
	umount "$MNT"
	echo "== 卸载完成"
fi
trap - EXIT INT TERM

ls -lh "$IMG"
echo "== 完成。模块目录: /usr/lib/modules/$KVER"
