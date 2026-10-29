# 小米10 (umi) 主线内核 bring-up 操作手册

> 没有 UART 的情况下，调试带宽全靠**屏幕** + **pstore** + **USB gadget**。
> 所以整条路线是「先把图像挤到屏幕上，再谈驱动」。
>
> **📌 上机测试顺序以 [RISK-AUDIT-2.md](notes/RISK-AUDIT-2.md) §4 的矩阵为准。**
> 相比本文，那个矩阵多了「第 0 步：先用原厂 boot.img 做一次 `fastboot boot` 对照」——
> 两分钟就能把「环境 / 打包 / ABL 通道」这一整类原因排除掉，是最便宜的一步。
>
> 改完 `config/umi.config` 之后先跑 `scripts/config-only.sh`（几十秒，不编译）：
> 它会逐条告诉你配置是否真的生效 —— 专治 `# CONFIG_X is not set` 写法陷阱。

所有命令在 **Windows PowerShell**（工作目录 `<repo>`）里执行。
WSL 发行版叫 `umi`（Alpine，里面 20 核、clang22/gcc16/dtc 都装好了）。

---

## 0. 一次性准备

```powershell
# 0.1 在 WSL 的 ext4 上重建一份干净内核树（D:\ 是大小写不敏感的，内核树不能在那儿编译）
wsl -d umi -u root -- sh <repo>/scripts/prepare-tree.sh

# 0.2 拉一份 aarch64 静态 busybox（给 initramfs 用）
wsl -d umi -u root -- sh <repo>/scripts/fetch-busybox.sh
```

> 为什么不能在 `D:\project\linux-src` 上编：
> 内核树里有只差大小写的文件对（例如 `net/netfilter/xt_connmark.c` / `xt_CONNMARK.c` 这类），
> Windows 目录是大小写不敏感的，检出时会互相覆盖/丢文件，`make` 会在奇怪的地方报错。
> 现在树在 WSL 里的 `/root/linux`（大小写敏感，git 状态干净）。

## 1. 编译内核

```powershell
wsl -d umi -u root -- sh <repo>/scripts/build.sh
```

脚本做的事：同步 DTS → `defconfig` → 合并 `config/umi.config` → **校验关键配置**（不通过就退出）
→ `make -j16 Image.gz dtbs` → 产物拷到 `out/`。

改设备树后只想快速验证语法/编译，用：

```powershell
wsl -d umi -u root -- sh <repo>/scripts/dtb-only.sh
```

产物：

```
out/Image.gz                     内核（gzip）
out/sm8250-xiaomi-umi.dtb        设备树
out/config-effective             实际生效的 .config
```

## 2. 打 initramfs

```powershell
wsl -d umi -u root -- sh <repo>/scripts/mkinitramfs.sh
# 可选：把 USB CDC-ACM 控制台也带上（阶段 3 用）
wsl -d umi -u root -- sh <repo>/scripts/mkinitramfs.sh --usb-console
```

产物 `out/initramfs.cpio.gz`（约 660 KB，里面有 sh / mount / dmesg / cat）。

## 3. 打包 boot.img

```powershell
python tools\pack-umi.py --name p1
```

打包前会**强制校验** DTB 的 `qcom,msm-id` / `qcom,board-id`（ABL 就靠这两个属性挑 DTB），
校验不过直接拒绝打包。产物 `out/boot-umi-p1.img`。

如果你手上有原厂 `boot.img` 备份，可以继承它的地址/cmdline：

```powershell
python tools\pack-umi.py --name p1 --template 原厂boot.img
```

---

## 4. 上机测试阶梯（一步一个变量，别跳）

> **上机前先读 [RISK-AUDIT.md](notes/RISK-AUDIT.md)**：那里把「黑屏」的 14 种可能原因、每种怎么区分
> 都列全了。下面是执行版。

### 步骤 A0 —— 先起「不看屏幕的眼睛」（每次测试前都做）

```powershell
powershell -ExecutionPolicy Bypass -File tools\watch-usb.ps1
```

它会在后台盯 USB 枚举（我们的 gadget ID 是 `1D6B:0104`），出现就打带秒数的时间戳，
并自动打开出现的串口，把控制台内容存到 `out\usb-console.log`。

**为什么这是最关键的一步**：只要 USB gadget 枚举出来了，就说明
「内核跑完 → initramfs 起来 → 用户态在跑」，**根本不需要看屏幕**。
这样就把「内核起不来」和「屏幕没显示」两件事彻底分开了。

而且 initramfs 会同时提供**两个** USB 功能：
- **CDC-ACM 串口**（实时交互，`watch-usb.ps1` 会自动抓）
- **U 盘**（Windows 上直接出现盘符，里面是 `dmesg.txt` / `pstore.txt` / `partitions.txt`）
  —— 不需要串口驱动、不需要终端软件，最省事的一条路

> 完整的 log 提取方案（七条通道）见 **[LOG-EXTRACTION.md](notes/LOG-EXTRACTION.md)**。

