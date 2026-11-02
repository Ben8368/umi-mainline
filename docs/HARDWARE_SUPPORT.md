# umi 硬件支持与缺口

本页区分驱动源码、设备树接线、运行依赖与真机证据。源码审计基于 Linux 6.18.59 的固定提交及本仓库，不把“未获得真机证据”写成“硬件损坏”。当前阶段只见 [CONTEXT](../CONTEXT.md)，逐轮命令与结果见 [2026-10-30 审计](archive/reviews/2026-10-30-hardware-enablement.md)。

默认打包输入是 Wi-Fi DTB。旧 plus 变体是独立实验配置：虽启用 ADSP/CDSP/SLPI/Venus 节点，但固件及保留内存未验收；其 PMU 缺使能 GPIO，不能作为可用无线配置。本文缺口默认针对 Wi-Fi DTB，不把 plus 的 status=okay 当运行证据。

## 支持矩阵

| 硬件 / 能力 | 现有实现及证据边界 | 缺口和开源优先路径 |
| --- | --- | --- |
| CPU、时钟、内存、UFS | 上游 SM8250 驱动；历史可启动及切根 | CPU 动态调频与深度省电保留限制，仍依赖 ignore-unused；不能据启动推断完整功耗管理 |
| 显示、背光、60Hz | DRM/MSM + 本仓库 GPL 面板驱动；上一轮 6.18 有亮屏观察 | 新产物 DPMS、恢复、长稳待测；90Hz 仍未启用，面板变种需独立证据 |
| ST FTS 触摸 | 厂商 GPL 源码移植，上一轮 6.18 有触摸事件 | 短按、首触、多点及恢复待验；Goodix 变种未适配，不以另一型号驱动冒充兼容 |
| Adreno 650、GL/Vulkan | DRM/MSM + Mesa Freedreno/Turnip；上一轮仅 GPU 初始化 | GPU 固件仍必需；本轮 GL/Vulkan 和 Plasma 需匹配 rootfs 实测 |
| QCA6390 Wi-Fi | 上游 ath11k/MHI/QRTR/WCN pwrseq；已有旧版联网记录 | 新内核模块、板级固件、关联与休眠待验；QCA6390 不是 WIL6210 |
| QCA6390 蓝牙 | 上游 hci_qca/btqca/serdev 已存在；Wi-Fi DTB 新增 uart6 连接 | 补齐 BLE、RFCOMM、BNEP、HIDP、UHID；控制器固件、NVM/地址、BlueZ、配对和共存仍未验收 |
| CS35L41 双功放、WCD938x、麦克风 | 上游有 CS35L41、WCD938x、SM8250 ASoC 与 SoundWire；本次补齐 CS35L41 I²C 模块 | 尚无本机声卡/DAI 路由与功放 DT；ADSP 固件、共享 reset、保护/标定和用户态 UCM 缺口。模块存在不等于有声卡 |
| 红外发射 | 厂商为 SE2 SPI；上游有 ir-spi，本次补齐 SPI/RC/LIRC 模块 | 下游 compatible 为 ir-spi，上游为 ir-spi-led；irda_regulator 供电及输出极性未证实，不能盲改 compatible 启用 |
| AW8697 马达 | 小米公开 GPL 实现及 2026-10-13 FF_RUMBLE v3 投稿可作候选，固定树仍只有 AW86927 | v3 探测时自动校准且校准失败继续注册，需要补齐失败退出/保护/生命周期审查和本机标定；不能直接套用其他手机实测 |
| NFC | 厂商 qcom,nq-nci @0x28；上游 nxp-nci 是候选协议栈 | 具体控制器身份、时钟/电源、复位及协议兼容未核实；当前无本机 DT 接入，不能只凭 I²C 地址判断型号 |
| 加速度、陀螺仪、磁力计、光线/接近 | SoC 有 SLPI remoteproc 支持；默认 Wi-Fi DTB 未启用传感器链 | 缺本机传感器型号/配置、SLPI 固件和协议适配。固定内核 IIO 目录未找到 QCOM SNS/SMGR 完整消费路径，不能只开 remoteproc 就声称传感器可用 |
| 蜂窝、短信、通话、GNSS | 厂商 kona-mhi 将 mdm 接到 PCIe2；上游有 PCIe/MHI/WWAN 与 SDX55 候选支持 | 本机 modem 的 PCI ID、ESOC 上电/复位、MHI 通道表、固件、QMI/用户态及通话音频未接通；不能误走 ADSP/SLPI 或把 Wi-Fi 的 MHI 配置当 modem 支持 |
| 前后摄像头、对焦、OIS、闪光灯 | 上游 CAMSS 已匹配 SM8250；厂商 DT 使用通用 qcom,cam-sensor 节点 | 缺实际 sensor 型号/寄存器驱动、CSI endpoint、时钟/供电序列、EEPROM/OIS/调校；CAMSS 不等于完整相机，禁止盲搬其他机型配置 |
| 视频硬解码/编码 | 上游 Venus 有 SM8250 支持和模块 | 默认 Wi-Fi DTB 未启用 video 节点，plus 仅实验启用；固件与 V4L2 用户态验证未补齐；GPU 渲染成功不能证明视频硬解可用 |
| 屏下指纹 | 历史清单记录 Goodix/FPC 候选，尚无本机 Linux 识别证据 | 型号、图像协议、TEE 与用户态匹配缺失；厂商内核 transport 源码不等于可用的开源识别栈 |
| 电源键、音量键、RTC | 已有 gpio-keys、PON 和 PM8xxx RTC 源码/节点 | 本轮按键事件、RTC 走时/唤醒未测；霍尔 GPIO14 在保守变体中仍被保留，暂不接入 |
| USB | DWC3 + HS PHY，现有 USB2 peripheral 调试路径 | OTG/Host、角色切换、USB3 未验收；不扩大当前 root/SSH/USB 权限 |
| PM8150B 电量计、SMB5 / PPS | 本仓库开放源码驱动；已有启动/节点读回 | 本机电池曲线、SOC 精度、实际充电与温控仍缺验收；不修改既有电压/电流参数 |
| BQ25970、并行充电 | BQ25970 源码已有，主动使能封闭；SMB1390 未接入 | 保护、采样电阻、闭环与看门狗未完成，保持禁用，见 RISK-001/005 |
| 无线/反向充电 | 厂商 DT 列 P9415 / RX1619 候选 | 固定主线树无对应精确驱动匹配；需确认实际变种、移植厂商源码并验收保护，不因源码公开便执行控制器固件升级 |
| 板级温度 | 八路 PM8150/B/L ADC5 通道及 IIO→hwmon 已接入，内建到救援内核 | 沿用固定厂商 DTS 的通道/100k 上拉/比率校准/200us 采样稳定时间；读数精度和位置仍需真机对照，不等于温控/充电保护 |
| 休眠、关机、温控策略 | 上游 TSENS 和基础电源管理路径 | 整机保护策略、深睡恢复和软件关机目标异常仍需验证；不把 Android 用户态 trip 值当成主线保护策略 |

