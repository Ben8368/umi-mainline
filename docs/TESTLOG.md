# 上机实测记录（第一次真机测试）

> 设备：小米10 `umi`，serianl `<serial>`，Android 13 / HyperOS V816
> 方式：**只用 `fastboot boot`（纯内存引导，不写任何分区）**
> 工具：`tools/fb.ps1`（带超时 + 状态机，见文末）

---

## 0. 三条硬结论（都有对照实验）

### ① `fastboot boot` 能用，但**一个 bootloader 会话只接受一次 `boot`**

| 同一会话内的第几次 | 命令 | 结果 |
|---|---|---|
| 第 1 次 | 任意镜像 | `Booting OKAY` |
| 第 2 次及以后 | 同一个文件 | `FAILED (remote: 'Failed to load/authenticate boot image: Load Error')` |

`reboot-bootloader` 之后就又能 boot 一次。**所有「Load Error」都是这个状态残留，不是镜像问题。**
（我一开始误判成「gzip 内核不行」，就是被这个骗了。）

### ② ABL 接受我们的**内核**，只拒绝我们的**DTB**

| 镜像组成 | 内核 | ramdisk | DTB | 结果 |
|---|---|---|---|---|
| 原厂全套 | 原厂 | 原厂 | 原厂 | ✅ 启动到 Android |
| 原厂去掉尾部补齐 | 原厂 | 原厂 | 原厂 | ✅ 启动 |
| 原厂 FDT#0 改 1 个字节 | 原厂 | 原厂 | 原厂(改) | ✅ 启动 → **ABL 不校验 DTB 字节** |
| dtb 段只放原厂 FDT#0 | 原厂 | 原厂 | 原厂 | ✅ 启动 → **单块 FDT、奇数长度、无 MP_DATA 都可以** |
| **HyA** | **我们的 47.6MB raw Image** | **我们的 663KB** | 原厂 | ✅ **`Booting OKAY` → +5.7s 离开 fastboot → 内核真的在跑**（vendor DTB 导致没有驱动能绑定，所以之后无响应） |
| HyB | 原厂 | 原厂 | **我们的** | ❌ `Booting OKAY` 后一直不回 fastboot（ABL 静默拒绝） |
| HyB2 | 原厂 | 原厂 | **我们的**，board-id 改 0 | ❌ 同上 |
| HyB-P | 原厂 | 原厂 | **我们的 + `__symbols__`** | ❌ 同上 |
| HyB-Q | 原厂 | 原厂 | **我们的 + 原厂 MP_DATA 元数据** | ❌ 同上 |
| HyB-V1 | 原厂 | 原厂 | **我们的 + 64KB 尾部空闲**（给 libfdt 写 bootargs/initrd 留空间） | ❌ 同上 |

→ **内核、ramdisk、镜像格式、dtb 段结构全部无罪。唯一被拒的是我们 DTB 的内容。**

### ③ 被拒的表现是「静默」：`Booting OKAY` 之后什么都不说，直接回到 fastboot UI

所以不能靠 fastboot 的输出判断，只能看**设备有没有离开 fastboot**（`fb.ps1` 就是这么判的）。

---

## 1. 我们的 DTB 和原厂 DTB 的差异（已逐条排除）

| 差异 | 试过 | 结论 |
|---|---|---|
| `qcom,board-id` = 43（原厂 base DTB 是 0） | 改成 0 | 不是原因 |
| 没有 `__symbols__`（原厂 1672 条，我们 0 条） | 用 `dtc -@` 生成 577 条 | 不是**单独**原因 |
| dtb 段没有 MP_DATA / `qcom,rtic-id` 元数据 | 把原厂那块 173 字节追加进去 | 不是原因 |
| `/chosen` 没有 `bootargs`，ABL 要新增属性 | DTB 尾部加 64KB 空闲空间 | 不是原因 |
| 单块 FDT vs 原厂 4 块 | 原厂只放 1 块 | **不是原因** |
| 尺寸非 4 对齐（121365 % 4 = 1） | 原厂 FDT#0 是 540219（%4=3）也正常 | 不是原因 |
| `compatible` = `xiaomi,umi` vs `qcom,kona` | 未单独测 | 可疑度低 |
| **overlay 目标 label 缺失** | 未测（需要 dtbo 分区） | **← 目前唯一还没排除、也最像的** |

