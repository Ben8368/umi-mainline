#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# mk-arch-rootfs.sh — 用 Arch Linux ARM 官方 tarball 造一个 ext4 rootfs 镜像
#
#   wsl -d umi -u root -- sh <repo>/scripts/mk-arch-rootfs.sh \
#       /mnt/d/project/UMI-mainline/tmp/ArchLinuxARM-aarch64-latest.tar.gz
#
# 可选参数（环境变量）：
#   SIZE_MB=6144         镜像大小（默认 6144 MiB）
#   OUT=/root/arch/umi-rootfs.img
#   ROOTPW=umi           root 密码（默认 umi；改了记得自己记住）
#   KEEP_MOUNT=1         不卸载 /mnt，方便手工再改（默认卸载）
#
# 产物：$OUT —— 直接 `fastboot flash userdata` 用。
#
# 为什么要做镜像而不是直接写分区：
#   fastboot 只认整块镜像。故意把文件系统做得比分区的 226 GB 小很多，
#   ext4 允许「文件系统 < 分区」，内核按 superblock 里记录的大小用，
#   尾部空白不碰 —— 这样刷写量从 226 GB 降到 6 GB。
set -e

WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
TAR=${1:-$WS/tmp/ArchLinuxARM-aarch64-latest.tar.gz}
SIZE_MB=${SIZE_MB:-6144}
OUT=${OUT:-/root/arch/umi-rootfs.img}
ROOTPW=${ROOTPW:-umi}
MNT=/mnt/umirootfs

