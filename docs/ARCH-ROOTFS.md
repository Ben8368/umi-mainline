# Arch Linux ARM 移植方案（umi）

> 目标：让小米 10 脱离电脑、断电重启也能自己进 Linux 发行版。
> 之前所有测试都是 `fastboot boot`（一次性，重启就回 MIUI）；从这一步开始改成**刷进分区**。
>
> **本文件里的刷写命令，每次执行前都要先向用户报备并拿到批准。**
> 约束（用户明示）：可以刷写分区；刷之前一定要说；不动电压。

---

## 1. 为什么是 Arch Linux ARM

- 官方 tarball `ArchLinuxARM-aarch64-latest.tar.gz` 是**通用 aarch64**，不绑定某块板子，
  内核和 DTB 都由我们自己提供，正好匹配现在的自编 mainline 内核。
- 滚动更新 + `pacman`，不需要像 Debian 那样折腾 ubuntu-base 的 init 脚本。
- 磁盘占用小：解压后 2.1 GB，6 GB 镜像够用很久。

## 2. 分区布局

mainline 内核看 UFS 是 `/dev/sda`（LUN0）+ `sdb..sdf`（其他 LUN）。
和 MIUI 的 `by-name` 对照关系（来自 `adb shell ls -l /dev/block/by-name/`）：

| 用途 | by-name | mainline | 大小 | 处理 |
|---|---|---|---|---|
| boot | `boot` | `sde50` | 128 MB | **刷** `boot-umi-arch.img` |
| 根文件系统 | `userdata` | `sda34` | 226 GB | **刷** `arch-rootfs.img`（6 GB，前缀部分） |
| 切根验证用 | `cache` | `sda29` | 356 MB | 可选：刷 `umi-mini-rootfs.img` 先试 |
| 不动 | `super` `system` `vendor` `dtbo` `vbmeta` … | | | MIUI 的，留着 |

**关键点**：ext4 允许「文件系统比它所在的分区小」。
所以 `arch-rootfs.img` 只做 6 GB，刷进 226 GB 的分区后，内核按 superblock 记录的
大小使用，尾部 220 GB 不被碰。刷写量因此从 226 GB 降到 6 GB。

> 想做满时（以后）：把镜像拷进手机，在手机里
> `resize2fs /dev/sda34` 就会长到分区末尾。

## 3. 镜像怎么造

### 3.1 Arch rootfs（正式）

```powershell
# 先下载官方 tarball（走本机代理，直连很慢）
curl.exe -L -x http://127.0.0.1:7890 `
  -o tmp\ArchLinuxARM-aarch64-latest.tar.gz `
  http://os.archlinuxarm.org/os/ArchLinuxARM-aarch64-latest.tar.gz

# 造镜像（在 WSL 里，需要 loop + mkfs.ext4）
wsl -d umi -u root -- sh scripts/mk-arch-rootfs.sh `
  /mnt/d/project/UMI-mainline/tmp/ArchLinuxARM-aarch64-latest.tar.gz