**最大嫌疑**：ABL 会从 `dtbo` 分区取 overlay 打到 base DTB 上，overlay 用 `&label` 找目标节点。
原厂 base DTB 有 1672 个 `__symbols__`，overlay 要的 label 全在；我们的 DTB 只有主线的 577 个，
`dsi_panel` / `sde` 之类根本没有 → overlay 打不上 → ABL 中止 → 静默回 fastboot。

---

## 2. 下一步（需要 dtbo 分区）

要从 TWRP 里把 `dtbo` 拉出来（32 MB），看 overlay 到底引用了哪些 label：

```sh
# 手机进 TWRP 后
adb shell ls -l /dev/block/by-name/
adb shell dd if=/dev/block/by-name/dtbo of=/tmp/dtbo.img
adb pull /tmp/dtbo.img dump/dtbo.img
```

拿到后可以：
1. 枚举 overlay 里的 `__fixups__` → 得到 ABL 需要的全部 label 清单
2. 在我们的 DTS 里把这些节点/标签**补成占位节点**（只要 label 存在、结构合法，overlay 就能打）
3. 重新编译 → 打包 → 再测

顺带值得一起拉的（都很小，排查价值高）：
`vbmeta`（128 KB）、`misc`（4 MB）、`logfs`（8 MB，ABL/XBL 的日志）、`devinfo`

---

## 3. 已确认可用的工具

`tools/fb.ps1` —— 带超时的状态机，专治「在 Android 里等 fastboot」这类卡死：

```powershell
powershell -ExecutionPolicy Bypass -File tools\fb.ps1 -Action state
powershell -ExecutionPolicy Bypass -File tools\fb.ps1 -Action tobl
powershell -ExecutionPolicy Bypass -File tools\fb.ps1 -Action boot -Image out\xxx.img -WatchSec 30
```

要点：
- 每个 fastboot/adb 调用都有硬超时，超时就 kill + taskkill /T
- 自动判断设备在 ADB / fastboot / 都不在，决定用 `adb reboot bootloader` 还是 `fastboot reboot-bootloader`
- 退出前 `adb kill-server`：否则 adb 守护进程会继承调用方句柄，让调用方一直等 EOF（**这就是之前反复"命令卡住"的根因**）
- 输出同时写 `out/fb.log`，即使外层超时也能事后看结果

---

## 4. ★ 突破：2026-10-23 晚，内核真的跑起来了，屏幕出现了 panic 二维码

### 根因确认：**ABL 会往 base DTB 上打 dtbo overlay，label 不全就静默拒绝**

从 TWRP 拉出 `dtbo` 分区（32 MB，sha256 `d6a6f4c0…`）后解析：

- `dtbo` 里有 **29 个 overlay**（board-id 全为 0，和原厂 base DTB 的 board-id 一致）
- 每个 overlay 有 90~170 个 fragment，**合计引用 241 个不同的 label**
- ABL 的 `logfs` 里能看到它确实在做这件事：
  `Apply Overlay total time: 448 ms` / `2884 ms`
  同时也确认了 `VB2: Authenticate complete! boot state is: orange`（AVB 放行，不是它的问题）

原厂 base DTB 有 **1672 个 `__symbols__`**，overlay 要的 241 个全在；
我们的主线 DTB 只有 **577 个**，且命名体系完全不同（`uart12` vs `qupv3_se12_2uart`、
`ufs_mem_hc` vs `ufshc_mem`、`usb_1` vs `usb0` …）→ **libfdt 找不到目标 → overlay 整体失败
→ ABL 中止 → 静默退回 fastboot**。

### 修法：给 overlay 要的 label 建空占位节点

`dts/umi-dtbo-stubs.dtsi`（自动生成）给 241 个 label 里缺的 **224 个**各建一个空占位节点，
并把 DTB 用 `dtc -@` 编译（必须，否则没有 `__symbols__`）。
overlay 有了目标就能打上去，而被它写进去的下游属性全部落在占位节点上，
对主线内核毫无影响（没有 compatible，没有驱动会绑定）。

编译后：DTB 185,527 字节，`__symbols__` **802 个**，overlay 需要的 241 个**缺 0 个**。

### 结果

`fastboot boot out/boot-umi-p2-dtbo.img`（我们的 47.6MB raw Image + 664KB initramfs + 修好的 DTB）
→ ABL 跳转 → 内核执行 → simpledrm 接管屏幕 → **内核 panic 并把日志画成了二维码**

