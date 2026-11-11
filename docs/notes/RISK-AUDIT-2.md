# 第二轮黑屏审计 — 把整条启动链重新逐段过一遍

> 这一轮换了个思路：不再猜「哪个假设最可能」，而是**沿着内核真正执行的路径一段段检查**，
> 每一段都去找「能让它在这里静默死掉」的具体条件，并且尽量用**本地源码/二进制**当证据，
> 而不是靠记忆。凡是查不到的，明确写「未验证」，不假装知道。
>
> 上一轮的清单在 [RISK-AUDIT.md](RISK-AUDIT.md)（假设 H1–H14）。本文只写**新的发现**
> 和**新的证据**，H1–H14 里已经排除的不再重复。

---

## 0. 三句话结论

1. **又找到 6 个真 bug**，全都是「编译出来的镜像看着完全正常、上机才发现」的那一类。
   已经全部修掉，并且都加了自动检查，以后不会再悄悄复发。
   其中 **B5 最要命**：第一步用来判断「屏幕还活着吗」的 `fbtest` 镜像，
   原来会被 ABL 当成 32 位内核，**根本跑不起来** —— 它会给出一个假的「屏被关了」。
2. **上一轮的三个致命项方向是对的**，而且这次拿到了 ABL 侧的旁证：
   `dtb_size=0` 时 ABL 返回 `EFI_NOT_FOUND` 然后**掉回 fastboot**，
   正好是「黑屏几秒回 fastboot」的样子。
3. **还剩 1 个从代码上根本排除不掉的未知**：ABL 会不会给我们的 DTB 再叠一层
   DTBO overlay（`androidboot.dtbo_idx=8`）。这条只能靠实机 + 对照实验。

---

## 1. 本轮修掉的真 bug

### B1 ★★★ `CONFIG_DRM_MSM` 一直是 `=m`，从来没被关掉过

**这是本轮最值钱的一条。** `config/umi.config` 里原本写的是：

```
# CONFIG_DRM_MSM is not set      ← 原因见 RUNBOOK「为什么必须关掉 mdss」
```

看起来是「关掉了」，实际上 **`merge_config.sh` 和 `scripts/build.sh` 都不认这种写法**：
`# CONFIG_X is not set` 必须**独占一行、后面一个字符都不能多**。多一个字它就当普通注释
跳过 → 该选项保持 defconfig 的默认值 → arm64 defconfig 里 `CONFIG_DRM_MSM=m`。

于是 `scripts/build.sh` 里那句 `check_n DRM_MSM` 也没救下来，因为它是这样写的：

```sh
if sed -n "s/^CONFIG_$1=\(.*\)\$/\1/p" .config | grep -qx 'y'; then   # 只判 =y
```

`=m` 不是 `=y`，所以检查通过、编译继续、`out/config-effective` 里躺着
`CONFIG_DRM_MSM=m` —— **文档说「mdss 没编」，实际编了（作为模块）**。

| 项目 | 内容 |
|---|---|
| 为什么危险 | 现在它没被加载，所以还没炸。但只要有**任何一次**把模块塞进 initramfs（或者以后换成真 rootfs），mdss 就会在 simpledrm 之后抢走 cont-splash，然后因为还没有 umi 的面板驱动而输出全黑 —— 把好不容易画上去的 log 一起抹掉。这种「配置文档和实际不符」的坑在盲调阶段最致命 |
| 证据 | `out/config-effective` 里 `CONFIG_DRM_MSM=m`；`sm8250.dtsi` 的 `display-subsystem@ae00000` 是 `status = "disabled"`，所以它目前确实不会被 probe —— 也就是说**现在还没炸，纯属侥幸** |
| 修法 | ① 把注释挪到单独一行，`# CONFIG_DRM_MSM is not set` 独占一行；② `build.sh` 的 `check_n` 改成 y/m 都算「开着」；③ `build.sh` 合并片段时对「看着像但其实不合法」的行**直接报错退出**，不再静默；④ 新增 `tools/config-audit.py` |
| 复验 | `python tools/config-audit.py` → 第 [1] 节「片段写法体检」会指出这类行 |

> 顺便说：这个坑还有个更隐蔽的变体 —— `# CONFIG_X is not set␠␠`（行尾多了两个空格）。
> 一样会被静默跳过。`tools/config-audit.py` 会连「片段里写了但 .config 里没生效」一起报出来。