```

产物 `/root/arch/umi-rootfs.img`（默认 6144 MiB），脚本已经把这些写进去了：

| 项目 | 内容 |
|---|---|
| `/etc/fstab` | `/dev/sda34 / ext4 rw,relatime 0 1` |
| root 密码 | `umi`（可用 `ROOTPW=xxx` 覆盖） |
| 串口控制台 | `serial-getty@ttyGS0` → **autologin root** |
| 屏幕控制台 | `getty@tty1` |
| SSH | `sshd` 已 enable，`PermitRootLogin yes` |
| 网络 | `usb0` 固定 `192.168.42.1/24`（RNDIS） |
| 主机名/时区 | `umi` / `Asia/Shanghai` |
| 干扰项 | `systemd-firstboot` 被 mask（它会在串口里卡交互式提问） |

### 3.2 最小验证 rootfs

```powershell
wsl -d umi -u root -- sh scripts/mk-mini-rootfs.sh
```

产物 `/root/arch/umi-mini-rootfs.img`（64 MiB）：静态 busybox + `/etc/inittab`，
init 起来就往 `ttyGS0` 打 `MINI ROOTFS IS ALIVE (switch_root worked)`。
**它的唯一用途是：在动 userdata 之前，先用 cache 分区验证切根链路。**

### 3.3 内核模块

内核把 `rtc-pm8xxx` / `overlay` / `veth` / `fuse` / `pinctrl-lpass-lpi` 编成了 `=m`。
没有模块目录时：

- 没有 RTC → 开机时间回到 1970 → `pacman` 的 GPG 校验全挂
- 没有 `overlay`/`veth` → 容器跑不了

所以 rootfs 里要有 `/usr/lib/modules/<ver>/`：

```powershell
wsl -d umi -u root -e sh -c "cd /root/linux && make ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- O=/root/linux/out -j20 modules"
# 然后挂载镜像，modules_install 进去（见 scripts/install-modules.sh）
```

## 4. initramfs 怎么交棒

`initramfs/init` 的 `[10] real root` 段（在 USB gadget **之后**，故意的）：

1. 等 `/dev/sda34` 出现（最多 30 秒）
2. `mount -t ext4 -o rw /dev/sda34 /newroot`
3. `mount --move /dev /proc /sys` 过去（`devtmpfs` 必须跟着走，否则切根后没有 console）
4. `exec switch_root /newroot /sbin/init`

**失败就停在救援 shell**，串口还活着，并打印失败原因。
`switch_root` 返回也当作失败处理（会提示「真根挂在 /newroot」）。

切根目标不是编译期固定的，是 initramfs 里的两个小文本文件：

```
/root-dev     内容 /dev/sda34
/root-fstype  内容 ext4
```

打包时用参数控制，**改它不需要重编内核**：

```powershell
wsl -d umi -u root -- sh scripts/mkinitramfs.sh --no-panic-test --root /dev/sda34
wsl -d umi -u root -- sh scripts/mkinitramfs.sh --no-panic-test --root /dev/sda29   # cache 验证用
```

> 为什么不用内核 cmdline 的 `root=`：本内核开了 `CONFIG_CMDLINE_FORCE=y`，
> 头里的 cmdline 是装饰性的，真正生效的那份是编译进 `Image` 的。
> 为改一个设备名重编内核不值当，所以做成 initramfs 的运行时配置。

## 5. 上机步骤

### 5.1 进 fastboot

```powershell
C:\Users\color\platform-tools\adb.exe reboot bootloader
fastboot devices
```

> **一个 bootloader 会话只能 `fastboot boot` 一次**（这是 umi 的 ABL 行为）。
> 所以刷写顺序要安排好，别把 `fastboot boot` 放在需要多次操作的计划里。

### 5.2 第一步：验证切根链路（低风险，建议先做）

```powershell
fastboot flash cache   out\umi-mini-rootfs.img
fastboot boot          out\boot-umi-cachetest.img
# 串口 COM3 @115200 上应该出现：
#   ==== [10] real root: /dev/sda29 (ext4) ====
#   mounted /dev/sda29 -> /newroot, handing over to /sbin/init
#   MINI ROOTFS IS ALIVE (switch_root worked)
```

代价：MIUI 的 OTA 缓存没了（无所谓）。

### 5.3 第二步：正式安装

```powershell
fastboot flash boot     out\boot-umi-arch.img
fastboot flash userdata out\arch-rootfs.img
fastboot boot           out\boot-umi-arch.img     # ← 不是 reboot
```

> **★ 刷完一定要跟一条 `fastboot boot 同一张镜像`，不要用 `fastboot reboot`。**
> 这台机器的 ABL 在 `reboot` 之后会直接回落 fastboot（刷进 boot 分区的镜像它
> 这次不接手），而 `fastboot boot` 能立刻把同一张图跑起来 —— 于是「持久化」
> 和「马上看到结果」一步到位。
>
> 另一个约束：**一个 bootloader 会话只能 `fastboot boot` 一次**。
> 所以顺序永远是 flash → boot，别把 boot 提前用掉。

- `userdata` 这一条会**抹掉 194 GB MIUI 数据**，不可逆
- `boot` 刷坏不怕：`dump/boot-stock.img` 是原厂备份，ABL 在 `sde39` 不受影响，
  fastboot 永远进得去
- 关于 AVB：设备已解锁（我们一直在 `fastboot boot` 自编内核），刷没有 AVB footer 的
  `boot.img` 会走到 "orange state" 警告，但**允许启动**
- 刷不进去时（大镜像）看 `docs/WIFI.md` 末尾的 TWRP + adb push 分块 dd 办法：
  `fastboot` 会先把整个文件读进内存，6 GiB 直接 `std::bad_alloc`

### 5.4 首次启动

串口 COM3 @115200。预期：

```
[    1.2] Run /init as init process          <- initramfs
UMI-INIT: ==== [10] real root: /dev/sda34 (ext4) ====
UMI-INIT: mounted /dev/sda34 -> /newroot, handing over to /sbin/init
Arch Linux 6.12.94-umi-dirty (ttyGS0)
umi login: root                              <- autologin，直接进
```

### 5.5 首次要做的三件事

```sh
# 1. 时间 —— 没 RTC 时先手动设，不然后面 pacman 全是签名错误
timedatectl set-time "2026-10-24 18:00:00"

