# 2026-10-30 硬件盘点与开源外设补齐

## 范围与环境

用户要求盘点未工作硬件、缺失驱动，优先开源并尝试补齐。本轮基于 11ebe89，在独立工作分支 codex/umi-hardware-enablement 实施；未提交、推送、合并或操作手机。此前 PR 的授权不自动扩大到本轮分支。

宿主 Windows x64、PowerShell 7.6.5；目标构建在 umi WSL 的 ext4。固定 Linux 6.18.59 / 1253a6aa5d104312bf0992afacc15220ae35bdf9，GCC aarch64-none-elf 16.1.0、Rust 1.82.0、bindgen 0.72.1。复用既有 out-source-parity 的对象作为增量缓存到独立 out-hardware；build.sh 重新生成配置、删除目标 Image.gz/三个 DTB，并执行完整 Image.gz dtbs modules 目标，不声称从空目录重建或可重复构建。

## 审计与实施

- [硬件矩阵](../../HARDWARE_SUPPORT.md) 分开记录驱动存在、DT 接线、固件/标定和实机证据。更正原 HARDWARE 中 QCA6390/WIL6210 混写、TE/BLE 混写及 Android 4.19 被写为当前内核的问题。
- 默认 Wi-Fi DTB 缺蓝牙子节点，原产物 BT_LE/UHID 关闭。核对小米 kernel_devicetree 固定提交 2aa073826fa357cc672c1e0f590d9dbe904203b0 的 umi include 链、SE6 地址、GPIO16–19 和 BT_EN GPIO21，再接入上游 qcom,qca6390-bt 与共享 WCN pwrseq。serial0 保留 uart12，serial1 分配 uart6；不增加电压或猜测固件文件名。
- base/plus DTB 原来已有蓝牙节点但 uart6=okay 与 GPIO 保留范围冲突，而且 PMU 缺 BT_EN；将 uart6 改回 disabled。plus 的 ADSP/CDSP/SLPI/Venus 虽有 okay 节点，仍只是旧实验配置，不视作硬件支持证据。
- 显式配置 BLE、BR/EDR、HCI UART/serdev/QCA、RFCOMM、BNEP、HIDP、UHID；构建检查拒绝缺失依赖。CS35L41 I²C、SPI/RC/LIRC 红外使用上游模块，暂不增加未经证实的硬件节点。
- 新增测试执行实际构建门禁，将每个要求的符号分别移除，确认失败；同时接受合法 built-in/module 组合，防止编译成功但功能被 Kconfig 丢弃。
- 未新增二进制固件或旧 Android 驱动。BusyBox 复用上一轮从固定 GPL 源码构建的静态产物，binary SHA256 7bf93037f081293c91c628c112ea221d04a4f6fe79932823e5116c5eb2111466，经来源 JSON 重新核对；本轮没有重新编译 BusyBox。

## 🚦 Audit Report

总体：可审查的开源接入与模块补齐；离线验证不等于设备可用。

🔴 阻断：本轮所有 L3 真机测试 not-run。蓝牙固件/NVM、共存、GPIO/UART 实际 probe；音频/红外板级数据；其他传感器/相机/modem 固件与接线及充电保护均不能由编译推定通过。不具备合并/整机验收结论。

🟡 跟进：RISK-006 和 TD-006 记录扩展外设条件；已有 RISK-001/002/004/005 继续开放。未改充电值或开发 root/SSH/USB 策略，原作者版权/固件保持不变。

## 验证

最终 36 项离线回归全部通过（exit 0，含新增配置缺项测试）；最终内核/DTB/模块构建、initramfs、boot v2 打包及独立产物核验均 exit 0。171 个实际构建输入与 Windows 工作区逐字节一致。

```sh
cd /root/umi-hardware-work
python3 -m unittest discover -s tests -p 'test_*.py' -v
TREE=/root/linux-6.18.59 OUT=/root/linux-6.18.59/out-hardware JOBS=12 TC=gcc sh scripts/build.sh
BUILD=/tmp/umi-hardware-initramfs sh scripts/mkinitramfs.sh --root none
python3 tools/pack-umi.py --dtb out/sm8250-xiaomi-umi-wifi.dtb -o out/boot-umi-hardware.img
```

