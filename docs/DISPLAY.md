# 面板驱动进度与设计（华星 j2_mp_42_02_0b）

> 目标：让 `qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd`（这台设备的华星屏）在主线里亮起来。
> **硬性约束：驱动/DTS 里不出现任何电压数值，不对任何 regulator 做 set_voltage。**

---

## 1. 面板识别（已完成）

设备自己的 cmdline：

```
msm_drm.dsi_display0=qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd:
androidboot.oled_panel_id=0B  androidboot.oled_pmic_id=0B
```

小米命名里 `j2_<供应商码>_<型号>`，据此分族（**推断**，不是官方文档）：

| 供应商 | 供应商码 | 变体 |
|---|---|---|
| **华星 CSOT** | `42` | `j2_42_02_0b`、`j2_p1_42_02_0b`、`j2_p2_1_42_02_0b`、**`j2_mp_42_02_0b`** ← 本机、`j2_mp_42_02_0b_post`、`j1s_42_02_0a{,_p1_1,_mp}`、`j1u_42_02_0b`、`j2s_mp_42_02_0a`、`j2s_mp_42_02_0b` |
| **三星 Samsung** | `38` | `j2_38_0c_0a`、`j2_p2_1_38_0c_0a`、`j1t_38_0c_0a`、`k11a_38_08_0a`、`j11_38_08_0a`、`l11r_38_08_0a` |
| 其它机型（1080×2400） | `36`/`42`/`35` | `l3a_*`、`l10a_*`、`k81_*`、`l81a_*`、`m82_*`（不是 umi 的） |

`mi,panel-id` 里直接编码了型号 ASCII：
`0x4a32 0x420201` → `"J2"` + `0x420201`；`0x4a3153` → `"J1S"`；`0x4c3341` → `"L3A"`；`0x4b3831` → `"K81"`。

---

## 2. 数据提取（已完成，可复现）

```powershell
# 1) 下游 DTB -> dts
wsl -d umi -u root -e sh -c "dtc -I dtb -O dts -o dump/downstream.dts \
    /mnt/d/project/xiaomi-umi-mainline/firmware_extracted/umi_downstream.dtb"

# 2) 把 52 个 qcom,mdss_dsi_* 节点（其中 28 个是 umi 变体）拆成单文件
python tools/extract-panels.py dump/downstream.dts --dump-dir dump/panels --json dump/panel-index.json

# 3) 转成主线用的 DTS include（每个变体一个 panel@0 节点，只开一个）
python tools/gen-panel-dts.py dump/panels -o dts/xiaomi-umi-panels.dtsi \
    --enable qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd
```

本机面板的关键参数（来自 `dump/panels/qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd.dts`）：

| 项 | 值 |
|---|---|
| 分辨率 / 刷新率 | 1080×2340（0x438×0x924）/ 60Hz（另有一档 90Hz） |
| 模式 | `dsi_cmd_mode`，24bpp，burst_mode |
| TE / reset | gpio66 / gpio12（都在 tlmm） |
| 背光 | `bl_ctrl_dcs`，min 1 / max 0x7ff，初始 0x133 |
| DSI 时钟 | 0x28a67e80 = 682 MHz |
| DSC | version 0x11，slice 0x21c×0x0c，per-pkt 2，8bpc/8bpp |
| PHY timings | `[00 18 06 06 21 20 06 06 04 02 04 00 15 16]` |
| 上电序列 | `qcom,mdss-dsi-reset-sequence = <1 1 0 1 1 10>` |

---

## 3. 驱动设计（已写，未编译未上机）

`patches/panel-xiaomi-umi.c`

**核心决定：驱动里不含任何面板数据，全部从 DT 读。**
理由：28 个变体，为每个写一份 C 数据既不可维护，也更容易抄错字节。换屏只改 DTS 里
哪个变体 `status = "okay"`，驱动一行都不用动。

**电压安全（硬性）**：
1. 只有 `regulator_bulk_enable/disable()`，**没有 set_voltage**；
2. 轨的名字从 `xiaomi,supply-names` 读，电压由 ABL/PMIC 决定；
3. 背光起始值 = `xiaomi,bl-min`（通常是 1），**不会自动拉满**；
4. DMA/时序/DSC 参数全部照抄下游 DTB，不做任何推算。

---

## 4. ★ 已解决：init 序列的包格式（2026-10-23）

**结论：7 字节头，`wait` 只有 1 字节，`dlen` 2 字节大端在偏移 5，`last` 不是结束符。**

依据是下游源码 `downstream-kernel/drivers/video/fbdev/msm/mdss_dsi_cmd.h`：