---

### B2 ★★ 页表是 52-bit VA + LPA2 + 5 级页表（arm64 新默认值）

`out/config-effective` 里：

```
CONFIG_PGTABLE_LEVELS=5
CONFIG_ARM64_VA_BITS=52
CONFIG_ARM64_VA_BITS_52=y
CONFIG_ARM64_PA_BITS=52
CONFIG_ARM64_LPA2=y
```

这不是我们写的，是 **arm64 Kconfig 现在的默认值**（`arch/arm64/Kconfig` 里
`prompt "Virtual address space size"` 下面 `default ARM64_VA_BITS_52`）。

| 项目 | 内容 |
|---|---|
| 为什么危险 | 52-bit VA / LPA2 全靠运行时读 `ID_AA64MMFR2_EL1.LVA` 和 `ID_AA64MMFR0_EL1.DS` 再决定要不要回退到 48-bit。Kryo 585（Cortex-A77）**大概率不支持 LPA2**（那是 ARMv8.7 的特性），所以内核会先按 52-bit 建立 early 页表、再在 `__cpu_setup` 里退回去。这条路径本身是主线正常代码，但它意味着**我们多了一个「只有在这颗 SoC 上才会走到」的分支**，而它一旦出错，症状就是「还没到 console 就不动了」—— 恰好是屏幕上必然一片黑的那段 |
| 证据 | `arch/arm64/Kconfig` 的 `default ARM64_VA_BITS_52`；`out/config-effective` 的实测值 |
| 修法 | 固定成最保守的 `CONFIG_ARM64_VA_BITS_48=y`。三层页表、普通 4K 页、不需要任何运行时能力探测 —— 这是十年来所有 arm64 手机 bring-up 都在用的配置 |
| 代价 | 内核虚拟地址空间少一半（48-bit 而不是 52-bit）。对 bring-up 完全无影响（设备只有 6~12 GB 内存） |

> 诚实说明：**这条不是「确定的 bug」**，主线在 52-bit 路径上跑得通的设备很多。
> 它属于「盲调阶段主动减变量」——把一个**无法观测**的失败分支直接去掉，代价是零。

---

### B3 ★ 两个根本不存在的 Kconfig 符号

`umi.config` 里有两行写了但从来没有任何效果：

| 写的 | 实际 | 说明 |
|---|---|---|
| `CONFIG_EARLY_PRINTK=y` | **不存在** | arm64 没有这个符号（只有 hexagon / powerpc 有）。arm64 上决定 earlycon 的是 `SERIAL_EARLYCON` + `SERIAL_QCOM_GENI_CONSOLE` + `OF_EARLYCON_DECLARE(...)`，三者都已经是 y，所以删掉不丢功能 |
| `CONFIG_MODULE_COMPRESS_NONE=y` | **不存在** | 它是 `choice` 里的一个选项，只有在 `CONFIG_MODULE_COMPRESS` 被选中时才会出现。实际 `.config` 里 `# CONFIG_MODULE_COMPRESS is not set` —— 等价于不压缩，也就是我们想要的状态 |

危害不大（没丢功能），但**「配置里写了、实际没生效」这件事本身**在盲调阶段必须清零，
否则以后每一条配置都要怀疑一次。已删掉换成说明性注释。

---

### B4 ★★ initramfs 体积以前没有上限，可能盖掉 ramoops

这是这次顺着「内存落点」查出来的新东西。

ABL 自己算 DTB 和 ramdisk 放哪（见下面 §3-R4），头里的 `ramdisk_addr` 是死的。
这台机器**下游启动时**的实测值是 `linux,initrd-start = 0xafe9f000`，
而我们的 `ramoops` 保留区从 `0xb0000000` 开始 ——

```
0xafe9f000  downstream initrd 落点
0xb0000000  我们的 ramoops 起点
中间只有   0x161000 = 1,449,984 字节 (1.38 MiB)
```

现在 initramfs 是 **663,789 字节（48%）**，安全。但以前没有任何提醒 —— 一旦加了东西
超过 1.38 MiB，且 ABL 把我们这个 ramdisk 摆在同一个位置，就会**直接覆盖 ramoops**，
表现是「pstore 永远是空的」甚至启动就崩。

**修法**：`scripts/mkinitramfs.sh` 现在会算体积，超过 1.1 MiB 警告、超过 1.35 MiB 直接拒绝打包。