# 2. 改 root 密码（万一串口断开只能靠 SSH）
passwd

# 3. 确认网络
ip addr show usb0
ssh root@192.168.42.1     # 从电脑上
```

## 6. 回退

| 坏在哪 | 怎么回 |
|---|---|
| boot 刷坏，进不了系统 | `fastboot flash boot dump\boot-stock.img` |
| Arch 起不来（切根失败） | 串口救援 shell 还在，可以 `fsck`/重刷 |
| 想回 MIUI | 重刷 MIUI 固件；**userdata 里的数据回不来** |

## 7. 已知限制（第一版）

- ~~**没有触摸**~~ **已修好**：缺的是 PM8150B GPIO5 的 boost 电源，见
  `docs/TOUCH.md` §12
- ~~**没有 GPU**~~ **已修好**：Adreno 650 可初始化（`gpu-initialized: 1`），
  固件要打进 initramfs，见 `docs/GPU.md`
- **没有 WiFi/蓝牙**：TLMM north tile 读不出来，相关 GPIO 无法申请
- **没有 RTC 备份电池**：断电后时间丢失，靠 NTP 或手动设
- 交互主要靠 **USB 串口 + RNDIS 网络**，也就是每次都要插线
- 屏幕背光、亮度、`repower` 都在 DRM 面板驱动里，能用

## 8. 相关脚本

| 脚本 | 作用 |
|---|---|
| `scripts/mk-arch-rootfs.sh` | tarball → 6 GB ext4 镜像 + 全部配置 |
| `scripts/mk-mini-rootfs.sh` | 64 MB busybox 镜像，验证 switch_root |
| `scripts/mkinitramfs.sh` | `--root` / `--rootfstype` 控制切根目标 |
| `tools/pack-umi.py` | 内核 + dtb + initramfs → boot.img（校验 ABL 需要的 id） |

## 9. 教训：不要直接改 boot 分区里的 dtb 段

试过把新 dtb `dd` 到 boot 分区的 `0xf2f000`（md5 校验完全一致），结果手机起不来、
ABL 回落 fastboot —— **即使 md5 对得上**。

原因没有完全查清（可能是 ABL 对 boot.img 的某种一致性检查，或者 dtb 段尾部
被写脏），但结论很明确：

> **每次换 dtb 都重新 `pack-umi.py` 打一张完整的 boot.img，然后
> `fastboot flash boot` + `fastboot boot`。**
> 不要图省事在手机上改分区里的 dtb 段。

代价是每次实验要按一次键进 fastboot，但至少不用猜为什么起不来。


## 10. 分区远大于镜像：首次启动后要缩放文件系统

镜像 out/arch-rootfs.img 是固定 6 GiB，但真正烧进去的是手机上的
/dev/sda34（226.3 GiB）。所以刚启动时 df 只有 5.9G：

`
/dev/sda34  5.9G  2.3G  3.6G  40% /
`

ext4 支持在线变长，不用重启、不用卸载：

`sh
resize2fs /dev/sda34
df -h /
`

`
The filesystem on /dev/sda34 is now 59318267 (4k) blocks long.
/dev/sda34  223G  2.3G  221G   2% /
`

注意：esize2fs 在线只能**变长**，缩小必须先卸载。以后换更大的镜像时
同样只要两行命令，别再重烧分区。