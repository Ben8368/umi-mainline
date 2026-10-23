#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""pack-umi.py — 把 out/ 里的产物打成能 `fastboot boot` 的 boot.img

两种 DTB 投递方式（ABL 两条路都认，任一条坏了另一条就是对照组）：

  v2 段（默认）   header_version=2，DTB 放进头的 dtb 段（dtb_size/dtb_addr）。
                  ABL 的 CheckImageHeader / ImageSize 会算上 dtb_size。
                  ★ dtb_size=0 时 ABL 返回 EFI_NOT_FOUND 直接掉回 fastboot，所以
                  这个字段为 0 一定不能用。

  v0 追加         header_version=0，DTB 直接拼在 Image.gz 的 gzip 流后面
                  （Image.gz-dtb），dtb_size=0，ABL 靠 DeviceTreeAppended() 扫。
                  这是 pmOS 的 device-xiaomi-elish 用的老路子。

用法：
    python tools/pack-umi.py                              # 默认 v2，阶段 1 镜像
    python tools/pack-umi.py --dtb-mode v0-append --name p1-v0
    python tools/pack-umi.py --template stock-boot.img
    python tools/pack-umi.py --kernel out/fbtest.bin --name fbtest --no-initramfs

打包前会做三项硬校验（都是「上机才会发现、而且回不来」的那类错）：
  1. kernel 段必须是 gzip（ABL 靠 gzip 魔数判定 64 位内核，否则走 32 位路径直接死）
  2. gzip 解出来的 Image 必须带 ARM\\x64 魔数
  3. DTB 必须是合法 FDT，且 < 2 MiB（ABL 的 DT_SIZE_2MB）
