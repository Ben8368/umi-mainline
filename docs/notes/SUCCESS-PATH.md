# 如果内核正常加载了，会发生什么（成功路径全流程）

> 先纠正一个容易混的概念：**「内核起来了」和「屏幕亮了」是两件事**。
> 我们的 initramfs 跑在内存里，**不依赖 UFS、不依赖面板驱动**，
> 所以「内核正常加载」的门槛其实不高 —— 但它意味着最难的那一段（盲调启动链）已经过了。
>
> 本文对应的是**当前这批产物**（`Image.gz` 14.83 MB、`initramfs.cpio.gz` 663 KB、
> `boot-umi-p1.img` 15.6 MB，配置见 `out/config-effective`），
> 审计结论见 [RISK-AUDIT-2.md](RISK-AUDIT-2.md)。

---

## 0. 先分清四个「成功」，每一个都独立成立

| 级别 | 判据 | 说明 | 失败时说明什么 |
|---|---|---|---|
| **S0** | `fbtest` 屏幕**红绿闪** | ABL 接受了镜像格式、跳到了 kernel 入口、cont-splash 地址和格式都对 | 不闪 = ABL 没跳（镜像/ABL 层）或屏被关了 |
| **S1** | `p1` 镜像**超过 5 秒**才回 fastboot（`<5s` 就是 ABL 层） | 内核至少开始执行了 | 秒回 = ABL 没跳 |
| **S2** | PC 上出现 USB 设备 **`1D6B:0104`** | **最硬的判据，完全不看屏幕**。出现 = 内核 + initramfs + 用户态全通 | 不出现但屏幕有字 = dwc3/PHY 的问题 |
| **S3** | 屏幕上出现 `==== [9] initramfs finished ====` | 全流程走完 | — |

**S2 和 S3 只要拿到一个，「能不能启动」这一关就过了。**
S2 出现而 S3 没出现，说明屏幕那条路（simpledrm / ABL 关屏）有问题，但内核是好的。

> 顺带一个免费结论：arm64 的 `setup_machine_fdt()` 遇到坏 DTB 是
> `while (true) cpu_relax()`（**卡死，不重启**），而 `CONFIG_PANIC_TIMEOUT=0` 又让 panic 不自动重启。
> 所以「黑屏几秒**回 fastboot**」这个行为本身，几乎排除了「内核拿到坏 DTB」和「内核 panic」
> —— 它只可能是 **ABL 没跳转**或者**硬件复位**。

---

## 1. 时间线（真实范围，别拿秒表对死数）

| 时刻 | 发生什么 | 屏幕 | PC |
|---|---|---|---|
| 0s | `fastboot boot out\boot-umi-p1.img` | ABL 的 logo / 或黑 | `fastboot` 返回 OKAY |
| 0.5–2s | ABL 解析 v2 头 → 读出 `dtb_size=121365` → 解压 14.8 MB 的 `Image.gz` → 建 `/chosen/linux,initrd-*` → 跳 kernel 入口 | 同上 | — |
| 1–3s | 内核早期：页表、memblock、CPU、GIC、定时器、earlycon（**这段屏幕上必然什么都没有**，正常） | 黑 | — |
| 3–8s | `device_initcall`：simpledrm 接管 `0x9c000000` 的 cont-splash → fbcon 绑定 → **屏幕上第一次出字** | 满屏 log 开始滚 | — |
| 8–30s | 驱动一个个 probe（pinctrl / rpmh / regulator / ufshc / dwc3 / tsens / i2c…），`loglevel=8` 所以 DEBUG 也打 | 一直在滚 | — |
| 30–40s | 内核 initcall 跑完 → 解压 initramfs → `Run /init as init process` | 出现 `UMI-INIT:` 前缀 | — |
| 40–50s | init 收集信息、读 pstore、把**全量 dmesg 重打到屏幕上** | 一大段滚动（**很慢，正常**） | — |
| 45–65s | 配 USB gadget（等 dwc3，最多等 20s） | `==== [7] USB gadget ...` | **设备出现**：串口 + U 盘盘符 |
| ~65s | `==== [9] initramfs finished ====` | 仍是滚动/静止 | U 盘里 5 个 txt |
| 再 +60s | `==== [8]` 自测：屏幕上**一个字都不再打** | **整屏变成二维码**，然后完全静止 | — |

