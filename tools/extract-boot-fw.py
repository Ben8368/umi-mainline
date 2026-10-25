#!/usr/bin/env python3
"""Pull the ST FTS .ftb image out of a vendor boot.img.

The Xiaomi/HyperOS kernel has the touch firmware compiled in (fts_fw.h), so the
only place the FW that the stock driver would burn still exists is inside the
boot image.  The kernel in the umi boot partition is gzip compressed; this
unpacks the boot header, gunzips the kernel, finds the .ftb header signature
(55 aa 55 aa 01 00 00 00 36 39 ...) and writes the blob out.

    python tools/extract-boot-fw.py <boot.img|boot.emmc.win> <out.bin>

Prints the parsed .ftb header fields so the version can be compared with what
the controller runs.
"""
import gzip
import io
import struct
import sys

FTB_SIG = bytes.fromhex("55aa55aa010000003639")


def parse_boot(data):
    if data[:8] != b"ANDROID!":
        raise SystemExit("not an Android boot image")
    kernel_size, = struct.unpack_from("<I", data, 8)
    page, = struct.unpack_from("<I", data, 36)
    if page < 512 or page > 65536 or page & (page - 1):
        raise SystemExit(f"implausible page size {page}")
    off = page
    return data[off:off + kernel_size]


def gunzip_any(blob):
    """Return the kernel payload, decompressing gzip if that is what it is."""
    if blob[:2] == b"\x1f\x8b":
        return gzip.decompress(blob)
    return blob


def ftb_report(blob):
    if len(blob) < 68:
        return
    sig, ver = struct.unpack_from("<II", blob, 0)
    chip = blob[8:10]
    svn, = struct.unpack_from("<I", blob, 12)
    fwv, = struct.unpack_from("<I", blob, 16)
    cfgid, = struct.unpack_from("<I", blob, 20)
    cfgv, = struct.unpack_from("<I", blob, 24)
    ext = blob[32:40]
    s0, s1, s2, s3 = struct.unpack_from("<IIII", blob, 44)
    org = blob[280:284]
    print(f"  sig      {sig:08X}")
    print(f"  ftb_ver  {ver}")
    print(f"  chip id  {chip[0]:02X}{chip[1]:02X}")
    print(f"  svn      0x{svn:04X}")
    print(f"  fw ver   0x{fwv:04X}")
    print(f"  cfg id   0x{cfgid:08X}  cfg ver 0x{cfgv:04X}")
    print(f"  ext rel  {ext.hex(' ')}")
    print(f"  sections fw {s0} cfg {s1} cx {s2} sec3 {s3}  "
          f"(total {68 + s0 + s1 + s2 + s3})")
    print(f"  org pages code/panel/cx/cfg = "
          f"{org[0]} {org[1]} {org[2]} {org[3]}")


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    img, out = sys.argv[1], sys.argv[2]
    data = open(img, "rb").read()
    print(f"{img}: {len(data)} bytes")
    kernel = parse_boot(data)
    print(f"kernel blob {len(kernel)} bytes, "
          f"magic {kernel[:2].hex(' ')}")
    image = gunzip_any(kernel)
    print(f"kernel image {len(image)} bytes")
    hits = []
    i = image.find(FTB_SIG)
    while i != -1:
        hits.append(i)
        i = image.find(FTB_SIG, i + 1)
    print(f"ftb candidates: {[hex(h) for h in hits]}")
    if not hits:
        raise SystemExit("no .ftb signature in the kernel image")
    for h in hits:
        blob = image[h:]
        s0, s1, s2, s3 = struct.unpack_from("<IIII", blob, 44)
        total = 68 + s0 + s1 + s2 + s3
        print(f"candidate at 0x{h:x} (claimed size {total})")
        ftb_report(blob)
        if 1000 < total <= len(blob):
            with open(out, "wb") as f:
                f.write(blob[:total])
            print(f"wrote {out} ({total} bytes)")
            return
    raise SystemExit("no candidate had a self-consistent size")


if __name__ == "__main__":
    main()
