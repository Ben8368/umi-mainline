# 黑屏原因全面排查（保险清单）

> **📌 有第二版了**：[RISK-AUDIT-2.md](RISK-AUDIT-2.md)。
> 那一版换了个方法（沿启动链逐段查，带内核源码出处），又找到 4 个真 bug，
> 并且对本文里几条结论做了修正/加强。**冲突时以后者为准。**
> 已知需要修正的地方（本文保留原样作为记录）：
> - §3 表里「改用 `CONFIG_FB_SIMPLE`」一节已过时 —— 现在走的是 `DRM_SIMPLEDRM`
>   （只有 DRM 驱动能挂 `drm_panic`）。`FB_SIMPLE` 与 `DRM_SIMPLEDRM` 在 Kconfig 里互斥。
> - §4 里「`DRM_MSM` 未编」当时是**错的**：因为配置片段的写法问题，它实际是 `=m`。
>   详见 RISK-AUDIT-2.md 的 B1。
> - §1 表 H2 对看门狗的推理是正确的，但缺了关键一环：`watchdog_need_worker()` 的条件
>   决定了「只要没人打开 `/dev/watchdog`，内核就会**永久**喂狗」。见 RISK-AUDIT-2.md §2 第 10 条。

> 你暂时没法上机，那这段时间最值钱的事就是把「黑屏几秒回 fastboot」的**所有**可能原因列全，
> 每条都给出：机理 / 证据 / 已做的保险 / 实机怎么区分。
> 这样等你真上手时，一次测试就能拿到最多信息，而不是反复瞎试。

---

## 0. 先修正上一版里的一个判断（重要）

上一版 DIAGNOSIS.md 里我写了：

> 「黑屏几秒回 fastboot」= 内核没执行到，问题在 ABL 层

**这句话不完全对**，还有第三种可能被我漏了：

> **内核执行了，但早期就挂/卡住了，然后被 ABL 留下的 APSS 看门狗复位** → 也是黑屏几秒回 fastboot。

机理：

1. 高通 ABL 在跳到内核之前会把 **APSS watchdog** 打开（这是高通 boot 流程的一部分）。
2. 主线 arm64 defconfig 里 **`CONFIG_QCOM_WDT=m`**（模块！），而我们的 initramfs 里**没有模块**，
   所以整个开机过程**没有任何人喂狗**。
3. 内核只要在「驱动 probe 阶段」卡住或跑得比看门狗超时慢 → 硬件复位 → 回到 fastboot。

这和「ABL 拒绝镜像」在观感上**完全无法区分**（都是黑几秒 → fastboot）。

**已做的保险**：`CONFIG_QCOM_WDT=y`（编进内核）。
配合内核默认的 `CONFIG_WATCHDOG_HANDLE_BOOT_ENABLED=y`，内核会**接手继续喂狗**，
于是「卡死」就真的表现为「卡死（黑屏不重启）」，而不再伪装成复位。

> 这条保险是「便宜保险」：如果原因就是它，那就修好了；如果不是，它也没有任何副作用。

---

## 1. 原因清单（按可能性排序）

