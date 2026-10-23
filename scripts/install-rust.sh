#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# install-rust.sh — 装一套能给内核用的 Rust 工具链（为了 DRM_PANIC 的二维码 panic 屏）
#
#   wsl -d umi -u root -- sh <repo>/scripts/install-rust.sh
#
# 为什么不用 Alpine 自带的 rust 1.96：
#   内核 6.12 的 Rust 代码用的是一批 #[feature(...)] 不稳定特性，
#   版本太新反而可能编不过。这里用和 6.12 同期的 1.82.0。
#   内核要求：rustc >= 1.78.0，bindgen >= 0.65.1（scripts/min-tool-version.sh）
#
# 需要三样东西：
#   rustc（指定版本）+ core/alloc 的源码（rust-src 组件，内核要拿它编 core）
#   bindgen（生成 C 绑定）
set -e

RUST_VER=${RUST_VER:-1.82.0}
echo "== 目标工具链版本: $RUST_VER"

# ---- bindgen ----
if command -v bindgen >/dev/null 2>&1; then
	echo "== bindgen 已有: $(bindgen --version)"
else
	echo "== 安装 rust-bindgen"
	apk add --no-cache rust-bindgen >/dev/null 2>&1 || apk add rust-bindgen
	echo "== bindgen: $(bindgen --version 2>/dev/null || echo '装失败')"
fi

# ---- rustup + 指定版本 ----
if [ -x "$HOME/.cargo/bin/rustc" ]; then
	echo "== rustup 已存在: $($HOME/.cargo/bin/rustc --version)"
else
	echo "== 安装 rustup（minimal profile）"
	if command -v curl >/dev/null 2>&1; then
		curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup-init.sh
	else
		wget -q https://sh.rustup.rs -O /tmp/rustup-init.sh
	fi
	sh /tmp/rustup-init.sh -y --profile minimal --default-toolchain none --no-modify-path
fi

export PATH="$HOME/.cargo/bin:$PATH"
export RUSTUP_HOME=${RUSTUP_HOME:-$HOME/.rustup}
export CARGO_HOME=${CARGO_HOME:-$HOME/.cargo}

echo "== 安装 $RUST_VER + rust-src 组件"
rustup toolchain install "$RUST_VER" --profile minimal --component rust-src
rustup default "$RUST_VER" >/dev/null

echo "== 版本核对"
rustc --version
bindgen --version

SYSROOT=$(rustc --print sysroot)
LIB="$SYSROOT/lib/rustlib/src/rust/library"
echo "== rust-src: $LIB"
if [ -d "$LIB/core" ]; then
	echo "   OK  core 源码在"
else
	echo "   !! 没找到 core 源码，内核编 Rust 会报 RUST_LIB_SRC 问题"
fi

echo ""
echo "== 以后编译内核前，先让环境里带上 rust："
echo "     export PATH=\$HOME/.cargo/bin:\$PATH"
echo "     export RUST_LIB_SRC=$LIB        # 如果内核没自动找到才需要"
echo ""
echo "== 然后跑： scripts/enable-panic-qr.sh"
