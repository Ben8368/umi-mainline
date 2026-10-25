#!/bin/sh
# 把仓库里的 stfts/（取自 zhaoyuanwang123/armbian 的
# patch/kernel/archive/sm8250-7.2/0043-umi-touch-stfts-panel-qdefconfig.patch）
# 转成 LF 并清掉 diff 里的 CRLF
set -e
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
find "$ROOT/stfts" -type f | while read -r f; do
	sed -i 's/\r$//' "$f"
done
echo "== stfts/ 已规范化为 LF"
file "$ROOT/stfts/Kconfig" 2>/dev/null || true
