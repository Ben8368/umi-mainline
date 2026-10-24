#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""raw2sparse.py — 把 raw 镜像转成 Android sparse image

为什么需要它：platform-tools 的 fastboot 在 `fastboot flash` 时**会先把整个
文件读进内存**（std::bad_alloc，实测 6 GiB 的 ext4 镜像直接崩，加 -S 也一样，
因为 -S 是在读完文件之后才切片的）。转成 sparse 后：

  * 只有非零块会被传，6 GiB 的镜像实际要传 2 GiB 左右
  * fastboot 认 0xed26ff3a 这个 magic，自动按 sparse 解析，不需要额外参数

用法：
    python tools/raw2sparse.py out\\arch-rootfs.img out\\arch-rootfs.simg

格式（system/core/libsparse/sparse_format.h）：
    header : magic u32 | major u16 | minor u16 | file_hdr_sz u16 |
             chunk_hdr_sz u16 | blk_sz u32 | total_blks u32 |
             total_chunks u32 | image_checksum u32
    chunk  : chunk_type u16 | reserved u16 | chunk_sz u32 | total_sz u32
    0xCAC1 RAW      : 后面跟 chunk_sz 个块的真实数据
    0xCAC2 FILL     : 后面跟一个块的内容，重复 chunk_sz 次
    0xCAC3 DONT_CARE: 不传数据，目标处保持原样
"""
import os
import struct
import sys

MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT = 0xCAC3

BLK = 4096
MAX_CHUNK_BLKS = 65536          # 每个 chunk 最多 256 MiB，保守起见
READ_CHUNK = 4 * 1024 * 1024    # 一次读 4 MiB


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src, dst = sys.argv[1], sys.argv[2]
    size = os.path.getsize(src)
    if size % BLK:
        print("!! 文件大小不是 4 KiB 的整数倍，sparse 会有尾巴问题", file=sys.stderr)
        return 2
    total_blks = size // BLK

    zero = b"\x00" * BLK
    fout = open(dst, "wb")
    fout.write(b"\x00" * 28)          # header 先占位，最后回填

    chunks = 0
    written = 0

    def emit(kind, nblk, payload=None):
        nonlocal chunks, written
        if kind == CHUNK_DONT:
            fout.write(struct.pack("<HHII", CHUNK_DONT, 0, nblk, 12))
            written += 12
        else:
            fout.write(struct.pack("<HHII", CHUNK_RAW, 0, nblk, 12 + nblk * BLK))
            fout.write(payload)
            written += 12 + nblk * BLK
        chunks += 1

    done = 0
    with open(src, "rb") as fin:
        while True:
            buf = fin.read(READ_CHUNK)
            if not buf:
                break
            nblk = len(buf) // BLK
            # 快速路径：整段全零就不用逐块比较了
            if buf.count(0) == len(buf):
                off = 0
                while off < nblk:
                    take = min(MAX_CHUNK_BLKS, nblk - off)
                    emit(CHUNK_DONT, take)
                    off += take
            else:
                # 逐块判定，把连续的同类块合并成一个 chunk
                i = 0
                while i < nblk:
                    cur_zero = (buf[i * BLK:(i + 1) * BLK] == zero)
                    j = i + 1
                    while j < nblk and (j - i) < MAX_CHUNK_BLKS:
                        nxt_zero = (buf[j * BLK:(j + 1) * BLK] == zero)
                        if nxt_zero != cur_zero:
                            break
                        j += 1
                    if cur_zero:
                        emit(CHUNK_DONT, j - i)
                    else:
                        emit(CHUNK_RAW, j - i, buf[i * BLK:j * BLK])
                    i = j
            done += nblk
            if done % 8192 == 0:      # 每 32 MiB 报一次
                pct = done * 100 // total_blks
                print(f"\r  扫描 {pct:3d}%  ({done * BLK // (1024*1024)} MiB)", end="", flush=True)

    print()
    fout.seek(0)
    fout.write(struct.pack("<IHHHHIIII", MAGIC, 4, 0, 28, 12, BLK,
                           total_blks, chunks, 0))
    fout.close()

    out_size = os.path.getsize(dst)
    print(f"== {src}: {size/1024/1024:,.1f} MiB, {total_blks} blocks")
    print(f"== {dst}: {out_size/1024/1024:,.1f} MiB, {chunks} chunks")
    print(f"== 省下 {100 - out_size * 100 // size}% 的传输量")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