> **别把「刷得慢」当成卡死。** framebuffer console 每滚一行要重画整屏
> （1080×2340×4 ≈ 10 MB），全量 dmesg 有上千行 → 光刷屏就要几十秒。
> **屏幕还在滚 = 还在跑。** 判断卡死的正确方法看 §6。

---

## 2. 屏幕上具体会看到什么

设备侧文字**全部是英文 ASCII**（VGA 字体没有中文字形，中文会变成方块；
`scripts/mkinitramfs.sh` 会在打包前强制检查）。

关键节点长这样（中间省略了大量驱动 probe 行）：

```
[    0.000000] Booting Linux on physical CPU 0x0000000000 [0x411fd0d1]   ← 0x411fd0d1 = Cortex-A77（Kryo 585 超大核）
[    0.000000] Linux version 6.12.94-umi (root@...) (aarch64-none-elf-gcc ...) #1 SMP PREEMPT
[    0.000000] Machine model: Xiaomi Mi 10
[    0.000000] earlycon: qcom_geni0 at MMIO32 0x00000000a90000 (options '115200n8')
[    0.000000] printk: bootconsole [qcom_geni0] enabled
[    0.000000] Memory: ... available
...
[    2.1] simple-framebuffer 9c000000.framebuffer: [drm] Initialized simpledrm 1.0.0
[    2.2] Console: switching to colour frame buffer device 135x146        ← 1080/8 x 2340/16
[    2.3] printk: legacy console [tty0] enabled
...
[   12.3] Run /init as init process
[   12.4] UMI-INIT: ############################################################
[   12.4] UMI-INIT: #  UMI MAINLINE BRING-UP INITRAMFS
[   12.4] UMI-INIT: #  If you can read this, the kernel booted, the console works
[   12.4] UMI-INIT: #  and user space is running.
[   12.4] UMI-INIT: #  The log also goes to: USB serial + txt files on the USB drive
[   12.4] UMI-INIT: ############################################################
[   12.5] UMI-INIT: ==== [1] basic info ====
[   12.5] UMI-INIT: kernel     : Linux version 6.12.94-umi ...
[   12.5] UMI-INIT: cmdline    : console=ttyMSM0,115200n8 console=tty0 loglevel=8 ...
[   12.5] UMI-INIT: DT model   : Xiaomi Mi 10
[   12.5] UMI-INIT: compatible : xiaomi,umi qcom,sm8250
[   12.5] UMI-INIT: fb0 size   : 1080,2340
[   12.6] UMI-INIT: ==== [2] pstore / ramoops: last boot's dying words ====
[   12.6] UMI-INIT:   /sys/fs/pstore is empty (clean shutdown, or ramoops did not register)
[   12.8] UMI-INIT: ==== [3] block devices / partitions ====
[   13.0] UMI-INIT: ==== [4] dmesg (full; same text is on screen) ====     ← 这一大段会滚很久
[   40.0] UMI-INIT: ==== [5] key subsystem state ====
[   40.5] UMI-INIT: ==== [7] USB gadget: CDC-ACM serial + mass storage (logs on a drive) ====
[   41.0] UMI-INIT:    FAT image ready (16 MiB, contains: dmesg.txt info.txt partitions.txt ...)
[   42.1] UMI-INIT:    bound UDC=a600000.usb (waited 1s)
[   42.1] UMI-INIT:    -> PC should now show: a serial port (COMx / ttyACM0) + a USB drive with the logs
[   42.1] UMI-INIT:    shell is running on /dev/ttyGS0
[   42.2] UMI-INIT: ==== [9] initramfs finished ====
[   42.2] UMI-INIT:    kernel is alive and user space is running. Reboot with the power key.
[   42.3] UMI-INIT: ==== [8] panic screen self-test ====
[   42.3] UMI-INIT:    in 60s the screen will switch to the drm_panic QR code.
[   42.3] UMI-INIT:    This looks exactly like a real panic. It is NOT a crash.
[   42.3] UMI-INIT:    Nothing will be printed after that on purpose: any further console
[   42.3] UMI-INIT:    output would make the screen repaint and erase the QR code.
[   42.3] UMI-INIT:    Scan it, then: python tools\\decode-panic-qr.py "<pasted string>"
   （然后 60 秒内屏幕上什么都不会再打印 —— 这是故意的，不是卡死）
[  102.3] （没有任何输出：整屏已经变成二维码，安静才保得住它）
```

