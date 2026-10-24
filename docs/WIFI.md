# QCA6390 WiFi 调查记录（umi）

> 目标：让 mi10 的 WiFi 在主线内核下工作。
>
> 结论（2026-10-24）：**PCIe 控制器已经能起来，但 QCA6390 上不了电** ——
> 控制它上电/复位的两个 GPIO（20、21、79、81）全在 TLMM 的 **NORTH tile**，
> 这块在这台机器上一访问就 SError。**当前主线此路不通**，下面是完整证据。

---

## 1. 硬件是什么

下游 DT（`dump/downstream.dts`）写得很清楚：

```
qcom,cnss-qca6390@b0000000 {
	compatible = "qcom,cnss-qca6390";
	wlan-en-gpio = <0x65 0x14 0x00>;        /* &tlmm 20 */
	qcom,wlan-rc-num = <0x00>;              /* PCIe0 */
	...
}
```

- 芯片：**QCA6390**（Wi-Fi 6，a/b/g/n/ac/ax）
- 总线：**PCIe0**（`1c00000.pcie`），设备 ID `pci17cb,1101`
- 供电：板载 PMU（`qcom,qca6390-pmu`，10 路 LDO）
- 使能：`wlan-en` = **GPIO 20**
- 复位：`perst` = **GPIO 79**（`GPIO_ACTIVE_LOW`）

主线 `ath11k` 是支持的（`ath11k_pci.ko`，`CONFIG_ATH11K_PCI=m`），
固件 `ath11k/QCA6390/hw2.0/{amss.bin,m3.bin,bdwlan.bin,board-2.bin}`
Arch 的 linux-firmware 自带，**已经齐了**，不缺固件。

## 2. 做到哪一步了

设备树 `dts/sm8250-xiaomi-umi-wifi.dts`（基线树 + PCIe/QCA6390）。

### 2.1 第一版：pinctrl-0 报 -EINVAL

```
sm8250-pinctrl f100000.pinctrl: error -EINVAL: pin-79 (1c00000.pcie)
qcom-pcie 1c00000.pcie: Error applying setting, reverse things back
```

`sm8250.dtsi` 的 `pcie0_default_state` 是 `pins = "gpio79"; function = "gpio"`，
`msm_pinmux_set_mux()` 的 `WARN_ON(i == g->nfuncs)` 分支被走到了。
先 `/delete-property/ pinctrl-0`。

### 2.2 第二版：probe failed -22

```
qcom-pcie 1c00000.pcie: probe with driver qcom-pcie failed with error -22
```

来源是 `pcie-qcom.c:qcom_pcie_probe()`：

```c
pcie->reset = devm_gpiod_get_optional(dev, "perst", GPIOD_OUT_HIGH);
if (IS_ERR(pcie->reset)) { ret = PTR_ERR(pcie->reset); ... }
```

而 `sm8250.dtsi` 给 pcie0 配了：

```dts
perst-gpios = <&tlmm 79 GPIO_ACTIVE_LOW>;
wake-gpios  = <&tlmm 81 GPIO_ACTIVE_HIGH>;
```

**79 / 81 都在 `gpio-reserved-ranges` 的 `<77 8>` 里**，`gpiod_get` 对保留引脚
返回 `-EINVAL`，probe 当场退出。

### 2.3 第三版：控制器起来了，但 link 不上

删掉 `perst-gpios` / `wake-gpios` 之后：

```
qcom-pcie 1c00000.pcie: host bridge /soc@0/pcie@1c00000 ranges:
qcom-pcie 1c00000.pcie:       IO 0x0060200000..0x00602fffff -> 0x0000000000
qcom-pcie 1c00000.pcie:      MEM 0x0060300000..0x0063ffffff -> 0x0060300000
qcom-pcie 1c00000.pcie: iATU: unroll T, 8 ob, 8 ib, align 4K, limit 1024G
qcom-pcie 1c00000.pcie: Phy link never came up          ← 关键
qcom-pcie 1c00000.pcie: PCI host bridge to bus 0000:00
pci 0000:00:00.0: [17cb:010b] type 01 class 0x060400 PCIe Root Port
pcieport 0000:00:00.0: PME: Signaling with IRQ 208
pcieport 0000:00:00.0: AER: enabled with IRQ 208
```

**控制器、iATU、Root Port 全部正常，只是链路上没有设备** ——
因为 QCA6390 根本没被使能（WLAN_EN 没拉高，PERST# 没释放）。

`/sys/bus/pci/devices/` 里只有 `0000:00:00.0`（自己），没有 `17cb:1101`。

## 3. 卡在哪：NORTH tile 的 GPIO 访问不了

