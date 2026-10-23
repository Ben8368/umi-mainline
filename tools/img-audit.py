#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""img-audit.py — 校验 arm64 Image / Image.gz 头，以及 kernel 负载类型

为什么单独做这个工具：Qualcomm ABL 的 UpdateKernelModeAndPkg() 靠「负载是不是 gzip /
有没有 ARM\\x64 魔数」来判定 64 位内核。判错了它就走 32 位路径，结果是
**黑屏几秒直接回 fastboot**，和 DTB 挑不到、看门狗复位长得一模一样，
在开发机上却完全看不出来（内核本身是好的）。

输出里 image_size > 实际解压长度是**正常的**：arm64 的 Image 是 objcopy 出来的
二进制，.bss 是 NOBITS 不在文件里，而 image_size 字段算的是 _end - _stext。
装载器按 image_size 预留、内核自己清 BSS。

用法：
    python tools/img-audit.py                      # 默认 out/Image.gz
    python tools/img-audit.py out/Image.gz 0x80080000   # 指定一个候选装载地址
"""
import os
import struct
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ARM64_MAGIC = 0x644D5241


def unpack_payload(raw):
    """返回 (Image 字节, 类型, 尾随数据长度)。类型：gzip / raw / lz4 / zstd / xz / unknown"""
    if raw[:2] == b"\x1f\x8b":
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        img = d.decompress(raw) + d.flush()
        return img, "gzip", len(d.unused_data)
    if raw[:4] == b"\x28\xb5\x2f\xfd":
        return b"", "zstd", 0
    if raw[:4] == b"\x04\x22\x4d\x18":
        return b"", "lz4", 0
    if raw[:6] == b"\xfd7zXZ\x00":
        return b"", "xz", 0
    if raw[56:60] == b"ARM\x64":
        # 裸 arm64 Image：magic 在 offset 56。offset 0 是 code0（一条 b 指令），
        # 所以**不能**用 raw[:4] 判断 —— 那样会把每个合法的裸 Image 都判成坏的。
        return raw, "raw(Image)", 0
    return b"", "unknown", 0


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(WS, "out", "Image.gz")
    if not os.path.isfile(path):
        print("!! 找不到 %s" % path)
        return 2
    raw = open(path, "rb").read()
    img, kind, trailing = unpack_payload(raw)

    print("== %s" % path)
    print("   文件         : %d 字节 (0x%x)" % (len(raw), len(raw)))
    print("   负载类型     : %s" % kind)
    bad = 0

    # ---------------------------------------------------- ABL 的 32/64 位判别
    if kind == "gzip":
        if trailing:
            print("   ·   gzip 流后有 %d 字节尾随数据（Image.gz-dtb 形态，正常）" % trailing)
        if img[56:60] == b"ARM\x64":
            print("   OK  gzip + ARM\\x64 → ABL 走 64 位路径")
        else:
            print("   !! gzip 里没有 ARM\\x64 魔数 → ABL 可能按 32 位内核处理（黑屏回 fastboot）")
            bad += 1
    elif kind == "raw(Image)":
        print("   OK  裸 arm64 Image（offset 0 有 ARM\\x64）")
        print("   ·   注意：裸 Image 有 47 MB，会明显拖慢 fastboot 传输")
    else:
        print("   !! 负载类型 %r 不被 ABL 认可（它只认 gzip / 裸 ARM64 Image /"
              " 'UNCOMPRESSED_IMG'+20 字节头）→ 走 32 位路径，黑屏回 fastboot" % kind)
        bad += 1
        print("\n== 结论：不可引导（继续往下看头信息也没意义，但仍然输出供参考）")

    if not img:
        print("\n== 结论：有 %d 处致命问题" % max(bad, 1))
        return 1

    # ---------------------------------------------------- arm64 Image 头
    print("   解压后 Image : %d 字节 (0x%x)" % (len(img), len(img)))
    code0, code1 = struct.unpack_from("<II", img, 0)
    text_offset, image_size, flags = struct.unpack_from("<QQQ", img, 8)
    res2, res3, res4, magic = struct.unpack_from("<QQQI", img, 32)
    res5 = struct.unpack_from("<I", img, 56)[0]
    print("   code0/code1  : 0x%08x 0x%08x" % (code0, code1))
    print("   text_offset  : 0x%x" % text_offset)
    print("   image_size   : 0x%x (%d)  ← 装载器要按这个数预留（含 .bss）"
          % (image_size, image_size))
    pg = (flags >> 1) & 3
    print("   flags        : 0x%x  endian=%s page_size=%s"
          % (flags, "BE" if flags & 1 else "LE",
             {0: "unspecified", 1: "4K", 2: "16K", 3: "64K"}[pg]))
    print("   magic        : 0x%08x  %s"
          % (magic, "OK ('ARM\\x64')" if magic == ARM64_MAGIC else "!! 不是 arm64 Image"))
    if magic != ARM64_MAGIC:
        bad += 1
    if pg != 1:
        print("   !! 页大小不是 4K —— 和设备 DT / 页表假设不一致")
        bad += 1
    if res2 or res3 or res4:
        print("   !! 保留字段非 0：0x%x 0x%x 0x%x" % (res2, res3, res4))
        bad += 1
    if text_offset:
        print("   !! text_offset=0x%x 非 0 —— 现代 arm64 应为 0" % text_offset)
        bad += 1
    if image_size < len(img):
        print("   !! image_size 比实际文件还小（异常）")
        bad += 1
    else:
        print("   ·  BSS/填充 = %d 字节（image_size - 文件大小，正常，内核自己清零）"
              % (image_size - len(img)))

    print("\n   -- 解压后落在哪 --")
    bases = [0x80080000, 0x80000000]
    if len(sys.argv) > 2:
        bases = [int(sys.argv[2], 0)]
    for b in bases:
        end = b + image_size
        print("   @0x%09x .. 0x%09x  (%d MiB)" % (b, end, image_size // (1024 * 1024)))
        if b & 0xFFFFF:
            print("        · 不是 1 MiB 对齐（arm64 只要求「2MB 对齐基址 + text_offset」，"
                  "text_offset=0 时严格说要求 2MB 对齐）")
        if end >= 0x1_0000_0000:
            print("        !! 超过 4 GiB，低地址 DDR 装不下")

    print("\n== 结论：%s" % ("通过" if not bad else "有 %d 处不对" % bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
