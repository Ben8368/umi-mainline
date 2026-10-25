#!/usr/bin/env python3
"""List and extract every ST FTS .ftb blob inside a binary image (boot.img etc.)."""
import sys, struct, hashlib, os

MAGIC = bytes.fromhex("55aa55aa010000003639")

def u32(d, o):
    return struct.unpack_from("<I", d, o)[0]

def main():
    path = sys.argv[1]
    outdir = sys.argv[2] if len(sys.argv) > 2 else None
    d = open(path, "rb").read()
    print(f"{path}: {len(d)} bytes")
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    i = n = 0
    while True:
        j = d.find(MAGIC, i)
        if j < 0 or j + 68 > len(d):
            break
        i = j + 1
        svn, fw, cfgid, cfg = struct.unpack_from("<IIII", d, j + 12)
        s0, s1, s2, s3 = struct.unpack_from("<IIII", d, j + 44)
        total = 68 + s0 + s1 + s2 + s3
        ok = 1000 < total <= 1 << 20 and j + total <= len(d)
        org = d[j + 280:j + 284]
        n += 1
        print(f"  0x{j:X} svn=0x{svn:06X} fw=0x{fw:04X} cfg=0x{cfg:08X} "
              f"secs={s0}/{s1}/{s2}/{s3} total={total} "
              f"org={'/'.join(str(x) for x in org)} {'OK' if ok else 'BAD'}")
        if outdir and ok:
            blob = d[j:j + total]
            name = os.path.join(outdir, f"st_fts_j2_fw{fw:04X}_cfg{cfg:08X}.ftb")
            open(name, "wb").write(blob)
            print(f"        -> {name} {total} B md5={hashlib.md5(blob).hexdigest()}")
    print(f"  {n} blob(s)")

if __name__ == "__main__":
    main()