```c
struct dsi_ctrl_hdr {
	char dtype;   /* data type */
	char last;    /* last in chain */
	char vc;      /* virtual chan */
	char ack;     /* ask ACK from peripheral */
	char wait;    /* ms   ← 只有 1 字节 */
	short dlen;   /* 16 bits ← 偏移 5，大端（mdss_dsi_panel.c 里 ntohs） */
} __packed;       /* sizeof == 7 */
```

还有两个曾被我误判成"非法"的 dtype，其实都在 `mdss_dsi_cmd.h` 里：

```
#define DTYPE_COMPRESSION_MODE  0x07   ← 开/关 DSC
#define DTYPE_PPS               0x0a   ← DSC picture parameter set
```

对应主线 API：`mipi_dsi_compression_mode()` / `mipi_dsi_picture_parameter_set()`。

### 验证（652 字节全消费，59 个包全识别）

用 `tools/parse-dsi-seq.py` 重新解析（之前那份 264 字节 / 13 包的记录是错的，
是读了一行被截断的 dts 造成的）：

```
  [ 0] DCS_LWRITE  dlen=6   f0 55 aa 52 08 07     ← 厂商命令页切到 07
  [ 1] DCS_WRITE1  dlen=2   c0 10
  ...
  [43] DCS_LWRITE  dlen=19  93 89 28 00 0c 02 00 02 0e 01 1f 00 07 08 bb 08 7a 10 f0
  [44] DCS_WRITE1  dlen=2   03 11
  [45] DCS_WRITE   dlen=2   2c 00                 ← write_mem_start
  [46] DCS_WRITE1  dlen=2   35 00                 ← TE on
  [47] DCS_WRITE1  dlen=2   53 20                 ← write_ctrl_display
  [48] DCS_LWRITE  dlen=5   51 00 00 00 00        ← 亮度 0
  [49] DCS_LWRITE  dlen=5   2a 00 00 04 37        ← column 0..1079
  [50] DCS_LWRITE  dlen=5   2b 00 00 09 23        ← page 0..2339
  ...
  [55] DCS_WRITE  wait=100  11 00                 ← sleep out（等 100 ms）
  [56] DCS_WRITE  dlen=2    29 00                 ← display on
  [57] DCS_LWRITE  dlen=6   f0 55 aa 52 08 00
  [58] DCS_WRITE1  dlen=2   b5 84                 ← display-on 之后还有两条
共 652 字节，59 个包，消费 652 字节（完全一致）
类型统计: DCS_LWRITE x26, DCS_WRITE1 x30, DCS_WRITE x3
```

off-sequence = 18 字节 2 个包：`28 00`（display off）→ `10 00`（sleep in，等 120 ms）。

### ★ 重要修正：init 序列里**没有 PPS**

两种 dtype（`0x07` / `0x0a`）确实合法，但**这块屏的 on-command 里一个都没有** ——
59 个包的 dtype 只有 `0x05/0x15/0x39`。

DSC 的 PPS 是**内核自己生成**的：下游 `mdss_dsi_panel.c`
`mdss_dsi_panel_dsc_pps_send()` 按 `qcom,mdss-dsc-*` 那组属性现算一个 128 字节的
`Picture Parameter Set` 发下去。所以主线这边也必须：

```c
dsi->dsc = &dsc_cfg;                       /* probe：slice/版本/bpp 从 DT 读 */
drm_dsc_pps_payload_pack(&pps, dsi->dsc);  /* prepare：现算 PPS */
mipi_dsi_picture_parameter_set(dsi, &pps);
```

`pic_width/pic_height`、RC 参数这些由 msm 的 `dsi_populate_dsc_params()`
在 `pre_enable`（**早于** `drm_panel.prepare()`）里填进同一块 `drm_dsc_config`，
所以 prepare 里 pack 出来的 PPS 是完整的。

### 踩过的坑（写进驱动注释了）

1. 按 8 字节头解析 → 第 1 包 `dlen` 明显错位（整段只有几百字节却算出上千）
2. 误以为 `0x07`/`0x0a` 是非法 DSI 类型 → 其实它们是 DSC 专用 dtype
   （但更关键的坑是下面第 4 条：这块屏根本不用它们）
3. **不能用 `last` 当循环终止条件** —— 第一个包就是 `last=1`，后面还有 58 个；
   下游解析循环只按 `dlen` 走完整段