要控制 QoS6390 上电，必须用 GPIO 20（WLAN_EN）和 79（PERST#）。
于是把这两个 pin 从 `gpio-reserved-ranges` 里单独放出来：

```dts
- gpio-reserved-ranges = <4 8>, <13 11>, <28 4>, <40 4>, <66 3>, <77 8>, <92 33>;
+ gpio-reserved-ranges = <4 8>, <13 7>, <21 3>, <28 4>, <40 4>, <66 3>, <77 2>, <80 5>, <92 33>;
```

并在 DTS 里加回 `perst-gpios` / `wlan-enable-gpios`。
**结果：手机直接起不来，ABL 回落 fastboot。**

> 这不是新现象。面板 reset 用的 **GPIO 12 是能读能写的**
> （实测 `val = 0x000002c3`，mux=0/OE=1/drive=3/pull-up），
> 但 **pin 28 一读就 synchronous external abort**。
> 所以 NORTH tile 不是整块坏、也不是整块好：**个别 pin 不可访问**，
> 而 20 / 79 恰好都在坏的那一堆里。

### 为什么不能「先探测一下再决定」

试过：用 `copy_from_kernel_nofault` 连读 68 个 NORTH 引脚做批量探测，
结果整机被看门狗复位 —— 那些访问产生的是 **SError（异步外部中止）**，
无法归属到某一条指令，`copy_from_kernel_nofault` 兜不住 → panic → WDT。

**教训：验证 NORTH 引脚只能一个一个来，而且每次失败都要按键重启。**

## 4. 还有什么路可以试（未验证）

1. **不通过 GPIO，用 PMIC 直接给 QCA6390 上电**
   下游用 10 路板载 LDO（`qca6390-pmu`）。如果这些 LDO 默认就开着、
   WLAN_EN 只是个 gate，也许可以绕过 GPIO。需要先确认
   `vreg_pmu_*` 在不开 wlan-en 的情况下是否真能输出电压。

2. **查 NORTH tile 的保护来源**
   SM8250 的 TLMM 分 west/south/north 三块（`0xf100000` / `0xf500000` / `0xf900000`）。
   north 的个别引脚可能是被 **XPU / TZ** 保护，也可能是 **interconnect 没打开**。
   值得对照下游 DT 里 `qcom,tlmm-gpio` 之类的配置。

3. **让 ABL 帮我们拉高 WLAN_EN**
   如果 bootloader 在某些条件下会打开 WiFi（比如 fastboot 的某个命令），
   可以在 `fastboot boot` 之前先让它使能。未验证。

4. **接受没有 WiFi**
   现在手机能：串口 console、USB 串口、RNDIS 网卡（Linux 侧 `usb0` 192.168.42.1
   已起来，Windows 侧驱动还差 MS OS Descriptor）。

## 5. 相关文件

| 文件 | 作用 |
|---|---|
| `dts/sm8250-xiaomi-umi-wifi.dts` | 基线树 + PCIe/QCA6390（当前是「控制器能起、link 不上」那一版） |
| `out/boot-umi-wifi4.img` | 上面这棵树 + 基线内核，`fastboot boot` 验证过 |
| `scripts/mk-dtb.sh` | 单独编一个 dtb（不重编内核） |
| `tools/pack-umi.py --dtb` | 换 dtb 打包 boot.img |

## 6. 实验流程备忘

调试期间比较高效的方式（不再需要反复按键）：

```sh
# 电脑上：dtb 190 KB -> gzip 36 KB -> base64 48 K 字符，串口约 5 秒
powershell -File tmp\send-dtb.ps1 -Chunk 400 -DelayMs 100

# 手机上：写进 boot 分区的 dtb 段（0xf2f000 = 15911152，512 字节对齐 = 31076）
dd if=/tmp/new.dtb of=/dev/sde50 bs=512 seek=31076 conv=notrunc
sync
dd if=/dev/sde50 bs=512 skip=31076 count=373 | head -c 190717 | md5sum
reboot
```

**注意**：dtb 段后面只剩 **202512 字节**，dtb 超过它就会踩到别的东西。
当前 dtb 190 KB，还有余量。

**关键前提**：`setsid`/`stty -echo -onlcr` 必须先关终端回显，
否则每发一个字符都被原样回显，带宽翻倍、控制台缓冲溢出，
传 24 KB 就卡死（实测过）。

## 7. 2026-10-24 第二轮：把能控的都控住了，卡仍然不出 link

第一轮的结论是「GPIO 20/79 不可访问」。这一轮把这些逐个证伪了：

### 7.1 找到了一个自己挖的坑：mk-dtb.sh 不同步 dtsi