这一条同时证明：
- boot.img 打包格式 ✓
- DTB 被 ABL 接受 ✓
- 内核能执行 ✓
- **屏幕可用**（推翻了第一轮审计里最悲观的 H3「ABL 跳转前关屏」）✓
- drm_panic + 二维码生成器（Rust）✓

### 仍然要注意的名字冲突

241 个 label 里有 **17 个**在我们 DTB 里已有真实节点，其中 **4 个是真正的 overlay 目标**
（不是被当 phandle 参数）：

| label | 被几个 fragment 当目标 | 预期影响 |
|---|---|---|
| `mdss_mdp` | 54 | 往 mdss 下加 ~50 个 `qcom,mdss_dsi_*` 面板节点；`mdss` 是 disabled、`DRM_MSM=n`，基本无害 |
| `soc` | 7 | 往 `soc@0` 下加 `mdss@ae00000`、`qcom,dsi-display-primary`、`gpio_keys`… 可能多出一个 gpio-keys 设备 |
| `spmi_bus` | 5 | 多出一套 `qcom,pm8150@0` 等 PMIC 节点，reg 冲突时驱动会优雅失败 |
| `tlmm` | 1 | 加 pinctrl 状态节点，无害 |

其余 13 个（`apps_smmu`/`intc`/`mdss_dsi0/1`/`pcie0..2`/`pdc`/`sdhc_2`/`xbl_aop_mem`/`ts_*`）
只被当 phandle 参数引用，不会改动我们的节点。

### 分析工具

`tools/dtb-analyze.py` —— 正确解析 dtbo 的 `__fixups__`（**注意：fixup 值里存的是
到属性值的偏移量，不是 phandle**，这一点很容易写错，我第一版就写错了，得出「没有 overlay
目标是重名 label」的错误结论）：

```powershell
python tools\dtb-analyze.py dump\dtbo.img --ours dump\dtb-our-sym.dtb
```

用 `dtc -I dtb -O dts dump\ov8.dtbo` 也能直接看到每个 fragment 的目标 label
（`__fixups__` 会被解析成 `/fragment@N:target:0` 这种可读形式）。

---

## 5. ★★ 里程碑：主线内核跑到了用户态（2026-10-23 晚）

解出来的 panic/QE 日志里出现了：

```
[    5.579775] Run /init as init process
[   30.173342] UMI-INIT: ==== [9] initramfs finished ====
[   30.182066] UMI-INIT:    kernel is alive and user space is running.
```

**内核 5.6 秒就把 `/init` 跑起来了，initramfs 全程走完。** 屏幕上的二维码其实是我们
自己 `[8]` 的 panic 屏自测（不是崩溃）。

### 一路上修掉的两个真问题

#### (1) TLMM NORTH tile 读不了 → `synchronous external abort`

现象：`Internal error: synchronous external abort: 96000010`，
调用栈 `msm_gpio_get_direction -> gpiochip_add_data_with_key -> msm_pinctrl_probe`。
寄存器 `x25=0x1c`、`x2=0x1c000` → **pin 28**；而 `pinctrl-sm8250.c:1150` 里
`PINGROUP(28, NORTH, ...)`，NORTH 对应 `reg` 里的 `0xf900000`。

对比原厂 DTB：`pinctrl@f000000 { reg = <0xf000000 0x1000000> }` —— 一整块 16 MB；
主线拆成 west/south/north 三块（0xf100000 / 0xf500000 / 0xf900000），
而 **umi 上 NORTH 那块访问会 abort**（被安全域保护或没上电）。

修法：把 NORTH 的引脚全部写进 `gpio-reserved-ranges`。
关键机制（`drivers/gpio/gpiolib.c`）：
`gpiochip_add_data_with_key()` 里 `gpiochip_init_valid_mask()`（处理 reserved-ranges）
**先于** 那个 `get_direction` 循环，而循环里有 `gpiochip_line_is_valid()` 判断 →
被 reserve 的引脚不会被读。

NORTH 引脚：`4-23, 28-31, 66-68, 77-84, 92-124`
代价：`gpio14`（霍尔键）、`gpio20/21`（WiFi/BT 使能）暂时不可用，已从 DTS 去掉。

#### (2) ★ 我关掉 `CONFIG_ARM_PSCI_CPUIDLE` 把整条电源/时钟链打断了

