# KDE Plasma Mobile on umi

状态（2026-10，镜像是 `boot-umi-plasma1.img` = GPU+触摸+WiFi 那一份 + 面板物理尺寸修复）：

```
plasmashell (Plasma Mobile 6.8.1) 在全屏 1080x2340 上跑着
kwin_wayland  drm 后端，持有 card1/renderD128 + event0..3（含触摸）
触摸可用（点得准），输出缩放 scale=2.5（逻辑 432x936）
GL 4.6 / GLES 3.2（freedreno FD650），Vulkan 1.3（turnip）
```

开机自动进桌面：`getty@tty1` 自动登录 `alarm` → `~/.bash_profile` 里
`exec startplasmamobile`。没有用 SDDM —— touch-only 的机器上少一个 greeter
就少一处会坏的地方。

## 1. 装

```sh
pacman -S --needed --disable-sandbox \
    plasma-mobile plasma-settings kscreen konsole
```

`plasma-mobile` 自己只有 20 MB，但会把 `plasma-workspace` / `kwin` /
`plasma-nano` / `plasma-keyboard` 一起拉下来（1 GB 量级）。它自带一个
wayland session：

```
/usr/share/wayland-sessions/plasma-mobile.desktop
    Exec=/usr/lib/plasma-dbus-run-session-if-needed /usr/bin/startplasmamobile
```

## 2. 自动登录 + 自动进桌面

`/etc/systemd/system/getty@tty1.service.d/autologin.conf`：

```ini
[Service]
ExecStart=
ExecStart=-/usr/bin/agetty --autologin alarm --noclear %I linux
```

`/home/alarm/.bash_profile`：

```sh
if [ -z "${WAYLAND_DISPLAY}" ] && [ "${XDG_VTNR}" = "1" ]; then
	exec /usr/lib/plasma-dbus-run-session-if-needed /usr/bin/startplasmamobile
fi
```

`systemctl disable sddm`（装了但不用）。

## 3. 触摸点不动：udev 的 `uaccess`（真正的坑）

现象：Plasma 起来了、界面在，但**点哪儿都没反应**；`/dev/input/event2`
权限是 `root:input 660`，登录用户打不开。

原因：

```
$ udevadm info --query=property --name=/dev/input/event2 | grep TAGS
TAGS=:power-switch:            <- 没有 uaccess
$ getfacl -p /dev/input/event2
user::rw-  group::rw-  other::---      <- 没有 user:alarm:rw 的 ACL
```

systemd 自带的 `70-uaccess.rules` 只给 **USB** 输入设备打 `uaccess` tag，
而 umi 的触摸是 **platform(i2c) 设备**（`platform:a94000.i2c`），所以 logind
从来不给登录会话发 ACL，KWin 的 libinput 自然打不开它。

修法（`/etc/udev/rules.d/71-umi-input-uaccess.rules`）：

```
SUBSYSTEM=="input", KERNEL=="event[0-9]*", TAG+="uaccess"
```

```sh
udevadm control --reload
udevadm trigger --action=change --subsystem-match=input
systemctl restart getty@tty1        # KWin 只在启动时枚举输入设备
```

兜底还可以 `usermod -aG input,video,render,audio alarm`。

修好之后：

```
$ ls -l /proc/$(pgrep -x kwin_wayland)/fd | grep input
 -> /dev/input/event0 (pm8941_pwrkey)
 -> /dev/input/event1 (pm8941_resin)
 -> /dev/input/event2 (fts)      <- 触摸
 -> /dev/input/event3 (gpio-keys)
```

## 4. “67 寸屏”：物理尺寸单位是 0.1 mm

现象：界面能点，但**小得离谱**（KWin 默认 scale=1）。

原因：下游 DT 里

```dts
xiaomi,physical-width-mm  = <0x2c6>;   /* 710 */
xiaomi,physical-height-mm = <0x601>;   /* 1537 */
```

单位是 **0.1 mm**，真机是 71.0 × 153.7 mm。驱动直接把它们喂给了
`connector->display_info.width_mm/height_mm`，于是 DRM 报 710×1537 mm，
`fastfetch` 里能看到 `1080x2340 in 67"`，KWin/kscreen 按这个算 DPI 就给了
scale 1.0。

修法：`patches/panel-xiaomi-umi.c` 里解析后除以 10（≥100 才除，防手写 DT 写
71 的情况）。修完 `fastfetch` 显示 `in 7"`。

## 5. 缩放：scale=2.5

KWin 在 Plasma 6 里不会按物理尺寸自动放大（kscreen 的自动缩放没生效），要显式设。
`~/.config/kwinoutputconfig.json`（KWin 自己的格式，是个数组）：

```json
[
  { "name": "outputs", "data": [ { "connectorName": "DSI-1", ..., "scale": 2.5 } ] },
  { "name": "setups",  "data": [ ... ] }
]
```

⚠️ **顺序**：KWin 退出时会把当前状态写回这个文件，所以必须

```
结束会话（等 kwin 真退出） → 改 scale → 起会话
```

否则刚改的值会被它覆盖（我踩过一次，白改）。

现用 **2.5** → 逻辑分辨率 432×936，接近普通手机。要更大就 3.0。

`kscreen-doctor` 在这台机器上会 **core dump**（`output.DSI-1.scale.2` →
`Aborted`），所以只能改文件；`kscreen` 的图形设置也一样不靠谱。

## 6. 会话挂了怎么救

```sh
systemctl restart getty@tty1
# 等 10~30 s；不行就看：
journalctl -b -u getty@tty1 --no-pager | tail
journalctl -b _UID=1000 --no-pager | tail -30
```

`loginctl terminate-session <id>` + `pkill -u alarm` 之后要靠 `getty@tty1`
重登才会再起 Plasma；重启 getty 本身不会杀掉已经在跑的会话进程，所以“重启
getty”要配合先结束会话。

## 7. 一键脚本

`scripts/umi-plasma.sh` 把第 1–3 步（装包、自动登录、udev、locale）固化了：

```sh
ssh root@PHONE 'sh /root/umi-plasma.sh --apply'
```

（不带 `--apply` 只打印要做什么。）

## 8. 还没做的

- 没有虚拟键盘自动弹出（`plasma-keyboard` 已装，但 Plasma Mobile 的输入法面板
  要在设置里挑一次；触摸-only 时建议先开“显示虚拟键盘”）
- 没有 GPU 过热降频（内核没接 cooling device，见 `docs/GPU.md`）
- 没有音频（`va_macro` 还缺 clock，见 `deferred` 列表）
- 没有重力/自动旋转（`qcom,sm8250` 的 imu 还没接）
- WiFi 能用但 `iwd` 需手动 `iwctl station wlan0 connect`
