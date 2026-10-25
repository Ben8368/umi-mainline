## 这个 PR 做什么

给 umi 补一份主线风格的 DRM 面板驱动，替换目前的 `simple-framebuffer`
（你仓库里 `&mdss` / `&mdss_dsi0` / `&mdss_dsi0_phy` 那段一直是注释掉的）。

| 文件 | 内容 |
|---|---|
| `rootfs-build/patch/kernel/archive/sm8250-6.18/0001-drm-panel-xiaomi-umi.patch` | 内核补丁：新增 `drivers/gpu/drm/panel/panel-xiaomi-umi.c`（931 行，compatible `xiaomi,umi-panel`）+ Kconfig/Makefile。**基于 v6.18 的 `drivers/gpu/drm/panel/` 生成**，可以直接 `git am` |
| `rootfs-build/patch/kernel/archive/sm8250-6.18/dt/xiaomi-umi-panels.dtsi` | 本机这块 **CSOT（华星光电）** 面板 `j2_mp_42_02_0b` 的时序与 652 字节 DCS on/off 序列（从原厂 DTB 生成）。换面板 = 用生成器重新导出这一份 |
| `rootfs-build/patch/kernel/archive/sm8250-6.18/dt/sm8250-xiaomi-umi-common.dtsi` | 打开 `&mdss` / `&mdss_dsi0` / `&mdss_dsi0_phy`，接上面板节点 |
| `docs/05-面板驱动.md` | 内核选项、换面板、已知问题 |

## 实测

设备：小米 10（umi / SM8250 / **CSOT（华星光电）** `j2_mp_42_02_0b` 面板），主线 **6.12.94**。

- 1080×2340 命令模式 + **DSC 1.1**（652 字节 on 序列），fbcon 正常
- 背光 `bl_ctrl_dcs`：`/sys/class/backlight/umi-panel`，亮度 1..2047
- 息屏再亮正常
- **偶发开机黑屏有救援开关**：`echo 1 > …/ae94000.dsi.0/repower` 重发 on
  序列（59 包/652 字节），不用重启 —— 这条对 DSC cmd mode 挺有用
- 数据驱动：驱动只认 `xiaomi,umi-panel`，时序/DCS 序列/panel-id 全在 DT 里，
  所以一个驱动能覆盖 umi 出厂的全部面板变体（华星 42 / 三星 38 / …）；
  本 PR 里的 dtsi 是**本机这块 CSOT `j2_mp_42_02_0b`** 那一份

日志与踩坑记录：<https://github.com/colorgarden/umi-mainline>（`docs/DISPLAY.md`）

## 注意

- 需要 `CONFIG_DRM_MSM=y` + `CONFIG_DRM_PANEL_XIAOMI_UMI=y`；注意
  `QCOM_OCMEM=m` 之类的依赖会把 `DRM_MSM` 悄悄降级成 `=m`。
- 驱动在 6.12 上验证过；6.18 的 panel API 没有大改，但建议先
  `make drivers/gpu/drm/panel/` 编一遍，编不过我来改。
- 触摸不在本 PR 范围内（ST FTS 另有一条线，缺的是 PM8150B GPIO5 的 boost
  电源，见 umi-mainline `docs/TOUCH.md` §12）。

## 顺便说一句谢谢

**谢谢你们的 GPU 部分。** 我这边 Adreno 650 能起来，基本是照你们的
`dtb/slim-ovf-wifi6-gpu-oc-final.dts` 和 `umi-gpu-maxfreq` 做的：

- DT 里 `&gmu` / `&gpu` `status = "okay"`（主线 `sm8250.dtsi` 里节点本来就全，
  `zap-shader` 带 `memory-region = <&gpu_mem>`）
- `a650_zap.mdt/.b00-.b02` + `a650_sqe.fw` + `a650_gmu.bin` 要打进
  **initramfs** —— adreno 是内建驱动，probe 发生在 rootfs 挂载之前，只放
  `/lib/firmware` 会 `-2`（`Direct firmware load for qcom/a650_sqe.fw failed`）
- 唯一的坑：MIUI 自带的 `a650_sqe.fw` 是 **v93**，6.12 要求 ≥ **v95**
  （`a650 SQE ucode is too old. Have version 93 need at least 95`），换
  linux-firmware 里的新版就好了

现在 `gpu-initialized: 1`、`revision: 650 (6.5.0.2)`、devfreq 305–587 MHz，
`fastfetch` 里也能看到 `Adreno 650 (msm/freedreno) · 305 MHz · max 587 MHz`。

> 小提示（如果以后要显示 GPU）：fastfetch 在 Linux 上是靠
> `/sys/class/drm/card*/device/{vendor,device}` 的 PCI ID 认显卡的，SM8250 的
> Adreno 是 platform device，没有 PCI ID，所以默认的 `gpu` 模块永远是空的。
> 用 `command` 模块读 devfreq 就行，脚本我放在
> <https://github.com/colorgarden/umi-mainline> 的 `contrib/fastfetch/`。
