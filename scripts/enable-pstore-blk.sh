#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# enable-pstore-blk.sh — 启用「panic 时直接把 log 写进裸分区」
#
#   wsl -d umi -u root -- sh <repo>/scripts/enable-pstore-blk.sh 8:15
#
# 参数是「主设备号:次设备号」（十六进制也行，比如 8:15 或 8f）。
#   sda  = 8:0，sdaN = 8:N        （UFS 的 sd 设备主号就是 8）
#   例如 sda15 → 8:15
#
# ⚠️ 先确认那个分区真的是「日志区」再启用！判断依据见 LOG-EXTRACTION.md。
#    小米10 自己的下游 cmdline 里有：
#      block2mtd.block2mtd=/dev/block/sda15,2097152 mtdoops.mtddev=0
#    说明 **sda15 就是厂商用来放内核崩溃日志的地方**（2 MB）。
#
# 原理：pstore/blk 在内核里是「待机」的，只有 cmdline 给了 blkdev 才激活。
#       UFS 没有 panic_write，所以必须同时给 best_effort=1（普通可睡眠 I/O）。
set -e

WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
DEV=${1:-}

if [ -z "$DEV" ]; then
	echo "用法: $0 <major:minor>   例如 $0 8:15   （sda15）"
	exit 1
fi

CFG=$WS/config/umi.config

if grep -q 'pstore_blk.blkdev=' "$CFG"; then
	echo "== umi.config 里已经有 pstore_blk.blkdev，先把它删掉"
	sed -i 's/ pstore_blk\.blkdev=[^"]*//' "$CFG"
fi

# 在 CONFIG_CMDLINE 末尾加上参数
sed -i "s|\(CONFIG_CMDLINE=\"[^\"]*\)\"|\1 pstore_blk.blkdev=$DEV pstore_blk.best_effort=1 pstore_blk.kmsg_size=1024\"|" "$CFG"

echo "== 新的 cmdline："
grep '^CONFIG_CMDLINE=' "$CFG" | sed 's/^/   /'
echo ""
echo "== 重编内核 + 重打 initramfs"
sh "$WS/scripts/build.sh"
sh "$WS/scripts/mkinitramfs.sh"
echo ""
echo "== 完成。之后："
echo "   1) 跑一次会崩的镜像 → panic 时 log 会被写进 /dev/$DEV 那个分区"
echo "   2) 进 TWRP，adb shell："
echo "        dd if=/dev/block/sda15 of=/tmp/pstore.bin bs=4096 count=512"
echo "        exit"
echo "      adb pull /tmp/pstore.bin"
echo "   3) python tools\\parse-pstore.py pstore.bin -o out\\pstore.txt"