现象：USB gadget 起不来（`dwc3 is not up`），deferred 列表的根是：

```
platform 18200000.rsc: deferred probe pending:
    wait for supplier /psci/power-domain-cpu-cluster0
```

`apps_rsc` 的 `power-domains = <&CLUSTER_PD>` 指向 `/psci/power-domain-cpu-cluster0`，
而**这个 PSCI 电源域的提供者在 `drivers/cpuidle/cpuidle-psci-domain.c`**，
由 `CONFIG_ARM_PSCI_CPUIDLE_DOMAIN` 门控，后者 `depends on ARM_PSCI_CPUIDLE`。

我在「第二轮审计」里为了减少盲调变量把 `ARM_PSCI_CPUIDLE` 关掉，结果：

```
rsc 拿不到电源域 → rpmhcc / rpmhpd 出不来 → GCC(100000.clock-controller) 没时钟
→ UFS / USB PHY / iommu / interconnect 全部 deferred → dwc3 is not up
```

**教训：`ARM_PSCI_CPUIDLE` 在这颗 SoC 上不是「省电开关」，它是电源域基础设施。**
已改回 `=y`，并在 `config/umi.config` 里写了实测日志作为证据。

### 附带发现

- `pstore: backend (ramoops) writing error (-28)` = **ENOSPC**：
  console-size 2 MB 时 dump 区只有 2 MB = 512 条 4 KB 记录，而
  `pstore.kmsg_bytes=2097152` 正好要 512 条 → 写不下。已改成 console-size 1 MB
  （dump 区 3 MB = 768 条）。
- DTBO 占位节点有副作用：overlay 把 `gpio-regulator` 的 `gpio` 指到 `/dtbo-stubs/stub-118`
  之类的占位节点上 → 这些 regulator 永远 deferred（**无害，只是噪声**）。
- `spmi_pmic_arb: Failed to create device link with f100000.pinctrl`：overlay 的副作用，无害。
- `clk: Not disabling unused clocks` / `PM: genpd: Not disabling unused power domains`
  → `clk_ignore_unused` / `pd_ignore_unused` 正常工作 ✓

### 从扫码到看清根因的工具链

```powershell
python tools\qr-from-photo.py out\shots\panic-qr2.jpg   # OpenCV，V40 常常解不出
# zxing-cpp 更可靠：pip install zxing-cpp  （tools/qr-from-photo.py 的思路 + 缩放就能出）
python tools\decode-panic-qr.py "<那串 https://umi.local/panic?...>"
```

微信/OpenCV 都解不出 V40 时，**zxing-cpp 一次命中**（照片缩放到 2 倍再解）。

---

## 6. ★★★ 完全成功：控制台 + UFS 全通（2026-10-23 19:5x）

修掉 `ARM_PSCI_CPUIDLE` 之后，`fastboot boot out/boot-umi-p6-psci.img` 的结果：

### 已验证可用

| 项目 | 证据 |
|---|---|
| 内核跑进用户态 | `Run /init as init process` → `==== [9] initramfs finished ====`，全程约 5.6 s |
| 屏幕 console | `[drm] Initialized simpledrm 1.0.0 for 9c000000.framebuffer on minor 0`、`Console: switching to colour frame buffer device 135x146` |
| 串口 console | `a90000.serial: ttyMSM0 at MMIO 0xa90000 (irq = 140 ...)`、`printk: legacy console [ttyMSM0] enabled` |
| **USB gadget** | `USB\VID_1D6B&PID_0104\UMI-MAINLINE`；电脑上出现 **COM3**（CDC-ACM）和 **E: 16 MB FAT32**（日志盘） |
| **root shell** | COM3 上直接是 `~ #` |
| **UFS** | `ufshcd-qcom 1d84000.ufshc` → `scsi host0: ufshcd` → 6 个 LUN：**sda/sdb/sdc/sdd/sde/sdf，共 84 个分区**；`sda` ≈ **237 GiB**（整片 UFS） |
| rpmh / 时钟 / regulator | `/sys/class/regulator` **36 个**；`deferred probe` 列表已空（只剩 dtbo 占位节点那几条无害噪声） |
| pstore | `pstore: Registered ramoops as persistent store backend`、`ramoops: using 0x400000@0xb0000000, ecc: 16` |

### 花屏 = 预期现象，不是 bug

