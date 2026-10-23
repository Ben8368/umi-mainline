#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# fetch-busybox.sh — 取一份 aarch64 静态 busybox（给 initramfs 用）
# x86_64 的 apk 可以跨架构下载包：--arch aarch64 + 显式 aarch64 仓库。
set -e
REL=$(cut -d. -f1,2 /etc/alpine-release)
REPO="https://dl-cdn.alpinelinux.org/alpine/v$REL/main"
echo "== Alpine $REL, 仓库 $REPO"
rm -rf /tmp/armroot
mkdir -p /tmp/armroot
apk add --root /tmp/armroot --initdb --arch aarch64 --allow-untrusted \
	--repository "$REPO" busybox-static 2>&1 | tail -4 || true
if [ -x /tmp/armroot/bin/busybox.static ]; then
	echo "== OK: /tmp/armroot/bin/busybox.static"
	ls -l /tmp/armroot/bin/
	exit 0
fi
# 退路：动态 busybox + musl 解释器
echo "== 静态包没拿到，退而取 musl + busybox"
apk add --root /tmp/armroot --initdb --arch aarch64 --allow-untrusted \
	--repository "$REPO" musl busybox 2>&1 | tail -4 || true
ls -l /tmp/armroot/bin /tmp/armroot/lib 2>/dev/null || true
