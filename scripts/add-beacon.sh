#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# add-beacon.sh — 把 umi-beacon 注入内核树并重编（极早期屏幕信标）
#
#   wsl -d umi -u root -- sh <repo>/scripts/add-beacon.sh
#
# 注入后：scripts/build.sh 编出来的 Image.gz 就带信标了。
# 撤销：scripts/remove-beacon.sh
set -e

TREE=${TREE:-/root/linux}
WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
SRC=$WS/tools/beacon/umi-beacon.c
DST=$TREE/drivers/video/umi-beacon.c
MK=$TREE/drivers/video/Makefile

[ -f "$SRC" ] || { echo "!! 找不到 $SRC"; exit 2; }

# 设备侧文本必须纯 ASCII：屏幕 console / panic 屏用的是 VGA 字体，没有中文字形
if LC_ALL=C grep -q '[^ -~	]' "$SRC"; then
	echo "!! $SRC 里有非 ASCII 字符（会在屏幕上显示成方块）："
	LC_ALL=C grep -n '[^ -~	]' "$SRC" | head -10 | sed 's/^/     /'
	exit 3
fi

cp -f "$SRC" "$DST"
if grep -q 'umi-beacon' "$MK"; then
	echo "== Makefile 里已经有 umi-beacon.o"
else
	printf '\nobj-y += umi-beacon.o\n' >> "$MK"
	echo "== 已把 obj-y += umi-beacon.o 追加到 $MK"
fi

echo "== 重编内核（信标版）"
sh "$WS/scripts/build.sh"

echo "== 把产物另存一份，别把正常镜像覆盖了"
cp -f "$WS/out/Image.gz" "$WS/out/Image-beacon.gz"
echo "   信标内核: $WS/out/Image-beacon.gz"
echo "   打包： python tools\\pack-umi.py --kernel out\\Image-beacon.gz --name beacon"
echo ""
echo "屏幕颜色对照："
echo "   黑        没进 postcore（或 ABL 把屏关了）"
echo "   蓝        postcore_initcall"
echo "   青        arch_initcall"
echo "   绿        subsys_initcall"
echo "   黄        fs_initcall"
echo "   黑底白字  device_initcall 之后（fbcon 起来了）"
