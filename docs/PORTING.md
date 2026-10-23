# 小米 10 (umi) 主线 Linux 移植状态

## 工作区结构

```
<repo>\
├── HARDWARE.md                          # 硬件清单（从真机+下游DTS提取）
├── PORTING.md                           # 本文件
├── downstream-kernel/                   # 下游 4.19 内核 (n0kernel, staging-umi)
│   └── arch/arm64/boot/dts/vendor/qcom/
│       ├── umi-sm8250.dtsi              # 设备树主文件
│       ├── umi-pinctrl.dtsi             # GPIO 配置
│       ├── xiaomi-sm8250-common.dtsi    # 公共配置（面板、充电、WiFi等）
│       └── dsi-panel-j2-mp-42-02-0b-dsc-cmd.dtsi  # J2 面板 init sequence
└── mainline-kernel/                     # 主线内核 (torvalds/linux.git)
    └── arch/arm64/boot/dts/qcom/
        ├── sm8250-xiaomi-umi.dts         # ← 新创建：顶层 DTS
        ├── sm8250-xiaomi-umi-common.dtsi # ← 新创建：设备树主文件
        └── Makefile                      # ← 已修改：添加 umi DTB
```

## 各组件支持状态

| 组件 | 状态 | 备注 |
|------|------|------|
| SoC (SM8250) | ✅ DTS 已写 | SoC 层主线完整支持 |
| CPU/SMP | ✅ DTS 已写 | sm8250.dtsi 提供 |
| UART 调试 | ✅ DTS 已写 | uart15, 波特率 115200 |
| UFS 存储 | ✅ DTS 已写 | 可直接 boot 进 rootfs |
| USB 2.0 | ✅ DTS 已写 | peripheral 模式, high-speed |
| Type-C PD | ✅ DTS 已写 | 双角色供电 |
| GPIO/按键 | ✅ DTS 已写 | 音量键 + 霍尔传感器 |
| GPU (A650) | ✅ DTS 已写 | freedreno 支持 |
| PCIe (WiFi) | ✅ DTS 已写 | QCA6390 理论上可用 |
| 蓝牙 | ✅ DTS 已写 | QCA6390 via UART6 |
| PMIC 供电 | ✅ DTS 已写 | pm8150/pm8150b/pm8150l/pm8009 |
| 简单帧缓冲 | ✅ DTS 已写 | 复用 bootloader 初始化画面 |
| 保留内存 | ✅ DTS 已写 | 从下游验证过的地址 |

| 组件 | 状态 | 备注 |
|------|------|------|
| pm8150a 供电 | ⚠️ workaround | fixed-regulator 绕过, 实际靠 bootloader 上电 |
| STM FTS 触控 | ⚠️ DTS 已写 | 需要主线 focaltech 驱动支持 `st,fts` |
| J2 CSOT 面板 | ❌ 需 driver | 面板 init 命令已有, 需写 panel driver |
| 电池/充电 | ❌ 不支持 | PM8150B GEN4 FG 主线无驱动 |
| 音频 | ❌ 未配置 | CS35L41 + WCD938x |
| Modem/X55 | ❌ 不可能 | 主线不支持 |

## pm8150a 问题说明

pm8150a (OLED bias PMIC) 在主线没有 DTSI 驱动。它提供：
- `pm8150a_l1` = 触控 VDD (1.8V)
- OLEDB / AB / IBB = 面板偏压

**解决方案**: bootloader (XBL/ABL) 在跳转内核前已初始化所有 PMIC 输出。
fixed-regulator 告诉内核"这条轨存在且已上电, 别碰它"。
这是所有主线高通设备的标准做法, elish/pipa 都是这么处理的。

## 下一步: 第一次编译

```bash
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
make defconfig
# 添加 SM8250 支持
scripts/config -e ARCH_QCOM
make olddefconfig
# 只编译 DTB 验证语法
make dtbs CHECK_DTBS=1 qcom/sm8250-xiaomi-umi.dtb
```

## 构建完整内核 + rootfs

使用 postmarketOS 的 pmbootstrap:
```bash
pmbootstrap init
# 选 vendor: xiaomi, device: umi (需要先在 pmaports 创建设备包)
pmbootstrap install --sdcard=/dev/sdX
```

## 引导测试

```bash
# 进入 fastboot
adb reboot bootloader
# 临时引导主线内核
fastboot boot arch/arm64/boot/Image.gz-dtb
```

## 待完成的关键工作

1. **写 J2 CSOT panel driver** (最大的活)
   - 已有完整的 DSI init sequence (从下游 `dsi-panel-j2-mp-42-02-0b-dsc-cmd.dtsi`)
   - DSC v1.1, 12 slices, 1080×2340, 60/90Hz
   - 参考: drivers/gpu/drm/panel/panel-novatek-nt36523.c (elish 的面板)

2. **主线 FTS 触控驱动支持 `st,fts`**
   - 主线已有 `drivers/input/touchscreen/stmfts.c` (STMicro) 和
     `drivers/input/touchscreen/focaltech_fts5452.c` (Focaltech)
   - 需要验证小米10的 `st,fts` 与现有驱动兼容, 或在现有驱动上加 compatible

3. **提取并打包 WiFi/GPU/BT 固件**
   - 从 Android `/vendor/firmware_mnt/image/` 提取
   - 放到 rootfs 的 `/lib/firmware/qcom/sm8250/xiaomi/umi/`

4. **测试并迭代**
   - 第一阶段: 串口输出 "Hello from mainline" → 已配置 UART
   - 第二阶段: USB gadget 网络 → 已配置 USB
   - 第三阶段: 挂载 rootfs → 已配置 UFS
   - 第四阶段: 显示画面 → simple-framebuffer (bootloader 画面)
   - 第五阶段: 面板点亮 → 需要 panel driver
   - 第六阶段: 触控可用 → 需要 st,fts 驱动
