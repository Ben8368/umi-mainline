# 把 log 弄出来看：七条通道

> 没有 UART 的手机，log 只能靠这七条路出来。每条能覆盖的时间窗口不一样，
> 所以不是「选一条」，而是**全都开着**，哪条能用就用哪条。

## 0. 一张表：什么情况下用哪条

```
内核启动时间轴：
start_kernel ──► postcore ─► arch ─► subsys ─► fs ─► device ─► late ─► 用户态(initramfs)
     │                                                        │              │
     │◄────────── 屏幕上必然什么都没有的窗口 ────────────────►│              │
     │                                                        │              │
  ⑦ 信标颜色                                        ① 屏幕出字    ② 串口 ③ U盘
     │                                                        │              │
     └──────────── ④ pstore/ramoops（崩溃时写进内存，下次开机读）─────────────┘
     └──────────── ⑤ pstore/blk（崩溃时直接写进裸分区，跨掉电）───────────────┘
     └──────────── ⑥ EDL 直接读内存（内核完全没跑也能读）─────────────────────┘
```

| # | 通道 | 前提 | 覆盖范围 | 跨掉电 | 麻烦程度 |
|---|---|---|---|---|---|
| ① | 屏幕（fbcon） | simplefb 起来了 + 屏没被 ABL 关 | device_initcall 之后 | 否 | 最直观 |
| ② | USB 串口（CDC-ACM） | 内核跑到用户态 + dwc3 正常 | 用户态之后，可交互 | 否 | 中 |
| ③ | **USB U盘（FAT 镜像）** | 同上 | 用户态之后，**免终端软件** | 否 | **最低** |
| ④ | pstore / ramoops | 崩溃过 + 能再启动到 initramfs | 上一次崩溃的完整 log | **否**（DRAM 掉电丢） | 低 |
| ⑤ | pstore/blk → 裸分区 | 需先确认日志分区 | panic 当时的完整 log | **是** | 中 |
| ⑥ | EDL/firehose 读内存 | 能进 9008 | 同上（直接读 0xb0000000） | 否 | 高 |
| ⑦ | 信标颜色 + **上次进度标记** | 屏没被关（标记则不需要屏） | 极早期（postcore 之前） | 否（但跨热复位） | 低 |
| ⑧ | **panic 屏（二维码）** | 屏没被关 | **panic 当时的日志**，扫一下就拿到 | 否 | 低 |

**推荐顺序**：上机前先起 `watch-usb.ps1`（同时覆盖 ② 和 ③），屏幕当参考，④ 兜底。

> ⚠️ 有三个坑是「没有它们，前面全都白搭」的，已经修好：
> 1. **ramoops 尺寸**：原来 console+pmsg 把 4 MB 占满，`dump_mem_sz = 0`
>    → **dmesg 记录区一条都没有**，panic 时整段 log 存不进来。现在
>    `record 0x1000 + console 0x200000` → 2 MB 记录区 / 512 条。
> 2. **ring buffer 只有 128 KB**（`LOG_BUF_SHIFT=17`）→ 开机 log 一多，
>    panic 时开头早被冲掉。现在是 2 MB。
> 3. **`pstore.kmsg_bytes` 默认只有 10 KB** → pstore 每次快照的日志上限，
>    不显式放大就等于没有现场。现在 cmdline 里传了 `pstore.kmsg_bytes=2097152`
>    （那个 Kconfig 符号带 `if EXPERT`，在配置片段里写会被静默打回默认值）。

---

## 1. 通道①：屏幕

`console=tty0` + `simple-framebuffer`@0x9c000000 + `DRM_SIMPLEDRM` + fbcon。
内核内置 cmdline 里已经强制带上（`CONFIG_CMDLINE_FORCE=y`），不需要做任何事。

- **能看到字**：说明内核已经走完核心初始化（device_initcall 之后）→ 后面的 log 全在屏幕上。
- **看不到字**：**不代表内核没跑**，只说明要么还没到 device_initcall，要么屏被 ABL 关了。
- 屏幕上字滚动很快，来不及看就用手机拍照/录像，或直接用通道 ②③ 拿完整文件。

## 2. 通道②：USB 串口（实时交互）

initramfs 里默认就配好了 CDC-ACM gadget（`1D6B:0104`），绑定后：

```powershell
# Windows：插上手机后会出现「USB 串行设备 (COMx)」
powershell -ExecutionPolicy Bypass -File tools\watch-usb.ps1
# 它会：盯 USB 枚举 → 自动打开串口 → 内容同时打印并写入 out\usb-console.log
```

Linux/macOS：`screen /dev/ttyACM0 115200`。

连上以后直接敲：

```
dmesg | tail -100
cat /sys/fs/pstore/*        # 上一次崩溃的日志
cat /proc/cmdline
ls /sys/bus/platform/drivers
```

## 3. 通道③：USB U盘（最省事，推荐）