| # | 假设 | 机理 | 证据 / 现状 | 已做的保险 | 实机怎么区分 |
|---|---|---|---|---|---|
| **H1** | ABL 挑不到 DTB | v2 头 `dtb_size=0`，主线 arm64 不支持 appended DTB | 你 12 个镜像全是 0；设备自己的 DTB 里 board-id=43 | 新打包器把 DTB 放进 dtb 段，board-id=43 | 看 `bootimg.py info` 输出；失败就换 `multiid` DTB |
| **H2** | **看门狗复位** | ABL 开了狗，`QCOM_WDT=m` 没人喂 | defconfig 里是 `=m`；Android 靠 ramdisk 里的模块喂 | **`CONFIG_QCOM_WDT=y`**（已加） | **掐秒表**：<5s 回 fastboot = ABL 层；>8s = 内核层 |
| **H3** | **ABL 跳转前把屏幕关了** | 面板 DSI 被关掉，写 0x9c000000 也没人扫出去 | 现象是「黑屏」而不是「定格在开机 logo」 | 无解（需要面板驱动）→ 靠 USB/pstore 通道 | **裸机 fbtest**：红绿闪 = 屏还活着；不闪 = 屏被关了 |
| **H4** | 内核在 console 起来之前就挂了 | `console=tty0` 要等 simpledrm 在 `device_initcall` 才绑定 | 内核机制如此（见第 2 节） | **umi-beacon**（极早期刷屏信标）+ pstore | 信标版镜像看屏幕颜色 |
| **H5** | 帧缓冲参数不对 | 地址/stride/format 错 → 花屏或全黑 | 地址 0x9c000000 与下游 DTB 的 cont_splash 一致；stride 按 1080*4 | 和 elish（已知能跑）完全一致的写法 | 花屏/斜切 → 换 stride（4352/4096） |
| **H6** | initramfs 解压失败 | 区域被 no-map 覆盖 / cpio 格式问题 | 已用 `cpio -H newc`+gzip；内容已验证 | 去掉了 `disp_rdump` 那块 no-map（少一块风险区） | 内核会打 "Initramfs unpacking failed"（有 console 就能看到） |
| **H7** | mdss 抢屏 | 没面板驱动时 DRM_MSM 接管 cont-splash → 全黑 | `CONFIG_DRM_MSM` 没编 | 已避开 | `dmesg \| grep -i msm` 应该什么都没有 |
| **H8** | DTB 内容缺东西 | 缺 psci/timer/gic/cpu 节点 → 起不来 | 全部来自上游 sm8250.dtsi，已核对 status | 关键节点状态已逐条核对（见第 4 节） | 卡在 `setup_arch` 类的位置 |
| **H9** | **ABL 把下游 DTBO overlay 打到我们的 DTB 上** | 设备 bootargs 里有 `androidboot.dtbo_idx=8`，ABL 会从 dtbo 分区取 overlay | 下游 overlay 的目标节点在主线上不存在 | 无（不动 dtbo 分区更安全） | 如果 ABL 因此报错，表现同 H1；可试「把 dtbo 分区刷成空/主线的」 |
| **H10** | pm8150a 无主线驱动 | 部分 regulator 拿不到 → 外设 defer | 主线现状 | `regulator-fixed` 顶 + `pd_ignore_unused clk_ignore_unused` | `dmesg` 里一堆 `-EPROBE_DEFER` |
| **H11** | dwc3 永远 defer | `usb-role-switch` 没有 connector | 老 DTS 里有 | 已去掉，改 `dr_mode="peripheral"` | USB 设备永远不出现 |
| **H12** | 内核/ramdisk 放哪儿冲突 | 内核 40 MB，头里 ramdisk_addr=0x1000000 | 设备 DTB 显示 ABL 自己把 initrd 放到 0xafe9f000（高地址），**不听头里的值** | 无风险（头里的值只是参考） | — |
| **H13** | cmdline 参数 | 裸 `earlycon` 无效、`console=ttyMSM0` 没接线 | 老镜像的 cmdline 就是这样 | 内置 cmdline + `CMDLINE_FORCE`，带 `console=tty0` | 屏幕上有没有字 |
| **H14** | KASLR / 地址随机 | 早期崩溃地址不可复现 | — | `CONFIG_RANDOMIZE_BASE=n` | — |

---

## 2. 必须知道的事实：内核有一段「屏幕上必然什么都没有」的窗口

这是无 UART 调试最大的坑，之前没说清楚：

```
start_kernel
   │
   ├── 内存/页表/中断/定时器/时钟/regulator/pinctrl 初始化
   │   ← 这一段如果卡住：屏幕上「必然」什么都没有
   │     （console=tty0 还没绑定，printk 只进 ring buffer，没人显示）
   │
   ├── postcore_initcall   ← umi-beacon 第 1 个信标（蓝）
   ├── arch_initcall       ← 信标（青）
   ├── subsys_initcall     ← 信标（绿）
   ├── fs_initcall         ← 信标（黄）
   ├── device_initcall     ← simpledrm probe → fbcon 绑定 → 屏幕开始出字
   └── late_initcall       ← pstore 后端注册完成（pstore_init 是 late_initcall）
```

三个直接结论：

1. **「屏幕上出现内核 log」这件事本身，就证明内核已经走过了全部核心初始化**。
   反过来说，**黑屏不能说明内核没跑**。
2. `console=tty0` 之前的日志不会丢，但只存在 ring buffer 里 —— 只有 **panic** 才会被
   `kmsg_dump` 整段写进 ramoops（下次开机可读）。**卡死（不是 panic）则什么都留不下。**
