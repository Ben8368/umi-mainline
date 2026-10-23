#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# prepare-tree.sh — 在 WSL(ext4) 里准备一份「干净」的 linux 树
#
# 为什么不能直接在 D:\ 上编译：
#   D:\project\linux-src 所在目录是大小写不敏感的（Case sensitive attribute disabled），
#   而内核树里存在只差大小写的文件对，例如
#       net/netfilter/xt_connmark.c   (匹配模块)
#       net/netfilter/xt_CONNMARK.c   (target 模块)
#   Windows 检出时后者被吞掉 → 编译 netfilter 会直接报 "No rule to make target xt_CONNMARK.o"。
#   所以必须在 ext4（大小写敏感）上重新检出。
#
# 本脚本用本地 git 仓库 clone 一份到 /root/linux（不需要联网，对象直接走本地 .git）。
set -e

SRC=${SRC:-/mnt/d/project/linux-src}
DST=${DST:-/root/linux}
WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}

if [ -d "$DST/.git" ]; then
	echo "== $DST 已存在，跳过 clone（要重建：rm -rf $DST 后重跑）"
else
	echo "== 从 $SRC clone 到 $DST（ext4，大小写敏感）"
	rm -rf "$DST"
	git clone --no-hardlinks --quiet "$SRC" "$DST"
fi

cd "$DST"
echo "== HEAD: $(git log --oneline -1 --no-decorate)"
echo "== 校验大小写冲突文件是否都在:"
for f in net/netfilter/xt_connmark.c net/netfilter/xt_CONNMARK.c \
	 include/uapi/linux/netfilter/xt_connmark.h \
	 include/uapi/linux/netfilter/xt_CONNMARK.h; do
	if [ -f "$f" ]; then echo "   OK   $f"; else echo "   MISS $f"; fi
done

echo "== 同步 umi 的 DTS"
for f in sm8250-xiaomi-umi-common.dtsi sm8250-xiaomi-umi.dts sm8250-xiaomi-umi-plus.dts; do
	cp -f "$WS/dts/$f" "arch/arm64/boot/dts/qcom/$f"
done
MK=arch/arm64/boot/dts/qcom/Makefile
if ! grep -q 'sm8250-xiaomi-umi\.dtb' "$MK"; then
	printf 'dtb-$(CONFIG_ARCH_QCOM)\t+= sm8250-xiaomi-umi.dtb\ndtb-$(CONFIG_ARCH_QCOM)\t+= sm8250-xiaomi-umi-plus.dtb\n' >> "$MK"
	echo "   Makefile 已追加 umi 条目"
else
	echo "   Makefile 已有 umi 条目"
fi

echo "== 完成。树: $DST"
