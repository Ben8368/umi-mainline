#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""tile-ranges.py — 从 pinctrl-sm8250.c 提取每个 tile 的引脚号，并把 umi 当前的
gpio-reserved-ranges 叠上去，看「哪些 tile 引脚还活着」。

    python3 tools/tile-ranges.py dts/sm8250-xiaomi-umi-common.dtsi
"""
import re
import sys


def compress(v):
    if not v:
        return "-"
    out, s, prev = [], v[0], v[0]
    for x in v[1:]:
        if x == prev + 1:
            prev = x
            continue
        out.append((s, prev))
        s = prev = x
    out.append((s, prev))
    return " ".join("%d-%d" % r if r[0] != r[1] else "%d" % r[0] for r in out)


def main():
    dtsi = sys.argv[1]
    src = open("/root/linux/drivers/pinctrl/qcom/pinctrl-sm8250.c",
               encoding="utf-8", errors="replace").read()
    tiles = {}
    for m in re.finditer(r"PINGROUP\((\d+),\s*(NORTH|SOUTH|WEST)", src):
        tiles.setdefault(m.group(2), []).append(int(m.group(1)))
    for t in tiles:
        tiles[t].sort()

    dts = open(dtsi, encoding="utf-8", errors="replace").read()
    m = re.search(r"gpio-reserved-ranges\s*=\s*([^;]+);", dts)
    res = set()
    if m:
        base, cnt = None, None
        nums = [int(x) for x in re.findall(r"0x[0-9a-fA-F]+|\d+", m.group(1))]
        for v in nums:
            if base is None:
                base = v
            else:
                res.update(range(base, base + v))
                base = None

    for t in ("WEST", "SOUTH", "NORTH"):
        pins = tiles.get(t, [])
        alive = [p for p in pins if p not in res]
        print("%-5s total %3d  保留后可用 %3d : %s" % (t, len(pins), len(alive), compress(alive)))

    # 关键引脚
    for name, p in (("panel reset", 12), ("panel TE", 66), ("hall key", 14),
                    ("disp-rate", 0x65), ("esd", 0x33)):
        if name in ("disp-rate", "esd"):
            continue
        print("  %-12s gpio%-3d -> %s" % (name, p, "RESERVED(不可用)" if p in res else "可用"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