> 反过来说，也有反证：elish 和 pipa 用的是**同一个 `ramoops@b0000000`**，
> 而这两个设备跑的是正经发行版（pmOS / 主线 rootfs），initramfs 通常比我们这个
> 只有 busybox + 一个脚本的 663 KB 大一个数量级。如果 ABL 真把 mainline 的 ramdisk
> 摆在 0xafe9f000 一路往上，它们早就把 ramoops 盖掉了。所以**大概率不冲突**，
> 这个上限只是把「万一」变成「编译期就知道」，代价是零。

---

### B5 ★★★ `boot-umi-fbtest.img` 根本引导不了 —— 它会被 ABL 当成 32 位内核

这条是查 B1~B4 的时候顺带掉出来的，但**危害最大**：因为 fbtest 是整个测试矩阵的第一步，
它的结论直接决定「屏幕这条路还要不要继续走」。

`tools/fbtest.py` 原来生成的是一段 84 字节的纯机器码 blob，**没有 arm64 Image 头**。
而 ABL 的 `UpdateKernelModeAndPkg()` 只认三种负载（gzip / `UNCOMPRESSED_IMG`+20 字节头 /
offset 56 处有 `ARM\x64` 魔数）—— 一个光秃秃的 blob 三种都不是，于是：

> ABL 认为这是 **32 位内核** → 走 32 位引导路径 → 跳过去执行一段 arm64 指令 →
> **黑屏几秒回 fastboot**

也就是说，即使屏幕完全正常，这个测试也会给出「不闪 = 屏被关了」的结论。
**它会制造一个假阴性，然后把整个调试方向从屏幕带偏到 USB/pstore。**

| 项目 | 内容 |
|---|---|
| 危害 | 让 H3（ABL 是否关屏）这个唯一能一票否决屏幕路线的实验**得出错误答案** |
| 修法 | `tools/fbtest.py` 现在在代码前面拼一个完整的 64 字节 arm64 Image 头：`code0` = `b +0x40` 跳到真正入口、`text_offset=0`、`image_size`、`flags=0xa`（LE + 4K 页）、offset 56 = `ARM\x64`、`res5=0`。代码本身是位置无关的（只有 movz/movk 和相对分支），放在哪个地址都能跑 |
| 复验 | `python tools\fbtest.py --show` → 打印 `offset 56 = b'ARMd'`（`\x64` 就是 ASCII `d`）和 `image_size=148`；`tools/verify.ps1` 也不再把它报成不合格 |

> 顺手纠正一个我自己差点犯的错：**arm64 Image 的 `ARM\x64` 魔数在 offset 56，不在 offset 0。**
> offset 0 是 `code0`，一条 `b` 指令。检查「这是不是一个合法的裸 arm64 Image」必须看
> `blob[56:60]`。三处工具（`pack-umi.py` / `img-audit.py` / `verify.ps1`）都已改成看 offset 56。

---

### B6 ★ `image_size` 比实际解压长度大 2.7 MB —— 这是正常的，别当 bug 修

`.bss` 是 NOBITS 段，`objcopy -O binary` 不会写进 `Image` 文件，而 arm64 头里的
`image_size = _end - _stext` 是**算上** .bss 的。装载器按 `image_size` 预留内存、
内核自己在 `__primary_switch` 里清 BSS。所以「`image_size` > 文件大小」永远成立
（这次是 50,397,184 vs 47,604,224，差 2.79 MB）。

以前 `img-audit.py` 会把这个报成错误。现在改成只检查 `image_size >= 文件大小`，
并把差值作为「BSS/填充」正常显示出来。

---

下面每一条都是这一轮**重新查过**的，不是从上一轮抄的。

