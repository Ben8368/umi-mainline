# 参考项目：MT6895-Mainline（小米 Redmi Note 11T Pro+ / xaga）

> https://github.com/MT6895-Mainline/
> 另一个「给手机移植主线」的项目，而且是**已经能日常使用**的那种
> （他们的 kernel 分支叫 `7.2-mt6895-xiaomi-xaga`，提交记录里已经在调视频编解码
> 性能、指纹、ModemManager 了 —— 说明 bring-up 阶段早就过去了）。
> 他们的机器是联发科 MT6895，SoC 不同，但**无 UART 盲调这件事是一样的**。
>
> 下面是逐条对照：哪些做法我们直接采纳了，哪些不适用。

---

## 1. 他们有哪些仓库

| 仓库 | 内容 | 对我们有用吗 |
|---|---|---|
| `linux` | 内核（7.2 分支），含 `arch/arm64/configs/xaga.config` 配置片段、`mt6895-xiaomi-xaga.dts` | **有用**（配置片段做法、bring-up 显示路线） |
| `initramfs` | **无 libc 的 C 版 init** + 固件 | **很有用**（`/dev/kmsg` 技巧） |
| `rootfs` | 根文件系统脚本 | 以后有用 |
| `quirks` | 音频 UCM、麦克风切换 | 不适用 |
| `mtk-mod-tee-nogz` / `mtk-ccci-userspace` / `modemmanager-mtk-soc` / `fpc1540-ta` / `libfprint` / `vaapi-mtk-vcp` | TEE、Modem、指纹、视频编解码 | 不适用（MTK 专用或后期阶段） |

## 2. 直接采纳的（已经改进到我们工作区里）

### 2.1 ⭐ ramoops 尺寸算错 —— 这是他们帮我发现的真 bug

他们 `xaga.config` 里专门为 pstore 写了一段注释：

> ```
> # --- pstore/ramoops: capture the previous boot's console across a WDT reset.
> # The region (0x48090000, 0xe0000) is reserved in the xaga DTS ramoops node,
> # matching the one LK passes via cmdline. Keep RAM built-in so a hang in late
> # boot still has a registered backend.
> CONFIG_PSTORE=y
> CONFIG_PSTORE_DEFAULT_KMSG_BYTES=10240
> CONFIG_PSTORE_COMPRESS=y
> CONFIG_PSTORE_CONSOLE=y
> CONFIG_PSTORE_PMSG=y
> CONFIG_PSTORE_RAM=y
> ```

「**across a WDT reset**」这四个字很关键：他们和我独立得出了同一个结论 ——
**看门狗复位是这类黑屏的头号嫌疑**，而 ramoops 是唯一能跨复位拿到现场的东西。

顺着这条线我回去核对了我们自己的 ramoops 尺寸，发现**我们原来是错的**：

`fs/pstore/ram.c` 的 `ramoops_probe()` 是这么算布局的：

```c
	dump_mem_sz = cxt->size - cxt->console_size - cxt->ftrace_size - cxt->pmsg_size;
	ramoops_init_przs("dmesg", ..., dump_mem_sz, cxt->record_size, &cxt->max_dump_cnt, ...);
```

我们原来写的是 `record 0x10000 + console 0x200000 + pmsg 0x200000 = 0x410000`，
**比 4 MB 的区域还大** → `dump_mem_sz = 0` → **dmesg 记录区一条都建不出来** →
panic 时整段 ring buffer 根本存不进去，只剩 console 区（从 `late_initcall`
才开始记）能留点东西。

**已修**：改成和 elish（已知能跑的 SM8250 主线移植）一致：

```dts
	ramoops@b0000000 {
		reg = <0x0 0xb0000000 0x0 0x400000>;
		record-size  = <0x1000>;     /* 4 KB 一条 */
		console-size = <0x200000>;   /* 2 MB 常驻 console 区 */
		ecc-size     = <16>;
	};
	/* dump_mem_sz = 4 MB - 2 MB = 2 MB → 512 条 dmesg 记录 ✓ */
```

顺带把 ring buffer 从 128 KB（`LOG_BUF_SHIFT=17`）放大到 2 MB，
否则开机 log 一多，panic 时开头早被冲掉了。

