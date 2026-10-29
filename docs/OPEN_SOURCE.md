# 源码、固件与 6.18 迁移清单

本轮选型口径：优先已有可维护、可编译且匹配本机的开放源码；其次是有明确来源的厂商开放源码；硬件必需而尚无经核验源码替代的固件单独标记并保留。公开下载、十六进制 C 数组、GPL 驱动加载的固件，都不能自动算作开放源码。

本表说明代码类别和替换判断，不声明真机验收。当前阶段只见 [CONTEXT](../CONTEXT.md)，迁移取证见[本轮记录](archive/reviews/2026-10-29-source-parity.md)。

## 逐项核查

| 部件 | 实际实现与来源 | 源码 / 二进制边界 | 选择与限制 |
| --- | --- | --- | --- |
| Linux / SM8250 基础驱动 | 固定 `gregkh/linux` v6.18.59，身份见[依赖](dependency-locks.md) | Linux 开放源码；完整树在仓库外 | 保留 6.12/7.2 兼容编译目标，补入 6.18 CI |
| 设备树 | `dts/*.dts` / `*.dtsi`，文件头 BSD-3-Clause | 可编辑 DTS 源码；部分板级数据由本机厂商 DTB 提取 | 继续从源码编译三个 DTB；DTS/面板命令不是可执行固件，不改变来源或冒称原创 |
| DPU / DSI / 面板 | 上游 `drivers/gpu/drm/msm` + `patches/panel-xiaomi-umi.c` | GPL 开放源码，面板命令保留在 DTS | 已用开放栈；不换成 Android 显示二进制 |
| 默认触摸 | `fts521/`，ST 2016–2023 GPL v2 声明，sm7150-mainline 移植；`patches/umi-i2c.c` | 厂商开放源码移植，并非 Linux 6.18 正式上游驱动 | 保留已有触摸证据路径；芯片内部原厂 Flash 固件仍是独立闭源依赖 |
| 备用触摸 | `stfts/`，ST GPL v2 声明，经 Armbian 补丁 0043 引入 | 驱动 C 源码公开；`stfts/fts_fw.h` 是 100476 字节固件的 C 数组，不是固件源码 | 默认不选；`FW_H_FILE` 未启用，数组也不是本机面板映像，不作为缺文件时的替代 |
| 旧触摸实验 | `patches/fts-umi.c` | GPL 源码 | 保留参考与归属，不切换默认驱动、不触发固件重刷 |
| 电量计 / SMB5 / BQ25970 | `power/`，来自 Armbian、Qualcomm、TI/Xiaomi 等，保留逐文件版权 / GPL 声明 | 可编译源码，不是闭源驱动 | 上游 `qcom_smbx.c` 的 PMI8998/PM660 匹配不能直接代替 PM8150B SMB5；BQ25970 仍禁用 |
| Adreno 650 内核驱动 | 上游 DRM/MSM/Adreno | GPL 开放源码 | 保留；SQE、GMU、ZAP 是另一层固件，不能因主机驱动开放而删掉 |
| OpenGL / Vulkan | rootfs 中 Mesa Freedreno / Turnip | MIT 等开放源码；本仓库不打包 Mesa | 继续使用该栈；6.18 的 GPU 初始化证据不能代替实际 GL/Vulkan / Plasma 回归 |
| QCA6390 Wi-Fi 主机驱动 | 上游 ath11k、MHI、QRTR、QMI、PCI pwrctrl、WCN pwrseq | Linux 开放源码，可从固定内核树编译 | 显式配置并编译、导出完整模块集合；不使用 Android 私有 WLAN `.ko` |
| QCA6390 固件 | rootfs 的 `ath11k/QCA6390/hw2.0/` | `amss.bin`、`m3.bin`、板级数据等是独立固件/数据，未纳入本仓库 | linux-firmware 提供二进制不等于固件开源；本轮未找到可重建且经本机验证的等价实现 |
| GPU 固件 | `firmware/qcom/a650_*` | 7 个二进制文件；原厂提取 / linux-firmware 历史来源 | 本轮只锁定现有哈希；未核验到可替换的完整源码与构建流程，不换随机设备的固件 |
| 救援 BusyBox | `scripts/build-busybox.py`，上游 BusyBox 1.37.0 | GPL 源码 → 本地 AArch64 静态程序 | 默认从固定 SHA256 源码构建；显式 `BB=` 才使用预编译程序；编译失败不静默改用下载包 |
| boot 打包工具 | `tools/pack-umi.py` / `bootimg.py` 等 | Python 源码 | 不引入来源不明的预编译打包器 |
| ABL / TrustZone / 设备内部固件 | 设备原有启动链及芯片内部存储 | 适配层之外，未建立开放替代闭包 | 不擦除、不重刷；“开源优先”不等于本机已无闭源组件 |