| # | 检查项 | 结论 | 证据（本地可复现） |
|---|---|---|---|
| 1 | arm64 `Image` 头 | ✅ 正常 | `tools/img-audit.py`：`text_offset=0`、`flags=0xa`（LE + **4K 页**）、`magic=0x644d5241`、`image_size=0x3040000` |
| 1b | `image_size` 比实际解压长度大 2.7 MB | ✅ 正常，不是 bug | `.bss` 是 NOBITS，`objcopy -O binary` 不会写进文件，而 `image_size = _end - _stext`。装载器按 `image_size` 预留、内核自己清 BSS。工具里已加说明，避免以后误判 |
| 2 | **ABL 的 32/64 位判别** | ✅ 会走 64 位 | ABL 的 `UpdateKernelModeAndPkg()` 只认三种负载：gzip、`UNCOMPRESSED_IMG`+20 字节头、带 `ARM\x64` 魔数。我们的 `Image.gz` 两者都符合。**这一条以前完全没检查过**，而它是「黑屏回 fastboot」的经典成因。现在 `pack-umi.py` 打包前强制校验 |
| 3 | DTB 的 `msm-id` / `board-id` | ✅ 与设备 1:1 | `tools/dtb.py ids`：设备 DTB = `0x164 0x20001` / `0x2b 0x0`；我们的 = 完全相同；两者都没有 `qcom,pmic-id` |
| 4 | reserved-memory 与设备 DTB | ✅ 现在 1:1 | 逐条比对 `umi_downstream.dtb`。**这轮补上了两个以前漏的**：`res_xbl_uefi_log_region@80880000`(80 KiB) 和 `dfps_data_region@9e300000`(1 MiB)。前者以前是「内核可以随便用」的状态，会把 XBL 的日志写坏 |
| 5 | `disp_rdump@0xb0400000` 故意不保留 | ✅ 故意的 | 我们的 ramoops 是 `0xb0000000..0xb0400000`，正好紧贴在它下面，不重叠。保留它反而是多一块内核不能碰的内存 |
| 6 | `ramoops` 参数 | ✅ 与 `sm8250-xiaomi-pipa.dts` / `sm8250-xiaomi-elish-common.dtsi` **逐字节一致** | 两个都是 `reg = <0x0 0xb0000000 0x0 0x400000>; record-size=0x1000; console-size=0x200000; ecc-size=16; no-map`。上一轮算的 `dump_mem_sz = 4 MB - 2 MB = 2 MB` 是对的 |
| 7 | `/memory` 节点 | ✅ 由 ABL 填 | 我们的 DTB 里是 `memory@80000000 { reg = <0 0x80000000 0 0> }`（size=0），设备 DTB 里已经被填成真实内存表 —— 说明 ABL 确实会改这个节点 |
| 8 | `/chosen/framebuffer` 能不能被创建 | ✅ 能 | `drivers/of/platform.c:577` 专门做 `of_get_compatible_child(of_chosen, "simple-framebuffer")` 然后 `of_platform_device_create()`。而且这个函数是 `arch_initcall_sync`，早于 simpledrm 的 `device_initcall`，顺序也是对的 |
| 9 | earlycon 能不能挂上 | ✅ 能 | `arch/arm64/boot/dts/qcom/sm8250.dtsi:2018` 的 `uart12` 是 `compatible = "qcom,geni-debug-uart"`，正好等于 `drivers/tty/serial/qcom_geni_serial.c:1539` 的 `OF_EARLYCON_DECLARE(qcom_geni, "qcom,geni-debug-uart", ...)`。我们的 `aliases { serial0 = &uart12 }` + `chosen/stdout-path = "serial0:115200n8"` 让裸参数 `earlycon` 能解析到它 |
| 9b | earlycon 的**引脚** | ✅ 与下游一致 | 主线 `qup_uart12_default` 是 `pins = "gpio34", "gpio35"; function = "qup12"`；设备 DTB 的 `qupv3_se12_2uart_active` 也是 `gpio34/gpio35` + `qup12`。（顺便纠正：旧笔记里写的「UART 在 gpio4/5」是错的） |
| 10 | 看门狗会不会被喂 | ✅ 会，而且是永久 | ① `qcom-wdt.c` 的 probe：如果 `WDT_EN` 已经置位，就调 `qcom_wdt_start()` 重设超时**并** `set_bit(WDOG_HW_RUNNING)`；② `watchdog_dev.c` 的 `watchdog_need_worker()` = `(t && !watchdog_active(wdd) && watchdog_hw_running(wdd))` —— 只要没人打开 `/dev/watchdog`，`watchdog_active()` 就一直是 false，worker 就**一直**喂（间隔 = timeout/2）。所以 `CONFIG_QCOM_WDT=y` 这个保险是有效的 |
| 10b | 看门狗节点 | ✅ 会 probe | 最终 DTB 里 `watchdog@17c10000` 没有 `status`（默认 okay），`compatible = "qcom,apss-wdt-sm8250", "qcom,kpss-wdt"`，`clocks = <&sleep_clk>`（`sm8250.dtsi:85` 的 `fixed-clock` 32764 Hz，随时可用，不会 `-EPROBE_DEFER`） |
| 11 | initramfs 结构 | ✅ 合法 | `out/initramfs.cpio.gz` → `newc` cpio，`/init` 权限 755、shebang `#!/bin/busybox sh`；`bin/busybox` 是 **ELF64 ARM aarch64 static-pie**；`bin/sh → /bin/busybox` 存在；`dev/proc/sys/tmp` 都在 |
| 11b | init 脚本需要的 applet | ✅ 都有 | busybox 里确实带 `mkfs.vfat`、`losetup`、`mdev`、`switch_root`（直接 `strings` 验证过），所以 `[7] USB` 那段的 FAT 镜像能建出来 |
| 12 | `CONFIG_BLK_DEV_INITRD` / `RD_GZIP` | ✅ 都 =y | 缺了前者内核会**完全忽略** boot.img 里的 ramdisk；`INITRAMFS_SOURCE=""`（不内嵌），`RD_GZIP=y` |
| 13 | DTB 无效会怎样 | ⚠️ **重要推论** | `arch/arm64/kernel/setup.c` 的 `setup_machine_fdt()`：DTB 无效 → `pr_crit(...)` 然后 `while (true) cpu_relax();`。**是卡死，不是重启。** 再加上 `CONFIG_PANIC_TIMEOUT=0`（panic 也不重启），所以「黑屏几秒**回 fastboot**」这件事，几乎不可能是「内核拿到了坏 DTB」或「内核 panic」—— 只能是 **ABL 根本没跳转**（或硬件复位） |
| 14 | `compatible = "xiaomi,umi"` 主线不认识会不会有问题 | ✅ 不会 | 6.12 的 arm64 **已经完全没有 machine_desc 列表**（`grep -rn DT_MACHINE_START arch/arm64/` = 0 个文件）。`setup_machine_fdt()` 只检查 DTB 本身合法，然后 `of_flat_dt_get_machine_name()` 读 `/model` 打一行日志。所以 `compatible` 里写什么都不影响启动 |
| 15 | DTB 大小 | ✅ 121,365 字节 | ABL 的 `DT_SIZE_2MB` 上限是 2 MiB，余量充足。`pack-umi.py` 现在会校验 |
| 16 | 设备树编译 | ✅ 只有上游噪声警告 | `out/*.dtc.log` 里全部来自 `sm8250.dtsi` / `pm8150*.dtsi`（重复 unit-address 等已知噪声）。`sm8250-xiaomi-umi-plus` 那条 `also defined at ...umi-plus.dts:134` 也属于同一类：dtc 只是在指「这个节点被你 extends 过」，警告本身是上游 `i2c@a8c000` / `spi@a8c000` 撞车 |
| 17 | 内核树与工作区一致 | ✅ 三个 DTS 全部 `SAME` | 避免「改的是 A、编的是 B」 |