## 蓝牙接入契约

只在 sm8250-xiaomi-umi-wifi.dts 中启用 uart6；base/plus 变体不释放 GPIO16–19；旧 base/plus 的 uart6=okay 与保留引脚冲突，已改回 disabled。serial0 继续是调试 uart12，新增 serial1 指向 uart6。Bluetooth 使用上游 qcom,qca6390-bt 及 PMU 子供电节点，复用 WCN pwrseq 的 bluetooth target；不再单独 request GPIO21，不增加或猜测电压参数。

Linux 的 pwrseq_qcom_wcn_match() 会沿 vddaon-supply 的父/祖父节点找到 PMU，不能把它直接指向主板 0.95V regulator。其余五个供电引用按上游 binding 保留。BT、HCI UART、UHID、功放和红外模块由同一 kernelrelease 导出；救援 initramfs 不含这些模块与 BlueZ，救援能启动不能当作蓝牙验收。

固定内核 btqca.c 对 QCA6390 使用 qca/htbtfw%02x.tlv 与 qca/htnv%02x.bin，%02x 来自实际 ROM 版本。先读取控制器请求，再核对 linux-firmware 或本机提取件的身份、来源和板级 NVM；不预先猜固件版本、不复制其他设备的蓝牙地址，也不下载二进制来冒充开源驱动。BlueZ 是首选用户态；BLE HID 需要 UHID。