没有面板驱动时，ABL 留下的 DSI/DPU 扫描链路没人维护，几十秒后就会失步 → 花屏 + console 停止更新。
**但内核照常跑，USB 照常工作。** 屏幕这条通道到此为止，真正的调试台是 COM3。

### 剩下的都是"功能"，不是"启动"

dmesg 里还剩这些**不致命**的提示，值得记下来：

| 提示 | 含义 |
|---|---|
| `[Firmware Bug]: Kernel image misaligned at boot, please fix your bootloader!` | ABL 把 raw Image 放在非 2 MB 对齐地址（`text_offset=0` 要求 2 MB 对齐）。只警告，能跑。**用 gzip 内核或让 ABL 自己解压就没有这条** |
| `psci: [Firmware Bug]: failed to set PC mode: -3` | 设备的 PSCI 固件不支持 PC mode，无害 |
| `ramoops: uncorrectable error in header` / `error in header, N` | 首次使用时那块内存是脏的，ECC 校验失败；**注册仍然成功**，下一次开机就有内容了 |
| `ufshcd-qcom: freq-table-hz property not specified` | 没配 UFS 变频表，只影响省电/性能 |
| `ufshcd_populate_vreg: Unable to find vdd-hba-supply` | 少一路 regulator 描述，无害 |
| `ufshcd-qcom: Undefined ref clk gating wait time, use default 255us` | 用默认值，无害 |

### 下一步（按性价比）

1. **真 rootfs**：UFS 已经能读，`sda34`（≈226 GiB）是 userdata，可以做成 ext4/f2fs 根分区
2. **USB 网卡**（RNDIS/CDC-NCM，`CONFIG_USB_CONFIGFS_RNDIS` 已开）→ ssh 进去，比串口方便
3. **面板驱动**：这才是屏幕花屏的根治办法（J2 CSOT 1080x2340 DSC cmd 屏，时序数据在 `umi_downstream.dtb` 里）
4. 把 `PSTORE_BLK` 指到 `logfs`/`oops` 分区，彻底摆脱"扫二维码看日志"

---

## 7. ★ 阶段二实测：mdss / DSI ctrl / 7nm PHY 全部起来（2026-10-23 20:4x）

镜像 `out/boot-umi-p7-drm.img`：内核 `6.12.94-umi #3`，`CONFIG_DRM_MSM=y`，
面板节点**没有** include。日志来源：USB 大容量存储盘的 `display.txt` / `dmesg.txt`。

### 结论表

| 组件 | 结果 | 证据 |
|---|---|---|
| mdss `display-subsystem@ae00000` | ✅ probe | `msm-mdss ae00000.display-subsystem: Adding to iommu group 4` |
| mdss 中断控制器 | ✅ 注册 | `/proc/interrupts`: `150: ... msm_mdss 4 Edge dsi_isr` |
| DSI ctrl `dsi@ae94000` | ✅ probe | `msm_dsi ae94000.dsi: supply refgen not found, using dummy regulator` |
| 7nm DSI PHY `phy@ae94400` | ✅ probe + bind | `/sys/bus/platform/drivers/msm_dsi_phy/ae94400.phy` |
| DPU | ❌ 没跑 | 见下面「重要修正」 |
| msm master | ❌ 没 bind | `/sys/bus/platform/drivers/msm` 下只有 bind/uevent/unbind，没有设备 |
| DRM card | ❌ 没出现 | `/sys/class/drm` 只有 simpledrm 的 card0 |
| simpledrm / fb0 | ✅ 没被抢 | `card0-Unknown-1 status=connected modes=1080x2340`，`/dev/fb0 1080,2340` |

### 重要修正：没有面板，DPU 根本不会初始化

`msm_drm_init()`（drivers/gpu/drm/msm/msm_drv.c:265）里的顺序是：

```c
	ret = component_bind_all(dev, ddev);      /* <- dsi_bind 在这里；没 panel 就 -ENODEV 退出 */
	if (ret)
		goto err_deinit_vram;
	if (priv->kms_init) {
		ret = msm_drm_kms_init(dev, drv); /* <- 这里才 mdp5_init -> dpu_kms_init */
```

我原来以为 DPU 会先初始化、再 bind 组件 —— **错了**。`component_bind_all()` 在 DPU
初始化之前，所以「先不接面板跑一次，验证 DPU」这个计划本身不成立：必须把面板节点
接进 DT（哪怕驱动把 prepare/enable 做成空操作），master 才绑得上，DPU 才会走到。

