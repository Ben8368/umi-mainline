#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# remove-beacon.sh — 撤销 umi-beacon 注入（恢复成干净内核）
#
#   wsl -d umi -u root -- sh <repo>/scripts/remove-beacon.sh
set -e

TREE=${TREE:-/root/linux}
WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
DST=$TREE/drivers/video/umi-beacon.c
MK=$TREE/drivers/video/Makefile

rm -f "$DST"
if grep -q 'umi-beacon' "$MK"; then
	# 删掉我们追加的那两行（空行 + obj-y）
	sed -i '/obj-y += umi-beacon\.o/d' "$MK"
	# 去掉可能留下的尾部空行
	sed -i -e :a -e '/^\n*$/{$d;N;};/\n$/ba' "$MK" 2>/dev/null || true
	echo "== 已从 $MK 移除 umi-beacon.o"
fi

echo "== 重编内核（干净版）"
sh "$WS/scripts/build.sh"
echo "== 完成"
