#!/bin/sh
# umi-plasma.sh — 在 umi 的 Arch 根分区上把 Plasma Mobile 开起来
#
#   wsl -d umi -u root -- sh scripts/umi-plasma.sh        # 打印步骤，不执行
#   ssh root@PHONE 'sh /root/umi-plasma.sh --apply'       # 手机侧执行
#
# 做四件事（都是踩过的坑）：
#
#   1. 装包：plasma-mobile / plasma-settings / kscreen / konsole
#   2. tty1 自动登录 alarm，~/.bash_profile 里 exec startplasmamobile
#      （不用 SDDM：touch-only 的机器上多一个 greeter 只会多一处坏掉的地方）
#   3. **udev uaccess**：触摸是 platform(i2c) 设备，systemd 自带的
#      70-uaccess.rules 只给 USB 输入设备打 uaccess tag，logind 就不给登录
#      用户授权 /dev/input/event*，KWin 的 libinput 打不开 → 触摸完全没反应。
#   4. locale：Qt/KWin 要 UTF-8（默认 LANG=C 时 kwin 会警告并退回 C.UTF-8）
set -e

APPLY=no
[ "$1" = "--apply" ] && APPLY=yes

run() {
	if [ "$APPLY" = yes ]; then
		sh -c "$1"
	else
		echo "  # $1"
	fi
}

echo "== 1/4 装包"
run "pacman -S --noconfirm --needed --disable-sandbox plasma-mobile plasma-settings kscreen konsole"

echo "== 2/4 tty1 自动登录 + 起 Plasma Mobile"
run "mkdir -p /etc/systemd/system/getty@tty1.service.d"
if [ "$APPLY" = yes ]; then
	cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/usr/bin/agetty --autologin alarm --noclear %I linux
EOF
	cat > /home/alarm/.bash_profile <<'EOF'
# tty1 自动进 Plasma Mobile（Wayland）
if [ -z "${WAYLAND_DISPLAY}" ] && [ "${XDG_VTNR}" = "1" ]; then
	exec /usr/lib/plasma-dbus-run-session-if-needed /usr/bin/startplasmamobile
fi
EOF
	chown alarm:alarm /home/alarm/.bash_profile
	chmod 644 /home/alarm/.bash_profile
	systemctl daemon-reload
	systemctl disable sddm 2>/dev/null || true
else
	echo "  # 写 /etc/systemd/system/getty@tty1.service.d/autologin.conf（agetty --autologin alarm）"
	echo "  # 写 /home/alarm/.bash_profile（exec startplasmamobile）"
	echo "  # systemctl daemon-reload; systemctl disable sddm"
fi

echo "== 3/4 udev：platform 输入设备也要 uaccess"
run "cat > /etc/udev/rules.d/71-umi-input-uaccess.rules"
if [ "$APPLY" = yes ]; then
	cat > /etc/udev/rules.d/71-umi-input-uaccess.rules <<'EOF'
# umi: 触摸 (fts, platform:a94000.i2c) / gpio-keys 都不是 USB 设备，
# systemd 的 70-uaccess.rules 只覆盖 USB 输入设备，所以 logind 永远不给登录
# 用户授权 /dev/input/event*，Wayland 合成器（KWin/libinput）就打不开。
SUBSYSTEM=="input", KERNEL=="event[0-9]*", TAG+="uaccess"
EOF
	udevadm control --reload
	udevadm trigger --action=change --subsystem-match=input
	for g in input video render audio; do
		usermod -aG "$g" alarm 2>/dev/null || true
	done
fi

echo "== 4/4 locale = UTF-8"
if [ "$APPLY" = yes ]; then
	grep -q '^#en_US\.UTF-8 UTF-8' /etc/locale.gen && \
		sed -i 's/^#en_US\.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen
	grep -q '^en_US\.UTF-8 UTF-8' /etc/locale.gen || \
		echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen
	locale-gen >/dev/null
	printf 'LANG=en_US.UTF-8\n' > /etc/locale.conf
	echo "  locale.conf = $(cat /etc/locale.conf)"
else
	echo "  # locale-gen en_US.UTF-8; echo LANG=en_US.UTF-8 > /etc/locale.conf"
fi

echo
echo "完成。重开一次会话让 KWin 重新枚举输入设备："
echo "  loginctl terminate-session \$(loginctl list-sessions --no-legend | awk '\$3==\"alarm\"{print \$1;exit}')"
echo "  systemctl restart getty@tty1"
