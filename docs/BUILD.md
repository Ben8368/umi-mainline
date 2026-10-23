# 构建和引导指南

## 1. 编译内核

```bash
# 在 WSL Alpine 中:
cd /tmp/mainline-kernel
make ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- -j$(nproc) Image.gz dtbs
```

## 2. 创建 initramfs

```bash
cd <repo>\initramfs
chmod +x init
find . | cpio -o -H newc | gzip > ../initramfs.cpio.gz
```

## 3. 打包 boot.img

```bash
# 将 DTB 附加到内核
cat arch/arm64/boot/Image.gz \
    arch/arm64/boot/dts/qcom/sm8250-xiaomi-umi.dtb \
    > Image.gz-dtb

# 使用 mkbootimg 打包
mkbootimg \
    --kernel Image.gz-dtb \
    --ramdisk initramfs.cpio.gz \
    --cmdline "console=ttyMSM0,115200 earlycon pd_ignore_unused clk_ignore_unused" \
    --base 0x0 \
    --kernel_offset 0x8000 \
    --ramdisk_offset 0x1000000 \
    --tags_offset 0x100 \
    --pagesize 4096 \
    --header_version 2 \
    -o boot-umi-mainline.img
```

## 4. 引导测试

```powershell
# 进入 fastboot
adb reboot bootloader

# 临时引导（不破坏原系统）
fastboot boot boot-umi-mainline.img

# USB 连接后:
# Linux: screen /dev/ttyACM0 115200
# Windows: PuTTY → COM port → 115200
```

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