### 步骤 A1 —— 记录启动耗时（辅助排查）

执行 `fastboot boot` 时**掐秒表**，记录「从执行命令到重新出现 fastboot」的时间：

| 时间 | 结论 | 下一步 |
|---|---|---|
| 几秒内返回 | ABL 拒绝和内核早期异常后复位都可能 | 先检查 fastboot 返回信息、USB 枚举和 pstore；不能只按耗时归因 |
| 延迟较长后返回 | 内核可能已开始执行，也可能有其他复位原因 | 用 USB + pstore 取日志，并与同一镜像的重复结果对照；不能把耗时当成定论 |
| 一直黑屏、不回落 fastboot | 内核卡死（`QCOM_WDT` 接手喂狗后的正常表现） | 步骤 C（pstore）+ 步骤 F（信标） |

### 步骤 A2 —— 裸机打屏测试（判断屏幕通道是否可用）

```powershell
python tools\fbtest.py
python tools\pack-umi.py --kernel out\fbtest.bin --name fbtest --no-initramfs
# 手机进 fastboot（关机后按住 音量- + 电源）
fastboot boot out\boot-umi-fbtest.img
```

这是一个 84 字节的裸机 aarch64 程序：把 `0x9c000000`（ABL 留下的 cont-splash 帧缓冲，
地址来自下游 `kona.dtsi` 的 `cont_splash_region@9c000000`）全屏涂红 → 涂绿 → 循环。

| 屏幕 | 结论 |
|---|---|
| **红绿闪烁** | ABL 接受了镜像格式 + DTB，**而且屏幕通道可用** → 后面所有屏幕调试都有效 |
| 一直黑屏（USB 也没动静） | 可能是 ABL 拒绝了；也可能是 **ABL 跳转前把屏关了** → 那就只能靠 USB/pstore 路线 |
| 黑几秒回 fastboot | 同上，看秒表 |

> 这一步的价值在于：**它决定后面还要不要指望屏幕**。如果连裸机刷屏都不亮，
> 就别再花时间在 fbcon 上了，直接走 USB 串口 + pstore。

### 步骤 B —— 阶段 1 内核：把 log 挤到屏幕上

```powershell
fastboot boot out\boot-umi-p1.img
```

期望看到：屏幕上出现内核 log（simpledrm 接管 cont-splash → fbcon 把 `console=tty0` 的内容画出来），
最后是我们 initramfs 的 banner：

```
############################################################
#  UMI MAINLINE BRING-UP INITRAMFS
#  能走到这里 = 内核已经跑起来、驱动了 console、还执行了用户态
############################################################
```

看到这个 banner = **移植成功了一大半**（说明 UFS 之外的核心子系统都活了）。

如果卡在黑屏且**不回落 fastboot**：内核在跑但 console 没起来 →
把 `config/umi.config` 里的 `loglevel=8` 保留，用步骤 C 的 pstore 捞日志。

### 步骤 C —— pstore：捞上一次崩溃的日志

ramoops 已经放在 `0xb0000000`（4 MB，`console-ramoops` + `pmsg-ramoops`）。
内核崩溃时会把 log 写进这块保留内存；**再 boot 一次我们的镜像**，initramfs 会自动把它打印出来：

```
==== [2] pstore / ramoops: last boot's dying words ====
  ---------------- /sys/fs/pstore/console-ramoops-0 ----------------
  ...
```

所以流程是：崩一次 → 再 `fastboot boot` 一次 → 看屏幕上的上一次日志。
这是没有 UART 时唯一能看到"崩溃现场"的办法。

### 步骤 D —— USB CDC-ACM 控制台（真正的交互式调试）

```powershell
wsl -d umi -u root -- sh <repo>/scripts/mkinitramfs.sh --usb-console
python tools\pack-umi.py --name p2
fastboot boot out\boot-umi-p2.img
```

如果 dwc3 起来了，电脑上会出现串口设备，用 PuTTY / `screen /dev/ttyACM0 115200` 连上去就有 shell。
（前提：`usb_1_dwc3` 是 peripheral 模式、`usb_1_hsphy` 正常、vbus 检测正常。
 起不来就先看 `dmesg | grep -i dwc3`。）

### 步骤 E —— 存储与 rootfs

UFS 通了以后（`dmesg | grep -i ufs`），就能挂 `userdata` / `system` 分区，
往里面放一个真正的 rootfs（`rootfs/` 里已经有素材），从"打 log"升级到"能干活"。

### 步骤 F —— 极早期屏幕信标（屏幕黑但 USB 也没动静时的最后手段）

内核从 `start_kernel` 到 `device_initcall` 之间，屏幕上**必然什么都没有**
（`console=tty0` 要等 simpledrm 在 device_initcall 才绑定）。这段盲区用信标填：

```powershell
wsl -d umi -u root -- sh <repo>/scripts/add-beacon.sh
python tools\pack-umi.py --kernel out\Image-beacon.gz --name beacon
fastboot boot out\boot-umi-beacon.img
```