厂商 FTS 文件同时含 GPL v2 声明和 ST 使用范围/免责声明原文，全部保留；这里记录源码可获得性，不对全部第三方材料作统一再许可或法律认证。

## 6.18 的 Wi-Fi 差距与上游路径

原构建只执行 `Image.gz dtbs`，但 ath11k / MHI / QRTR / PCI pwrctrl 等为 `=m`，仅交付 boot.img 无法给新内核提供这些模块。现在构建目标包含 `modules`，并以真实 `kernelrelease` 导出模块包、文本/二进制 depmod 索引与哈希清单；缺失任一模块或索引则拒绝收集新内核产物。模块包写入普通目录，不挂载或改写 rootfs。

固定 6.18.59 源码中，`drivers/pci/probe.c:pci_scan_device()` 在读 PCI ID 前创建 DT 对应的 pwrctrl 平台设备；`drivers/pci/pwrctrl/pci-pwrctrl-pwrseq.c` 匹配 `pci17cb,1101`，调用 `devm_pwrseq_get(..., "wlan")` 和 `pwrseq_power_on()`，随后交给 pwrctrl 重扫总线。本机 DTS 已有 `vddaon-supply` 等连接，与该路径的入口条件对应。

这是可以优先验证的上游实现，不应直接把旧树的 early-poweron 补丁叠加上去，更不能由源码推断 PERST# / WLAN_EN 的实测时序已经正确。安装匹配模块、核对固件和采集 PCIe/ath11k 日志之后，才可判断是否仍需最小回移。相关风险见 RISK-002。

## 不能盲换的候选

- 上游 `drivers/input/touchscreen/stmfts.c` 也是开放源码，但匹配为 `st,stmfts`；现有 FTS5 驱动还承担本机初始化、补偿和事件格式。没有芯片 ID、协议、恢复与短按对照测试，不仅凭同名 ST FTS 换掉已有实现。
- upstream SMB2/SMBB 与本机 SMB5 不具有可直接互换的芯片契约。已有 `power/` 本来就是源码，换成不匹配的“上游驱动”不会提高开放程度，反而涉及供电风险。
- Mesa Freedreno/Turnip 已满足开放用户态驱动需求，但不能替换设备内运行的 SQE/GMU/ZAP 程序。未找到源码不等于断言世界上不存在，而是本轮没有可审查、可重建、可验证的等价替代证据。

## 小米官方触摸源码候选

2026-10-30 核对 MiCode/Xiaomi_Kernel_OpenSource 的 `umi-q-oss` 来源，固定 commit `db67ca6001320efc1f945c270635434fc403a9d4` 下的 [fts_521/fts.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/db67ca6001320efc1f945c270635434fc403a9d4/drivers/input/touchscreen/fts_521/fts.c) 可读取，229667 字节，SHA256 `b593d0076b675d3e11ed13e1ba360dd99db3ac7e3d537a38883c6b6a85244f73`，保留 ST 及 Xiaomi 版权。可将它作为板级协议和事件处理的比较来源；当前默认 FTS5 也是公开 GPL 源码，不因换成另一份厂商源码便提高开放程度。尚未完成接口差异审查与本机回归，不将旧 Android 驱动直接覆盖到 6.18，也不执行控制器固件更新。

## 来源与可追溯性

- [Linux 固定源码](https://github.com/gregkh/linux/tree/1253a6aa5d104312bf0992afacc15220ae35bdf9)、[PCI pwrctrl](https://github.com/gregkh/linux/blob/1253a6aa5d104312bf0992afacc15220ae35bdf9/drivers/pci/pwrctrl/pci-pwrctrl-pwrseq.c)。
- [FTS5 参考移植](https://github.com/sm7150-mainline/linux/commit/36f473a81f63ecfbe58d5d13f6ed998ce7885c50)、[Armbian 来源](https://github.com/zhaoyuanwang123/armbian)、[原触摸记录](TOUCH.md)、[供电来源](BATTERY.md)。原引入未全部固定提交，不能假称完整供应链已锁定。
- [Mesa Freedreno/Turnip 官方文档](https://docs.mesa3d.org/drivers/freedreno.html)、[linux-firmware 项目](https://gitlab.com/kernel-firmware/linux-firmware)。仅作项目入口，不把现有二进制归属于未经核对的最新提交。
- [BusyBox 官方源码](https://busybox.net/downloads/busybox-1.37.0.tar.bz2)及[官方 SHA256](https://busybox.net/downloads/busybox-1.37.0.tar.bz2.sha256)，固定于 [source-lock.json](../config/source-lock.json)。
- 仓库固件精确字节数与 SHA256 见 [manifest.json](../firmware/manifest.json)，`python3 scripts/check-firmware.py` 核对，initramfs 打包前也强制运行；哈希只能证明身份，不能证明授权或硬件兼容。