initramfs 里会现场做一个 16 MiB 的 FAT 镜像（busybox 的 `mkfs.vfat` + `loop`），
里面是这几个文件，然后作为大容量存储挂给电脑：

```
info.txt          内核版本 / cmdline / model / tty / fb
pstore.txt        上一次崩溃的 log（如果有）
dmesg.txt         本次开机完整 dmesg
partitions.txt    所有块设备 + 分区大小 + by-name 列表（很有用）
subsystems.txt    drm / udc / uart / ufs 等关键子系统的状态
```

插上手机 → Windows 直接出现一个盘符 → 打开 txt 复制出来。**不需要装驱动、不需要终端软件。**

> 如果 Windows 提示"需要格式化"：说明 FAT 镜像没做成功（busybox 的 mkfs.vfat 或 loop 不可用），
> 那就用通道 ②（串口）—— 两个功能是同时提供的，一个不行另一个还能用。

## 4. 通道④：pstore / ramoops —— 上一次崩溃的日志

**这是「内核没跑到用户态」时唯一的现场。** 原理：

1. ramoops 占着物理内存 `0xb0000000`（4 MiB，`console-size=0x200000`）。
2. 内核 panic/oops 时，`kmsg_dump` 会把**整个 printk ring buffer**写进这块内存
   （cmdline 里的 `printk.always_kmsg_dump=1` 保证连正常重启也 dump）。
3. **DRAM 在热复位后内容还在** → 再 `fastboot boot` 一次我们的镜像，
   initramfs 就会把它打出来（屏幕 + 串口 + U盘里的 `pstore.txt`）。

所以流程是：**崩一次 → 再 boot 一次 → 看 pstore**。

⚠️ 两个注意：
- 掉电（拔电池/长按电源关机）会丢。所以崩完**先别关机**，直接再 boot 一次。
- 如果内核是**卡死**（不是 panic），不会有 dump —— 这就是为什么要开
  `DETECT_HUNG_TASK` / `SOFTLOCKUP_DETECTOR` + `panic_on_oops`，把「卡死」变成「panic」。

## 5. 通道⑤：pstore/blk → 裸分区 → TWRP 读回（唯一跨掉电的）

panic 时直接把 log 写进一个裸分区，不需要用户态参与，而且**掉电也不丢**。

### 5.1 先确认哪个分区是日志区

证据（来自**这台设备自己**的下游 cmdline）：

```
block2mtd.block2mtd=/dev/block/sda15,2097152 mtdoops.mtddev=0 mtdoops.record_size=2097152
```

说明厂商就是用 **sda15 的前 2 MB 放内核崩溃日志**（mtdoops）。

再核对一次（三种方式任选）：
- 跑一次我们的镜像，看 U盘里的 `partitions.txt`（里面有每个 `/dev/sdXN` 的大小）；
  日志分区通常只有 2～32 MiB。
- TWRP 里：`ls -l /dev/block/by-name`
- fastboot：`fastboot getvar all`（会列出 `partition-size:xxx`）

### 5.2 启用

```powershell
# sda = 8:0，sdaN = 8:N → sda15 就是 8:15
wsl -d umi -u root -- sh <repo>/scripts/enable-pstore-blk.sh 8:15
```

脚本会把 `pstore_blk.blkdev=8:15 pstore_blk.best_effort=1` 加进内核 cmdline 并重编
（`best_effort=1` 是必须的：UFS 没有 `panic_write`，只能走普通可睡眠 I/O）。

> 内核里 `CONFIG_PSTORE_BLK=y` 已经编好，但**默认待机**：不给 `blkdev` 参数就完全不动作，
> 所以不开这个功能也不会有任何副作用。

### 5.3 读回来

```powershell
# 手机进 TWRP（TWRP 自带 root adb）
adb shell "dd if=/dev/block/sda15 of=/tmp/pstore.bin bs=4096 count=512"
adb pull /tmp/pstore.bin
python tools\parse-pstore.py pstore.bin -o out\pstore.txt
```

`parse-pstore.py` 会认 pstore zone 的 `DBGC` 魔数并解出文本；认不出来就退化成
「把可打印段全抠出来」，内核 log 本来就是纯文本，通常够用。

## 6. 通道⑥：EDL / firehose 直接读内存（内核完全没跑也能读）

ramoops 就在物理内存 `0xb0000000`，用 9008 模式的 firehose programmer 可以直接读：

```
# 手机进 9008（EDL）：adb reboot edl  或  fastboot oem edl
edl r 0xb0000000 0x400000 ramoops.bin
python tools\parse-pstore.py ramoops.bin -o out\ramoops.txt
```

- 地址和大小来自 DTS：`ramoops@b0000000 { reg = <0x0 0xb0000000 0x0 0x400000>; }`
- 需要小米的 firehose loader（`prog_firehose_ddr.elf`，在线刷包里）；有些机器读也要授权。
- **完全不需要内核能跑**，所以是最后的兜底。