改了 `sm8250-xiaomi-umi-common.dtsi` 的 `gpio-reserved-ranges`，编译出来的 dtb 里
却还是旧值。原因是 `tmp/mk-dtb.sh` 只把**主 .dts** 拷进内核树，
树里那份 `common.dtsi` 一直是旧的。现在会同步 common/panels/touch/dtbo-stubs 全部。

### 7.2 gpio 79（PERST#）可用

只把 79 从 `<77 8>` 里单独放出来（拆成 `<77 2>` + `<80 5>`），配上：

```dts
&pcie0 { perst-gpios = <&tlmm 79 GPIO_ACTIVE_LOW>; };
```

`probe failed -22` **消失**，控制器完整起来：

```
qcom-pcie 1c00000.pcie: iATU: unroll T, 8 ob, 8 ib, align 4K, limit 1024G
qcom-pcie 1c00000.pcie: PCI host bridge to bus 0000:00
pci 0000:00:00.0: [17cb:010b] PCIe Root Port
pcieport 0000:00:00.0: PME: Signaling with IRQ 208
```

debugfs 里也确认了：`gpio79 : out high func0 2mA pull down`。

### 7.3 gpio 20（WLAN_EN）也可用，而且真被拉高了

上游 `pwrseq-qcom-wcn` 用 `GPIOD_ASIS` 请求 wlan-enable —— **只请求不改电平**，
假设 bootloader 已经拉高。umi 的 ABL 没有。于是用 gpio-hog 强制拉高：

```dts
&tlmm {
	wlan_en_hog: wlan-en-hog {
		gpio-hog;
		gpios = <20 GPIO_ACTIVE_HIGH>;
		output-high;
	};
};
```

20 同样从 `<13 11>` 里单独放出（`<13 7>` + `<21 3>`）。
结果：`gpio20 : out high func0 2mA pull down`，系统正常没崩。

### 7.4 电源也确认全开

```
vreg_s6a_0p95 = enabled      vreg_s8c_1p35 = enabled
vreg_s5a_1p9  = enabled      vreg_s4a_1p8  = enabled
vreg_l5a_0p88 = enabled      vreg_l9a_1p2  = enabled
```

`pwrseq-qcom_wcn` 和 `pci-pwrctl-pwrseq` 都正确绑定
（后者挂在 `1c00000.pcie:pcie@0:wifi@0` 上）。

### 7.5 PERST 时序也没问题

主线的时序是够的：

```c
qcom_ep_reset_assert:   PERST=1, usleep_range(1000, 1500)
qcom_ep_reset_deassert: msleep(100), PERST=0, usleep_range(1000, 1500)
```

### 7.6 结果：还是 `Phy link never came up`

电源、使能、复位、时序全都满足了，卡依然不响应。所以剩下的唯一解释是
**QCA6390 自己的 PMU 还没有被初始化**。

下游 `cnss2` 驱动（`downstream-kernel/drivers/net/wireless/cnss2/`）的上电序列是：

```c
int cnss_power_on_device(struct cnss_plat_data *plat_priv)
{
	cnss_vreg_on_type(plat_priv, CNSS_VREG_PRIM);   /* 电源 */
	cnss_clk_on(plat_priv, &plat_priv->clk_list);   /* 时钟 */
	cnss_select_pinctrl_enable(plat_priv);          /* WLAN_EN */
	plat_priv->powered_on = true;
}
```

下游 DT 里还有几个主线没有的东西：

```
qcom,sw-ctrl-gpio = <&tlmm 124 0>;     /* 诊断用，打印电平 */
qcom,cmd_db_name = "smpf2";            /* RPMh 命令数据库资源 */
qcom,vdd-wlan-aon-config = <...>;      /* 每路轨的电压配置 */
```

**下一步**要么把 `cnss2` 的电源序列移植成一个小的 mainline 驱动，
要么接受这台机器的 WiFi 在主线内核上暂时做不到。

### 7.7 kexec 能换内核，换不了设备树

顺便试了 `kexec -l Image.gz --initrd=... --dtb=...`：内核加载成功、能启动，
但 `/proc/device-tree` 里还是旧设备树（`pcie status = disabled`）。
**`--dtb` 在 arm64 上不生效**，所以 WiFi 调试没法用 kexec 省按键，
每次换 dtb 还是得 `fastboot boot`。
（kexec 带 initrd 本身是好用的，以后调内核参数可以省一次重启。）

## 8. 第三轮：逐项对齐作者 dtb 后仍然不通，dtbo 也排除了

### 8.1 作者镜像里扒出来的真实情况

`Armbian-unofficial_26.11.0-trunk_Xiaomi-umi_...rootfs.img` 里：

- 内核 `7.2.7-current-sm8250`，**驱动全是主线原版**（ath11k_pci / pwrseq-qcom-wcn /
  pci-pwrctl-pwrseq），**没有任何自定义补丁**
