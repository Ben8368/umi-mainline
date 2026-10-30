#!/bin/sh
# mkimage.sh —— **唯一**的镜像入口：编内核 + 打一张全功能镜像 out/boot-umi.img
#
#   wsl -d umi -u root -- sh /mnt/d/project/UMI-mainline/scripts/mkimage.sh
#
# 这张镜像里同时有（都在内核/DT 里，不需要再挑）：
#   - 面板驱动（CSOT j2_mp_42_02_0b，DSC cmd mode）
#   - 触摸（fts521 主线移植版；换厂商版用 TOUCH=stfts 并另存名）
#   - GPU（Adreno 650，DT 打开 gmu/gpu + initramfs 里的 a650 固件）
#   - Wi-Fi 的 DTS；ath11k 等模块另交付到 out/modules-<release>.tar.gz
#   - 电量计 / 主充电器（BQ25970 主动快充默认隔离，见 docs/BATTERY.md）
#
# boot.img 不包含 rootfs 模块和 Wi-Fi 固件；救援模式不保证 Wi-Fi/桌面。
# 其它 boot-umi-*.img 都是实验对照，
# 要么是某个驱动还没合进来的验证版（TOUCH=stfts），要么是历史遗留。
set -e
WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
NAME=${NAME:-boot-umi.img}
ROOTDEV=${ROOTDEV:-none}
ROOTFSTYPE=${ROOTFSTYPE:-ext4}

echo "== [1/3] 编内核（默认配置：全功能）=="
sh "$WS/scripts/build.sh"

echo "== [2/3] 生成 initramfs（root=${ROOTDEV}）=="
sh "$WS/scripts/mkinitramfs.sh" --root "$ROOTDEV" --rootfstype "$ROOTFSTYPE"

echo "== [3/3] 打包 $WS/out/$NAME =="
python3 "$WS/tools/pack-umi.py" \
	--dtb "$WS/out/sm8250-xiaomi-umi-wifi.dtb" \
	-o "$WS/out/$NAME"

ls -l "$WS/out/$NAME"
echo "== 完成：fastboot boot out/$NAME =="
