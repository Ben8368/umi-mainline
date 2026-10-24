import re

path = "downstream-kernel/arch/arm64/boot/dts/vendor/qcom/dsi-panel-j2-mp-42-02-0b-dsc-cmd.dtsi"
src = open(path, encoding="utf-8", errors="replace").read()

blocks = re.findall(r"qcom,mdss-dsi-on-command = \[(.*?)\];", src, re.S)
print("on-command arrays:", len(blocks))


def parse(block):
    body = re.sub(r"/\*.*?\*/", " ", block, flags=re.S)
    toks = re.findall(r"\b([0-9A-Fa-f]{2})\b", body)
    pkts = []
    k = 0
    while k + 7 <= len(toks):
        try:
            dtype = int(toks[k], 16)
        except ValueError:
            k += 1
            continue
        if dtype in (0x05, 0x15, 0x39, 0x03, 0x13, 0x23, 0x29):
            plen = int(toks[k + 5], 16) * 256 + int(toks[k + 6], 16)
            payload = toks[k + 7:k + 7 + plen]
            pkts.append((dtype, int(toks[k + 4], 16), tuple(payload)))
            k += 7 + plen
        else:
            k += 1
    return pkts


a = parse(blocks[0])
b = parse(blocks[1])
print("packets:", len(a), len(b))

for i, (pa, pb) in enumerate(zip(a, b)):
    if pa != pb:
        print("DIFF at packet %d" % i)
        print("  A dtype %02x wait %02x : %s" % (pa[0], pa[1], " ".join(pa[2])))
        print("  B dtype %02x wait %02x : %s" % (pb[0], pb[1], " ".join(pb[2])))

if a == b:
    print("arrays are byte identical")