**看到 `==== [9] initramfs finished ====` = 完全成功。**

三个小提醒：
- **`[8]` 故意排在 `[9]` 后面**，而且是脚本做的最后一件事。因为 QR 码是直接画进扫描缓冲的，
  之后**任何**console 输出都会让 fbcon 重画屏幕、把 QR 立刻擦掉。
  所以：说明文字全在 `sleep` 之前打完，画成功之后**一个字都不打**，
  只有失败才打错误（那时候也没有 QR 需要保护）。
- `==== [6] ...`（把 log 写进裸分区）只有打包时加 `--dump-partition` 才有，默认没有。
  节号不连续是正常的，别以为漏了一段就是出错。
- `[ 102.3]` 之后屏幕**完全静止**是**成功的标志**。判断卡死请看 §6，不要靠"还在不在滚"。

### 顺手能当场确认「跑的是不是新内核」

```
[   12.5] UMI-INIT: cmdline    : console=ttyMSM0,115200n8 console=tty0 loglevel=8 keep_bootcon earlycon ...
```

因为 `CONFIG_CMDLINE_FORCE=y`，`/proc/cmdline` 里**一定**会显示编译进 Image 的那一整串。
如果看到的是一串 `androidboot.*`，说明跑的是 Android 的下游内核，不是我们的。

---

## 3. PC 上会看到什么

先把「不看屏幕的眼睛」挂上：

```powershell
powershell -ExecutionPolicy Bypass -File tools\watch-usb.ps1
```

```
[  38.4s] *** 检测到 USB gadget 1D6B:0104 —— 内核已经跑到 initramfs/用户态了！ ***
[  38.4s]     USB 串行设备 (COM7)
[  39.1s] 打开串口 COM7 @ 115200（Ctrl+C 退出）
...（控制台内容自动打印并存进 out\usb-console.log）
```

这个 gadget 的身份证是写死的，看到就知道一定是我们的 initramfs：

| 字段 | 值 |
|---|---|
| VID:PID | `1d6b:0104`（Linux Foundation / Multi-purpose gadget） |
| manufacturer | `Xiaomi` |
| product | `Mi 10 bring-up logs` |
| serialnumber | `umi-mainline` |
| 功能 | `acm.usb0`（串口 `/dev/ttyGS0`）+ `mass_storage.usb0`（16 MiB FAT 镜像） |

Windows 资源管理器里会多一个**可移动磁盘**，里面：

```
dmesg.txt        本次开机完整 dmesg
pstore.txt       上一次崩溃的日志（有的话，这是最值钱的一个）
info.txt         内核版本 / cmdline / model / fb 分辨率
partitions.txt   所有块设备 + 分区大小 + by-name（UFS 起来后这里能看到真实分区表）
subsystems.txt   drm / udc / uart / ufs 等关键子系统状态
```

> 如果 Windows 弹"需要格式化"：**别格**。那说明 FAT 镜像没建成功
> （那时 `[7]` 会打 `FAT image failed`）。损坏的是那个 16 MiB 的临时镜像，不是你的盘。
> 这时用串口通道就行，日志一样能拿到。

