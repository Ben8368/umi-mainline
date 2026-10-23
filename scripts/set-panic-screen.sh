#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# set-panic-screen.sh — 切换 panic 屏的样式
#
#   wsl -d umi -u root -- sh <repo>/scripts/set-panic-screen.sh qr_code
#   ... kmsg     只画日志文本
#   ... user     只画一句「请重启」
#
# 三种都编在核心里（DRM_PANIC_SCREEN 是个字符串选项，运行时也能改），
# 这里只是改内核内置 cmdline 里的 drm.panic_screen=，然后重编。
#
# 另外：运行时也能直接改（不用重编）：
#     echo kmsg > /sys/module/drm/parameters/panic_screen
set -e

WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
MODE=${1:-}
CFG=$WS/config/umi.config

case "$MODE" in
qr_code|kmsg|user) ;;
*)
	echo "用法: $0 qr_code | kmsg | user"
	grep -n 'CONFIG_DRM_PANIC_SCREEN=' "$CFG" | sed 's/^/   现在: /'
	exit 1
	;;
esac

sed -i "s|^CONFIG_DRM_PANIC_SCREEN=\".*\"|CONFIG_DRM_PANIC_SCREEN=\"$MODE\"|" "$CFG"

# 把 drm.panic_screen= 也放进 cmdline（双保险：内核里那个是编译期默认值）
if grep -q 'drm.panic_screen=' "$CFG"; then
	sed -i "s|drm\.panic_screen=[a-z_]*|drm.panic_screen=$MODE|" "$CFG"
else
	sed -i "s|\(CONFIG_CMDLINE=\"[^\"]*\)\"|\1 drm.panic_screen=$MODE\"|" "$CFG"
fi

echo "== 现在是："
grep -n -E 'CONFIG_DRM_PANIC_SCREEN=|^CONFIG_CMDLINE=' "$CFG" | sed 's/^/   /'
echo ""
echo "== 重编"
sh "$WS/scripts/build.sh"
echo ""
echo "== 完成，打包：python tools\\pack-umi.py --name p1"