---

## 3. 仍然排除不掉的（按危险程度排）

### R1 ★★★ ABL 会不会给我们的 DTB 再叠一层 DTBO overlay

设备的下游 cmdline 里有 `androidboot.dtbo_idx=8 androidboot.dtb_idx=0`。
这说明这台机器**正常工作流是「boot.img 里的 base DTB + dtbo 分区里的 overlay」**。
下游每个 overlay 都是打在 `&mdss_dsi0`、`&dsi_panel` 这类节点的 `__overlay__` 上，
而**我们的 DTB 里根本没有这些节点**（mdss 是 disabled，面板驱动还没写）。

| 问题 | 怎么办 |
|---|---|
| 如果 ABL 在 `fastboot boot` 时也去 apply overlay，而目标节点不存在，它可能报错并**掉回 fastboot** | 这条只能靠对照实验区分，见 §4 的步骤 3 |
| 现有保险 | 无。但**不影响**「先把内核跑起来」这个目标：`fastboot boot` 走的是内存引导，ABL 对它的处理和 `fastboot flash boot` 之后正常启动不一定相同 |
| 判别方法 | ① 先做 §4 步骤 0（用原厂 boot.img 做对照）；② 如果原厂能 `fastboot boot` 起来而我们的不行，嫌疑立刻集中到 DTB/overlay；③ 也可以把 `dtbo` 分区 flash 成空白再试（**危险，先备份**） |