[ -f "$TAR" ] || { echo "!! 找不到 tarball: $TAR"; exit 1; }
case "$OUT" in /*) ;; *) echo "!! OUT 要用绝对路径"; exit 1 ;; esac

echo "== 输入  $TAR"
echo "== 输出  $OUT ($SIZE_MB MiB)"
mkdir -p "$(dirname "$OUT")"

# ---- 1. 空镜像 + ext4 ------------------------------------------------------
if [ -f "$OUT" ]; then
	echo "== 已存在，删掉重做"
	rm -f "$OUT"
fi
truncate -s "${SIZE_MB}M" "$OUT"
# -m 0: 不给 root 留 5% 保留块，6 GB 的空间要全部可用
# -b 4096: UFS 的逻辑扇区是 4 KiB，1 KiB / 2 KiB 块的 ext4 挂不上去
#          （小镜像上 mke2fs 会自作主张选 1024，见 mk-mini-rootfs.sh 的教训）
# -L umiroot: 挂载时好认
mkfs.ext4 -q -F -L umiroot -m 0 -b 4096 "$OUT"
echo "== ext4 建好了"

# ---- 2. 解压 tarball -------------------------------------------------------
mkdir -p "$MNT"
mount -o loop "$OUT" "$MNT"
trap 'umount "$MNT" 2>/dev/null || true' EXIT INT TERM

echo "== 解压 Arch Linux ARM（几百 MB，要一会儿）"
# --numeric-owner: 保留 tarball 里的 uid/gid，不然 root 会变成 Alpine 的编号
# --xattrs:        Arch 的包依赖 security.capability 之类的扩展属性
tar --numeric-owner --xattrs --xattrs-include='*' -xzf "$TAR" -C "$MNT"
echo "== 解压完成：$(du -sh "$MNT" | cut -f1)"

# ---- 3. 基础系统配置 -------------------------------------------------------
echo "== 写配置"

# 3a. fstab —— 根分区就是 userdata (sda34)。用 PARTLABEL 更稳，
#     但 MIUI 的 GPT 里 userdata 是 /dev/block/by-name/userdata，主线内核
#     直接叫 /dev/sda34，这里两个都留一条注释。
cat >"$MNT/etc/fstab" <<'EOF'
# /dev/sda34 == userdata (Mi 10, umi). 主line 内核下 UFS LUN0 是 sda。
/dev/sda34	/	ext4	rw,relatime	0	1

# 需要的话把下面打开（都在同一个 UFS 上）：
#/dev/sda29	/cache	ext4	defaults,noatime	0	2
#/dev/sda13	/logfs	ext4	defaults,noatime	0	2
EOF

# 3b. root 密码 + 允许 root 登录
if command -v openssl >/dev/null 2>&1; then
	HASH=$(openssl passwd -6 "$ROOTPW")
elif command -v mkpasswd >/dev/null 2>&1; then
	HASH=$(mkpasswd -m sha-512 "$ROOTPW")
else
	echo "!! 没有 openssl / mkpasswd，root 密码设不了"
	exit 2
fi
# tarball 里已经有 root 这一行；用 sed 原地换掉第二个字段
if grep -q '^root:' "$MNT/etc/shadow"; then
	sed -i "s|^root:[^:]*:|root:${HASH}:|" "$MNT/etc/shadow"
else
	echo "root:${HASH}:19000:0:99999:7:::" >>"$MNT/etc/shadow"
fi
chmod 600 "$MNT/etc/shadow"
# Arch Linux ARM tarball 的 root 账号默认是锁的/已知密码，这里顺手解锁
sed -i 's/^root:!:/root:/' "$MNT/etc/shadow"

# 3c. 串口控制台：ttyGS0 是 USB CDC-ACM 那一路（就是电脑上的 COM3）
#     自动登录 root，省掉每次敲密码 —— 反正是自己的手机。
mkdir -p "$MNT/etc/systemd/system/getty.target.wants"
ln -sf /usr/lib/systemd/system/serial-getty@.service \
	"$MNT/etc/systemd/system/getty.target.wants/serial-getty@ttyGS0.service"
mkdir -p "$MNT/etc/systemd/system/serial-getty@ttyGS0.service.d"
cat >"$MNT/etc/systemd/system/serial-getty@ttyGS0.service.d/autologin.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear %I 115200 linux
Type=idle
EOF

# 3d. 屏幕上的 tty1 也给一个 getty（fbcon 已经在画字了）
ln -sf /usr/lib/systemd/system/getty@.service \
	"$MNT/etc/systemd/system/getty.target.wants/getty@tty1.service"

# 3e. 网络：usb0 是 RNDIS 那一路。手机端固定 192.168.42.1，
#     Windows 侧会拿到 192.168.42.x（RNDIS 默认 DHCP 由手机端起）。
mkdir -p "$MNT/etc/systemd/network"
cat >"$MNT/etc/systemd/network/10-usb0.network" <<'EOF'
[Match]
Name=usb*

[Network]
Address=192.168.42.1/24
ConfigureWithoutCarrier=yes
# 手机给电脑当网关：打开 IPv4 转发 + NAT 需要额外规则，
# 先只要「电脑能连手机」这一半。
EOF
chown root:root "$MNT/etc/systemd/network/10-usb0.network"
chmod 644 "$MNT/etc/systemd/network/10-usb0.network"

# RNDIS 的 DHCP：让 Windows 自动拿到地址（dnsmasq 没装，用 systemd 的就够，
# Windows 会自己 link-local 或者手动配。这里先不管，串口才是主通道。）

# 3f. 主机名 / 时区
echo umi >"$MNT/etc/hostname"
cat >"$MNT/etc/hosts" <<'EOF'
127.0.0.1	localhost
::1		localhost
127.0.1.1	umi.localdomain	umi
EOF
ln -sf /usr/share/zoneinfo/Asia/Shanghai "$MNT/etc/localtime"

# 3g. sshd：允许 root 用密码登录（第一次连上去方便，之后自己改成密钥）
mkdir -p "$MNT/etc/ssh/sshd_config.d"
cat >"$MNT/etc/ssh/sshd_config.d/10-umi.conf" <<'EOF'
PermitRootLogin yes
PasswordAuthentication yes
EOF
ln -sf /usr/lib/systemd/system/sshd.service "$MNT/etc/systemd/system/multi-user.target.wants/sshd.service"

# 3h. 时间：pacman 对时间很敏感（GPG 签名会报错）。
#     RTC 驱动是模块，第一版还没装 modules，所以开机时间大概率是 1970。
cat >"$MNT/etc/systemd/timesyncd.conf" <<'EOF'
[Time]
NTP=ntp.aliyun.com time1.cloud.tencent.com
FallbackNTP=pool.ntp.org
EOF

# 3i. 关掉第一次开机的几个干扰项
#     systemd-firstboot 会卡在交互式提问上，串口里看不到就当掉了。
rm -f "$MNT/etc/systemd/system/multi-user.target.wants/systemd-firstboot.service" 2>/dev/null || true
ln -sf /dev/null "$MNT/etc/systemd/system/systemd-firstboot.service" 2>/dev/null || true

# ---- 4. 收尾 ---------------------------------------------------------------
sync
if [ "${KEEP_MOUNT:-0}" = 1 ]; then
	echo "== KEEP_MOUNT=1，$MNT 还挂着"
	trap - EXIT INT TERM
else
	umount "$MNT"
	trap - EXIT INT TERM
	echo "== 卸载完成"
fi

ls -lh "$OUT"
echo ""
echo "== 完成。刷写命令（**先跟用户确认**）："
echo "   fastboot flash userdata $(basename "$OUT")"
echo "== 首次登录：串口 COM3 @115200，root 密码 = $ROOTPW（ttyGS0 自动登录）"