### 2.1b ⭐ 还有第二个坑：pstore 每次只快照 10 KB

顺着 `PSTORE_DEFAULT_KMSG_BYTES` 这条线又挖出一个：

```c
/* fs/pstore/platform.c */
unsigned int kmsg_bytes = CONFIG_PSTORE_DEFAULT_KMSG_BYTES;   /* 默认 10240 */
module_param(kmsg_bytes, uint, 0444);
MODULE_PARM_DESC(kmsg_bytes, "amount of kernel log to snapshot (in bytes)");
```

pstore 在 panic 时**最多只快照 `kmsg_bytes` 字节的日志**，而默认值是 **10240（10 KB）**
—— 对一个开机日志几十上百 KB 的内核来说等于没有。

而且这个 Kconfig 符号带 `if EXPERT`：

```
config PSTORE_DEFAULT_KMSG_BYTES
	int "Default kernel log storage space" if EXPERT
	depends on PSTORE
	default "10240"
```

`EXPERT` 不开时它**没有提示符** → 你在配置片段里写 `=2097152` 会被 `olddefconfig`
直接打回默认值（我就是这么踩的，编完一看 `.config` 里还是 10240）。

**正确做法**：走 cmdline 上的 module_param：

```
pstore.kmsg_bytes=2097152
```

**已修**：加进 `CONFIG_CMDLINE`，正好和 2 MB 的 dump 区、2 MB 的 ring buffer 对齐。

### 2.2 ⭐ 用 `/dev/kmsg` 当用户态日志通道

他们的 `init.c` 整个 init 只有一种输出方式：

```c
	g_kmsg_fd = openat(AT_FDCWD, "/dev/kmsg", O_WRONLY, 0);
	...
	write_(g_kmsg_fd, s, strlen_(s));
```

好处是**一次写入同时拿到三件事**：
1. 内核会自动把它打到 console（也就是屏幕）上，不用自己再写 tty0；
2. 它进了 printk ring buffer → 会随 `kmsg_dump` 一起进 ramoops；
3. 于是「initramfs 走到哪一步」这件事在**下次崩溃的日志里**也能看到。

**已采纳**：我们 initramfs 的 `say()` 现在优先写 `/dev/kmsg`（写不进去才退回 tty0）。
注意大段内容（上一次崩溃的 log）**不**写 kmsg —— 那会把 ring buffer 冲掉。

### 2.3 ⭐ bring-up 阶段用 fbdev simplefb，而不是 DRM simpledrm

他们 bring-up 配置（`xaga.config`）里是：

```
# Simple framebuffer + fbcon for the LK logo/early display
CONFIG_FB=y
CONFIG_FB_SIMPLE=y
CONFIG_FRAMEBUFFER_CONSOLE=y
CONFIG_FRAMEBUFFER_CONSOLE_DETECT_PRIMARY=y
```

**没有 DRM**（DRM 是他们后面接显示驱动时才加的）。理由是少一层就少一个失败点：
simplefb 就是 `ioremap + register_framebuffer`，不经过 DRM core / KMS / GEM。

**已采纳**：bring-up 镜像改成 `FB_SIMPLE`，并把 `DRM_SIMPLEDRM` 明确关掉
（两个驱动都匹配 `"simple-framebuffer"`，同时开就变成"谁先 probe 谁占坑"的不确定行为）。
想切回去随时用 `scripts/set-console-path.sh simpledrm`。

### 2.4 配置片段 + `merge_config.sh` 的做法

他们用 `arch/arm64/configs/xaga.config` 片段，注释里写明：

```
# Merge on top of the arm64 defconfig:
#   scripts/konfig/merge_config.sh arch/arm64/configs/defconfig arch/arm64/configs/xaga.config
```

和我们 `config/umi.config` 的做法完全一样 ✓（说明这条路是对的，不用改）。

### 2.5 「内核里没有 /lib/modules，所以关键驱动必须 =y」

他们反复强调这一点，例如：

> `# MT6319 external CPU bucks (spmi USID 6/7). Must be built-in: the target
> # rootfs has no /lib/modules, so =m would never load.`