> 这是目前**唯一**从代码上无法排除、又直接对应「黑屏回 fastboot」的假设。

### R2 ★★★ ABL 跳转前把屏幕关掉了（上一轮的 H3，仍未排除）

如果 ABL 在 handoff 前把 DSI 关掉（或者 DPU 停止扫描），那么无论 simpledrm 把字写得多好，
屏幕都是黑的。这条**无法从内核侧修**（要面板驱动），只能靠非屏幕通道。

- 判别：`out/boot-umi-fbtest.img`（裸机红绿闪）。闪 → 屏还活着；不闪 → 屏被关，屏幕调试到此为止。
- 退路：USB gadget（`out/boot-umi-p1.img` 已经内置 CDC-ACM + U 盘模式）。**只要 `watch-usb.ps1` 看到 `1D6B:0104`，就说明内核+initramfs+用户态全通了**，与屏幕无关。

### R3 ★★ earlycon 可能在最早期 abort

`qcom_geni_serial_earlycon_setup()` 是**纯裸寄存器操作**，它不使能任何时钟/电源域，
默认「引导装载机已经把这个串口配好、时钟已经开着」。

- 支持「没问题」的证据：设备的下游 cmdline 就是 `console=ttyMSM0,115200n8`，
  说明 ABL 确实在用这个串口打日志，那它就得把 QUP1_SE4（0xa90000）配置好。
- 支持「可能出问题」的证据：下游的 `msm_geni_serial` 控制台驱动**自己会开时钟**，
  所以「ABL 开过」这件事并不能从下游能跑反推出来。如果时钟没开，读 `geni_se_read_proto()`
  要么返回垃圾（→ 返回 `-ENXIO`，earlycon 静默失效，**安全**），要么总线 abort（→ 极早期挂死，**致命**）。
- 处理：**不做改动**（earlycon 是唯一能覆盖 `start_kernel → console_init` 这段的输出通道，
  成本远大于风险）。但把判别方法写进 §4 步骤 4：实在怀疑时，用
  `scripts/build.sh` 重编一个去掉 `earlycon` 的 Image 做对照 —— 注意因为
  `CONFIG_CMDLINE_FORCE=y`，**改 cmdline 必须重编内核**，不能靠 `fastboot` 传（见 R5）。

### R4 ★★ 头里的 `kernel_addr` / `ramdisk_addr` / `tags_addr` / `dtb_addr` 全是死字段

据 ABL 的 `QcomPkg/Library/BootLib/BootLinux.c`：`BootParamlist` 结构体里**根本没有**
这些字段，地址是 ABL 自己算的（kernel 由 RAM 分区表 / EFI 变量推出，ramdisk 和 DTB
按相对 kernel 末尾的偏移算）。`dtb_size` 倒是**真的生效** —— 所以 v2 头里 `dtb_size`
必须 > 0，等于 0 时 ABL 返回 `EFI_NOT_FOUND` 直接掉回 fastboot。

这对我们意味着三件事：

1. 我们头里写的 `dtb_addr = 0x01f00000` **没有意义**，ABL 会自己放。所以「DTB 会不会
   落进某个 no-map 区」这个担心可以放下 —— 它总是紧跟在 kernel/ramdisk 附近。
2. `ramdisk_addr = 0x01000000` 同样没有意义。**这解释了为什么我们的 initramfs 只有 663 KB
   却仍然要小心**（见 B4）：它可能被摆到 0xafe9f000 这种高地址。
3. v2 头的 `dtb_size` 是**唯一**真正起作用的地址类字段 —— `pack-umi.py` 现在会断言它 > 0。

> 注：这些是研究结论（ABL 源码），我本地没法独立验证。所以 `pack-umi.py` 同时提供
> `--dtb-mode v0-append`（老式的 `Image.gz-dtb`，DTB 拼在 gzip 流后面，`dtb_size=0`），
> 让两条投递路径互为对照组 —— 见 §4 步骤 3。

### R5 ★ `CONFIG_CMDLINE_FORCE=y` 让 cmdline 无法在 `fastboot` 层做 A/B

好处：保证 `console=tty0` 一定在（否则设备上什么都没得看）。
坏处：**任何 cmdline 实验都必须重编内核**，不能像别的项目那样
`fastboot boot --cmdline='...'` 一次一次试。

