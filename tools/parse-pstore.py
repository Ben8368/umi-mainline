#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""parse-pstore.py — 从裸转储里把内核 log 抠出来

用在两个场景（都是「内核没跑到用户态、屏幕也看不见」时的救命通道）：

  1) EDL / firehose 直接从内存读出来的 ramoops 区
     （小米10 的 ramoops 在物理 0xb0000000，大小 4 MB）
        edl r 0xb0000000 0x400000 ramoops.bin
        python tools/parse-pstore.py ramoops.bin -o out/ramoops.txt

  2) pstore/blk 写进分区的裸数据（TWRP 里 dd 出来）
        adb shell dd if=/dev/block/sda15 of=/tmp/pstore.bin bs=4096 count=512
        adb pull /tmp/pstore.bin
        python tools/parse-pstore.py pstore.bin -o out/pstore.txt

能识别的两种格式：
  * ramoops / persistent_ram：zone 头 magic 0x43474244 ('DBGC')，后面跟环形缓冲
  * pstore/blk (pstore zone)：同样的 magic，元数据布局不同
识别不出来也没关系：会退化成「把可打印 ASCII 段全抠出来」，
内核 log 本来就是纯文本，这一步通常就够了。

用法：
    python tools/parse-pstore.py DUMP [--dump-offset 0x200000] [-o out.txt]
    python tools/parse-pstore.py DUMP --strings-only
"""
import argparse
import os
import re
import struct
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PSZ_SIG = 0x43474244          # 'DBGC'，ramoops 和 pstore-blk 都用它
SIG_BYTES = struct.pack("<I", PSZ_SIG)


def try_inflate(data, max_out=4 << 20):
    """pstore 的 CONFIG_PSTORE_COMPRESS=y 时，记录是**裸 deflate**流
    （zlib_deflateInit2 传了 -MAX_WBITS，没有 zlib 头），而且一个 zone 里
    可能连着好几个流。这里一个个解开拼起来。"""
    out = bytearray()
    rest = data
    for _ in range(512):
        if len(rest) < 8 or len(out) > max_out:
            break
        d = zlib.decompressobj(-15)
        try:
            chunk = d.decompress(rest, max_out)
        except zlib.error:
            break
        if not chunk:
            break
        out += chunk
        if not d.unused_data:
            break
        rest = d.unused_data
    return bytes(out)


def printable_ratio(data):
    if not data:
        return 0.0
    head = data[:65536]
    n = sum(1 for b in head if b in (9, 10, 13) or 32 <= b < 127)
    return n / len(head)


def looks_compressed(data):
    return printable_ratio(data) < 0.85


def printable_runs(data, minlen=24):
    """把可打印 ASCII 段抠出来（内核 log 是纯文本，这一步最实用）"""
    out = []
    cur = bytearray()
    for b in data:
        if b in (9, 10, 13) or 32 <= b < 127:
            cur.append(b)
        else:
            if len(cur) >= minlen:
                out.append(bytes(cur).decode("ascii", "replace"))
            cur = bytearray()
    if len(cur) >= minlen:
        out.append(bytes(cur).decode("ascii", "replace"))
    return out


def parse_ramoops(data, verbose=True):
    """按 persistent_ram 的 zone 头扫一遍：sig + start + size"""
    zones = []
    pos = 0
    while True:
        i = data.find(SIG_BYTES, pos)
        if i < 0:
            break
        pos = i + 4
        # persistent_ram_buffer: u32 sig; size_t start; size_t size; char data[]
        for off in (4, 8):
            try:
                start, size = struct.unpack_from("<QQ", data, i + off)
            except struct.error:
                continue
            if start < size <= len(data) and size >= 64:
                zones.append((i, off, start, size))
                break
    return zones


def looks_like_kernel_log(text):
    score = 0
    for pat in (r"\[\s*\d+\.\d+\]", r"Linux version", r"Booting Linux",
                r"Call trace:", r"Kernel panic", r"initcall", r"Memory:"):
        if re.search(pat, text):
            score += 1
    return score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--strings-only", action="store_true", help="跳过格式解析，直接抠文本")
    ap.add_argument("--min-len", type=int, default=24)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    with open(a.dump, "rb") as f:
        data = f.read()
    print("== %s: %d 字节 (0x%x)" % (a.dump, len(data), len(data)))

    chunks = []

    if not a.strings_only:
        zones = parse_ramoops(data)
        print("== 找到 %d 个 pstore zone 头 (magic 'DBGC')" % len(zones))
        for (base, hdr, start, size) in zones:
            data_off = base + hdr + 16
            buf = data[data_off:data_off + size]
            if not buf:
                continue
            # 环形缓冲：有效内容从 start 开始绕一圈
            if 0 < start < len(buf):
                buf = buf[start:] + buf[:start]

            # 内核默认开了 CONFIG_PSTORE_COMPRESS（裸 deflate）。
            # 不做启发式猜测：直接试着解压，谁的结果更像文本就用谁。
            raw = buf
            dec = try_inflate(buf)
            if len(dec) >= 64 and printable_ratio(dec) > printable_ratio(raw):
                buf = dec
                if not a.quiet:
                    print("   zone @0x%-9x 解压后 %d 字节（可打印率 %.0f%%）"
                          % (base, len(dec), printable_ratio(dec) * 100))

            txt = buf.split(b"\0\0")[0]
            try:
                s = txt.decode("utf-8", "replace")
            except Exception:
                s = txt.decode("latin-1", "replace")
            if len(s.strip()) < 32:
                continue
            chunks.append("########## zone @0x%x (start=%d size=%d) ##########\n%s"
                          % (base, start, size, s))
            if not a.quiet:
                print("   zone @0x%-9x size=%-9d 有效文本 %d 字节, 像内核 log 吗: 得分 %d"
                      % (base, size, len(s), looks_like_kernel_log(s)))

    if not chunks:
        print("== 没解析出 zone（可能 dump 不完整/格式不同），退化成抠文本")
        # 先整体试一次裸 deflate（压缩过的 dump 在这里能救回来）
        dec = try_inflate(data)
        if len(dec) > 1024:
            print("   整个 dump 是压缩的，解出 %d 字节" % len(dec))
            data = dec
        runs = printable_runs(data, a.min_len)
        best = sorted(runs, key=lambda r: (-looks_like_kernel_log(r), -len(r)))
        # 把像 log 的段按出现顺序拼起来
        keep = [r for r in runs if looks_like_kernel_log(r)]
        if not keep:
            keep = best[:40]
        chunks.append("########## 从裸数据里抠出来的文本段（共 %d 段） ##########\n" % len(runs)
                      + "\n---\n".join(keep))

    out = "\n\n".join(chunks)
    if a.output:
        os.makedirs(os.path.dirname(os.path.abspath(a.output)) or ".", exist_ok=True)
        with open(a.output, "w", encoding="utf-8") as f:
            f.write(out)
        print("== 写出 %s (%d 字节文本)" % (a.output, len(out)))
        # 顺便打印尾部，让人一眼看到崩在哪
        tail = out.strip().splitlines()[-25:]
        print("---- 结尾 25 行 ----")
        for line in tail:
            print("   " + line[:160])
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
