# 小米10 (umi / M2001J2C, SM8250) 主线内核移植失败诊断

> 结论先放前面：**这不是内核代码的问题，是 boot.img 打包格式的问题。**
> 你之前做的 12 个镜像，ABL（高通 bootloader）一个都没法正常接手 —— 头里 `dtb_size=0`，
> 而主线 arm64 内核**根本不支持**把 DTB 追加在 kernel 尾部。ABL 挑不到 DTB，直接把控制权收回 fastboot。

---

## 1. 现象

- `fastboot boot boot-*.img` → 屏幕黑几秒 → 重新回到 fastboot
- 没有 UART，只能靠屏幕/重启行为判断

## 2. 我实际从你工作区里读出来的证据

用新写的 `tools/bootimg.py` 逐个解析了你所有的 boot 镜像，结果**完全一致**：

| 镜像 | header_version | **dtb_size** | **dtb_addr** | **header_size** | id(sha1) | kernel 形态 |
|---|---|---|---|---|---|---|
| boot-umi-mainline.img | 2 | **0** | **0** | **0** | 全 0 | Image.gz-dtb |
| boot-umi-mainline-v2/v3.img | 2 | **0** | **0** | **0** | 全 0 | Image.gz-dtb |
| boot-umi-minimal.img | 2 | **0** | **0** | **0** | 全 0 | Image.gz-dtb |
| boot-elish-test.img | 2 | **0** | **0** | **0** | 全 0 | Image.gz-dtb |
| boot-pmos-umi.img | 2 | **0** | **0** | **0** | 全 0 | Image.gz-dtb |
| boot-pmos-raw-umi.img | 2 | **0** | **0** | **0** | 全 0 | Image（未压缩）+ DTB 追加 |
| boot-debug / boot-dbg2 / boot-video / boot-screen1-3,5 | 2 | **0** | **0** | **0** | 全 0 | Image.gz-dtb |
| boot-final.img | 2 | **0** | **0** | **0** | 全 0 | Image.gz-dtb |
| boot-screen4.img | 2 | **0** | **0** | **0** | 全 0 | **kernel 段里放的是一个 DTB 文件**（126976 B，FDT@0，123926 B） |
| 正确值应该是 | 2 | DTB 大小 | 0x01f00000 | **1660** | 非 0 | Image.gz + dtb 段 |

另外两个实测数据：

- 老 DTB `sm8250-xiaomi-umi.dtb` 的 `qcom,board-id = <0x8 0>`，
  而下游 `downstream-kernel/arch/arm64/boot/dts/vendor/qcom/umi-sm8250-overlay.dts` 写的是 **`<43 0>`**。
  `qcom,msm-id = <356 0x20001>` 是对的（= kona v2.1）。
- `initramfs.cpio.gz` 只有 **1106 字节**，里面的 `/init` 是 `#!/bin/sh` 脚本，
  但 cpio 里**没有 `/bin/sh`、没有 busybox** → 就算内核跑起来，最后也会 `No working init found`。

### 2.1 决定性证据：设备自己的下游 DTB

`<old-dump>\firmware_extracted\umi_downstream.dtb`（947766 字节，从机器上扒下来的）
是**权威参考**，里面写得很清楚：

```
qcom,msm-id   = <0x164 0x20001>      → 356 = SM8250, rev 0x20001 = kona v2.1   ✔ 跟我们一致
qcom,board-id = <0x2b 0x0>           → 43 就是 umi                              ✔ 跟新 DTB 一致，老的 8 是错的
根节点没有 qcom,pmic-id               → ABL 不比对 pmic-id                       ✔ 跟我们一致
chosen/bootargs: androidboot.dtb_idx=0 androidboot.dtbo_idx=8   → ABL 按序号挑 DTB
                 androidboot.verifiedbootstate=orange / vbmeta.device_state=unlocked  → 验证是关的
                 androidboot.cert=M2001J2C / hwversion=2.9.0    → 机器身份确认
                 androidboot.bootdevice=1d84000.ufshc           → UFS 地址，跟主线 ufs_mem_hc 对得上
                 androidboot.usbcontroller=a600000.dwc3         → USB 地址，跟主线 usb_1 对得上
                 msm_drm.dsi_display0=qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd  → 面板型号（J2 CSOT DSC cmd 模式）
chosen/linux,initrd-start = 0xafe9f000            → ramdisk 是 ABL 自己找地方放的（高地址），
chosen/linux,initrd-end   = 0xafffe3b8              不是 boot.img 头里的 ramdisk_addr=0x1000000
                                                     → 所以「内核 40MB 会不会压到 ramdisk」这个担心不存在
reserved-memory:
    cont_splash_region@9c000000  0x9c000000 + 0x2300000   ✔ 跟我们的 simple-framebuffer 地址一致
    disp_rdump_region            0xb0400000 + 0x1000000   ✔ 跟我们 DTS 的 disp-rdump 一致
    没有任何 ramoops 区域         → 下游用的是 mtdoops(block2mtd /dev/block/sda15)
                                   我们新加的 ramoops@0xb0000000 正好落在 disp_rdump 下面那块空内存里
```