### DSI PLL 在 probe 阶段锁不上（阶段三要盯）

```
[   12.340876] DSI PLL(0) lock failed, status=0x00000000
[   12.344411] PLL(0) lock failed
[   12.354123] WARNING: CPU: 7 PID: 12 at drivers/clk/clk.c:1200 clk_core_disable+0xa4/0xc0
[   12.971382] Call trace:
[   12.989122]  __clk_set_parent_after+0xa8/0x100
[   13.000691]  clk_core_reparent_orphans_nolock+0x7c/0xc4
[   13.013850]  of_clk_add_hw_provider.part.0+0x80/0x11c
[   13.039151]  dsi_phy_driver_probe+0x288/0x394
```

链路：7nm PHY 在 probe 里注册自己的 clk provider，时钟框架顺手把之前挂成 orphan 的
`dsi0_phy_pll_out_dsiclk` 重新挂到新父时钟上（`clk_core_reparent_orphans_nolock`），
这个过程 enable/disable 了一次 → 把 DSI PLL 的 VCO 也拉起来 → 但此时 PHY 的供电和
参考时钟还没配好 → 锁不上（状态寄存器读回 0x00000000）。

- 两行 `ERROR` 来自 `dsi/phy/dsi_phy_7nm.c:354` / `:449` 的 `pr_err`，**不致命**：
  PHY 驱动照样 bind 成功
- 真正的 PLL 锁定在 `dsi_mgr_bridge_power_on()` → `msm_dsi_phy_enable()`，
  阶段三才验得到

### 没有回归

| 项 | 证据 |
|---|---|
| UFS | `ufshcd-qcom 1d84000.ufshc` 已 bind，6 个 LUN |
| USB gadget | `/sys/class/udc: a600000.usb` |
| 串口 | `printk: legacy console [ttyMSM0] enabled`（本次日志就是从 COM3 + U 盘拿的） |
| framebuffer | `/dev/fb0` 1080x2340，屏幕上仍然有 log |
| 全篇扫描 | 没有 `Unable to handle` / `Oops` / `BUG:` / `synchronous external abort`；只有 ramoops 旧脏头噪声 |

→ **`CONFIG_DRM_MSM=y` 这一举是安全的，可以继续。**

### 顺带记一笔

dmesg 里那些 `vreg_xxx: Setting A-BuV` 是 `regulator_sync_state()` 在 late_initcall
把 DT 里**已经写死**的电压约束下发下去（打印的区间就是 DTS 里的 min-max，不是 DRM
临时算出来的），和显示无关。

## 8. 阶段三：把面板节点接进来（`xiaomi,no-init`）

镜像 `out/boot-umi-p8-dsi.img`（DTB 187,597 字节）。相对阶段二只改了两处：

1. `dts/sm8250-xiaomi-umi.dts` 打开 `#include "xiaomi-umi-panels.dtsi"`
2. 生成的 `dts/xiaomi-umi-panels.dtsi` 里面板 `status="okay"` + `xiaomi,no-init`

`xiaomi,no-init` 让驱动的 `prepare/enable/disable/unprepare` 全部直接返回，
DT 里也没有 `reset-gpios` 和任何 `supply-names` —— **一个字节都不会发给面板**。

这一步要回答：

| 问题 | 看什么 |
|---|---|
| DSI 能不能 attach / master 能不能绑 | `card1` 是否出现在 `/sys/class/drm` |
| DPU 能不能初始化 | dmesg 里 `dpu`/`mdp` 相关、`ae01000.display-controller` 是否 bind |
| DSI PLL 真锁得起来吗 | 有没有第二次 `DSI PLL(0) lock failed`（在 bridge power_on 阶段） |
| 时序是否合理 | `mode: 1080x2340@60, 1112x3532 total, ...` 那行 |

---

## 9. ★★★ 画面出来了：面板驱动一次成功（2026-10-24 凌晨）

这是整个项目里最重要的一次启动。**屏幕亮了，而且在正常打印内核日志。**

### 阶段三（`boot-umi-p8-dsi.img`，`xiaomi,no-init`，不往面板发一个字节）