## 7. 通道⑦：信标颜色 + 「上次走到哪一步」的标记

`scripts/add-beacon.sh` 编出来的内核做两件事：

**（a）屏幕上刷颜色**（postcore/arch/subsys/fs 四个 initcall 各一个颜色）：
黑 → 蓝 → 青 → 绿 → 黄 →（device_initcall 之后 fbcon 接管）。
卡在哪一段，屏幕颜色就停在哪一档。

**（b）把进度写进内存**（cont-splash 保留区的最后 4 KB —— 那块内存没人用，
而且**热复位不会被清掉**）。下次开机时，postcore 阶段会先把它读出来 printk：

```
UMI-BEACON: 上次启动走到 stage 4 = fs_initcall (标记版本 1, 上次是第 3 次带信标启动)
```

这一行的意义在于：**屏幕完全不亮也能知道上次卡在哪** —— 它会进 dmesg、
进 USB 串口、进 pstore（如果上次是 panic 的话）。

详见 RUNBOOK 步骤 F。

---

## 8. 通道⑧：panic 屏 + 二维码（扫一下就把 log 拿走）

**这是最舒服的一条路**：panic 时内核不管 console 有没有挂，直接把日志画进扫描缓冲；
开了二维码那档就把**压缩后的整段日志编成一个二维码**画在屏幕上。手机扫一下，
log 就到手了 —— 不用拍照抄字，也不用读串口。

### 8.1 已经配好了

```ini
CONFIG_DRM_SIMPLEDRM=y          # 只有 DRM 驱动能挂 drm_panic（simpledrm 实现了 get_scanout_buffer）
CONFIG_DRM_PANIC=y
CONFIG_DRM_PANIC_DEBUG=y        # debugfs 手动触发（下面 8.3 的自测就靠它）
CONFIG_FONT_TER16x32=y          # 1080x2340 屏上字大一点
CONFIG_DRM_PANIC_SCREEN="qr_code"
CONFIG_DRM_PANIC_SCREEN_QR_CODE=y
CONFIG_DRM_PANIC_SCREEN_QR_CODE_URL="https://umi.local/panic"
CONFIG_DRM_PANIC_SCREEN_QR_VERSION=40
CONFIG_RUST=y                   # 二维码生成器是 Rust 写的（drm_panic_qr.rs）
```

> 二维码生成器是**内核里第一个 Rust 组件**，所以内核要能编 Rust。
> 工具链用 `scripts/install-rust.sh` 装（rustc 1.82 + bindgen + libclang）。
> 没有 Rust 时这几个选项会被**静默**关掉 —— 所以 `build.sh` 专门校验它们。

三种样式可以在**运行时**切换，不用重编：

```
cmdline:            drm.panic_screen=qr_code | kmsg | user
运行时:             echo kmsg > /sys/module/drm/parameters/panic_screen
改默认值再重编:     scripts/set-panic-screen.sh kmsg
```

### 8.2 扫码之后怎么读

二维码里是 `<URL>?a=aarch64&v=6.12.94-umi&zl=<一长串数字>`（数字串是 13 bit 一组
写成 4 位十进制的 zlib 压缩日志）。用手机扫码 App 扫出来，把**整串**粘给解码器：

```powershell
python tools\decode-panic-qr.py "https://umi.local/panic?a=aarch64&v=6.12.94-umi&zl=0123456789..."
python tools\decode-panic-qr.py -f scanned.txt -o out\panic.txt    # 扫码 App 导出的文件
```

> 不想用解码器？把 `CONFIG_DRM_PANIC_SCREEN_QR_CODE_URL` 设成空字符串再重编，
> 二维码里就是**未压缩的日志文本**，随便什么扫码 App 直接就能看（代价是装的内容少 2/3）。

### 8.3 上机前先自测（不用真崩）

`CONFIG_DRM_PANIC_DEBUG=y` 会在 debugfs 里放一个触发点。initramfs 默认
**启动 60 秒后自动画一次 panic 屏**（`mkinitramfs.sh --test-panic N` 改秒数，
`--no-panic-test` 关掉），于是正常开机也能确认「这张屏扫不扫得出来」。

手动触发：

```
echo 1 > /sys/kernel/debug/dri/0/drm_panic_plane_0
```

> 想先看日志的话，趁那 60 秒看；日志同时也进了 U 盘和串口。

---

## 9. 一句话总结怎么用

```powershell
# 每次上机前
powershell -ExecutionPolicy Bypass -File tools\watch-usb.ps1     # 覆盖 ②③，自动存 out\usb-console.log

# 崩了之后（别关机）
fastboot boot out\boot-umi-p1.img                                 # 触发 ④，pstore 会自己打出来
# 想跨掉电留存 → 先 enable-pstore-blk.sh 8:15（通道⑤）
# 什么都起不来 → 通道⑥ EDL 读 0xb0000000
```