3. 所以我们要做两件事：
   - 把「卡死」变成「panic」→ `DETECT_HUNG_TASK` + `SOFTLOCKUP_DETECTOR` + `panic_on_oops`
     （本次已加：卡 D 状态 60s 或死循环不调度 → panic → 整段 log 进 ramoops）
   - 把「panic」变成「下次开机能看到」→ `printk.always_kmsg_dump=1`（连正常重启也 dump）

---

## 3. 本次新增的保险（都在已经重编的镜像里）

| 保险 | 作用 |
|---|---|
| `CONFIG_QCOM_WDT=y` | 接手 ABL 留下的看门狗，卡死不再伪装成复位（H2） |
| `CONFIG_DETECT_HUNG_TASK=y` + `BOOTPARAM_HUNG_TASK_PANIC=y` + 60s | 驱动 probe 卡 D 状态 → panic → 整段 log 进 ramoops |
| `CONFIG_SOFTLOCKUP_DETECTOR=y` + `BOOTPARAM_SOFTLOCKUP_PANIC=y` | probe 里死循环不调度 → 同样 panic |
| cmdline `printk.always_kmsg_dump=1` | 正常重启也 dump 完整 log，下次开机必能读回来 |
| **修掉 ramoops 尺寸 bug**（record 0x1000 + console 0x200000） | 原来 4 MB 区域被 console+pmsg 占满 → **dmesg 记录区为 0**，panic 时整段 log 根本存不进来。详见 [REFERENCE-MT6895.md](REFERENCE-MT6895.md) 2.1 |
| **cmdline 加 `pstore.kmsg_bytes=2097152`** | pstore 每次快照的日志上限默认只有 **10 KB**（那个 Kconfig 带 `if EXPERT`，配置片段里写会被静默打回默认值）。详见 2.1b |
| **`CONFIG_LOG_BUF_SHIFT=21`**（ring buffer 128 KB → 2 MB） | 否则开机 log 一多，panic 时开头早被冲掉了 |
| **改用 `CONFIG_FB_SIMPLE`（关掉 `DRM_SIMPLEDRM`）** | ~~少一层（不经 DRM core/KMS/GEM），出字的失败点更少~~ **已改回 `DRM_SIMPLEDRM`**：只有 KMS 驱动能挂 `drm_panic`（二维码 panic 屏），而且 `FB_SIMPLE` 和 `DRM_SIMPLEDRM` 在 Kconfig 里互斥。见 [RISK-AUDIT-2.md](RISK-AUDIT-2.md) |
| **initramfs 的日志改写 `/dev/kmsg`** | 用户态消息进 ring buffer → 随崩溃日志一起被 ramoops 保存（MT6895 项目的做法） |
| cont-splash 恢复成整块 `0x2300000` | 不再缩小，避免内核把 ABL 还在扫描输出的内存拿去分配（H5） |
| 删掉 `disp_rdump@0xb0400000` 那块 no-map | 少一块「内核不能碰」的内存，降低 initramfs 正好落进去的风险（H6） |
| initramfs 默认开 USB CDC-ACM + 等 UDC 20s | 屏幕靠不住时的实时通道（H3/H4） |
| **initramfs 同时提供 USB U 盘（FAT 镜像）** | PC 上直接出现盘符，里面是 `dmesg.txt`/`pstore.txt`，免终端软件 |
| **`CONFIG_PSTORE_BLK=y`（默认待机）** | panic 时可直接把 log 写进裸分区，跨掉电保存（见 [LOG-EXTRACTION.md](LOG-EXTRACTION.md) 通道⑤） |
| `tools/parse-pstore.py` | 把 ramoops / 裸分区转储里的内核 log 抠出来（支持压缩过的 pstore） |
| `tools/beacon/umi-beacon.c` | 极早期信标：屏幕颜色五档 + **把进度写进保留区，下次开机报「上次走到 stage N」**（H4） |
| `tools/watch-usb.ps1` | PC 侧盯 USB 枚举：**不用看屏幕**就知道内核有没有跑到用户态 |

