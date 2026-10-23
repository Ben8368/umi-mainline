#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# multiid-dtb.sh — 生成一个「多个 board-id 都认」的备用 DTB
#
# 背景：ABL 按 qcom,msm-id / qcom,board-id 挑 DTB。umi 下游用的是 board-id=43，
# 万一实机上 ABL 报不匹配（黑屏几秒回 fastboot），用这个脚本做一个
# qcom,board-id = <43 0>, <8 0>, <0 0> 的版本再试一次，用来区分
# 「格式问题」和「board-id 不匹配」。
#
#   wsl -d umi -u root -- sh <repo>/scripts/multiid-dtb.sh
#   python tools\pack-umi.py --dtb out\sm8250-xiaomi-umi-multiid.dtb --name p1m
set -e

WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
OUT=${OUT:-$WS/out}
SRC=$OUT/sm8250-xiaomi-umi.dtb
DST=$OUT/sm8250-xiaomi-umi-multiid.dtb
TMP=/tmp/umi-multiid.dts

[ -f "$SRC" ] || { echo "!! 先编译出 $SRC"; exit 2; }

dtc -I dtb -O dts -o "$TMP" "$SRC" 2>/dev/null
# 把根节点上的 board-id 展开成多个候选
sed -i 's/qcom,board-id = <0x2b 0x00>;/qcom,board-id = <0x2b 0x00>, <0x08 0x00>, <0x00 0x00>;/' "$TMP"
# msm-id 也把 kona v2.0 / v2.1 都列上（有些 ABL 会带 revision 一起比）
sed -i 's/qcom,msm-id = <0x164 0x20001>;/qcom,msm-id = <0x164 0x20001>, <0x164 0x20000>, <0x164 0x10000>;/' "$TMP"

if ! grep -q 'board-id = <0x2b 0x00>, <0x08 0x00>' "$TMP"; then
	echo "!! 没找到根节点的 board-id，dtc 反编译结果可能变了，检查 $TMP"
	exit 3
fi

dtc -I dts -O dtb -o "$DST" "$TMP" 2>/dev/null
ls -l "$DST"
echo "== 用 dtb.py 复核："
python3 - "$DST" <<'EOF' 2>/dev/null || true
import sys, subprocess
EOF
echo "   复核命令： python tools\\dtb.py ids out\\sm8250-xiaomi-umi-multiid.dtb"
echo "== 完成。打包时加 --dtb $DST"
