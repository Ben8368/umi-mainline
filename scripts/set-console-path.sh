#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# set-console-path.sh — 在「fbdev simplefb」和「DRM simpledrm」两条出字路线之间切换
#
#   wsl -d umi -u root -- sh <repo>/scripts/set-console-path.sh simplefb
#   wsl -d umi -u root -- sh <repo>/scripts/set-console-path.sh simpledrm
#
# 两条路都能把 console=tty0 的内容画到屏幕上，区别只是「谁去接管 ABL 留下的
# cont-splash 帧缓冲」：
#
#   simpledrm（默认）
#       CONFIG_DRM + CONFIG_DRM_SIMPLEDRM + DRM_FBDEV_EMULATION
#       ★ 只有它能挂 drm_panic（panic 时把日志/二维码画到屏幕上）
#         —— simpledrm 实现了 get_scanout_buffer
#
#   simplefb（最朴素的退路）
#       CONFIG_FB + CONFIG_FB_SIMPLE + FRAMEBUFFER_CONSOLE
#       少几层（不经过 DRM core/KMS/GEM），但没有 drm_panic，
#       而且 Kconfig 里 FB_SIMPLE 带 "depends on !DRM_SIMPLEDRM"，两者互斥。
#       切到它之后 DRM_PANIC 会变成"编着但没人挂"，不报错但也不干活。
set -e

WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
MODE=${1:-}
CFG=$WS/config/umi.config

[ -f "$CFG" ] || { echo "!! 找不到 $CFG"; exit 2; }

case "$MODE" in
simplefb)
	# 关掉 simpledrm，打开 fb_simple
	sed -i 's|^CONFIG_DRM_SIMPLEDRM=y|# CONFIG_DRM_SIMPLEDRM is not set|' "$CFG"
	sed -i 's|^# CONFIG_DRM_SIMPLEDRM is not set|# CONFIG_DRM_SIMPLEDRM is not set|' "$CFG"
	sed -i 's|^# CONFIG_FB_SIMPLE is not set|CONFIG_FB_SIMPLE=y|' "$CFG"
	grep -q '^CONFIG_FB_SIMPLE=y' "$CFG" || \
		sed -i 's|^CONFIG_FB=y|CONFIG_FB=y\nCONFIG_FB_SIMPLE=y|' "$CFG"
	;;
simpledrm)
	sed -i 's|^CONFIG_FB_SIMPLE=y|# CONFIG_FB_SIMPLE is not set|' "$CFG"
	sed -i 's|^# CONFIG_DRM_SIMPLEDRM is not set|CONFIG_DRM_SIMPLEDRM=y|' "$CFG"
	;;
*)
	echo "用法: $0 simplefb | simpledrm"
	grep -n -E 'CONFIG_(FB_SIMPLE|DRM_SIMPLEDRM|DRM=|FB=)' "$CFG" | sed 's/^/   现在: /'
	exit 1
	;;
esac

echo "== 切换成 $MODE，现在配置片段里是："
grep -n -E 'CONFIG_(FB_SIMPLE|DRM_SIMPLEDRM|DRM=|FB=)' "$CFG" | sed 's/^/   /'
echo ""
echo "== 重编 + 重打 initramfs"
sh "$WS/scripts/build.sh"
sh "$WS/scripts/mkinitramfs.sh"
echo ""
echo "== 完成，打包：python tools\\pack-umi.py --name p1"
