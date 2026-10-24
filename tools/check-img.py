import gzip
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "out/Image.gz"
d = gzip.decompress(open(path, "rb").read())
probes = [
    b"sysinfo res %ux%u tx %u rx %u",
    b"sysinfo frames raw@%04x",
    b"enable 4: full panel init",
    b"enable 5: full init + ioff trim",
    b"enable 6: full init + ioff + gesture",
    b"ioff trim: A4 08 02 00",
    b"gesture feature: A2 03",
    b"%s @%04x n %d min %d max %d avg %lld head",
    b"panel init %02x: A4 00 %02x",
    b"repower: on-sequence",
    b"dbg %d",
]
for p in probes:
    print("%-40s %d" % (p.decode(), d.count(p)))
