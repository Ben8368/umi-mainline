# 小米 10 (umi) 硬件清单 — 主线移植参考

## 基本信息
- SoC: Qualcomm SM8250 (Snapdragon 865, codename "kona")
- 代号: umi
- 型号: M2001J2C
- 当前内核: 4.19 (Android 13, SDK 33)

---

## 1. 显示面板 — CSOT J2 MP AMOLED

| 参数 | 值 |
|------|-----|
| 面板节点 | `dsi_j2_mp_42_02_0b_dsc_cmd` |
| 面板名 | `qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd` |
| 类型 | DSI CMD mode (AMOLED) |
| 分辨率 | 1080 × 2340 |
| 物理尺寸 | 71 × 154 mm |
| 支持刷新率 | 60Hz, 90Hz |
| 色深 | 24-bit (8bpc) |
| 压缩 | DSC v1.1, 12 slices × 540px, 8bpp |
| 通道数 | 4-lane DSI |
| 时钟 | 682 MHz |

### 60Hz 时序
- H: front=16, back=8, pulse=8
- V: front=600, back=560, pulse=32

### 90Hz 时序
- H: front=16, back=8, pulse=8
- V: front=4, back=8, pulse=4

### 关键 GPIO
| 功能 | GPIO | 说明 |
|------|------|------|
| Panel Reset | tlmm 12 | 复位 |
| TE (撕裂效应) | tlmm 66 | BLE信号 |
| ESD IRQ | tlmm 51 | 上升沿触发, ONESHOT |
| Display Rate | tlmm 50 | 刷新率选择 |

### 背光
- 类型: DCS 命令控制 (bl_ctrl_dcs)
- 范围: 1–2047 (12-bit)
- 启动亮度: 536

### 电源
- 供电项: dsi_panel_pwr_supply_vci

### Panel ID
- 0x4A32 0x00420201

---

## 2. 触控 — 意法半导体 STM FTS

| 参数 | 值 |
|------|-----|
| DT compatible | `st,fts` |
| I2C 总线 | qupv3_se13_i2c (i2c-3) |
| I2C 地址 | 0x49 |
| IRQ GPIO | tlmm 39 (IRQF_ONESHOT \| IRQF_TRIGGER_LOW) |
| Reset GPIO | tlmm 38 |
| AVDD 供电 | touch_vddio_vreg (fixed regulator, GPIO 69) |
| VDD 供电 | pm8150a_l1 |
| 分辨率 | 1080 × 2340 |
| 固件 | st_fts_j2.ftb |
| FOD 区域 | lx=421, ly=1788, size=238×238 |
| 驱动源文件 | drivers/input/touchscreen/fts_521/fts.c |
| 备选触控 | Goodix GT9889 @ 0x5d (另一硬件版本) |

### 触控配置变体
| cfg | tp-vendor | tp-module | 固件 |
|-----|-----------|-----------|------|
| 0 | 0x38 | 0 | st_fts_j2_1.ftb |
| 1 | 0x42 | 1 | st_fts_j2_2.ftb |
| 2 | 0x42 | 2 | st_fts_j2_3.ftb |

---

## 3. 存储

| 参数 | 值 |
|------|-----|
| 类型 | UFS |
| 控制器 | 1d84000.ufshc |
| PHY | QMP v4 |
| vdda-phy | pm8150_l5 |
| vdda-pll | pm8150_l9 |
| vcc | pm8150_l17 (2.5–2.95V) |
| vccq | pm8150_l6 |
| vccq2 | pm8150_s4 |

---

## 4. USB

| 参数 | 值 |
|------|-----|
| USB0 | dwc3@a600000 (high-speed only) |
| PHY | usb2_phy0 + usb_nop_phy |
| USB1 | 禁用 (displayport phy 禁用) |

---

## 5. 电池与充电

- PM8150B 充电 + 电量计
- 电池: GYBM 4780mAh / NVTBM4N 4780mAh
- 充电 IC: BQ2597x (主) + SMB1390 (并行)
- 无线充电: IDT P9415 / Nuvolta RX1619
- 快充协议: QC3.0 / PD PPS / 33W
- 电量计: PM8150B GEN4 FG (5-pin battery)

---

## 6. 无线

| 组件 | 芯片 | 说明 |
|------|------|------|
| WiFi | WIL6210 (QCA6390) | 802.11ax |
| 蓝牙 | QCA6390 | BT 5.x |
| NFC | NQ-NCI @ I2C 0x28 | GPIO 111(irq), 83(ven) |

---

## 7. 音频

- 扬声器: CS35L41 × 2 (I2C 0x40, 0x42)
- 音频编解码: kona-mtp-snd-card (WCD938x)
- GPIO: 112, 113, 114

---

## 8. 马达

- AW8697 线性马达 @ I2C 0x5A
- GPIO: reset=130, irq=129

---

## 9. 传感器

- 指纹: Goodix (屏下光学) + FPC1020 (备选)
- 指纹 GPIO: reset=24, irq=23, pwr=10
- 霍尔传感器: GPIO 14

---

## 10. 保留内存 (关键！)

| 区域 | 地址 | 大小 | 说明 |
|------|------|------|------|
| xbl_aop_mem | 0x80600000 | 0x260000 (2.375MB) | XBL/AOP |
| disp_rdump | 0xb0400000 | 0x01000000 (16MB) | 显示 ramdump, no-map |

---

## 11. 散热 (ADC 通道)

| 传感器 | PMIC | ADC 通道 |
|--------|------|---------|
| xo_therm | pm8150 | ADC_XO_THERM_PU2 |
| skin_therm | pm8150 | ADC_AMUX_THM1_PU2 |
| pa_therm1 | pm8150 | ADC_AMUX_THM2_PU2 |
| wireless_therm | pm8150b | ADC_AMUX_THM1_PU2 |
| conn_therm | pm8150b | ADC_AMUX_THM3_PU2 |
| camera_flash_therm | pm8150l | ADC_AMUX_THM1_PU2 |
| skin_msm_therm | pm8150l | ADC_AMUX_THM2_PU2 |
| pa_therm2 | pm8150l | ADC_AMUX_THM3_PU2 |