源树保留既有 FTS 宏重定义及 DTC 警告，不宣称零警告。6.12/7.2 完整矩阵、DT schema 全量验证、远端 CI/CodeRabbit 和本轮手机启动/配对/声音/红外测试均 not-run。固件分发条件仍由 RISK-004 限制。

后续应先在明确设备授权和回退方案下验证新镜像基础功能与蓝牙；匹配模块/固件必须单独安装到经过确认的 rootfs，救援镜像不含 BlueZ 和无线模块。音频/红外继续收集板级信息；马达、modem、传感器和相机分开推进，禁止同时打开所有节点。

## 最终核验结果

- scripts/governance-docs-check.py、tests/governance-docs.py、scripts/git-hooks-test.py、tests/ci-policy.py（6 项）、tests/bot-dispatch.py（22 项）、scripts/check-tree.py 和 git diff --check 均 exit 0；文本门禁 0 errors。
- 完整构建导出 1372 模块（原产物 1363）；独立检查 Bluetooth/HCI UART/btqca、RFCOMM/BNEP/HIDP/UHID、CS35L41 三个模块、ir-spi/SPI GENI、原有 ath11k/MHI/QRTR/RTC 等存在。模块包无链接，depmod 文本/二进制索引及源 modules.order 对应；内核/配置/模块包哈希与 manifest 相符。
- 独立解析三个 DTB：Wi-Fi 的 uart6=okay，六个 BT supply 指向 PMU 子节点，BT_EN=GPIO21、GPIO16–21 未保留、qup6 pinctrl 正确；serial0 仍 uart12。base/plus 的 uart6=disabled。每个 DTB 保留八个 disabled SPMI 别名，BQ25970 在 base/plus 缺省不存在，在 Wi-Fi 禁用。
- 第一次独立核验拒绝 base DTB：发现它和 plus 一样存在被保留引脚上的 uart6=okay。补修 base 后重新执行完整构建、打包和核验，最终全部 exit 0；没有放宽核验条件。
- boot v2 独立解析后的 kernel/DTB/ramdisk 与输入完全一致；ARM64 magic、init 源码、已核验来源 BusyBox 与 root-dev=none 均正确。救援包没有无线模块和 BlueZ，不能靠临时启动此镜像完成蓝牙配对。
- 产物存于本地 out/hardware-audit/，Git 忽略；delivery-verification.json、build-inputs.json、verify-delivery.py 和本地短/长日志用于追溯，不提交二进制或原始长日志。kernelrelease 仍为 6.18.59-umi-dirty，和旧产物名称相同，安装时必须按本次哈希成套使用，不能混用旧模块。

| 最终产物 | 字节数 | SHA256 |
| --- | ---: | --- |
| `Image.gz` | 16,276,975 | `3416a988cc95dd66f09da85957d50855550e4fd3dbd02abe3965a4fbda97d8a2` |
| `sm8250-xiaomi-umi.dtb` | 192,691 | `2226ac89cdd3bfb15dec253620d1decb60159ae2ec93fbc96745c9aadcadae6f` |
| `sm8250-xiaomi-umi-plus.dtb` | 188,729 | `8a4b17bf93f68475cb91e0486c50074deb3f7e2f530b44a174150ca6343ad0ca` |
| `sm8250-xiaomi-umi-wifi.dtb` | 195,463 | `289b64f5f6bcbf79477b19409c7ca90cc9214ec57705a1c451d36ea3dfe41183` |
| `initramfs.cpio.gz` | 1,290,092 | `dc206e3f9f25f0ec19adb8adde2b83630da863a8ef0fba3a79cddcd8eb03fda2` |
| `boot-umi-hardware.img` | 17,768,448 | `7a7a48f2339d18d83029d9874465befcf5167496d6ad168e1f1496125ea17438` |
| `modules-6.18.59-umi-dirty.tar.gz` | 18,443,038 | `340b29dc95e9832260870db4102266e62a3e29355b5120034668a28c6ac60eac` |
