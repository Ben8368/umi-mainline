# Adreno 650 (GPU) on Xiaomi Mi 10 / umi — 已可初始化

状态（2026-10，6.12.94-umi-dirty）：

```
/sys/kernel/debug/dri/1/gpu:
    gpu-initialized: 1
    revision: 650 (6.5.0.2)
/sys/class/devfreq/3d00000.gpu/cur_freq        = 305000000   (空闲)
/sys/class/devfreq/3d00000.gpu/available_frequencies
    = 305 400 441.6 490 525 587 MHz
/dev/dri/card1, /dev/dri/renderD128            = 都在
```

开机日志：

```
adreno 3d00000.gpu: Adding to iommu group 7
platform 3d6a000.gmu: Adding to iommu group 10
msm_dpu ae01000.display-controller: [drm:adreno_request_fw] loaded qcom/a650_sqe.fw  from new location
msm_dpu ae01000.display-controller: [drm:adreno_request_fw] loaded qcom/a650_gmu.bin from new location
```

没有 `GPU_SET Timeout`，没有 `zap` 报错。

## 1. DT：打开 gmu / gpu

主线的 `sm8250.dtsi` 里 GPU 节点是全的（opp-table、`qcom,gmu`、
`nvmem-cells = <&gpu_speed_bin>`、`iommus = <&adreno_smmu>`、`zap-shader`
带 `memory-region = <&gpu_mem>`），只是 `status = "disabled"`。

`dts/sm8250-xiaomi-umi.dts` 里加：

```dts
&gmu {
    status = "okay";
};

&gpu {
    status = "okay";

    zap-shader {
        firmware-name = "qcom/a650_zap.mdt";
    };
};
```

`gpucc`（`clock-controller@3d90000`）和 `adreno_smmu` 本来就没有 `status`
属性，默认就是开的；`gpu_mem` 保留区在 `sm8250.dtsi` 里也有。

`zap-shader/firmware-name` 在 6.12 里其实**没人读**（zap 的固件名来自
`a6xx_catalog.c` 的 `.zapfw`），留着是给更新内核的兼容位。

## 2. 固件

需要的文件（都来自本机 MIUI 的 `/vendor/firmware`，或从 linux-firmware 取）：

| 文件 | 来源 | 说明 |
|---|---|---|
| `a650_zap.mdt` + `a650_zap.b00/.b01/.b02` | MIUI vendor | zap shader，分段格式 |
| `a650_sqe.fw` | **linux-firmware**（新版） | MIUI 那份是 v93，内核要求 ≥ v95 |
| `a650_gmu.bin` | MIUI vendor / linux-firmware | 两边同尺寸（41548 B） |
| `a650_zap.mbn` | linux-firmware | 单文件版 zap，备用 |

`qcom_mdt_load()` 的取名规则是**把固件名最后 3 个字符换成 `bXX`**
（`drivers/soc/qcom/mdt_loader.c:83`），所以分段文件名必须和 `.mdt`
同前缀：

```
qcom/a650_zap.mdt
qcom/a650_zap.b00
qcom/a650_zap.b01
qcom/a650_zap.b02
```

### 2.1 版本坑

MIUI 自带的 `a650_sqe.fw` 在 6.12 上会被拒：

```
adreno 3d00000.gpu: [drm:a6xx_ucode_load] *ERROR* a650 SQE ucode is too old.
    Have version 93 need at least 95
```

换成 linux-firmware 里的（31964 B）即可：

```
https://gitlab.com/kernel-firmware/linux-firmware/-/raw/main/qcom/a650_sqe.fw
```

（`git.kernel.org` 的 `/plain/` 直链会返回 150 字节的错误页，别用。）

## 3. 关键：固件必须放进 initramfs

adreno 是**内建**驱动，probe 发生在 initramfs 阶段，那时 rootfs 还没挂上，
`request_firmware()` 只看得到 initramfs 里的 `/lib/firmware`。放在 rootfs 的
`/lib/firmware` 里只会得到：

```
Direct firmware load for qcom/a650_sqe.fw failed with error -2
[drm:adreno_request_fw] *ERROR* failed to load a650_sqe.fw
```

表现就是：`/dev/dri/*` 和 `3d00000.gpu` 的 devfreq 节点都在（msm 已经
bind），但 `cur_freq = 0`、`gpu-initialized` 不存在 —— GPU 停在未初始化状态。

所以 `scripts/mkinitramfs.sh` 现在会从仓库的 `firmware/qcom/` 把
`a650_*` 拷进 initramfs 的 `/lib/firmware/qcom/`（并且再平铺一份到
`/lib/firmware/`，因为 `adreno_request_fw()` 两种路径都会试）。

树外要复现的话，把上面四个文件放进 rootfs 的 `/lib/firmware/qcom/` **并且**
确保它们出现在 initramfs 里即可。

## 4. 自检

```sh
dmesg | grep -i -e adreno -e a650
cat /sys/kernel/debug/dri/*/gpu | head -4      # gpu-initialized: 1 / revision: 650
cat /sys/class/devfreq/3d00000.gpu/cur_freq    # 空闲 305 MHz
cat /sys/class/devfreq/3d00000.gpu/available_frequencies   # .. 587 MHz
```

## 5. 还没有的

- **没有 GPU cooling device**：devfreq 不会因为过热降频，满载请自己盯温度。
  上游 `sm8250.dtsi` 里 `gpu` 有 `#cooling-cells`，但没接 thermal zone。
- 用户态还没装：测 `glxinfo -B` 需要 mesa/freedreno，`vulkaninfo` 需要
  turnip。内核侧已经就绪（`renderD128` 可用）。
- 超频档（670/800/900 MHz）没开：`gpu_opp_table` 里 670 MHz 需要
  `opp-supported-hw = <0xa>`，取决 `gpu_speed_bin` 熔丝；默认 587 MHz 是
  原厂最稳档。
- GMU 的 `rscc`/`gmu_pdc` 走的是 `sm8250.dtsi` 里的地址，未做额外校验。