授权真机测试后，先安装匹配模块/固件，确认 uart6 与 hci0、驱动请求的固件名；再逐项测试 BR/EDR 和 BLE 扫描、配对、HID 事件、断开重连、Wi-Fi 并发与休眠恢复。不要用测试中的主动扫描或配对替代只读盘点。检查 HCI 地址是否有效且唯一，缺失时先核对本机校准来源。

## 板级温度读取契约

三个 DTB 共用 xiaomi-umi-thermistors.dtsi，新增的 board-thermistors 使用上游 iio-hwmon；ADC5、HWMON 和 IIO_HWMON 均内建，救援环境不依赖模块安装或新的固件。固定厂商 umi-sm8250.dtsi 中的 ADC_*_PU2 和主线 ADC5_*_100K_PU 对应同一 0x4c–0x4f 通道编号。每路保留 ratiometric、1:1 预缩放和 200us 硬件稳定时间，值来自同一份本机公开 DTS。

在目标内核驱动正常绑定后，hwmon 名称应为 board_thermistors，temp1..temp8 依次为 xo_therm、skin_therm、pa_therm1、wireless_therm、conn_therm、camera_flash_therm、skin_msm_therm、pa_therm2；单位为毫摄氏度。以 tempN_label 和 IIO label 核对，不能固定 hwmon0 编号。供电位置与实际精度须和 Android 及外部测温对照。

这里只增加测量通路。厂商八个 thermal zone 使用 user_space governor 和 125000m°C passive trip；本项目没有其 Android 策略服务、完整冷却映射或已验收的阈值，因此没有复制该值作为保护。断路/短路/读数异常、热区策略与充电保护仍是 RISK-001/005/006 的验收内容。不会因为出现温度文件而允许主动快充。

## 来源与优先级

- 固定 [Linux 源码](https://github.com/gregkh/linux/tree/1253a6aa5d104312bf0992afacc15220ae35bdf9)：drivers/bluetooth/hci_qca.c、btqca.c、drivers/power/sequencing/pwrseq-qcom-wcn.c、arch/arm64/boot/dts/qcom/sm8250.dtsi 及 sm8250-xiaomi-elish-common.dtsi。相同 SoC 的参考只用于理解 binding，不能替代本机接线。
- 小米 [kernel_devicetree 固定来源](https://github.com/MiCode/kernel_devicetree/tree/2aa073826fa357cc672c1e0f590d9dbe904203b0)：qcom/umi-sm8250.dtsi 包含 xiaomi-sm8250-common.dtsi；后者启用 SE6 UART、定义 BT_EN GPIO21、AW8697、NFC 和 SE2 红外。kona-qupv3.dtsi 给出 SE6 地址 0x998000，kona-pinctrl.dtsi 给出 GPIO16–19；umi-audio-overlay.dtsi、umi-sm8250-camera-sensor-mtp.dtsi 和 kona-mhi.dtsi 分别提供音频、相机与 modem 线索。厂商节点同时列出多个候选不证明全部焊接在本机。
- 小米 [GPL 内核来源](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/db67ca6001320efc1f945c270635434fc403a9d4) 的 drivers/input/misc/aw8697_haptic/ 是马达移植候选，保留原版权；未未经审查移入旧内核 API 或自动校准路径。
- AW8697 [2026-10-13 v3 投稿](https://lkml.iu.edu/hypermail/linux/kernel/2610.1/12414.html)，消息 ID 20261013-mainlining-v3-2-fca981f62b57@proton.me；未声称已合入固定内核。候选及未直接引入原因见 [本次补充审计](archive/reviews/2026-10-30-board-thermistors.md)。
- 优先顺序：已有上游驱动和本机 DT 接线 → 可审查厂商源码移植 → 必要的设备固件。板级校准、固件和闭源用户态分别记录，不能因为主机驱动是 GPL 就称整套硬件无二进制依赖。

后续实施依赖见 [实施计划](implementation-plan.md)；剩余不确定性见 [风险](RISK_REGISTER.md)，有意延后的接入见 [技术债](TECH_DEBT.md)。