所以：**board-id 43 不再是猜测，是设备自己的 DTB 里写着的。**


## 3. 为什么"黑屏几秒回 fastboot"

链路是这样的：

```
fastboot boot boot.img
   ↓
ABL 解析 boot image 头（v2）
   ↓
从 dtb 段（dtb_size/dtb_addr）拿 DTB，按 qcom,msm-id / qcom,board-id 匹配平台
   ↓
匹配成功 → 加载 kernel 到 kernel_addr(0x8000)，x0 = DTB 物理地址，跳过去
匹配失败 → 放弃，回到 fastboot 菜单            ← 你遇到的就是这里
   ↓
Linux head.S → start_kernel → setup_arch → setup_machine_fdt
   ↓
DTB 无效时（arch/arm64/kernel/setup.c:182）：
   pr_crit("Error: invalid device tree blob ... Please check your bootloader.")
   while (true) cpu_relax();        ← 无限空转，不会重启！
```

**关键判据（记住这条，以后很有用）：**

| 屏幕表现 | 含义 |
|---|---|
| 黑几秒 → **回到 fastboot** | 要么 ABL 层拒绝（镜像格式/DTB 不匹配），**要么内核早期挂掉后被 ABL 留下的 APSS 看门狗复位**（见 [RISK-AUDIT.md](RISK-AUDIT.md) H2）——用**秒表**区分：<5s 是前者，>8s 是后者 |
| **一直黑屏、不重启、不回落 fastboot** | 内核跑起来了但卡在某处（DTB 无效空转 / 早期 hang / 或 QCOM_WDT 接手喂狗后的正常卡死表现） |
| 屏幕出字 | 恭喜，进入真正的调试阶段 |

> 补充：arm64 遇到无效 DTB 时是 `while (true) cpu_relax();` **死转不重启**
> （`arch/arm64/kernel/setup.c:182`），所以「一直黑屏不重启」也可能只是「DTB 无效」。
> 完整的原因清单和每条怎么区分，见 **[RISK-AUDIT.md](RISK-AUDIT.md)**。

因为主线 arm64 **没有** `CONFIG_ARM64_APPENDED_DTB`（全树 grep 为空；只有 32 位 arm 有 `ARM_APPENDED_DTB`），
所以 `Image.gz-dtb` 这种下游习惯的打包方式在主线**完全无效** —— DTB 必须放在 boot image 的 dtb 段里。

## 4. 逐条根因与修法

| # | 根因 | 证据 | 修法 |
|---|---|---|---|
| 1 | **DTB 没进 dtb 段**（dtb_size=0），ABL 挑不到 | 12 个镜像全是 0 | `tools/bootimg.py` / `tools/pack-umi.py` 把 DTB 写进 v2 dtb 段，`dtb_addr=0x01f00000` |
| 2 | **`qcom,board-id` 错**（`<8 0>` 应为 `<43 0>`） | 下游 umi overlay = 43 | `dts/sm8250-xiaomi-umi-common.dtsi` 里已改成 `<43 0>` |
| 3 | **`header_size=0`、`id` 全 0** | 实测 | 打包时写 `header_size=1660`、按 AOSP 规则算 sha1 |
| 4 | **没有任何可见输出**：cmdline 只有 `console=ttyMSM0`（没接线） + 裸 `earlycon` | 老 cmdline 实测 | 内置 cmdline 强制加上 `console=tty0 keep_bootcon ignore_loglevel loglevel=8`；`CONFIG_CMDLINE_FORCE=y` |
| 5 | **`earlycon` 静默失效**：没有 `chosen/stdout-path`，裸 `earlycon` 不绑定任何设备 | 老 DTB 无 stdout-path | DTS 里加 `aliases{serial0=&uart12}` + `chosen{stdout-path="serial0:115200n8"}`（uart12 = 0xa90000 = 下游 qupv3_se12_2uart） |
| 6 | **mdss/dsi 是开的但没面板驱动** → KMS 接管 cont-splash 后画不出东西，全黑 | 老 DTB 有 mdss 节点 | 第一阶段 `CONFIG_DRM_MSM` 不编；靠 `simple-framebuffer`@0x9c000000 + `DRM_SIMPLEDRM` + fbcon 出 log |
| 7 | **initramfs 里没有 shell** | 1106 B cpio | `scripts/fetch-busybox.sh` 拉 aarch64 静态 busybox，`scripts/mkinitramfs.sh` 重新打包（662 KB，带 sh/mount/dmesg） |
| 8 | **`usb-role-switch` 没有 connector** → dwc3 永远 EPROBE_DEFER | 老 DTS | 去掉 role-switch，直接 `dr_mode="peripheral"` + `phys=<&usb_1_hsphy>` |
| 9 | **pm8150a 没有主线驱动** → 部分 regulator 拿不到 → 外设 defer/hang | 主线现状 | 用 `regulator-fixed` 顶 `pm8150a_l1` 等；cmdline 加 `pd_ignore_unused clk_ignore_unused` |

