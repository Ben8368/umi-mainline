# 构建和引导指南

## 0. 一条命令出镜像（推荐）

```sh
wsl -d umi -u root -- sh /mnt/d/project/UMI-mainline/scripts/mkimage.sh
# 产物：out/boot-umi.img
```

这张 `out/boot-umi.img` 是默认临时引导镜像；构建会依次生成内核/三个新 DTB、fresh initramfs，再打包。默认 `ROOTDEV=none` 进入救援模式，不自动挂载 userdata。已安装 Arch 的设备可在确认真实根分区后显式设置 `ROOTDEV=/dev/sda34`，例如在 Linux 中运行 `ROOTDEV=/dev/sda34 sh scripts/mkimage.sh`。刷写不是本构建命令的一部分。

镜像内容：

| 子系统 | 在哪 |
|---|---|
| 面板（CSOT j2_mp_42_02_0b，DSC cmd） | `patches/panel-xiaomi-umi.c` + `dts/xiaomi-umi-panels.dtsi` |
| 触摸（ST FTS，fts521 主线移植版） | `fts521/`（`patches/fts-umi.c` 是旧版，不编） |
| GPU（Adreno 650） | `dts/*.dts` 的 `&gpu`/`&gmu` + `firmware/qcom/a650_*` 打进 initramfs |
| Wi-Fi（QCA6390 PCIe） | Wi-Fi DTS + 同版本 ath11k/MHI/pwrctrl 模块包；rootfs 另需固件 |
| 电量计 / 主充电器（BQ25970 默认禁用） | `power/qcom_fg.c`、`qcom_pm8150b_charger.c`、`bq25970_charger.c` |
| 桌面（Plasma Mobile，在 rootfs 里） | `scripts/umi-plasma.sh` |

功能在同一适配层累加。`boot.img` 不含 rootfs 模块和 Wi-Fi 固件；救援模式也不等于 Wi-Fi、蓝牙或桌面已可用。`out/archive/` 里的
`boot-umi-*.img` 都是历史实验对照（某次单一驱动的验证版），平时不用管。

### 只重打镜像、不重编内核

```sh
python tools/pack-umi.py --dtb out/sm8250-xiaomi-umi-wifi.dtb -o out/boot-umi.img
```

### 换一个驱动做对照实验（可选）

```sh
TOUCH=stfts sh scripts/build.sh            # 厂商 5.2.4 驱动
python tools/pack-umi.py --dtb out/sm8250-xiaomi-umi-wifi.dtb -o out/boot-umi-stfts.img
```

实验镜像**一定要另起名字**，别覆盖 `boot-umi.img`。

## 1. 编译内核（mkimage.sh 内部做的事）

```sh
sh scripts/prepare-tree.sh  # 首次准备或核验 config/kernel.env 固定的源码身份
sh scripts/build.sh
# 干的事：同步 dts/ 和驱动补丁进默认 /root/linux-6.18.59 → defconfig + 合并 config/umi.config
#        → 注入面板/触摸/电量计驱动 → 编 Image.gz + 三个 DTB + modules
# 产物：out/Image.gz、三个 DTB、config-effective、modules-<release>.tar.gz、kernelrelease
```

默认 `TREE` 会在构建开始前用 `git -C "$TREE" rev-parse HEAD` 核对 `config/kernel.env` 中的完整提交；显式提供非空 `TREE` 时保留兼容构建路径，不做固定版本限制。

### 6.18.x 独立构建

6.18.59 的固定源码身份、独立 `TREE` / `OUT` / `WS`、兼容修复、构建命令、产物哈希与运行边界见 [构建记录](archive/reviews/2026-10-29-linux-6.18.59-build.md)。切换版本时使用新的 ext4 源码树和产物目录，避免继承旧树手工补丁或覆盖原镜像；默认版本统一由 `config/kernel.env` 固定为 6.18.59，构建/配置/DTB/模块辅助脚本共用它；`TREE=` / `OUT=` 仍可显式指定旧版兼容构建。`prepare-tree.sh` 克隆固定标签并比对完整 SHA，拒绝覆盖已有错误版本的目录；6.18 也进入手动编译 CI。

### 模块交付

`build.sh` 会执行 `make Image.gz dtbs modules`，再调用 `export-modules.py`，在普通临时目录中执行 `modules_install` 并生成匹配版本的 depmod 索引（宿主须安装 kmod）。模块归档、清单、kernelrelease、Image.gz、三个 DTB 和 config-effective 作为一个交付组发布；可捕获替换错误时恢复整组旧文件，原本缺失的文件会移除。导出不挂载 rootfs、不删除旧版模块、不访问手机。包内为 `lib/modules/<kernelrelease>/`，适用于已由维护者确认目录布局的 rootfs；真实设备安装另需授权。

`out/modules-manifest.json` 记录模块数、内核/配置/模块包 SHA256，`out/kernelrelease` 给出唯一对应版本。不能给 6.18 使用 6.12 的 `.ko`。即使包存在，也需在真实 rootfs 验证 modprobe、QCA6390 固件、PCIe 枚举、网络连接和休眠恢复。

