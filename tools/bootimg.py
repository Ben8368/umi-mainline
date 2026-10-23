#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""bootimg.py — Android boot image (header v0/v1/v2) 解析 / 解包 / 打包工具

小米10 (umi, SM8250) 的 bootloader 走的是 Android boot image v2：
    ANDROID! | 4096B 头 | kernel | ramdisk | second | recovery_dtbo | dtb
ABL 会从 dtb 段里按 qcom,msm-id / qcom,board-id 挑 DTB。
老版本的 mkbootimg.py 把 dtb_size 写成 0（DTB 塞在 kernel 尾部），
ABL 拿不到匹配的 DTB 就直接掉回 fastboot —— 这是黑屏几秒回 fastboot 的头号嫌疑。

用法：
    python bootimg.py info  boot.img
    python bootimg.py unpack boot.img -d outdir
    python bootimg.py pack --kernel Image.gz --dtb sm8250-xiaomi-umi.dtb \
        --ramdisk initramfs.cpio.gz --cmdline "..." -o new-boot.img
    python bootimg.py pack --template stock-boot.img --kernel Image.gz \
        --dtb sm8250-xiaomi-umi.dtb -o new-boot.img     # 从原厂镜像继承地址/cmdline
"""
import argparse
import gzip
import hashlib
import os
import struct
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAGIC = b"ANDROID!"
FDT_MAGIC = b"\xd0\x0d\xfe\xed"
GZIP_MAGIC = b"\x1f\x8b"

# 常见默认值（小米/高通 kona 平台，原厂 boot.img 用的就是这套）
DEF_KERNEL_ADDR = 0x00008000
DEF_RAMDISK_ADDR = 0x01000000
DEF_TAGS_ADDR = 0x00000100
DEF_DTB_ADDR = 0x01F00000
DEF_PAGE_SIZE = 4096


def align(n, page):
    return (n + page - 1) // page * page


class BootImg:
    def __init__(self):
        self.raw = b""
        self.magic = b""
        self.kernel_size = 0
        self.kernel_addr = DEF_KERNEL_ADDR
        self.ramdisk_size = 0
        self.ramdisk_addr = DEF_RAMDISK_ADDR
        self.second_size = 0
        self.second_addr = 0
        self.tags_addr = DEF_TAGS_ADDR
        self.page_size = DEF_PAGE_SIZE
        self.header_version = 0
        self.os_version = 0
        self.name = b""
        self.cmdline = b""
        self.id = b"\0" * 32
        self.extra_cmdline = b""
        self.recovery_dtbo_size = 0
        self.recovery_dtbo_offset = 0
        self.header_size = 0
        self.dtb_size = 0
        self.dtb_addr = DEF_DTB_ADDR
        # 段落数据
        self.kernel = b""
        self.ramdisk = b""
        self.second = b""
        self.recovery_dtbo = b""
        self.dtb = b""
        self.trailing = b""

    # ---------------------------------------------------------------- parse
    @classmethod
    def parse(cls, data):
        b = cls()
        b.raw = data
        if len(data) < 4096 or data[:8] != MAGIC:
            raise ValueError("不是 Android boot image（magic 不对）")
        (b.magic,
         b.kernel_size, b.kernel_addr,
         b.ramdisk_size, b.ramdisk_addr,
         b.second_size, b.second_addr,
         b.tags_addr, b.page_size,
         b.header_version, b.os_version,
         b.name, b.cmdline, b.id, b.extra_cmdline) = struct.unpack_from("<8s10I16s512s32s1024s", data, 0)
        if b.header_version >= 1:
            (b.recovery_dtbo_size, b.recovery_dtbo_offset, b.header_size) = struct.unpack_from("<IQI", data, 1632)
        else:
            b.header_size = 1632
        if b.header_version >= 2:
            (b.dtb_size, b.dtb_addr) = struct.unpack_from("<IQ", data, 1648)
        else:
            b.header_size = max(b.header_size, 1648) if b.header_version == 1 else 1632

        p = b.page_size
        off = p
        b.kernel = data[off:off + b.kernel_size]; off += align(b.kernel_size, p)
        b.ramdisk = data[off:off + b.ramdisk_size]; off += align(b.ramdisk_size, p)
        b.second = data[off:off + b.second_size]; off += align(b.second_size, p)
        if b.header_version >= 1:
            off += align(b.recovery_dtbo_size, p)
        if b.header_version >= 2:
            b.dtb = data[off:off + b.dtb_size]; off += align(b.dtb_size, p)
        b.trailing = data[off:]
        return b

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls.parse(f.read())

    # ---------------------------------------------------------------- info
    def cmdline_str(self):
        raw = self.cmdline + b" " + self.extra_cmdline
        return raw.split(b"\0", 1)[0].decode("utf-8", "replace").strip()

    def kernel_kind(self):
        if self.kernel[:2] == GZIP_MAGIC:
            return "gzip"
        if self.kernel[:4] == b"\x1f\x8b\x08\x00" or self.kernel[:2] == GZIP_MAGIC:
            return "gzip"
        if self.kernel[:4] == b"\x02\x00\x00\x00" or self.kernel[56:60] == b"ARM\x64":
            return "raw arm64 Image"
        if self.kernel[:2] == b"BZ":
            return "bzip2"
        if self.kernel[:4] == b"\xfd7zXZ":
            return "xz"
        if self.kernel[:4] == b"\x89LZO":
            return "lzo"
        return "unknown"

    def embedded_dtbs(self):
        """在 kernel blob 里找 FDT（含 gzip 解压后再找）

        ★ Image.gz-dtb（header v0 + 追加 DTB）的关键点：gzip 流后面跟着 DTB，
          所以**必须**用 decompressobj 取 unused_data，而不是 gzip.decompress()
          —— 后者会把尾部当成第二个 gzip 成员然后报 BadGzipFile，看起来像坏了，
          其实完全正常。引导装载机（ABL / U-Boot / lk）走的都是 zlib 的
          Z_STREAM_END 语义，也就是停在第一个成员末尾。
        """
        hits = []
        blob = self.kernel
        note = ""
        if blob[:2] == GZIP_MAGIC:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)   # 16 = 按 gzip 头解析
            try:
                blob = d.decompress(blob)
                blob += d.flush()
            except Exception as e:                        # noqa: BLE001
                return hits, "gzip 解压失败: %s" % e
            if d.unused_data:
                note = "（gzip 流后还有 %d 字节，是 Image.gz-dtb 的正常形态）" % len(d.unused_data)
                blob = blob + d.unused_data               # 一起扫，追加的 DTB 在尾部
        start = 0
        while True:
            i = blob.find(FDT_MAGIC, start)
            if i < 0:
                break
            # 用 totalsize 校验是不是真的 FDT
            if i + 8 <= len(blob):
                tot = struct.unpack_from(">I", blob, i + 4)[0]
                if 0x1000 < tot <= len(blob) - i:
                    hits.append((i, tot))
            start = i + 4
        return hits, "解压后 %d 字节%s" % (len(blob), note)

    def dump(self, label=""):
        p = self.page_size
        print("== %s" % (label or "<image>"))
        print("   magic            %r  header_version=%d  page_size=%d" % (self.magic, self.header_version, p))
        print("   header_size      %d (v2 应为 1660)" % self.header_size)
        print("   kernel           size=%-10d addr=0x%08x  off=0x%x  (%s)" %
              (self.kernel_size, self.kernel_addr, p, self.kernel_kind()))
        print("   ramdisk          size=%-10d addr=0x%08x  off=0x%x" %
              (self.ramdisk_size, self.ramdisk_addr, p + align(self.kernel_size, p)))
        print("   second           size=%-10d addr=0x%08x" % (self.second_size, self.second_addr))
        print("   tags_addr        0x%08x" % self.tags_addr)
        if self.header_version >= 1:
            print("   recovery_dtbo    size=%d offset=%d" % (self.recovery_dtbo_size, self.recovery_dtbo_offset))
        if self.header_version >= 2:
            print("   dtb              size=%-10d addr=0x%08x  off=0x%x" %
                  (self.dtb_size, self.dtb_addr,
                   p + align(self.kernel_size, p) + align(self.ramdisk_size, p) +
                   align(self.second_size, p) + align(self.recovery_dtbo_size, p)))
        print("   name             %r" % self.name.split(b"\0", 1)[0])
        print("   cmdline          %r" % self.cmdline_str())
        print("   id(sha1)         %s" % self.id.hex())
        if self.dtb_size:
            ok = self.dtb[:4] == FDT_MAGIC
            print("   dtb magic        %s" % ("FDT OK" if ok else "不是 FDT！(%r)" % self.dtb[:4]))
        else:
            print("   dtb magic        <dtb_size=0，ABL 只能靠 kernel 内嵌 DTB>")
        hits, note = self.embedded_dtbs()
        print("   kernel 内嵌 DTB  %s  %s" % (hits if hits else "无", note))
        if self.trailing.strip(b"\0"):
            print("   trailing         %d 字节（非 0，可能是 AVB 签名）" % len(self.trailing))
        return self

    # ---------------------------------------------------------------- pack
    def pack(self):
        p = self.page_size
        parts = [self.kernel, self.ramdisk, self.second, self.recovery_dtbo]
        if self.header_version >= 2:
            parts.append(self.dtb)
        for i, d in enumerate(parts):
            if d:
                parts[i] = d + b"\0" * (align(len(d), p) - len(d))
        body = b"".join(parts)

        sha = hashlib.sha1()
        for d, n in ((self.kernel, self.kernel_size), (self.ramdisk, self.ramdisk_size),
                     (self.second, self.second_size), (self.recovery_dtbo, self.recovery_dtbo_size)):
            sha.update(d)
            sha.update(struct.pack("<I", n))
        if self.header_version >= 2:
            sha.update(self.dtb)
            sha.update(struct.pack("<I", self.dtb_size))
        self.id = sha.digest()

        head = struct.pack("<8s10I16s512s32s1024s",
                           MAGIC,
                           self.kernel_size, self.kernel_addr,
                           self.ramdisk_size, self.ramdisk_addr,
                           self.second_size, self.second_addr,
                           self.tags_addr, self.page_size,
                           self.header_version, self.os_version,
                           self.name.ljust(16, b"\0")[:16],
                           self.cmdline.ljust(512, b"\0")[:512],
                           self.id,
                           self.extra_cmdline.ljust(1024, b"\0")[:1024])
        if self.header_version >= 1:
            head += struct.pack("<IQI", self.recovery_dtbo_size, self.recovery_dtbo_offset,
                                1660 if self.header_version >= 2 else 1648)
        if self.header_version >= 2:
            head += struct.pack("<IQ", self.dtb_size, self.dtb_addr)
        head = head.ljust(p, b"\0")
        return head + body + self.trailing


# -------------------------------------------------------------------- 命令行
def read(p):
    with open(p, "rb") as f:
        return f.read()


def cmd_info(a):
    for path in a.image:
        BootImg.load(path).dump(os.path.basename(path))
    return 0


def cmd_unpack(a):
    b = BootImg.load(a.image)
    os.makedirs(a.dir, exist_ok=True)
    for name, data in (("kernel", b.kernel), ("ramdisk", b.ramdisk),
                       ("second", b.second), ("recovery_dtbo", b.recovery_dtbo),
                       ("dtb", b.dtb)):
        if data:
            fn = os.path.join(a.dir, name)
            with open(fn, "wb") as f:
                f.write(data)
            print("写出 %s (%d 字节)" % (fn, len(data)))
    if b.embedded_dtbs()[0] and not b.dtb_size:
        blob = b.kernel
        if blob[:2] == GZIP_MAGIC:
            blob = gzip.decompress(blob)
        off, tot = b.embedded_dtbs()[0][0]
        fn = os.path.join(a.dir, "kernel-appended.dtb")
        with open(fn, "wb") as f:
            f.write(blob[off:off + tot])
        print("写出 %s (kernel 内嵌 DTB, %d 字节)" % (fn, tot))
    return 0


def cmd_pack(a):
    b = BootImg()
    if a.template:
        t = BootImg.load(a.template)
        b.page_size = t.page_size
        b.header_version = max(t.header_version, a.header_version or 0)
        b.kernel_addr = t.kernel_addr or DEF_KERNEL_ADDR
        b.ramdisk_addr = t.ramdisk_addr or DEF_RAMDISK_ADDR
        b.second_addr = t.second_addr
        b.tags_addr = t.tags_addr or DEF_TAGS_ADDR
        b.dtb_addr = t.dtb_addr or DEF_DTB_ADDR
        b.name = t.name
        b.os_version = t.os_version
        b.cmdline = t.cmdline
        b.extra_cmdline = t.extra_cmdline
        print("== 模板 %s：page=%d hdr=%d kernel@0x%x ramdisk@0x%x tags@0x%x dtb@0x%x" %
              (os.path.basename(a.template), b.page_size, b.header_version,
               b.kernel_addr, b.ramdisk_addr, b.tags_addr, b.dtb_addr))
        print("   模板 cmdline: %r" % t.cmdline_str())
    else:
        b.page_size = a.page_size
        b.header_version = a.header_version if a.header_version is not None else 2
        b.kernel_addr = a.kernel_addr
        b.ramdisk_addr = a.ramdisk_addr
        b.tags_addr = a.tags_addr
        b.dtb_addr = a.dtb_addr

    b.kernel = read(a.kernel)
    b.kernel_size = len(b.kernel)
    b.ramdisk = read(a.ramdisk) if a.ramdisk else b""
    b.ramdisk_size = len(b.ramdisk)
    b.second = read(a.second) if a.second else b""
    b.second_size = len(b.second)
    b.recovery_dtbo = read(a.recovery_dtbo) if a.recovery_dtbo else b""
    b.recovery_dtbo_size = len(b.recovery_dtbo)

    if a.append_dtb:
        if not a.dtb:
            print("!! --append-dtb 需要 --dtb")
            return 2
        b.kernel += read(a.dtb)
        b.kernel_size = len(b.kernel)
        b.dtb = b""
        b.dtb_size = 0
        print("== 已把 DTB 追加到 kernel 尾部（Image.gz-dtb 形式），dtb_size=0")
    elif a.dtb:
        b.dtb = read(a.dtb)
        b.dtb_size = len(b.dtb)
        if b.header_version < 2:
            b.header_version = 2
    else:
        b.dtb = b""
        b.dtb_size = 0
        print("!! 没有给 --dtb：dtb_size=0，ABL 只能靠 kernel 内嵌 DTB（很可能挑不到）")

    if a.cmdline is not None:
        cb = a.cmdline.encode()
        b.cmdline = cb[:512]
        b.extra_cmdline = cb[512:1536]
    if a.name:
        b.name = a.name.encode()[:16]

    out = b.pack()
    with open(a.output, "wb") as f:
        f.write(out)
    print("== 写出 %s (%d 字节)" % (a.output, len(out)))

    # ---- 自检：重新解析一遍，确认字段/偏移都对
    v = BootImg.load(a.output)
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("   OK   " if cond else "   FAIL ") + msg)
        ok = ok and cond

    chk(v.kernel_size == b.kernel_size, "kernel_size=%d" % v.kernel_size)
    chk(v.ramdisk_size == b.ramdisk_size, "ramdisk_size=%d" % v.ramdisk_size)
    chk(v.dtb_size == b.dtb_size, "dtb_size=%d" % v.dtb_size)
    chk(v.header_version == b.header_version, "header_version=%d" % v.header_version)
    chk(v.cmdline_str() == b.cmdline_str(), "cmdline=%r" % v.cmdline_str())
    if v.dtb_size:
        chk(v.dtb[:4] == FDT_MAGIC, "dtb 段是合法 FDT")
    if v.embedded_dtbs()[0]:
        chk(True, "kernel 内嵌 DTB: %s" % (v.embedded_dtbs()[0],))
    print("== 自检 %s" % ("通过" if ok else "失败"))
    return 0 if ok else 3


def main():
    ap = argparse.ArgumentParser(description="Android boot image v0/v1/v2 工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="打印头部信息")
    p.add_argument("image", nargs="+")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("unpack", help="解出各段")
    p.add_argument("image")
    p.add_argument("-d", "--dir", default="unpacked")
    p.set_defaults(func=cmd_unpack)

    p = sub.add_parser("pack", help="打包")
    p.add_argument("--kernel", required=True)
    p.add_argument("--dtb")
    p.add_argument("--ramdisk")
    p.add_argument("--second")
    p.add_argument("--recovery-dtbo")
    p.add_argument("--cmdline")
    p.add_argument("--name")
    p.add_argument("--template", help="从现成 boot.img 继承地址/cmdline/版本")
    p.add_argument("--append-dtb", action="store_true", help="把 DTB 追加到 kernel 尾（Image.gz-dtb）")
    p.add_argument("--header-version", type=int, default=None)
    p.add_argument("--page-size", type=int, default=DEF_PAGE_SIZE)
    p.add_argument("--kernel-addr", type=lambda s: int(s, 0), default=DEF_KERNEL_ADDR)
    p.add_argument("--ramdisk-addr", type=lambda s: int(s, 0), default=DEF_RAMDISK_ADDR)
    p.add_argument("--tags-addr", type=lambda s: int(s, 0), default=DEF_TAGS_ADDR)
    p.add_argument("--dtb-addr", type=lambda s: int(s, 0), default=DEF_DTB_ADDR)
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_pack)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