- 现在的取舍是对的（`console=tty0` 比灵活性重要）。
- 但如果哪天需要用 cmdline 二分（比如 `cpuidle.off=1`、`iommu.passthrough=1`），
  记住改的是 `config/umi.config` 里的 `CONFIG_CMDLINE`，然后重跑 `scripts/build.sh`。
- 别改成 `CMDLINE_EXTEND`：那样 ABL 的 cmdline 会被拼在最前面，里面带着
  `block2mtd.block2mtd=/dev/block/sda15,2097152 mtdoops.mtddev=0 video=vfb:...`
  之类的下游残留，等于又加回一堆变量。

---

## 4. 这次上机按这个顺序做（每一步都能独立得出一个结论）

| 步 | 做什么 | 看到什么 | 说明什么 |
|---|---|---|---|
| **0** | 电脑上先跑 `tools\watch-usb.ps1`；然后 `fastboot boot` **你自己备份的原厂 boot.img** | 能正常启动 Android | **证明 `fastboot boot` 这条路、ABL 的 v2 头解析、你的打包环境全都是通的。** 这一步失败就完全不用往下走 —— 问题不在我们的内核 |
| **1** | `fastboot boot out\boot-umi-fbtest.img` | 屏幕红绿闪 | 闪 → 屏还活着（R2 排除），屏幕调试有意义；不闪 → **ABL 关屏了**，直接跳到步骤 3 靠 USB/pstore |
| **2** | 掐秒表 `fastboot boot out\boot-umi-p1.img` | 几秒回到 fastboot？ | **< 5 s** → ABL 层（R1 或 payload 格式）；**> 8 s** → 内核层（走步骤 3）。注意：因为 `setup_machine_fdt` 失败是**卡死**、panic 也不重启，所以「回 fastboot」本身就指向 ABL 或硬件复位 |
| **3** | 同一步骤 2，盯着 `watch-usb.ps1` | 出现 `1D6B:0104` | **出现 = 内核 + initramfs + 用户态全部跑通**，剩下的只是「屏幕为什么没显示」和「面板驱动」的问题，不是「内核起不来」 |
| **4** | 什么都看不到就再 boot 一次同镜像 | 屏幕上有 `==== [2] pstore` 的内容 | 上一次的完整 dmesg 被 ramoops 存下来了 → 直接看崩在哪一行 |
| **5** | `fastboot boot out\boot-umi-p1-v0-append.img` | 和步骤 2 对比 | 如果 **v0-append 能跑、v2 不能**，就说明 ABL 的 dtb 段解析和我们想的不一样（R4）；反过来说明 v2 没问题 |
| **6** | `scripts\add-beacon.sh` 编信标内核 → `boot-umi-beacon.img` | 屏幕蓝/青/绿/黄 | 颜色 = 已经走过的 initcall 阶段；配合同一镜像下一次启动时的 `UMI-BEACON: previous boot reached stage N` 一起看 |

> 步骤 0 是这轮新加的，也是最便宜的一步。它把「环境/打包/ABL」和「我们的内核」
> 彻底切开 —— 没有它，前面所有实验都可能是在验证一个从一开始就坏的通道。

---

## 5. 本轮工具与脚本变化

