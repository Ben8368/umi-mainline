#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""dtbo-analyze.py — 分析 dtbo 分区里的 overlay 到底往哪些节点打东西

为什么需要它：这台机器的 ABL 会在跳转前把 dtbo 里的 29 个 overlay 打到
boot.img 的 base DTB 上。overlay 用 &label 指定目标节点，libfdt 靠 base DTB 的
__symbols__ 解析；任何一个 label 找不到，overlay 就整体失败，ABL 静默退回 fastboot。

本脚本做正确的 __fixups__ 解析（fixup 值里存的是**到属性值的偏移量**，不是 phandle，
很容易写错），输出：
  * 每个 overlay 的 fragment 目标 label
  * 目标 label 里哪些是我们主线 DTB 里已经有真实节点的（= 危险，overlay 会真的改它）
  * 哪些只能建占位节点

用法：
    python tools/dtb-analyze.py dump/dtbo.img
    python tools/dtb-analyze.py dump/dtbo.img --ours dump/dtb-our-sym.dtb
"""
import argparse
import collections
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
try:
    from dtb import parse  # noqa: E402
except Exception:  # noqa: BLE001
    parse = None

DT_TABLE_MAGIC = 0xD7B7AB1E
FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


def fdt_walk(blob):
    """返回 [(路径, 属性名, 值起始偏移, 值长度)]，偏移是相对 blob 起点。"""
    (magic, totalsize, off_struct, off_strings,
     off_memrsv, ver, last_comp, boot_cpu, size_strings, size_struct) = struct.unpack_from(">10I", blob, 0)
    assert magic == FDT_MAGIC, "不是 FDT"
    out = []
    path = []
    p = off_struct
    end = off_struct + size_struct
    while p < end:
        tok, = struct.unpack_from(">I", blob, p)
        p += 4
        if tok == FDT_BEGIN_NODE:
            e = blob.index(b"\0", p)
            path.append(blob[p:e].decode("latin1"))
            p = (e + 1 + 3) & ~3
        elif tok == FDT_END_NODE:
            if path:
                path.pop()
        elif tok == FDT_PROP:
            ln, nameoff = struct.unpack_from(">II", blob, p)
            p += 8
            nm = blob[off_strings + nameoff:blob.index(b"\0", off_strings + nameoff)].decode("latin1")
            out.append(("/" + "/".join(x for x in path if x), nm, p, ln))
            p = (p + ln + 3) & ~3
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            break
        else:
            raise ValueError("unknown fdt token 0x%x" % tok)
    return out


def iter_overlays(dtbo):
    magic, total, hsize, esize, cnt, eoff, pgsz, ver = struct.unpack_from(">8I", dtbo, 0)
    if magic != DT_TABLE_MAGIC:
        # 也许整个文件就是一块 overlay
        yield (0, 0, 0, dtbo)
        return
    for i in range(cnt):
        off = eoff + i * esize
        dt_size, dt_off, did, rev = struct.unpack_from(">4I", dtbo, off)
        if dt_size == 0:
            continue
        yield (i, did, rev, dtbo[dt_off:dt_off + dt_size])


def analyze_overlay(blob):
    """返回 (targets, fixups, 每个 target 加了什么)"""
    props = fdt_walk(blob)
    # __fixups__ 的每个属性：值是一串 u32 偏移
    fixup_offsets = {}
    fixups = {}
    for path, nm, voff, ln in props:
        if path != "/__fixups__":
            continue
        fixups[nm] = ln // 4
        for k in range(ln // 4):
            o = struct.unpack_from(">I", blob, voff + k * 4)[0]
            fixup_offsets[o] = nm
    # 每个 fragment 的 target 属性值偏移 -> label
    targets = {}
    for path, nm, voff, ln in props:
        if not (path.startswith("/fragment@") or "/__overlay__" in path):
            continue
        if nm in ("target", "target-path") and path.count("/") == 1:
            frag = path.rsplit("/", 1)[-1]
            if nm == "target":
                lab = fixup_offsets.get(voff)
                targets[frag] = lab if lab else "?phandle:0x%x" % struct.unpack_from(">I", blob, voff)[0]
            else:
                targets[frag] = "PATH:" + blob[voff:voff + ln].split(b"\0")[0].decode("latin1")
    return targets, fixups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dtbo")
    ap.add_argument("--ours", default=None, help="我们编译出的 -@ DTB（用来判断 label 是否已存在真实节点）")
    a = ap.parse_args()

    dtbo = open(a.dtbo, "rb").read()
    ours = set()
    if a.ours and parse:
        d = open(a.ours, "rb").read()
        tot = struct.unpack_from(">I", d, 4)[0]
        root, _ = parse(d[:tot])
        sym = next((c for c in root.children if c.name == "__symbols__"), None)
        if sym:
            ours = set(sym.props.keys())

    tgt_cnt = collections.Counter()
    per_overlay = []
    for idx, did, rev, blob in iter_overlays(dtbo):
        targets, fixups = analyze_overlay(blob)
        per_overlay.append((idx, did, rev, targets, fixups))
        for lab in targets.values():
            tgt_cnt[lab] += 1

    print("区块数 %d\n" % len(per_overlay))
    print("===== 每个 overlay 的 fragment 目标 =====")
    for idx, did, rev, targets, fixups in per_overlay:
        labs = sorted(set(targets.values()))
        print("overlay #%-2d board-id=%-3d rev=%-3d  fragment %d 个  目标: %s"
              % (idx, did, rev, len(targets), ", ".join(labs) if labs else "<无>"))

    print("\n===== 目标 label 使用统计 =====")
    for lab, n in tgt_cnt.most_common():
        mark = ""
        if ours:
            mark = "  ← 主线已有真实节点（overlay 会真的改它）" if lab in ours else "  (需占位)"
        print("   %-30s x%-3d%s" % (lab, n, mark))

    allfix = collections.Counter()
    for _, _, _, _, fx in per_overlay:
        for k in fx:
            allfix[k] += 1
    print("\n===== 所有 __fixups__ label（base DTB 必须全部提供）共 %d 个 =====" % len(allfix))
    if ours:
        dup = sorted(set(allfix) & ours)
        print("其中主线已有真实节点的 %d 个：" % len(dup))
        for x in dup:
            print("   %s" % x)
    print("\n完整清单可用： python tools/dtb-analyze.py %s --ours dump/dtb-our-sym.dtb > dump/dtbo-report.txt" % a.dtbo)


if __name__ == "__main__":
    sys.exit(main())