## 5. 还没解决 / 仍不确定的

1. **ABL 到底怎么处理 v2 的 dtb 段**：设备自己的 bootargs 里有 `androidboot.dtb_idx=0`，
   说明它是按序号取 dtb 段里的第 0 个 DTB。我们只放一个 DTB，理论上就是它。
   但为了排除"它其实还要按 board-id 过滤"的可能，`scripts/multiid-dtb.sh` 可以生成一个
   `qcom,board-id = <43 0>, <8 0>, <0 0>` 的备用 DTB 用来对照实验。
2. **面板驱动**：`qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd`（J2 CSOT 1080×2340 DSC cmd 模式），
   主线**还没有驱动**。这一阶段靠 cont-splash 打 log，真正点亮屏幕是后面的事。
3. **触摸**：`st,fts` 芯片主线没有驱动（`stmfts.c` 只匹配 `st,stmfts`），要自己写或改。
4. **没有 UART**：所有判断只能靠屏幕 + pstore + USB gadget，调试带宽很低，
   所以 initramfs 里做了 pstore 自动回显（见 RUNBOOK 阶段 2）。
5. **`fastboot boot` 是单次的**：重启就回到原来的系统/原来分区里的 boot，不会破坏设备。
   要固化就得 `fastboot flash boot`（有原厂备份就敢刷）。
6. **帧缓冲 stride**：我们按 `1080*4 = 4320` 填的。如果上机后屏幕出现斜切/错位，
   说明 ABL 实际用的 pitch 是别的值（试试 4352 或 4096），改 DTS 里 `simple-framebuffer` 的 `stride`。

## 6. 这次新做出来的东西

```
tools/bootimg.py          Android boot image v0/v1/v2 解析/解包/打包（带自检）
tools/pack-umi.py         一键打包：强制校验 DTB 的 msm-id/board-id，再打 boot.img
tools/dtb.py              DTB 解析：看 ABL 关心的匹配属性、reserved-memory、chosen
tools/fbtest.py           裸机 aarch64 打屏 payload（红绿闪），验证 ABL 是否接受镜像
tools/watch-usb.ps1       PC 侧盯 USB 枚举：不看屏幕就知道内核有没有跑到用户态
tools/beacon/umi-beacon.c 极早期屏幕信标（黑/蓝/青/绿/黄五档）
tools/dts-check.py        DTS 静态检查（label 引用、括号、delete-node）
dts/sm8250-xiaomi-umi-common.dtsi    bring-up 最小设备树（board-id 43、simpledrm、ramoops）
dts/sm8250-xiaomi-umi.dts            单板 dts（Xiaomi Mi 10）
dts/sm8250-xiaomi-umi-plus.dts       进阶版（wifi/bt/gpu/adsp/touch，暂 disabled）
config/umi.config         内核配置片段（simpledrm + fbcon + 内置 cmdline + 看门狗 + lockup 检测）
initramfs/init            bring-up init：打 banner / 回显 pstore / 全量 dmesg / USB 控制台
scripts/prepare-tree.sh   在 WSL ext4 上重建干净内核树（D:\ 是大小写不敏感的，内核树不能在那儿编译）
scripts/build.sh          一键编译 Image.gz + dtbs（含配置自检）
scripts/fetch-busybox.sh  拉 aarch64 静态 busybox
scripts/mkinitramfs.sh    打 initramfs.cpio.gz
scripts/dtb-only.sh       只编 DTB（改设备树时快速迭代）
scripts/multiid-dtb.sh    备用：生成多 board-id 候选的 DTB（排除 ABL 匹配问题）
scripts/add-beacon.sh     注入并编译「信标内核」
scripts/remove-beacon.sh  撤销信标
RISK-AUDIT.md             黑屏原因全面排查（14 种可能 + 每种怎么区分）
```