替换前会备份整个交付组；若回滚也失败，命令报错并保留输出目录下 `.modules-backup-*` 中以原文件名保存的恢复副本；先停止消费混合产物，核对并恢复完整交付组后再使用。这是可捕获 I/O 错误的回滚，不保证进程被杀、断电或并发读写时整个交付组整体原子切换。

## 2. 创建 initramfs

BusyBox 默认从官方 GPL 源码构建，源码身份在 `config/source-lock.json`。需要 Python ≥3.12、make、宿主 C 编译器和带静态 libc 的 arm64 **Linux** 交叉工具链（Ubuntu: `gcc-aarch64-linux-gnu libc6-dev-arm64-cross`）；内核用的 `aarch64-none-elf-` 不带 Linux libc，不能用于 BusyBox。

```sh
python3 scripts/build-busybox.py --jobs 4
# 离线也可传 --source-archive /path/busybox-1.37.0.tar.bz2，仍强制校验固定 SHA256
# 若内核与用户态工具链位于不同 WSL 发行版，将源码产物用 BB=/path/busybox.static 显式传入
```

输出包含 ELF、实际配置和来源 JSON。构建使用通用软件哈希，禁用 1.37.0 与新头文件不兼容且救援不用的 `tc` applet；完整 rootfs 可使用 iproute2。既有预编译 Alpine BusyBox 仍是开放项目的二进制分发，但不再作为自动回退：只有显式 `BB=/path/to/busybox.static` 才选用，路径无效直接失败。

initramfs 打包前还会检查 BusyBox 是小端 ELF64、目标为 AArch64 且不含动态解释器；显式预编译文件也执行相同校验。源码构建发布 ELF、配置和来源 JSON 时使用回滚，失败时恢复旧文件；回滚失败会保留 `.busybox-backup-*` 恢复副本。

默认救援模式，已安装根分区用 `--root /dev/sda34` 显式选择。所有打包阶段失败都会停止，不发布半成品覆盖旧 initramfs。

打包前强制校验 `firmware/manifest.json` 的完整文件集合和哈希；新增或修改固件须先复核来源并更新清单，失败不覆盖已有 initramfs。

GPU 固件必须在这里面（adreno 是内建驱动，probe 时 rootfs 还没挂上）：

```sh
sh scripts/mkinitramfs.sh          # 会把 firmware/qcom/a650_* 打进去
# 产物：out/initramfs.cpio.gz
```

## 3. 打包 boot.img

```sh
python tools/pack-umi.py --dtb out/sm8250-xiaomi-umi-wifi.dtb -o out/boot-umi.img
```

`tools/pack-umi.py` 在显式提供 `--template` 时读取原厂 boot.img 的地址/页大小等参数；默认使用内建参数，
把 `Image.gz` + `initramfs.cpio.gz` + DTB 打成一个 Android v2 boot image。

## 4. 引导测试

```powershell
fastboot boot out\boot-umi.img
# 救援模式：USB CDC-ACM 串口 root shell
# 已显式选择安装根分区且配置网络/sshd 后：ssh root@192.168.42.1（USB RNDIS）
```

完整流程见 `RUNBOOK.md`。

## 关键内核参数

| 参数 | 作用 |
|------|------|
| `console=ttyMSM0,115200` | UART 调试控制台 |
| `earlycon` | 早期启动日志 |
| `pd_ignore_unused` | 不关闭"未使用"的供电域（保护 pm8150a 设备） |
| `clk_ignore_unused` | 不关闭"未使用"的时钟 |

没有这两个 ignore 参数，主线内核会关掉 pm8150a 的供电，导致触控等设备断电。

## 调试技巧

如果内核没启动到串口输出：

1. **检查 pstore**: `adb shell su -c "cat /sys/fs/pstore/console-ramoops-0"` — 看上次引导的日志
2. **检查是否有 ABL 限制**: 某些固件版本禁用了 `fastboot boot`，尝试 `fastboot flash boot` 或 kexec
3. **尝试不同的 DTB 加载方式**: 有些 bootloader 需要把 DTB 放在 boot.img 的 recovery_dtbo 分区

## 使用 kexec 作为备选

如果 fastboot 不行：

```bash
# 在 Android root shell 上:
# 1. 把主线内核和 dtb 推到手机
adb push Image.gz /data/local/tmp/
adb push sm8250-xiaomi-umi.dtb /data/local/tmp/
adb push initramfs.cpio.gz /data/local/tmp/

# 2. kexec 加载
adb shell su -c "kexec -l /data/local/tmp/Image.gz \
    --dtb=/data/local/tmp/sm8250-xiaomi-umi.dtb \
    --initrd=/data/local/tmp/initramfs.cpio.gz \
    --command-line=\"console=ttyMSM0,115200 earlycon pd_ignore_unused clk_ignore_unused\""

# 3. 跳转
adb shell su -c "kexec -e"
```