```
[13.98] msm_dpu ae01000.display-controller: bound ae94000.dsi (ops dsi_ops)
[14.10] [drm:dpu_kms_hw_init] dpu hardware revision:0x60000000
[14.16] [drm] Initialized msm 1.12.0 for ae01000.display-controller on minor 1
[14.60] msm_dpu ae01000.display-controller: [drm] fb0: msmdrmfb frame buffer device
```
- `/sys/class/drm/card1-DSI-1/status = connected`，`modes = 1080x2340`
- 中断：`msm_mdss 0 Edge msm` 670 次、`4 Edge dsi_isr` 213 次 → 管道在真跑
- **补正阶段二的结论**：`msm_dpu` 是独立 platform 驱动，阶段二其实已经 probe 过
  （`disp_cc_mdss_mdp_clk` = 300 MHz、`disp_cc_pll1` = 600 MHz 都是 enabled）。
  没起来的只是 **msm 这个 component master**，所以没有 card。

### 阶段四（`boot-umi-p9b-panel.img`，真正发 init 序列）

```
[13.206556] panel-xiaomi-umi: prepare 1080x2340@60Hz (DSC)
[13.206566] 没有 reset-gpios（GPIO12 在 TLMM NORTH tile），跳过复位脉冲
[13.320704] panel-xiaomi-umi: on-sequence: 发了 59 个包 / 652 字节
[13.512013] msm_dpu: [drm] fb0: msmdrmfb frame buffer device
```

- **59 个包 / 652 字节全部发完，零报错**
- DSC 的 `compression_mode` + PPS 排在 init 序列前面，无报错
- 真正的 enable 阶段**没有** `DSI PLL lock failed`（只有 probe 那次无害的）

### 现场实测（用户观测 + 串口取样）

| 项 | 值 |
|---|---|
| 屏幕 | **先花一下（ABL cont-splash → modeset 切换），然后正常打印内核日志** |
| `card1-DSI-1` | `connected` / `enabled` / dpms `On` |
| 中断（启动后约 1 分钟） | `msm_mdss 0 Edge msm` 4947 次、`4 Edge dsi_isr` 1023 次 |
| 错误 | 全篇无 underrun / DSI timeout / ESD / abort |
| 背光 | `brightness=1 → 200`，`max_brightness=2047`，回读一致，无报错 |
| 时序 | `1080x2340@60, 1112x3532 total, 235655 kHz` |

→ **上游 SM8250 那个 MIPI DSC bug 在这条路径上没有触发**；
→ **不需要 reset 脉冲也能正常初始化**（这块屏的 init 序列是幂等的，ABL 已经点过一遍）；
→ **TLMM NORTH tile 的问题这次没有挡住面板**。

## 10. 顺带修掉的一个真问题：面板 VCI 被内核关掉

阶段三的 dmesg 里出现了：

```
[   42.087568] display_panel_vci: disabling
[   42.099126] touch_vddio_vreg: disabling
```

`display_gpio_regulator_vci`（下游 `regulator-fixed`，3.0V，`regulator-boot-on`，
由 ABL 打进来的 dtbo overlay 注入，我们的 DTS 里**没有**这个节点、也没有它的 label）
没有任何消费者，被 `regulator_init_complete()` → `regulator_late_cleanup()` 在 42 秒关掉。
面板 3.0V 没了 → 屏幕会黑。

修法：cmdline 加 `regulator_ignore_unused`（和已有的 `pd_ignore_unused`
`clk_ignore_unused` 是同一类保护）。这是一次内核重编（`CMDLINE_FORCE=y`）。

验证：阶段四的 dmesg 里出现

```
[   10.915733] clk: Not disabling unused clocks
[   10.921311] PM: genpd: Not disabling unused power domains
[   42.086744] regulator: Not disabling unused regulators
```

`disabling` 那两行不再出现，而且这是**唯一**一处会主动改供电行为的改动 ——
它只是"不关"，不是"改值"，所以仍然满足「不许改任何电压」的约束。

## 11. 现在的状态和剩下的事

**已经能用了**：UFS、USB（COM3 + 日志 U 盘）、显示（1080x2340 控制台）。

还没做，按性价比排：

