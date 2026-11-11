#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# rust-check.sh — 查一下内核为什么没认出 Rust 工具链
#
#   wsl -d umi -u root -- sh <repo>/scripts/rust-check.sh
set -u

export PATH="$HOME/.cargo/bin:$PATH"
export RUSTUP_HOME=${RUSTUP_HOME:-$HOME/.rustup}
export CARGO_HOME=${CARGO_HOME:-$HOME/.cargo}
TREE=${TREE:-/root/linux}

echo "== 工具链"
echo "   rustc   : $(command -v rustc || echo 没有)  $(rustc --version 2>/dev/null)"
echo "   bindgen : $(command -v bindgen || echo 没有)  $(bindgen --version 2>/dev/null)"
echo "   sysroot : $(rustc --print sysroot 2>/dev/null)"

SYSROOT=$(rustc --print sysroot 2>/dev/null)
LIB="$SYSROOT/lib/rustlib/src/rust/library"
if [ -d "$LIB/core" ]; then
	echo "   rust-src: OK ($LIB)"
else
	echo "   rust-src: !! 缺 core 源码"
fi

echo ""
echo "== 内核里的可用性检查（scripts/rust_is_available.sh）"
cd "$TREE" || exit 2
if [ -n "${RUST_LIB_SRC:-}" ]; then
	echo "   RUST_LIB_SRC=$RUST_LIB_SRC"
else
	export RUST_LIB_SRC="$LIB"
	echo "   显式设置 RUST_LIB_SRC=$RUST_LIB_SRC"
fi

sh scripts/rust_is_available.sh
rc=$?
echo "   退出码 = $rc （0 = 可用）"

echo ""
echo "== make rustavailable"
make ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- O=out rustavailable 2>&1 | tail -20

echo ""
echo "== 当前 .config 里的相关符号"
grep -E 'CONFIG_(RUST|HAVE_RUST|RUST_IS_AVAILABLE|DRM_PANIC_SCREEN_QR_CODE)' out/.config 2>/dev/null || echo "   （一个都没有）"