> 跨项目参考：**[REFERENCE-MT6895.md](REFERENCE-MT6895.md)** 记录了从
> [MT6895-Mainline](https://github.com/MT6895-Mainline/)（另一个已能日常使用的手机主线移植）
> 学到的做法，其中第 2.1 节就是那个 ramoops 尺寸 bug。

---

## 4. 静态核对结果（这些已经排除）

- **DTB 里 ABL 关心的三个属性**：`qcom,msm-id = <356 0x20001>` ✓、`qcom,board-id = <43 0>` ✓
  （与设备自己 DTB 完全一致）、根节点无 `qcom,pmic-id` ✓（设备 DTB 也没有）
- **`simple-framebuffer` 的位置是对的**：内核 `drivers/of/platform.c:577` 专门找
  `/chosen` 下面 compatible 为 `simple-framebuffer` 的子节点。我们和 elish（已知能跑的
  SM8250 移植）写法完全一致 ✓
- **关键节点 status 逐条核对**（只列非 okay 的）：
  `i2c3`（触摸，故意关）、`pcie×3`（WiFi，故意关）、`gpu`、`remoteproc×3`（DSP，故意关）。
  UFS / USB / pon / tlmm / gpi_dma / qupv3 / apps_rsc / smem / watchdog / cpufreq / psci /
  timer / gic / tsens / llcc / smmu **全部 okay** ✓
- **显示链路配置**：`DRM=y` + `DRM_SIMPLEDRM=y` + `DRM_FBDEV_EMULATION=y` +
  `FRAMEBUFFER_CONSOLE=y`，`DRM_MSM` 未编，没有 `FB_SIMPLE` 抢同一个节点 ✓
- **内存节点**：上游写的是 `reg = <0x0 0x80000000 0x0 0x0>`（size=0），注释明说
  「等 bootloader 填」；设备 DTB 里已经被 ABL 填成真实内存表 ✓
- **`minidump.img` 是安卓用户态崩溃 dump（里面全是 logcat/app 堆栈），不是启动日志** —— 没用，别指望它
- **`sleep_clk` 存在**（fixed-clock 32764 Hz），所以 `qcom_wdt` 能 probe ✓

---

## 5. 还没排除的（必须实机或更多资料）

1. **ABL 到底怎么处理 v2 的 dtb 段**（是否还按 board-id 过滤、是否打 DTBO overlay）。
   → 保险：`scripts/multiid-dtb.sh` 生成多 board-id 候选的 DTB 做对照实验。
2. **ABL 跳转前有没有关屏**（H3）。这是唯一能一票否决「屏幕调试」的假设。
   → 判别：裸机 fbtest。不闪就得转向 USB/pstore 路线。
3. **面板驱动**：下游 DTB 里 `qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd`
   （`mi,panel-id = <0x4a32 0x420201>`，cmd mode + DSC，1080×2340）**完整的上电时序、
   TE 配置、HDR 参数都在**，`umi_downstream.dtb` 里有 15 个面板变体 —— 也就是说
   以后写主线面板驱动所需的数据是齐的，不用去猜。这是第 4 阶段的事。
4. **触摸 `st,fts`** 主线无驱动（`stmfts.c` 只匹配 `st,stmfts`），要自己写。
5. **`fastboot flash boot` 的固化流程**（等 `fastboot boot` 验证通过再做）。

---

## 6. 上机时的执行顺序（每一步都能独立得出结论）

| 步骤 | 命令 | 观察 | 结论 |
|---|---|---|---|
| **0** | 电脑上跑 `tools\watch-usb.ps1` | 它会一直盯 USB | 后面每一步都靠它当「不看屏幕的眼睛」 |
| **1** | `fastboot boot out\boot-umi-fbtest.img` | 红绿闪？ | 闪 → 屏还活着（H3 排除）；不闪 → 屏被关/地址不对 |
| **2** | 掐秒表 `fastboot boot out\boot-umi-p1.img` | 几秒回到 fastboot？ | <5s → ABL 层（换 multiid DTB 再试）；>8s → 内核层（走第 3 步） |
| **3** | 同上，盯着 watch-usb 输出 | 出现 `1D6B:0104`？ | 出现 → **内核跑到用户态了**，只是屏幕没显示 |
| **4** | 再 boot 一次 | 屏幕上出现 pstore 内容？ | 有 → 上一次的 log 捞到了，直接看崩在哪 |
| **5** | `add-beacon.sh` 编信标内核 → `boot-umi-beacon.img` | 屏幕什么颜色？ | 蓝/青/绿/黄 = 卡在对应阶段之后；黑 = 还没到 postcore 或屏被关 |

> **关键**：步骤 1 和 3 是**完全不依赖屏幕**的判据。
> 只要 USB 能枚举出来，就说明内核 + initramfs + 用户态全通了，
> 剩下的是「怎么把 log 弄出来看」的问题，而不是「内核为什么起不来」的问题。