| 事项 | 说明 | 风险 |
|---|---|---|
| 亮度调节范围 | 现在只验证了 1 → 200，实际用到多少要实测 | 无（这是亮度不是电压） |
| TLMM NORTH tile | GPIO12（面板 reset）、GPIO66（TE）、gpio14（霍尔键）、gpio20/21（WiFi/BT 使能）全在 NORTH，读寄存器 abort。**面板不用 reset 也能亮**，但 ESD 恢复、WiFi 都卡在这 | 中（要查清是 XPU 还是没上电） |
| 90 Hz 时序 | 面板节点里有第二个 timing（90 Hz），驱动现在只用 timing@0（60 Hz） | 低 |
| 触摸 | 需要 `goodix` / 对应 IC 驱动 + NORTH 那块电源 | 低 |
| GPU | `msm_dpu: no GPU device was found`，`CONFIG_DRM_MSM` 的 GPU 部分要单独接 | 中 |
| rootfs | UFS `sda34` ≈226 GiB 可以做成根分区 | 低（但**要写分区**，另说） |
| 回退 | 任何时候 `fastboot boot out\boot-umi-p7-drm.img`（阶段二，纯 console 不碰面板） | — |

---

## 12. 收尾：亮度是最后一关（2026-10-24）

### 现象

面板 init 全部成功（59 包零报错）、DPU 以 ~56 fps 出帧（`msm_mdss 0 Edge msm` 4 秒涨 224 次）、
`fb0/name = msmdrmfb`、fbcon 已切到它上面（`Console: switching to colour frame buffer device 135x146`）、
`actual_brightness = 400` —— **但屏幕全黑**。往 framebuffer 里灌 4 MB 随机噪声也不显示。

### 根因：背光值太小

```
echo 400  > /sys/class/backlight/umi-panel/brightness   -> 全黑
echo 2047 > /sys/class/backlight/umi-panel/brightness   -> 正常显示
```

这块屏的亮度映射**远比线性陡**：400/2047（19.5%）看起来就是黑的，接近上限才亮。
所以「链路全好但屏是黑的」不是数据通路问题，是亮度值问题。

initramfs 的 `[5a]` 现在默认写 **1500**（人眼可读），要暗中测再往下调。

### 这一路的三个自造 bug（都记在驱动注释里）

| 版本 | 问题 | 结果 |
|---|---|---|
| p11 | 用 `copy_from_kernel_nofault` 批量读 68 个 NORTH 引脚 | SError 兜不住 → panic → `QCOM_WDT` 复位整机 |
| p12 | `reset-sequence` 按 `u8*` 读大端 u32 | 读到全 0 → 复位脉冲 0ms → 加复位反而全黑 |
| p13/p14 | `of_property_read_u32_array(..., ARRAY_SIZE(arr))` 属性比数组短 | 返回 `-EOVERFLOW` → 掉进默认分支，真实三段时序没生效 |

### 最终确认可用的状态

| 能力 | 状态 |
|---|---|
| 内核启动 | ✅ `6.12.94-umi`，约 12 秒 |
| 显示 + 内核控制台 | ✅ 1080x2340@60，DSC，4-lane cmd mode |
| 亮度调节 | ✅ 1..2047（≈1000 以上才有可见亮度，默认取 1500） |
| 熄屏再亮 | ✅ 见下面实测 |
| 复位脚 | ✅ GPIO12（从 NORTH 保留区单独放出） |
| UFS / USB console / 日志 U 盘 | ✅ |

### 熄屏再亮实测（亮度 1500，屏正常状态下）

```
[786.807606] off-sequence: sent 2 packets / 18 bytes      ← display-off + sleep-in
[792.222685] prepare 1080x2340@60Hz (DSC)
[792.246656] reset sequence: default low 1ms -> high 10ms ← 复位脉冲
[792.372427] on-sequence: sent 59 packets / 652 bytes
```
`actual_brightness` 仍是 1500，**屏幕完整恢复，用户确认「完全正常」**。

> 注：之前那次「亮几秒又黑」的熄屏测试是在亮度 400（全黑）状态下做的，
> 结论无效 —— 那是同一个亮度问题，不是复位问题。

> 注 2：这次日志显示的是 `reset sequence: default low 1ms -> high 10ms`，
> 说明 `reset-sequence` 的 `-EOVERFLOW` 还没修好（见上表第三个 bug）。
> 之后编了一版用真实三段时序（高1ms→低1ms→高10ms）的，因为默认值已经能正常工作，
> 这一版**没有上机验证**，留作后续替换。

工作镜像：`out/boot-umi-p14-ascii.img`（含上述全部修复，日志已全英文）。
驱动：`patches/panel-xiaomi-umi.c`；面板数据：`dts/xiaomi-umi-panels.dtsi`（自动生成）。
