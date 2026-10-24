#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# mk-mini-rootfs.sh — 造一个「最小但真的能切进去」的 ext4 rootfs
#
# 用途：在动 userdata（226 GB，MIUI 数据）之前，先用它验证
#   initramfs -> switch_root -> 真 rootfs 这条链路是通的。
# 它会被刷到 cache 分区（sda29，356 MB，只是 OTA 缓存，抹了无害），
# 所以第一次刷写不碰任何有价值的数据。
#
#   wsl -d umi -u root -- sh <repo>/scripts/mk-mini-rootfs.sh
#
# 产物：/root/arch/umi-mini-rootfs.img（默认 64 MiB）
set -e

WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
SIZE_MB=${SIZE_MB:-64}
OUT=${OUT:-/root/arch/umi-mini-rootfs.img}
BB=${BB:-/tmp/armroot/bin/busybox.static}
MNT=/mnt/umimini

[ -x "$BB" ] || { echo "!! 找不到静态 busybox: $BB"; exit 1; }

echo "== 输出 $OUT ($SIZE_MB MiB)"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT"
truncate -s "${SIZE_MB}M" "$OUT"
mkfs.ext4 -q -F -L umimini -m 0 "$OUT"

mkdir -p "$MNT"
mount -o loop "$OUT" "$MNT"
trap 'umount "$MNT" 2>/dev/null || true' EXIT INT TERM

# POSIX sh 没有 {a,b} 展开，逐个建
for d in bin sbin etc etc/init.d proc sys dev tmp root run usr usr/bin usr/sbin; do
	mkdir -p "$MNT/$d"
done

cp "$BB" "$MNT/bin/busybox"
chmod 755 "$MNT/bin/busybox"
for a in sh ls cat echo mount umount sleep dmesg grep sed mkdir ln \
         reboot poweroff sync hostname ps kill; do
	ln -sf /bin/busybox "$MNT/bin/$a"
done
ln -sf /bin/busybox "$MNT/sbin/init"

cat >"$MNT/etc/init.d/rcS" <<'EOF'
#!/bin/sh
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev 2>/dev/null
mkdir -p /run /dev/pts
hostname umi-mini
echo "" >/dev/ttyGS0
echo "=================================================" >/dev/ttyGS0
echo "  MINI ROOTFS IS ALIVE (switch_root worked)" >/dev/ttyGS0
echo "  $(cat /proc/version)" >/dev/ttyGS0
echo "  cmdline: $(cat /proc/cmdline)" >/dev/ttyGS0
echo "  mounts:" >/dev/ttyGS0
mount | sed 's/^/    /' >/dev/ttyGS0
echo "  block devices:" >/dev/ttyGS0
ls /dev/sd* 2>/dev/null | sed 's/^/    /' >/dev/ttyGS0
echo "=================================================" >/dev/ttyGS0
echo "" >/dev/ttyGS0
EOF
chmod 755 "$MNT/etc/init.d/rcS"

cat >"$MNT/etc/inittab" <<'EOF'
::sysinit:/etc/init.d/rcS
ttyGS0::respawn:-/bin/sh
tty1::respawn:-/bin/sh
::ctrlaltdel:/bin/reboot
::shutdown:/bin/umount -a -r
EOF

# 如果切根成功，屏幕上也能看到东西
echo "umi-mini" >"$MNT/etc/hostname"

sync
umount "$MNT"
trap - EXIT INT TERM

ls -lh "$OUT"
echo ""
echo "== 完成。刷到 cache 测试（**先跟用户确认**）："
echo "   fastboot flash cache $(basename "$OUT")"
echo "   fastboot boot out\\boot-umi-arch.img      # initramfs 里 root-dev=/dev/sda34 改成 /dev/sda29 再试"