"""
import argparse
import gzip
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bootimg import BootImg, DEF_DTB_ADDR  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(WS, "out")

FDT_MAGIC = b"\xd0\x0d\xfe\xed"
GZIP_MAGIC = b"\x1f\x8b"
ARM64_MAGIC = b"ARM\x64"          # Image 头 offset 56
DTB_MAX = 2 * 1024 * 1024         # ABL 的 DT_SIZE_2MB

# 必须和 config/umi.config 里的 CONFIG_CMDLINE 保持一致：
# 内核开了 CMDLINE_FORCE=y，实际生效的是内核里那一份，这里只是别让两边看着不一样。
DEFAULT_CMDLINE = (
    "console=ttyMSM0,115200n8 console=tty0 loglevel=8 keep_bootcon earlycon "
    "pd_ignore_unused clk_ignore_unused printk.always_kmsg_dump=1 "
    "pstore.kmsg_bytes=2097152"
)


def run_check(dtb):
    """调用 dtb.py ids 校验 msm-id/board-id，返回是否通过"""
    tool = os.path.join(WS, "tools", "dtb.py")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, tool, "ids", dtb],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    print((r.stdout or "").rstrip())
    if r.returncode != 0:
        print((r.stderr or "").rstrip())
    return r.returncode == 0


def check_kernel_payload(blob, what="kernel"):
    """ABL 的 UpdateKernelModeAndPkg()：不是 gzip / 没有 ARM\\x64 就按 32 位内核处理。

    这类错误在开发机上完全看不出来（内核本身没问题），上机就是「黑屏几秒回 fastboot」，
    所以放在打包器里拦。"""
    problems = []
    if blob[:2] == GZIP_MAGIC:
        try:
            img = gzip.decompress(blob)
        except Exception as e:                      # noqa: BLE001
            problems.append("%s 是 gzip 但解压失败：%s" % (what, e))
            return problems
        if img[56:60] != ARM64_MAGIC:
            problems.append("%s 解压后 offset 56 不是 ARM\\x64 魔数 → 不是 arm64 Image"
                            % what)
        if not img[:4]:
            problems.append("%s 解压后是空的" % what)
        return problems
    if blob[56:60] == ARM64_MAGIC:
        # 裸 arm64 Image：magic 在 offset 56（**不是** offset 0 —— offset 0 是 code0，
        # 一条 b 指令）。这里以前写成 blob[:4] 是错的，会把合法的裸 Image 判成坏镜像。
        return []
    if blob[:4] == b"UNCO":                      # "UNCOMPRESSED_IMG" 形式
        return []
    problems.append("%s 既不是 gzip，也不带 offset 56 的 ARM\\x64 魔数（前 8 字节 %s）"
                    " —— ABL 会把它当 32 位内核，直接黑屏回 fastboot"
                    % (what, blob[:8].hex()))
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", default=os.path.join(OUT, "Image.gz"))
    ap.add_argument("--dtb", default=os.path.join(OUT, "sm8250-xiaomi-umi.dtb"))
    ap.add_argument("--initramfs", default=os.path.join(OUT, "initramfs.cpio.gz"))
    ap.add_argument("--no-initramfs", action="store_true")
    ap.add_argument("--os-version-int", type=lambda s: int(s, 0), default=None,
                    help="boot 头里的 os_version（原厂 umi 是 436208003 = 13.0.0）")
    ap.add_argument("--dtb-mode", choices=("v2", "v0-append"), default="v2",
                    help="v2 = DTB 放头的 dtb 段（默认）；v0-append = Image.gz-dtb")
    ap.add_argument("--template", help="原厂 boot.img：继承地址/page_size/cmdline")
    ap.add_argument("--cmdline", default=None)
    ap.add_argument("--name", default=None, help="输出名后缀：out/boot-umi-<name>.img")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--force", action="store_true", help="即使校验不过也继续")
    a = ap.parse_args()

    for f in (a.kernel, a.dtb):
        if not os.path.isfile(f):
            print("!! 缺少 %s" % f)
            return 2

    # ---------------------------------------------------------------- 硬校验
    fatal = []
    print("== 校验 kernel 段（ABL 的 32 位/64 位判别）")
    with open(a.kernel, "rb") as f:
        kernel = f.read()
    for p in check_kernel_payload(kernel):
        fatal.append(p)
        print("   !! " + p)
    if not fatal:
        print("   OK  gzip + ARM\\x64，ABL 会走 64 位路径")

    print("== 校验 DTB（ABL 匹配属性）")
    if not run_check(a.dtb) and not a.force:
        print("!! DTB 校验不过，先修 DTS 再打包（--force 可强行继续）")
        return 3
    with open(a.dtb, "rb") as f:
        dtb = f.read()
    if dtb[:4] != FDT_MAGIC:
        fatal.append("dtb 不是合法 FDT（前 4 字节 %r）" % dtb[:4])
        print("   !! " + fatal[-1])
    if len(dtb) >= DTB_MAX:
        fatal.append("dtb 有 %d 字节，超过 ABL 的 2 MiB 上限" % len(dtb))
        print("   !! " + fatal[-1])
    if not fatal:
        print("   OK  FDT, %d 字节 (< 2 MiB)" % len(dtb))

    if fatal and not a.force:
        print("!! 有 %d 处硬错误，已中止（--force 可强行继续，但大概率浪费一次上机）"
              % len(fatal))
        return 3

    # ---------------------------------------------------------------- 组头
    b = BootImg()
    b.header_version = 2 if a.dtb_mode == "v2" else 0
    b.page_size = 4096
    b.kernel_addr = 0x00008000
    b.ramdisk_addr = 0x01000000
    b.tags_addr = 0x00000100
    b.dtb_addr = DEF_DTB_ADDR
    b.cmdline = (a.cmdline or DEFAULT_CMDLINE).encode()
    b.name = b"umi-mainline"

    if a.template:
        t = BootImg.load(a.template)
        print("== 模板 %s: page=%d hdr=%d kernel@0x%x ramdisk@0x%x tags@0x%x dtb@0x%x"
              % (os.path.basename(a.template), t.page_size, t.header_version,
                 t.kernel_addr, t.ramdisk_addr, t.tags_addr, t.dtb_addr))
        print("   模板 cmdline: %r" % t.cmdline_str())
        b.page_size = t.page_size or 4096
        b.os_version = t.os_version          # ★ ABL 的 boot_verify 会看这个；原厂 13.0.0
        b.name = b""                         # 原厂 name 是空的，别给自己加变量
        b.kernel_addr = t.kernel_addr or b.kernel_addr
        b.ramdisk_addr = t.ramdisk_addr or b.ramdisk_addr
        b.tags_addr = t.tags_addr or b.tags_addr
        b.dtb_addr = t.dtb_addr or b.dtb_addr

    if a.os_version_int is not None:
        b.os_version = a.os_version_int
        print("== os_version = %d" % b.os_version)
    if a.dtb_mode == "v0-append":
        # Image.gz + DTB 直接拼在一起；头部 dtb_size=0，ABL 用 DeviceTreeAppended() 扫
        b.kernel = kernel + dtb
        b.dtb = b""
        b.dtb_size = 0
        print("== DTB 模式 v0-append：DTB(%d) 拼在 Image.gz 尾部，dtb_size=0" % len(dtb))
    else:
        b.kernel = kernel
        b.dtb = dtb
        b.dtb_size = len(dtb)
        print("== DTB 模式 v2：dtb_size=%d, dtb_addr=0x%x" % (b.dtb_size, b.dtb_addr))
    b.kernel_size = len(b.kernel)

    if not a.no_initramfs:
        if not os.path.isfile(a.initramfs):
            print("!! 缺少 %s（先跑 scripts/mkinitramfs.sh）" % a.initramfs)
            return 2
        with open(a.initramfs, "rb") as f:
            b.ramdisk = f.read()
        b.ramdisk_size = len(b.ramdisk)
    else:
        b.ramdisk = b""
        b.ramdisk_size = 0

    suffix = a.name or ("p1" if a.dtb_mode == "v2" else "p1-" + a.dtb_mode)
    out = a.output or os.path.join(OUT, "boot-umi-%s.img" % suffix)
    with open(out, "wb") as f:
        f.write(b.pack())

    print("== 写出 %s (%d 字节)" % (out, os.path.getsize(out)))
    v = BootImg.load(out)
    v.dump(os.path.basename(out))

    # ---------------------------------------------------------------- 自检
    ok = True
    def chk(cond, msg):
        nonlocal ok
        if not cond:
            print("!! 自检失败：%s" % msg)
            ok = False

    chk(v.header_version == b.header_version, "header_version=%d" % v.header_version)
    chk(v.kernel_size == b.kernel_size, "kernel_size 对不上")
    if a.dtb_mode == "v2":
        chk(v.dtb_size == b.dtb_size, "dtb_size 对不上")
        chk(v.dtb[:4] == FDT_MAGIC, "dtb 段不是 FDT")
        chk(v.header_size == 1660, "header_size=%d（应为 1660）" % v.header_size)
        chk(v.dtb_size > 0, "dtb_size=0 → ABL 会 EFI_NOT_FOUND 掉回 fastboot")
    else:
        chk(v.dtb_size == 0, "v0 模式下 dtb_size 必须为 0")
        tail = v.kernel[-len(dtb):]
        chk(tail[:4] == FDT_MAGIC, "kernel 尾部不是 FDT")
    chk(v.ramdisk_size == b.ramdisk_size, "ramdisk_size 对不上")

    print("== 自检 %s" % ("通过" if ok else "失败"))
    if ok:
        print("")
        print("注意：头里的 cmdline 是**装饰性的** —— 内核开了 CONFIG_CMDLINE_FORCE=y，")
        print("      真正生效的是编译进 Image 的那一份。要改 cmdline 必须重编内核。")
        print("下一步（手机进 fastboot 后）：")
        print("    fastboot boot %s" % os.path.basename(out))
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