**这条直接解释了我们的看门狗问题**：主线 arm64 defconfig 里 `CONFIG_QCOM_WDT=m`，
而我们的 initramfs 里没有模块 → 看门狗永远不会被喂 → ABL 留下的狗一咬就是复位。
（我们已经改成 `=y` 了。）

---

## 3. 记下来但暂时用不上的

### 3.1 panic 时把 log 画成二维码（`CONFIG_DRM_PANIC` + QR）—— **已抄过来**

他们开了：

```
CONFIG_DRM_PANIC=y
CONFIG_DRM_PANIC_DEBUG=y
CONFIG_FONT_TER16x32=y
CONFIG_DRM_PANIC_SCREEN_QR_CODE=y
CONFIG_DRM_PANIC_SCREEN="qr_code"
```

注释说得很清楚：

> `# DRM panic: render the panic kmsg (or QR) onto the panel via drm_panic.`
> `# --- Panic screen: QR encoding the compressed kmsg, scannable from a photo.`

**拿手机拍一张屏幕，就能把 panic 日志读出来** —— 无串口调试最漂亮的一招。

#### 抄过来时踩到的东西

1. **二维码生成器是 Rust 写的**（`drivers/gpu/drm/drm_panic_qr.rs`，内核里第一个 Rust 组件），
   所以 `CONFIG_DRM_PANIC_SCREEN_QR_CODE` 的依赖是 `DRM_PANIC && RUST`。
   他们的配置注释也提了：*"Needs the Rust toolchain pinned in build-xaga-work-7.2-lz4.sh
   (RUST_DIR). Use "kmsg" instead of "qr_code" if building without Rust."*
   → 我们用 `scripts/install-rust.sh` 装了 **rustc 1.82.0**（和 6.12 同期，
   比 Alpine 自带的 1.96 稳）+ rust-src 组件 + bindgen。
   还差一个坑：**bindgen 需要 `libclang.so`**，Alpine 默认只装了
   `clang22-libs`（`libclang-cpp.so`），要另外装 **`clang22-libclang`**，
   再给它 `LIBCLANG_PATH=/usr/lib/llvm22/lib`。这三样齐了 `make rustavailable`
   才会说 "Rust is available!"。
2. **没有 Rust 时这些选项会被静默关掉**（Kconfig 里 `RUST_IS_AVAILABLE` 是
   Makefile 探出来的），配置片段里写了 `=y` 也不会报错 —— 只是二维码没了。
   所以 `build.sh` 现在专门校验 `RUST=y` 和 `DRM_PANIC_SCREEN_QR_CODE=y`。
3. **`drm_panic` 需要 KMS 驱动实现 `get_scanout_buffer`**。他们的驱动里有；
   我们暂时没有面板驱动，但 **`simpledrm` 也实现了**（`drivers/gpu/drm/tiny/simpledrm.c`），
   所以不用等面板驱动就能用。代价是出字路线必须走 DRM（不能用 fbdev simplefb）——
   这也是把默认配置从 `FB_SIMPLE` 改回 `DRM_SIMPLEDRM` 的原因。
4. **二维码里装什么**由 `CONFIG_DRM_PANIC_SCREEN_QR_CODE_URL` 决定：
   - 留空 → 二维码里直接是未压缩日志文本，随便什么扫码 App 都能看（但装得少）；
   - 填了 → `<URL>?a=<arch>&v=<版本>&zl=<数字串>`，数字串是 13 bit 一组写成
     4 位十进制的 **zlib 压缩**日志，能装 3 倍内容，但要解码器还原。
     官方解码器是 https://github.com/kdj0c/panic_report ；
     我们也写了个离线的 `tools/decode-panic-qr.py`（已做往返测试）。
5. **可以不用真崩就验证**：`CONFIG_DRM_PANIC_DEBUG=y` 会在 debugfs 里放
   `dri/<N>/drm_panic_plane_<N>`，写 1 就画一次。我们的 initramfs 默认
   启动 60 秒后自动触发一次，方便先确认"扫不扫得出来"。

### 3.2 无 libc 的 C 版 init

他们的 `init.c` 用裸系统调用（`svc 0` + 手写 `ksys()`）写了一个 13 KB 的静态 init，
编译方式是：