- `lib/firmware/ath11k/QCA6390/hw2.0/` 固件齐全
- 他的 `sm8250-xiaomi-umi.dtb` 里：

```dts
pcie@1c00000 {
	perst-gpios = <&tlmm 79 GPIO_ACTIVE_LOW>;
	wake-gpios  = <&tlmm 81 GPIO_ACTIVE_HIGH>;
	pinctrl-0   = <&pcie0_default_state>;
	status = "okay";
};
qca6390-pmu {
	pinctrl-0 = <&bt_default_state>, <&wlan_default_state>;
	wlan-enable-gpios = <&tlmm 20 GPIO_ACTIVE_HIGH>;
	bt-enable-gpios   = <&tlmm 21 GPIO_ACTIVE_HIGH>;
};
gpio-reserved-ranges = <28 4>, <40 4>;     /* 只保留这两段，NORTH 全放 */
```

我们把这些**逐项照抄**（`wifi10`），结果依旧 `Phy link never came up`。

### 8.2 6.12 和 7.2 的 pinctrl 驱动没有可移植的差异

逐行 diff 过 `pinctrl-msm.c` / `pinctrl-msm.h` / `pinctrl-sm8250.c`：

- `struct msm_pinctrl` 两边都是 `void __iomem *regs[MAX_NR_TILES]`（6.12 就支持多 tile）
- `MSM_ACCESSOR` 宏两边一样，都走 `pctrl->regs[g->tile]`
- `msm_pinmux_set_mux()` 一字不差
- pin 20/28/79 的 `PINGROUP(..., NORTH, ...)` 定义完全相同

**所以「把 7.2 的修复移植回 6.12」这件事本身不成立 —— 没有那个修复。**

### 8.3 dtbo 分区也被排除了

猜过 ABL 会在 `fastboot boot` 时往 base dtb 上打 dtbo overlay，把我们的配置改掉。
实测运行时设备树：

```
/proc/device-tree/qca6390-pmu/wlan-enable-gpios = 00 00 00 54 00 00 00 14 00 00 00 00   (gpio20) ✓
/proc/device-tree/soc@0/pcie@1c00000/perst-gpios = ... 0x4f 0x01                       (gpio79) ✓
/proc/device-tree/soc@0/pcie@1c00000/status      = okay                                 ✓
/proc/device-tree/soc@0/pinctrl@f100000/gpio-reserved-ranges = <28 4> <40 4>            ✓
```

**和送进去的 dtb 完全一致**，overlay 没有动 WiFi 相关的任何节点。

### 8.4 最后把所有能查的都查了，全部正常

| 项目 | 实测值 |
|---|---|
| `gpio20` (WLAN_EN) | `out high func0 16mA` ✅ 真的拉高了（pwrseq power_on 干的） |
| `gpio79` (PERST#) | `out high` ✅ 复位已释放 |
| `gpio81` (WAKE) | `in high` ✅ |
| `gpio124` (SW_CTRL) | `in high` |
| `pcie_0_gdsc` | `on` ✅ |
| `vreg_l5a_0p88` / `vreg_l9a_1p2` | `enabled` users=4/3 ✅ |
| `gcc_pcie_wifi_clkref_en` | `1` (by `1c06000.phy` ref) ✅ |
| `gcc_pcie_phy_aux_clk` | `1` ✅ |
| `gcc_pcie0_phy_refgen_clk` | `1` @100 MHz ✅ |
| `gcc_pcie_0_pipe_clk` | `2` ✅ |
| PHY 驱动 | `qcom-qmp-pcie-phy` 已绑定 ✅ |
| PERST 时序 | assert 1 ms → hold 100 ms → release ✅ |

**电源域、六路 regulator、四个时钟、PHY、复位、使能，全部到位，QCA6390 仍然不参与 PCIe 链路训练。**

### 8.5 结论：卡在主线够不到的地方

主线这一侧已经没有可改的了。剩下的可能性都在驱动之外：

1. **RPMh / XPU 配置**：下游 DT 有 `qcom,cmd_db_name = "smpf2"`，
   `cnss2` 用它向 RPMh 查询资源并下发 sleep/wake 命令。主线没有这个机制，
   而 QCA6390 很可能需要 XPU 授权它才能被 PCIe 看到。
2. **硬件本身**：这颗 QCA6390 在 umi 上可能确实没工作（或者需要固件先跑起来）。
3. 作者那句「完全能跑」大概率指的是**系统**能跑，不一定包括 WiFi ——
   他的镜像里没有留下任何 WiFi 已连通的痕迹。

**当前状态**：Arch + 串口 + SSH + USB 网卡可用，WiFi 待续。
