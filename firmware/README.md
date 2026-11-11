# firmware/

从**本机**（小米 10 / umi，MIUI/HyperOS 的原厂分区）取出来的固件，供主线
内核使用。**不是**从别的设备或网上下载后改名的。

| 路径 | 来源 | 用途 |
|---|---|---|
| `qcom/a650_zap.mdt` + `.b00/.b01/.b02` | `/vendor/firmware/`（MIUI） | Adreno 650 的 zap shader（分段格式） |
| `qcom/a650_sqe.fw` | linux-firmware | SQE 微码；MIUI 那份是 v93，6.12 要求 ≥95 |
| `qcom/a650_gmu.bin` | `/vendor/firmware/`（MIUI） | GMU 固件 |
| `qcom/a650_zap.mbn` | linux-firmware | 单文件 zap，备用 |

它们由 `scripts/mkinitramfs.sh` 打进 initramfs —— 因为 adreno 是内建驱动，
probe 时 rootfs 还没挂上，`request_firmware()` 看不到 rootfs 里的文件。
细节见 `docs/GPU.md`。

来源与许可：`a650_zap.*`、`a650_gmu.bin` 来自 Qualcomm/Xiaomi 随设备分发的
固件（与 linux-firmware 中 `qcom/` 的同类文件同一授权体系）；`qcom/a650_sqe.fw`
与 `qcom/a650_zap.mbn` 直接取自 linux-firmware。
