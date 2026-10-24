import io
import os
import struct

path = "tmp/armbian/boot.img"
d = open(path, "rb").read()
print("file size", len(d))

magic = d[:8]
page = struct.unpack("<I", d[36:40])[0] or 2048
print("magic", magic, "page", page)
ksize = struct.unpack("<I", d[8:12])[0]
kaddr = struct.unpack("<I", d[12:16])[0]
rsize = struct.unpack("<I", d[16:20])[0]
print("kernel_size", ksize, "kernel_addr", hex(kaddr), "ramdisk_size", rsize)

kernel = d[page:page + ksize]
rest = page + ((ksize + page - 1) // page) * page
ramdisk = d[rest:rest + rsize]

os.makedirs("tmp/armbian/out", exist_ok=True)
open("tmp/armbian/out/kernel.bin", "wb").write(kernel)
open("tmp/armbian/out/ramdisk.bin", "wb").write(ramdisk)


def kind(b):
    if b[:2] == b"\x1f\x8b":
        return "gzip"
    if b[:4] == b"\x28\xb5\x2f\xfd":
        return "zstd"
    if b[:4] == b"\x02\x21\x4c\x18":
        return "lz4"
    if b[:3] == b"\x5d\x00\x00":
        return "lzma"
    if b[:4] == b"\x04\x22\x4d\x18":
        return "lz4legacy"
    if b[0x38:0x3c] == b"ARMd":
        return "arm64 Image"
    if b[:4] == b"0707" or b[:6] == b"070701":
        return "cpio"
    return "unknown"


print("kernel:", kind(kernel), "ramdisk:", kind(ramdisk))
print("ramdisk head:", ramdisk[:16].hex())