| 文件 | 变化 |
|---|---|
| `tools/config-audit.py` | **新增**。四件事：① 片段写法体检（专抓 B1 那类静默失效）② 逐条核对片段是否生效 ③ 「必须项/必须不要项」清单 ④ 依赖传染检查 |
| `tools/img-audit.py` | **新增**。校验 ABL 的 32/64 位判别（gzip 或 offset 56 的 `ARM\x64`）+ arm64 Image 头全部字段，并解释 `image_size > 文件大小` 是正常的 |
| `tools/fbtest.py` | **B5 修复**：payload 改成「64 字节 arm64 Image 头 + 原代码」，头里 `code0 = b +0x40`、offset 56 = `ARM\x64`。以前是一段裸机器码，ABL 会当 32 位内核处理，**这个测试永远给不出正确答案** |
| `tools/verify.ps1` | **新增**。一条命令跑完四项静态自检（配置 / 内核负载 / boot.img 头 / initramfs 体积），退出码 0/1，上机前跑一次 |
| `tools/pack-umi.py` | 打包前**硬校验**三条：payload 必须是 gzip/裸 Image、DTB 必须是 FDT 且 < 2 MiB、`dtb_size > 0`（v2 模式）；新增 `--dtb-mode v0-append`；提示「头里的 cmdline 是装饰性的」 |
| `tools/bootimg.py` | `embedded_dtbs()` 改用 `decompressobj` + `unused_data`。原来用 `gzip.decompress()` 会把 `Image.gz-dtb` 的尾部当第二个 gzip 成员然后报错，看起来像镜像坏了，其实完全正常 |
| `config/umi.config` | 修 B1 / B2 / B3；新增「bring-up 保守值」一节（关 `ARM_PSCI_CPUIDLE` / SMMU 强制 bypass / CPR / cpufreq-hw）。注：`CONFIG_CPU_IDLE` 本身**关不掉**（`drivers/acpi/Kconfig:269` 的 `ACPI_PROCESSOR` 会 `select` 它，而 arm64 defconfig 里 `ACPI=y`）；关掉 `ARM_PSCI_CPUIDLE` 就够了 —— arm64 用 DT 启动时那是唯一会注册的 cpuidle 驱动，没有驱动就退回 `default_idle_call()`（WFI） |
| `config/umi-later.config` | **新增**。能启动之后**一组一组**往回开的清单，每组都写了「打开前先确认什么、打开后如果挂了怎么办」 |
| `scripts/build.sh` | `check_n` 现在 y/m 都算失败（B1 的直接原因之一）；配置合并阶段对非法 `not set` 行**报错退出**；新增 `check_v` 和一批新校验项 |
| `scripts/mkinitramfs.sh` | 新增体积闸门（警告 1.1 MiB / 拒绝 1.35 MiB，理由见 B4） |
| `dts/sm8250-xiaomi-umi-common.dtsi` | 补 `res_xbl_uefi_log@80880000` 和 `dfps-data@9e300000`，让内存图和设备 DTB 完全对齐 |

---

## 6. 复现本轮审计

```powershell
# 配置（片段写法 + 是否生效 + 必须项）——几十秒，不用编译
wsl -d umi -u root -e sh <repo>/scripts/config-only.sh

# 内核负载类型 + arm64 Image 头
python tools\img-audit.py

# 把审计用到的内核源码事实全部 dump 出来（本文每一条带出处的结论都能这样复核）
wsl -d umi -u root -e sh <repo>/scripts/collect-facts.sh

# 重新编译 DTB 并检查内存图
wsl -d umi -u root -e sh <repo>/scripts/dtb-only.sh
python tools\dtb.py check out\sm8250-xiaomi-umi.dtb

# 重新打包两个变体
python tools\pack-umi.py --name p1
python tools\pack-umi.py --dtb-mode v0-append
```

本轮改完之后，一次完整复跑的结果是：

```
scripts/config-only.sh      -> [3] 必须项 72 项全部 OK；[4] 8 项「必须不要有」全部 OK
out/config-effective        -> # CONFIG_DRM_MSM is not set
                               CONFIG_ARM64_VA_BITS=48  CONFIG_ARM64_PA_BITS=48  PGTABLE_LEVELS=4
                               # CONFIG_ARM_PSCI_CPUIDLE is not set
                               # CONFIG_ARM_SMMU_DISABLE_BYPASS_BY_DEFAULT is not set
tools/img-audit.py          -> OK gzip + ARM\x64；text_offset=0；flags=0xa；magic=0x644d5241
tools/verify.ps1            -> 四项全部通过（配置 / 内核负载 / boot.img / initramfs 体积）
```

最终产物：

```
Image.gz                        14,831,127 字节（解压 47,604,224，image_size 0x3010000）
sm8250-xiaomi-umi.dtb              121,365 字节
initramfs.cpio.gz                  663,789 字节（上限 1,382,400，占 48%）
boot-umi-fbtest.img                131,072 字节（裸 arm64 Image 148 字节 + DTB）
boot-umi-p1.img                 15,626,240 字节
boot-umi-p1-v0-append.img       15,626,240 字节
boot-umi-p1m.img                15,626,240 字节
```

---

## 7. 一句话总结优先级

> 如果只做一件事：**先做 §4 步骤 0（`fastboot boot` 原厂 boot.img）**。
> 它花 2 分钟，却能一次性排除掉「环境 / 打包 / ABL 通道」这一整类原因 ——
> 而这轮查下来，这一类恰恰是「黑屏几秒回 fastboot」最像的成因
> （`setup_machine_fdt` 失败是卡死、panic 不重启，都不长这样）。
