"""Parse an ST FTS .ftb image (firmware / config / CX sections).

    python3 tools/ftb-parse.py dump/fts/st_fts_j2_2.ftb

The layout is the one parseBinFile() walks in the vendor driver
(fts_lib/ftsFlash.c): a 32 bit little endian header, then the four section
sizes, then the sections back to back:

    [0]   signature 0x55aa55aa
    [4]   ftb version (1)
    [8]   target chip id (2 bytes)
    [12]  svn revision
    [16]  firmware version (low 16 bits)
    [20]  config project id
    [24]  config version
    ...   external release info, then sec0..sec3 sizes
    sec0  firmware code
    sec1  configuration
    sec2  CX / panel initialisation data     <- the one that matters here
    sec3  (unused)
"""

import sys

path = sys.argv[1] if len(sys.argv) > 1 else "dump/fts/st_fts_j2_2.ftb"
data = open(path, "rb").read()
print("file: %s  %d bytes" % (path, len(data)))


def u32(off):
    return int.from_bytes(data[off:off + 4], "little")


print("signature  %08x  (expect 55aa55aa)" % u32(0))
print("ftb_ver    %08x  (expect 1)" % u32(4))
print("chip id    %02x %02x" % (data[8], data[9]))
print("svn rev    %08x" % u32(12))
print("fw ver     %04x" % (u32(16) & 0xffff))
print("cfg proj   %08x" % u32(20))
print("cfg ver    %08x" % u32(24))

total = len(data)
best = None
for off in range(28, 96, 4):
    sizes = [u32(off + 4 * i) for i in range(4)]
    s = sum(sizes)
    if 0 < s <= total and total - s in (off + 16, off + 20, off + 24):
        best = (off, sizes, total - s)
        break

if not best:
    print("section table not found, u32 dump from 28:")
    print(" ".join("%d:%d" % (o, u32(o)) for o in range(28, 96, 4)))
    sys.exit(1)

off, sizes, hdr = best
print("section table at %d, header %d bytes" % (off, hdr))
for name, value in zip(("fw code  (sec0)", "config   (sec1)",
                        "CX/panel (sec2)", "sec3"),
                       sizes):
    print("  %-16s %7d bytes %s" % (name, value,
                                    "EMPTY" if value == 0 else ""))