信标驱动在四个 initcall 阶段直接往 cont-splash 帧缓冲刷整屏纯色：

| 屏幕颜色 | 说明内核至少走到了 |
|---|---|
| 黑 | 还没进 `postcore_initcall`（或 ABL 把屏关了） |
| 蓝 | `postcore_initcall` |
| 青 | `arch_initcall` |
| 绿 | `subsys_initcall` |
| 黄 | `fs_initcall` |
| 黑底白字控制台 | `device_initcall` 之后（simpledrm + fbcon 起来了） |

用完撤销：`wsl -d umi -u root -- sh <repo>/scripts/remove-beacon.sh`

### 步骤 G —— panic 屏 / 二维码（不用真崩就能先验证）

内核里已经配好了 `DRM_PANIC` + `qr_code`：panic 时会把**压缩后的日志编成二维码**
画在屏幕上，手机扫一下就把整段 log 拿走（见 [LOG-EXTRACTION.md](notes/LOG-EXTRACTION.md) 通道⑧）。

initramfs 默认**开机 60 秒后自动画一次**（这是自测，不是真崩），
所以第一次成功启动时就能顺手确认"这张屏扫不扫得出来、解码器好不好用"：

```
扫码 → 把整串内容粘给解码器：
python tools\decode-panic-qr.py "https://umi.local/panic?a=aarch64&v=6.12.94-umi&zl=0123456789..."
```

不想自动画：`mkinitramfs.sh --no-panic-test`；改秒数：`--test-panic 120`。
想换样式（`qr_code` / `kmsg` / `user`）：`scripts/set-panic-screen.sh kmsg`。
运行时直接改（不用重编）：`echo kmsg > /sys/module/drm/parameters/panic_screen`。

---

## 5. 屏幕表现 → 结论对照表（贴墙上）

| 表现 | 含义 | 下一步 |
|---|---|---|
| 黑几秒 → 回 fastboot | ABL 拒绝、内核早期异常后复位等原因都可能 | 检查 fastboot 返回信息、USB 枚举与 pstore；必要时用同一镜像重复对照 |
| 一直黑屏，不重启 | 内核卡死（QCOM_WDT 接手喂狗后的表现） | 步骤 C 捞 pstore；步骤 F 看信标颜色 |
| USB 出现 1D6B:0104 | **内核 + initramfs + 用户态全通了**，只是屏幕没显示 | 接串口拿 log，转去修显示 |
| 出现 kernel log | 成功 | 继续看哪个驱动没起来 |
| log 停在某行 | 崩溃点 | 那行的驱动就是元凶，先禁掉它 |
| 屏幕花屏/条纹/斜切 | 帧缓冲 stride 或格式不对 | 改 DTS 里 simple-framebuffer 的 `stride`（试 4320 / 4352 / 4096）或 `format` |
| 亮着但全白/全黑 | backlight/panel 没驱动 | 这是后面的面板驱动工作，属正常 |

> 屏幕出字但整体斜着切：说明 ABL 用的 pitch 不是 1080×4。
> 1080×4 = 4320（我们当前用的），也可能是 4352（按 64 对齐）或 4096。
> 改 `dts/sm8250-xiaomi-umi-common.dtsi` 里的 `stride = <(1080 * 4)>`，重跑 `dtb-only.sh` + `pack-umi.py` 即可。

## 6. 救砖 / 恢复

- `fastboot boot <img>` 是**临时**启动，不写 flash，重启就回到原样 —— 大胆试。
- 真要刷写时才用 `fastboot flash boot <原厂boot.img>`，**刷之前先确认原厂备份在手**。
- 卡在 fastboot：长按电源 10 秒强制断电，再按组合键重进。
- 最坏情况（进了 EDL/9008）：用小米官方线刷包恢复（需要授权账号）。

## 7. 常见坑

1. **`D:\` 上编译内核**：大小写不敏感 → 丢文件、乱报错。内核树必须放 WSL ext4。
2. **`Image.gz-dtb`**：主线 arm64 **不支持** appended DTB（只有 32 位 arm 有 `ARM_APPENDED_DTB`）。
   DTB 必须走 boot image 的 v2 `dtb` 段。
3. **裸 `earlycon`**：没有 `chosen/stdout-path` 时它不绑定任何设备，静默什么都不打印。
4. **`console=ttyMSM0`**：那是 `uart12`(0xa90000)，手机上没引出线，等于没有 console。要有 `console=tty0`。
5. **开了 mdss 就全黑**：没有面板驱动时，`DRM_MSM` 会接管 cont-splash 但画不出东西，
   所以 bring-up 阶段必须 `# CONFIG_DRM_MSM is not set`。
6. **WSL 的 `localhost` 警告**：`wsl:` 那行红字是 WSL 的网络提示，无害，可以忽略。
7. **PowerShell 5.1 读 .ps1**：UTF-8 必须带 BOM，否则中文注释会按 GBK 解析报语法错。
8. **`fastboot boot` 需要设备处于 fastboot 模式**：`adb reboot bootloader` 或 关机后 音量- + 电源。