4. **32 位单元必须补齐成 4 字节大端**，不能按"有效位数"截断。
   下游 DT 写 `<0x39010000 0x6f0 0x55aa5208 …>`，实际字节是
   `39 01 00 00 | 00 00 06 f0 | 55 aa 52 08 …`，
   也就是 dtype=0x39 last=1 vc=0 ack=0 wait=0 dlen=0x0006 payload=`f0 55 aa 52 08 07`。
   按 `0x6f0` → `06 f0` 只有 2 字节的话，整段后半截全部错位
5. **`0x05` 后面那个 `00` 是填充不是参数**：
   `0x05` 是「短写、0 参数」，`0x15` 是「短写、1 参数」，`0x39` 是长写。
   一律丢给 `mipi_dsi_dcs_write_buffer()` 会把 `11 00` 当成「0x11 + 参数 0x00」。

驱动 `patches/panel-xiaomi-umi.c` 已按此实现。

---

## 4.5 ★ 新发现的硬卡点：面板的 reset / TE 脚都在 TLMM NORTH tile

这是目前唯一真正卡住面板的东西，和 DSI 数据无关。

`sm8250-xiaomi-umi-common.dtsi` 里那组保命的

```
gpio-reserved-ranges = <4 20>, <28 4>, <40 4>, <66 3>, <77 8>, <92 33>;
```

把 **NORTH tile 的 68 个引脚全部标成 reserved**（实测：先遇到 pin 28
`synchronous external abort 96000010`，加保留后内核正常起来）。
用 `tools/tile-ranges.py` 对一遍：

```
WEST  total  47  保留后可用  47
SOUTH total  65  保留后可用  61 : 0-3 24-27 32-39 44-65 69-76 85-91 125-132
NORTH total  68  保留后可用   0 : -
  panel reset  gpio12  -> RESERVED(不可用)
  panel TE     gpio66  -> RESERVED(不可用)
```

下游 `downstream-kernel/drivers/pinctrl/qcom/pinctrl-kona.c` 里
`#define NORTH 0x00900000 / SOUTH 0x00500000 / WEST 0x00100000`，
加上 ioremap 基址 `reg = <0xf000000 0x1000000>`，
换算出来 WEST=0xf100000 / SOUTH=0xf500000 / NORTH=0xf900000 ——
**和主线 `sm8250.dtsi` 的三个 region 一模一样**，所以不是地址写错，
就是这块区域在 umi 上读不了。

### 应对（不冒险的走法）

- **TE 脚不需要**：主线 msm DSI 的命令模式用的是 DSI 控制器自己的 TE 输入，
  根本不去读 GPIO66（下游那个 `qcom,platform-te-gpio` 是下游驱动用的）。
- **reset 脚先不用**：ABL 起来时面板已经被它点着了（cont-splash 还亮着），
  驱动把 `reset-gpios` 做成可选的，拿不到就跳过复位脉冲、直接发 init 序列 ——
  这块屏的 init 序列是幂等的（sleep-out → 一堆寄存器 → display-on），
  在已经点亮的屏上再跑一遍通常没问题。
- 真正的修法（以后再做）：查清 NORTH tile 为什么读不了
  （是被 XPU 保护 / 需要某个 GDSC / 还是 ABL 把这块 map 关了），
  修好之后再给回 `reset-gpios`。

## 5. 后续步骤（按顺序）

1. ~~确认包格式~~ — 已完成（§4）
2. ~~生成 `dts/xiaomi-umi-panels.dtsi`~~ — 已完成，只开 `j2_mp_42_02_0b`
3. ~~打开 `CONFIG_DRM_MSM=y` + `&mdss`/`&mdss_dsi0`/`&mdss_dsi0_phy` okay~~ — 已完成
4. **阶段二（当前）**：DTB 里**不 include** 面板节点 → 只验证
   mdss / DPU / DSI ctrl / 7nm PHY 能 probe，一个字节都不发到屏上
5. **阶段三**：取消 `sm8250-xiaomi-umi.dts` 末尾的 include，面板 `status="okay"`
   但带 `xiaomi,no-init` → DSI 真正 attach、connector 出现、card0 注册，
   仍然不碰面板
6. **阶段四**：去掉 `xiaomi,no-init` → 真正发 DSC + init 序列，亮度从 `bl_min` 起
7. 已知风险：上游 SM8250 **MIPI DSC 有 bug**（drm/msm issue #42），而这块屏依赖 DSC；
   如果 DSI 链起来了但画面不对，先去查那个 issue 的状态

## 6. 保留物

- 已验证可用的镜像：`out/boot-umi-p6-psci.img`（UFS + COM3 + 日志 U 盘全通）
- 随时可回退：`fastboot boot out/boot-umi-p6-psci.img`，不写任何分区
