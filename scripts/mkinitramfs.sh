#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# mkinitramfs.sh — 打一个能用的 initramfs（静态 aarch64 busybox + init 脚本）
#
#   wsl -d umi -u root -- sh <repo>/scripts/mkinitramfs.sh
#   ... --no-usb-console            不带 USB 串口 + U盘（默认带）
#   ... --reboot 60                 到点自动重启（方便反复试；默认不重启）
#   ... --dump-partition sda15      把 log 也写进 /dev/sda15（用 TWRP 读回来，谨慎使用）
#   ... --test-panic 60             N 秒后自动画一次 panic 屏（二维码自测，默认 60 秒）
#   ... --no-panic-test             不做这个自测
#
# 产物：$WS/out/initramfs.cpio.gz
set -e

WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
BUILD=${BUILD:-/tmp/initramfs-build}
BB=${BB:-/tmp/armroot/bin/busybox.static}

USB=1
REBOOT=""
DUMPPART=""
PANICTEST="60"
while [ $# -gt 0 ]; do
	case "$1" in
	--usb-console) USB=1 ;;
	--no-usb-console) USB=0 ;;
	--reboot) shift; REBOOT="$1" ;;
	--dump-partition) shift; DUMPPART="$1" ;;
	--test-panic) shift; PANICTEST="$1" ;;
	--no-panic-test) PANICTEST="" ;;
	*) echo "未知参数 $1"; exit 1 ;;
	esac
	shift
done

if [ ! -x "$BB" ]; then
	echo "== 没有静态 busybox，先跑 fetch-busybox.sh"
	sh "$WS/scripts/fetch-busybox.sh"
fi
[ -x "$BB" ] || { echo "!! 拿不到静态 busybox"; exit 2; }

# ---- 设备侧文本必须是纯 ASCII ----
# 手机屏幕上的 console 和 panic 屏用的都是 VGA 8x16 字体，没有中文字形 ——
# 中文会变成一堆方块。所以 init 脚本里**打印出来的东西**（以及注释）都强制英文。
if LC_ALL=C grep -q '[^ -~	]' "$WS/initramfs/init"; then
	echo "!! initramfs/init 里有非 ASCII 字符（会在屏幕上显示成方块）："
	LC_ALL=C grep -n '[^ -~	]' "$WS/initramfs/init" | head -10 | sed 's/^/     /'
	echo "   请改成英文再打包。"
	exit 3
fi
echo "== init 脚本是纯 ASCII（屏幕上不会出方块）"

echo "== 组装 $BUILD"
rm -rf "$BUILD"
mkdir -p "$BUILD/bin" "$BUILD/sbin" "$BUILD/proc" "$BUILD/sys" "$BUILD/dev" \
         "$BUILD/tmp" "$BUILD/etc" "$BUILD/usr/bin" "$BUILD/usr/sbin"

cp "$BB" "$BUILD/bin/busybox"
chmod 755 "$BUILD/bin/busybox"
# 常用 applet 先建好链接（init 里也会 busybox --install，这里做双保险）
for a in sh ls cat echo mount umount sleep dmesg grep sed tr cut head tail \
         reboot poweroff sync mkdir ln mknod find cp mv rm chmod date printf \
         tee hexdump od which ps kill setsid dd; do
	ln -sf /bin/busybox "$BUILD/bin/$a"
done

cp "$WS/initramfs/init" "$BUILD/init"
chmod 755 "$BUILD/init"

[ "$USB" = 1 ] && echo "usb" > "$BUILD/usb-console"
[ -n "$REBOOT" ] && echo "$REBOOT" > "$BUILD/reboot-after"
[ -n "$DUMPPART" ] && echo "$DUMPPART" > "$BUILD/dump-partition"
[ -n "$PANICTEST" ] && echo "$PANICTEST" > "$BUILD/panic-test"

echo "== 打包 cpio.gz"
cd "$BUILD"
find . -print0 | cpio --null -o -H newc --quiet | gzip -9 > "$WS/out/initramfs.cpio.gz"

ls -l "$WS/out/initramfs.cpio.gz"

# ---- 体积上限 ----
# ABL 自己算 ramdisk 的落点，头里的 ramdisk_addr 是死的（实测被忽略）。
# 这台机器下游启动时 ramdisk 落在 0xafe9f000，而我们的 ramoops 保留区从
# 0xb0000000 开始 —— 中间只有 0x161000 = 1,449,984 字节。
# 如果 ABL 把我们这个 ramdisk 摆在同一个位置，超过这个数就会**覆盖 ramoops**
# （表现：pstore 永远是空的，甚至启动就崩）。
# 现在只有 663 KB（约 46%），但加了东西容易忘 —— 所以在这里卡一道。
SIZE=$(wc -c < "$WS/out/initramfs.cpio.gz")
LIMIT_WARN=$((1100 * 1024))
LIMIT_HARD=$((1350 * 1024))
if [ "$SIZE" -ge "$LIMIT_HARD" ]; then
	echo "!! initramfs 有 $SIZE 字节，超过安全上限 $LIMIT_HARD"
	echo "   0xafe9f000(下游 ramdisk 落点) 到 0xb0000000(ramoops 起点) 只有 1,449,984 字节。"
	echo "   要么把东西挪到 USB 里，要么把 ramoops 挪到别处（见 DIAGNOSIS.md 的 ramoops 一节）。"
	exit 4
elif [ "$SIZE" -ge "$LIMIT_WARN" ]; then
	echo "   · 注意：initramfs 已到 $SIZE 字节（安全上限 $LIMIT_HARD）"
else
	echo "== 体积 OK：$SIZE 字节（上限 $LIMIT_HARD，约 $((SIZE * 100 / LIMIT_HARD))%）"
fi

echo "== 内容预览"
zcat "$WS/out/initramfs.cpio.gz" | cpio -t --quiet 2>/dev/null | head -20
echo "== 完成"
