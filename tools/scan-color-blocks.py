#!/usr/bin/env python3
"""扫 out/ 里的 boot 镜像，找出还带“满屏色块/panic 自测”的：

  - b"umi-beacon"   早期 bring-up 的信标驱动（四个 initcall 阶段刷整屏纯色）
  - b"/panic-test"  initramfs 里的 panic 屏自测（启动 N 秒后满屏二维码）
  - b"drm_panic"    只是提示，真正会刷屏的是上面两个

用法： python tools/scan-color-blocks.py out/archive
"""
import gzip
import os
import struct
import sys

MARKERS = [b"umi-beacon", b"/panic-test", b"drm_panic_plane_"]


def boot_parts(data):
    if data[:8] != b"ANDROID!":
        return b"", b""
    kernel_size, = struct.unpack_from("<I", data, 8)
    ramdisk_size, = struct.unpack_from("<I", data, 16)
    page, = struct.unpack_from("<I", data, 36)
    off = page
    kern = data[off:off + kernel_size]
    off += (kernel_size + page - 1) // page * page
    ram = data[off:off + ramdisk_size]
    return kern, ram


def deblob(b, limit=200 << 20):
    if b[:2] != b"\x1f\x8b":
        return b
    try:
        return gzip.decompress(b[:limit])
    except Exception:
        return b""


def main():
    dirs = sys.argv[1:] or ["out"]
    for d in dirs:
        for name in sorted(os.listdir(d)):
            if not name.endswith(".img"):
                continue
            p = os.path.join(d, name)
            try:
                data = open(p, "rb").read()
            except Exception as e:
                print(f"{name:34s} 读取失败: {e}")
                continue
            kern, ram = boot_parts(data)
            blob = deblob(kern) + b"\n" + deblob(ram)
            hits = [m.decode() for m in MARKERS if m in blob]
            tag = ", ".join(hits) if hits else "clean"
            print(f"{name:34s} {len(data)/1e6:6.1f} MB  {tag}")


if __name__ == "__main__":
    main()
