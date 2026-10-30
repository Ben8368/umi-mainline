# firmware/

供主线内核加载的**二进制固件**，历史来源包括本机（小米 10 / umi）原厂分区和 linux-firmware，逐项见下表。它们不是驱动源码，也不因公开下载而成为开源。

| 路径 | 来源 | 用途 |
|---|---|---|
| `qcom/a650_zap.mdt` + `.b00/.b01/.b02` | `/vendor/firmware/`（MIUI） | Adreno 650 的 zap shader（分段格式） |
| `qcom/a650_sqe.fw` | linux-firmware | SQE 微码；MIUI 那份是 v93，6.12 要求 ≥95 |
| `qcom/a650_gmu.bin` | `/vendor/firmware/`（MIUI） | GMU 固件 |
| `qcom/a650_zap.mbn` | linux-firmware | 单文件 zap，备用 |

它们由 `scripts/mkinitramfs.sh` 打进 initramfs —— 因为 adreno 是内建驱动，
probe 时 rootfs 还没挂上，`request_firmware()` 看不到 rootfs 里的文件。
细节见 `docs/GPU.md`。

来源与许可必须分开核实：历史记录中的本机提取没有保存完整原厂版本与逐文件许可；linux-firmware 引入也尚未记录准确提交。不能由“同类固件”推定当前字节的再分发权，更不能将本仓库 GPL/BSD 许可套用到固件。发布前须补齐对应的原始许可文本与版本依据，见 RISK-004。

精确字节数、SHA256 与禁用的触摸固件 C 数组见 [manifest.json](manifest.json)，用 `python3 scripts/check-firmware.py` 校验。驱动与固件的分层清单、替换判断见 [OPEN_SOURCE](../docs/OPEN_SOURCE.md)。本轮不删除来源、不改动固件字节、不启用触摸固件烧写。
