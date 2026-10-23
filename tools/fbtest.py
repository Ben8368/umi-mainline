#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""fbtest.py — 生成一个「裸机 aarch64 打屏」测试内核

目的：把「ABL 到底有没有接受我们的镜像、有没有真的跳过去执行」这件事
和「Linux 内核有没有跑起来」彻底分开。

payload 做的事（MMU 关着、直接写物理地址）：
    把 0x9c000000 那块 ABL 留下的 cont-splash 帧缓冲
    全屏涂红 → 延时 → 全屏涂绿 → 延时 → 循环

屏幕开始红绿闪烁 = ABL 接受镜像、跳到 kernel 入口、帧缓冲地址/格式都对。
屏幕还是黑的    = 问题在 ABL/镜像格式/显示管线，跟 Linux 无关，别再瞎调内核。

★ 重要：payload **必须带完整的 arm64 Image 头**（64 字节，`ARM\\x64` 魔数在 offset 56）。
  ABL 的 UpdateKernelModeAndPkg() 靠「是不是 gzip / 有没有 Kernel64Hdr 魔数」来决定
  走 32 位还是 64 位引导路径。一个光秃秃的机器码 blob 会被当成 **32 位内核**，
  结果是黑屏几秒回 fastboot —— 和「ABL 拒绝了镜像」完全无法区分，
  等于让这个测试给出一个假的「屏被关了」结论。所以这里在代码前面拼了真头。

用法：
    python tools/fbtest.py -o out/fbtest.bin
    python tools/pack-umi.py --kernel out/fbtest.bin --name fbtest --no-initramfs
"""
import argparse
import os
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 1080x2340 的像素数
W, H = 1080, 2340
WORDS = W * H  # 2527200 = 0x268B20

ARM64_MAGIC = 0x644D5241
HDR_SIZE = 64          # arm64 Image 头长度（含 magic 和 res5）
ENTRY_OFF = 0x40       # 代码从 offset 64 开始


def asm(fb_addr=0x9C000000, delay=0x0F000000):
    hi = (fb_addr >> 16) & 0xFFFF
    w_low = WORDS & 0xFFFF
    w_high = (WORDS >> 16) & 0xFFFF
    d_high = (delay >> 16) & 0xFFFF
    return f"""
_start:
    movz x1, #{hi:#x}, lsl #16        // x1 = framebuffer base {fb_addr:#x}
    movz x4, #{w_low:#x}
    movk x4, #{w_high:#x}, lsl #16    // x4 = {WORDS} words (1080x2340x4)
    b blink
blink:
    movz w2, #0xff, lsl #16           // ARGB red
    bl fill
    bl delay
    movz w2, #0xff00                  // ARGB green (0x0000ff00)
    bl fill
    bl delay
    b blink
fill:
    mov x9, x1
    mov x8, x4
fill_loop:
    str w2, [x9], #4
    subs x8, x8, #1
    b.ne fill_loop
    ret
delay:
    movz x5, #{d_high:#x}, lsl #16    // ~0.3s spin
delay_loop:
    subs x5, x5, #1
    b.ne delay_loop
    ret
"""


def assemble(src, addr=0x8000 + ENTRY_OFF):
    from keystone import Ks, KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN
    ks = Ks(KS_ARCH_ARM64, KS_MODE_LITTLE_ENDIAN)
    enc, cnt = ks.asm(src, addr=addr)
    return bytes(enc), cnt


def build_header(code_len):
    """arm64 Image 头 64 字节。字段顺序见 Documentation/arch/arm64/booting.rst"""
    image_size = HDR_SIZE + code_len
    code0 = 0x14000000 | ((ENTRY_OFF // 4) & 0x03FFFFFF)   # b <offset 64>（PC 相对，位置无关）
    flags = 0x2 | 0x8        # bit1-2 = 1 (4K 页)，bit3 = 1 (48-bit reachable)
    return struct.pack("<IIQQQQQQII",
                       code0,            # 0:   code0 —— 跳到真正的入口
                       0,                # 4:   code1
                       0,                # 8:   text_offset（现代 arm64 为 0）
                       image_size,       # 16:  image_size
                       flags,            # 24:  flags
                       0, 0, 0,          # 32/40/48: res2/res3/res4
                       ARM64_MAGIC,      # 56:  magic 'ARM\\x64'
                       0)                # 60:  res5（EFI PE 头偏移，裸 payload 用 0）


def disasm(blob, addr=0x8000 + ENTRY_OFF):
    try:
        from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    except Exception:
        return None
    md = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    return "\n".join("   0x%04x: %-8s %s" % (i.address, i.bytes.hex(), i.mnemonic + " " + i.op_str)
                     for i in md.disasm(blob, addr))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "out", "fbtest.bin"))
    ap.add_argument("--fb-addr", type=lambda s: int(s, 0), default=0x9C000000)
    ap.add_argument("--delay", type=lambda s: int(s, 0), default=0x0F000000)
    ap.add_argument("--show", action="store_true", help="打印反汇编")
    a = ap.parse_args()

    src = asm(a.fb_addr, a.delay)
    code, cnt = assemble(src)
    print("== 汇编 %d 条指令，%d 字节（代码从 offset 0x%x 开始）" % (cnt, len(code), ENTRY_OFF))
    if a.show:
        d = disasm(code)
        print(d or "(装 capstone 才能反汇编)")

    hdr = build_header(len(code))
    blob = hdr + code
    assert len(hdr) == HDR_SIZE
    assert blob[56:60] == b"ARM\x64", "头部 magic 位置不对"

    os.makedirs(os.path.dirname(a.output), exist_ok=True)
    with open(a.output, "wb") as f:
        f.write(blob)
    print("== 写出 %s（%d 字节 = %d 字节头 + %d 字节代码）"
          % (a.output, len(blob), HDR_SIZE, len(code)))
    print("   自检：offset 0  = 0x%08x（b +0x%x → 入口）"
          % (struct.unpack_from("<I", blob, 0)[0], ENTRY_OFF))
    print("        offset 56 = %r  ← ABL 靠这个判定 64 位内核"
          % blob[56:60])
    print("        image_size= %d" % struct.unpack_from("<Q", blob, 16)[0])
    print("   打包： python tools/pack-umi.py --kernel %s --name fbtest --no-initramfs" % a.output)
    print("   期望：屏幕红绿交替闪烁；黑屏则说明问题在 ABL/镜像/显示管线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