串口连上以后可以敲：

```sh
dmesg | tail -50
cat /proc/cmdline
ls /dev/block                     # UFS 起来没有，看这里
cat /sys/fs/pstore/*              # 上一次崩在哪
ls /sys/class/drm
cat /sys/class/udc/*
reboot -f                         # 不用长按电源键
```

---

## 4. 这批配置的「副作用」—— 成功了也会看到这些，别当成故障

这一轮为了降低盲调变量，关掉了几组「要探测硬件能力再决定怎么走」的子系统
（理由见 [RISK-AUDIT-2.md](RISK-AUDIT-2.md)）。它们关着会导致**下面这些现象，全部正常**：

| 现象 | 原因 | 想打开时 |
|---|---|---|
| `/sys/devices/system/cpu/cpu0/cpuidle` **不存在** | `CONFIG_ARM_PSCI_CPUIDLE` 关了 | 见 `config/umi-later.config` 组 A |
| `/sys/devices/system/cpu/cpu0/cpufreq` **不存在**，`lscpu` 频率固定 | `ARM_QCOM_CPUFREQ_HW` / `QCOM_CPR` 关了 | 组 C |
| 待机功耗偏高、机身温热 | 同上（CPU 不降频、不进 PSCI power-collapse） | 组 A、C |
| `dmesg` 里没有 `arm-smmu ... context fault` | SMMU 允许 bypass（这是故意的，先别收紧） | 组 B |
| 没有 `msm` / `dpu` / `dsi` / `adreno` 任何字样 | `CONFIG_DRM_MSM` 真关掉了（屏幕走 simpledrm） | 第二阶段，需要面板驱动 |
| 没有 `adsp` / `cdsp` / `mpss` remoteproc | 那些节点本来就 `disabled` | 第二阶段，需要固件 |
| 一堆 `-EPROBE_DEFER` | pm8150a 没有主线驱动，regulator 永远等不到 | 正常，只要关键外设最终 okay |

> **`CONFIG_DRM_MSM` 现在是 `n`**（以前因为配置写法问题一直是 `m`）。
> `out/config-effective` 里可以直接看到 `# CONFIG_DRM_MSM is not set`。

---

## 5. 怎么「离开」成功状态

init 最后是 `while true; do sleep 3600; done`（故意的，这样屏幕上的字不会消失）。三种走法：

1. **长按电源键 ~10 秒** → PON 硬件复位（`POWER_RESET_QCOM_PON=y` 已编）
2. **串口里敲** `reboot -f`
3. `fastboot` 侧：`fastboot reboot`（如果 bootloader 还认命令的话）

> 别直接拔电池——没有的事。也别指望它会自己重启：`CONFIG_PANIC_TIMEOUT=0`。

---

## 6. 「成功了但还有毛病」清单

| 现象 | 含义 | 处理 |
|---|---|---|
| **USB 出现（S2），屏幕全黑** | 内核全通了，只是 ABL 跳转前把屏关了（旧假设 H3） | **不是故障，直接认了** —— 用 USB 干活，屏幕等第二阶段面板驱动 |
| 屏幕出字但**整体斜切 / 条纹** | 帧缓冲 `stride` 不对 | 改 DTS 里 `stride`：`4320`（当前）/ `4352`(1088*4) / `4096` |
| 屏幕出字但只有下半部分 / 花屏 | `width/height/format` 不对 | 改 `simple-framebuffer` 的 `width=1080 height=2340 format="a8r8g8b8"` |
| 屏幕出字但**颜色串了** | 通道顺序不对 | 换 `format`：`a8r8g8b8` → `x8r8g8b8` / `a8b8g8r8` |
| log **停在某一行不动超过 60 秒** | 那个驱动 probe 卡在 D 状态 | 已编 `HUNG_TASK`+`BOOTPARAM_HUNG_TASK_PANIC` → 会自动 panic → 整段 log 进 ramoops。再 boot 一次看 `[2] pstore` |
| log 停在某行但**没有任何 panic** | 可能是 softlockup 没触发 / 卡在中断里 | 再 boot 一次；`printk.always_kmsg_dump=1` 会连正常重启都 dump |
| USB 不出现但屏幕正常（S3 有、S2 无） | dwc3 / hsphy / vbus 没通 | `dmesg \| grep -i -E 'dwc3\|usb_1\|hsphy\|typec'` |
| 开机 30 秒后**自动重启** | 要么真 panic（在看门狗接手之前），要么 ABL 的狗没被接手 | 再 boot 看 `[2] pstore`；如果 pstore 是空的，说明是 ABL 层 |
| `/sys/fs/pstore` **永远是空的** | ramoops 没注册，或者被别的内存覆盖 | `dmesg \| grep -i ramoops`；若 `ramoops: probe failed` 就是 DTS 地址问题 |
| `WARNING: CPU: ... at drivers/...` | 驱动里的小毛病 | **不是启动失败**，bring-up 阶段正常。记下来，不影响 |
| `Call trace:` | 同上 | 同上 |
| `random: crng init done` 出现得晚 | 无所谓 | — |