```
aarch64-linux-gnu-gcc -nostdlib -static -fno-stack-protector \
    -fno-builtin -ffreestanding -Os -o root/init init.c
```

好处是不依赖 busybox（initramfs 只有十几 KB）。我们用的是静态 busybox（660 KB），
换来的是完整的 shell / mount / mkfs.vfat / dd，对我们这种"要把 log 弄出来"的场景更值。
**不过**：如果他们这套思路后面被证明更稳（比如 busybox 在我们的内核上跑不起来），
这是个现成的退路 —— 写一个只做 `mount devtmpfs/proc/sys` + 往 `/dev/kmsg` 打日志的
最小 init，几十行就够。

### 3.3 从分区里搬固件（nvdata → rootfs）

他们 init 里最长的两段代码是：挂 `nvdata` 分区（只读），把 WiFi NVRAM / BT 地址 /
触摸固件拷到 rootfs 的 `/lib/firmware`，注释解释了为什么必须拷：

> `The WiFi driver is loaded after switch_root, so both the NVRAM blob and the
> connectivity firmware must be on the real rootfs (not the initramfs tmpfs).`

**对我们是第 4/5 阶段的事**：我们的 `sm8250-xiaomi-umi-plus.dts` 里 qca6390 WiFi/BT
需要固件（`qca6390` 的 `amss20.bin` 等，`<old-dump>\firmware_extracted\`
里已经有一份）。到时候同样要处理「initramfs 里的固件在 switch_root 后消失」的问题。

### 3.4 硬编码分区号 + 先列一遍磁盘

他们 `init.c` 里 `BOOT_PARTITION "/dev/sdc86"`、`NVDATA_PARTITION "/dev/sdc13"` 是写死的，
但前面有一句 `list_disks()` 先把 `/dev/sd*` 全打出来 —— 就是靠这个把号找出来的。

我们的 initramfs 也是这个思路（`partitions.txt` 里打全部块设备 + by-name），
而且我们更进一步：**不写死**，靠 `--dump-partition` 参数指定。

### 3.5 启动标记（`CONFIG_XAGA_MARKER_WRITER`）

他们有一个自己的 "xaga boot marker writer" 驱动（配置片段里一行 `CONFIG_XAGA_MARKER_WRITER=y`），
从名字看就是记录启动进度用的 —— 和我们的 `umi-beacon` 是同一个思路。

**我们做得更全一点**：beacon 除了在屏幕上刷颜色（黑/蓝/青/绿/黄），
还把进度写进 cont-splash 保留区最后 4 KB，下次开机先把上次的进度 printk 出来：

```
UMI-BEACON: 上次启动走到 stage 4 = fs_initcall (标记版本 1, 上次是第 3 次带信标启动)
```

这样即使**屏幕完全不亮**，也能知道上次卡在哪一段（这行会进 dmesg / USB 串口 / pstore）。

---

## 4. 明确不适用的

- 所有 `MTK_*` 驱动、`mtk-mod-tee-nogz`（改 TEE）、`mtk-ccci-userspace`（MTK Modem）、
  `vaapi-mtk-vcp`（MTK 视频编解码）、`fpc1540-ta` / `libfprint`（他们的指纹方案）——
  都是联发科或机型专用。
- 他们的 Waydroid / netfilter / overlayfs 那一大段是**跑容器**用的，属于后期。
- MTK 的引导链（LK + `boot.img`/`vendor_boot`）和高通 ABL 完全不同，
  **boot 镜像打包那一套不能照搬**（我们这边的坑是 v2 头 + dtb 段 + board-id）。

---

## 5. 一句话总结

他们最大的价值不是代码，而是**验证了我们的方向**：

1. 「黑屏 → 看门狗复位 → 用 ramoops 跨复位捞日志」这条链是对的（他们也这么干）；
2. bring-up 阶段显示走最简单的那条路（fbdev simplefb）；
3. 用户态日志写 `/dev/kmsg`，让它在内核日志里留下痕迹；
4. 关键驱动必须编进内核（没有 `/lib/modules`）。

以及**帮我们抓到一个真 bug**：ramoops 尺寸算错，dmesg 记录区为 0。
