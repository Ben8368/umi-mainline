#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# config-only.sh — 只做「defconfig + 合并片段 + olddefconfig + 校验」，不编译
#
# 用途：改完 config/umi.config 之后，几十秒内确认每条都真的生效了，
#       不用等半小时的编译才知道某个 `# CONFIG_X is not set` 又写错了。
#
#   wsl -d umi -u root -e sh <repo>/scripts/config-only.sh
set -e
WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
# shellcheck source=../config/kernel.env
. "$WS/config/kernel.env"
TREE=${TREE:-/root/linux-$UMI_KERNEL_VERSION}
OUT=${OUT:-$TREE/out-cfg}
FRAGMENT=${FRAGMENT:-$WS/config/umi.config}

# Rust 工具链：CONFIG_RUST 依赖 Kconfig 里的 RUST_IS_AVAILABLE，而它是靠
# 「Kconfig 阶段能不能找到 rustc/bindgen」算出来的。这里不摆好环境，
# RUST 和二维码相关符号会整片消失（看起来像「被静默丢弃」，其实只是没工具链）。
if [ -x "$HOME/.cargo/bin/rustc" ]; then
	PATH="$HOME/.cargo/bin:$PATH"
	export PATH
	export RUSTUP_HOME=${RUSTUP_HOME:-$HOME/.rustup}
	export CARGO_HOME=${CARGO_HOME:-$HOME/.cargo}
	if [ -z "${RUST_LIB_SRC:-}" ]; then
		SYSROOT=$(rustc --print sysroot 2>/dev/null || true)
		if [ -n "$SYSROOT" ] && [ -d "$SYSROOT/lib/rustlib/src/rust/library/core" ]; then
			export RUST_LIB_SRC="$SYSROOT/lib/rustlib/src/rust/library"
		fi
	fi
fi
if [ -z "${LIBCLANG_PATH:-}" ] && [ -e /usr/lib/llvm22/lib/libclang.so ]; then
	export LIBCLANG_PATH=/usr/lib/llvm22/lib
fi

mkdir -p "$OUT"
echo "== [1/3] defconfig"
make -s -C "$TREE" ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- O="$OUT" defconfig

echo "== [2/3] 合并 $FRAGMENT"
F="$OUT/frag.clean"
: > "$F"
bad=0
while IFS= read -r line; do
	case "$line" in
	CONFIG_*=*) printf '%s\n' "$line" >> "$F" ;;
	"# CONFIG_"*" is not set") printf '%s\n' "$line" >> "$F" ;;
	"# CONFIG_"*" is not set"[!\ ]*|"# CONFIG_"*" is not set "*)
		echo "   !! 非法指令（会被静默跳过）：$line"
		bad=1 ;;
	esac
done < "$FRAGMENT"
[ "$bad" = 0 ] || { echo "!! 片段里有非法指令"; exit 2; }
cat "$F" >> "$OUT/.config"
make -s -C "$TREE" ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- O="$OUT" olddefconfig 2>/dev/null

echo "== [3/3] 结果"
cp -f "$OUT/.config" "$WS/out/config-candidate"
echo "   候选配置写到 out/config-candidate（out/config-effective 保持不动 —— 它的含义是"
echo "   「当前 out/Image.gz 是用哪份配置编出来的」，要等到重编才会更新）"
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
$PY "$WS/tools/config-audit.py" "$OUT/.config" --fragment "$FRAGMENT" || true
