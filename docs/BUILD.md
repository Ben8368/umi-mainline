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
| WiFi/BT（QCA6390 PCIe，MAC 固定） | `dts/sm8250-xiaomi-umi-wifi.dts` |
| 电量计 / 主充电器（BQ25970 默认禁用） | `power/qcom_fg.c`、`qcom_pm8150b_charger.c`、`bq25970_charger.c` |
| 桌面（Plasma Mobile，在 rootfs 里） | `scripts/umi-plasma.sh` |

功能是**一张镜像里累加**的，不要按功能分镜像。`out/archive/` 里的
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
sh scripts/build.sh
# 干的事：同步 dts/ 和驱动补丁进 /root/linux → defconfig + 合并 config/umi.config
#        → 注入面板/触摸/电量计驱动 → 编 Image.gz + 三个 DTB（-@ 带 __symbols__）
# 产物：out/Image.gz、out/sm8250-xiaomi-umi*.dtb、out/config-effective
```

## 2. 创建 initramfs

默认救援模式，已安装根分区用 `--root /dev/sda34` 显式选择。所有打包阶段失败都会停止，不发布半成品覆盖旧 initramfs。

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