---

## 7. 成功之后马上要做的事（按性价比排）

### 第 1 件：把「不依赖屏幕的眼睛」固化下来
能枚举 USB、能敲命令，就等于**拿到了一个真正的调试控制台**。从此不用再靠屏幕猜。
先把这一轮的 `out\usb-console.log` 和 U 盘里的 `dmesg.txt` 存档 —— 那是第一份「证明它能跑」的证据。

### 第 2 件：确认 UFS 起没起（下一个真正的坎）

```sh
dmesg | grep -i -E 'ufs|ufshcd|scsi'
ls /dev/block
```

- 出现 `/dev/sda` 之类 → UFS 通了 → 可以开始做 rootfs
- 什么都没有 → UFS 是下一个攻坚点（`1d84000.ufshc` + QMP UFS PHY + L17A/L6A/S4A 那几路 regulator）

### 第 3 件：验证 panic 二维码真的能扫
开机 ~60 秒后屏幕变二维码是**自测不是真崩**（脚本画完就不再打任何字，所以它会一直留在屏上）。
扫一下 → `python tools\decode-panic-qr.py "<粘贴>"`。
能还原出日志 = **以后真崩时，你拍张照就能把现场拿走**，这是这个项目最重要的基础设施。

### 第 4 件：按 `config/umi-later.config` **一组一组**往回打开
A（cpuidle）→ C（CPR/cpufreq）→ B（SMMU 收紧）→ D（显示/GPU/DSP）。
**一次只开一组，开完上机验一次** —— 一起开就等于又回到「黑屏，不知道是谁」。

### 第 5 件：往「能用的手机」推进

| 阶段 | 内容 | 依赖 |
|---|---|---|
| 2 | UFS 挂载 + 真 rootfs（`rootfs/` 里已有素材） | UFS |
| 3 | USB 网卡（RNDIS/CDC-NCM）→ `ssh` 进去 | dwc3 |
| 4 | **面板驱动**：`DRM_MSM` + J2 CSOT 1080×2340 DSC cmd 屏 | 上游 mdss/dsi；面板时序在 `umi_downstream.dtb` 里有 15 个变体可用；注意上游 MIPI DSC 有已知 bug |
| 5 | 触摸（`st,fts` 主线无驱动）、WiFi/BT（qca6390，固件在 `firmware_extracted/`） | — |
| 6 | GPU、音频、摄像头、传感器…… | — |

---

## 8. 一句话

**正常加载之后你会得到**：屏幕上滚一整屏内核 log（如果 ABL 没关屏），
加上电脑上多一个 `1D6B:0104` 的串口和 U 盘，里面是完整的开机日志
—— 从此调试从「盲人摸象」变成「有控制台」。

屏幕亮不亮已经**不重要**了；真正要接着打的是 **UFS → rootfs → 面板**。
