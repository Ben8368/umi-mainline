#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""dtb.py — 极简 FDT(DTB) 解析器：打印关键属性 / 按路径查节点 / 校验

为什么需要它：小米10 掉回 fastboot 的第一嫌疑是 ABL 挑不到 DTB，
而 ABL 只看这几个属性：
    /qcom,msm-id      <SoC-ID  revision>
    /qcom,board-id    <board-ID subtype>
    /qcom,pmic-id     <pmic0 pmic1 pmic2 pmic3>
所以每次打包前都必须确认编译出来的 DTB 里这几个值是对的。

用法：
    python dtb.py ids   out/sm8250-xiaomi-umi.dtb      # 只看 ABL 关心的匹配属性
    python dtb.py props out/sm8250-xiaomi-umi.dtb       # 看 model/compatible/chosen/...
    python dtb.py ls    out/sm8250-xiaomi-umi.dtb       # 列出所有节点
    python dtb.py find  out/...dtb reserved-memory      # 按名字找节点
    python dtb.py check out/...dtb                      # 结构自检
"""
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FDT_MAGIC = 0xD00DFEED

# 字符串属性直接打印；u32 属性按「可能是什么」两种形式都打印
STR_PROPS = {"model", "compatible", "status", "stdout-path", "bootargs", "label", "reg-names"}


class Node:
    __slots__ = ("name", "parent", "props", "children", "depth")

    def __init__(self, name, parent=None, depth=0):
        self.name = name
        self.parent = parent
        self.props = {}
        self.children = []
        self.depth = depth

    def path(self):
        if self.parent is None:
            return "/"
        return (self.parent.path().rstrip("/") + "/" + self.name)

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def parse(data):
    hdr = struct.unpack_from(">10I", data, 0)
    magic, totalsize, off_struct, off_strings, off_rsvmap, version, lastcomp = hdr[:7]
    if magic != FDT_MAGIC:
        raise ValueError("不是 FDT（magic=0x%08x）" % magic)
    strings = data[off_strings:]
    root = None
    cur = None
    p = off_struct
    while True:
        tok = struct.unpack_from(">I", data, p)[0]
        p += 4
        if tok == 1:  # FDT_BEGIN_NODE
            end = data.index(b"\0", p)
            name = data[p:end].decode("utf-8", "replace")
            p = end + 1
            p = (p + 3) & ~3
            n = Node(name, cur, 0 if cur is None else cur.depth + 1)
            if cur is None:
                root = n          # 第一个 BEGIN_NODE 才是真正的根节点
            else:
                cur.children.append(n)
            cur = n
        elif tok == 2:  # FDT_END_NODE
            cur = cur.parent
            if cur is None:
                break
        elif tok == 3:  # FDT_PROP
            ln, nameoff = struct.unpack_from(">II", data, p)
            p += 8
            val = data[p:p + ln]
            p = (p + ln + 3) & ~3
            end = strings.index(b"\0", nameoff)
            pname = strings[nameoff:end].decode("utf-8", "replace")
            cur.props[pname] = val
        elif tok == 4:  # FDT_NOP
            pass
        elif tok == 9:  # FDT_END
            break
        else:
            raise ValueError("坏 token 0x%x @0x%x" % (tok, p - 4))
    return root, totalsize


def u32s(v):
    return list(struct.unpack(">%dI" % (len(v) // 4), v[:len(v) // 4 * 4]))


def fmt(v):
    try:
        s = v.split(b"\0", 1)[0].decode("utf-8")
        if all(32 <= ord(c) < 127 for c in s) and s:
            return '"%s"' % s
    except Exception:
        pass
    if len(v) % 4 == 0:
        return " ".join("<0x%x>" % x if x > 9 else "<%d>" % x for x in u32s(v))
    return v.hex()


def cmd_ids(a):
    root, _ = parse(open(a.dtb, "rb").read())
    found = {}
    for k in ("qcom,msm-id", "qcom,board-id", "qcom,pmic-id"):
        if k in root.props:          # 只看根节点：regulator 子节点里的 qcom,pmic-id 是另一回事
            found[k] = u32s(root.props[k])
    print("== ABL 用来挑 DTB 的属性 (%s)" % a.dtb)
    ok = True
    for k in ("qcom,msm-id", "qcom,board-id", "qcom,pmic-id"):
        if k in found:
            v = found[k]
            extra = ""
            if k == "qcom,msm-id":
                extra = "   SoC=%d rev=0x%x" % (v[0], v[1]) if len(v) >= 2 else ""
            if k == "qcom,board-id":
                pairs = ["<%d %d>" % (v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
                extra = "   " + " ".join(pairs)
            print("   %-16s %s%s" % (k, " ".join("0x%x" % x for x in v), extra))
        else:
            print("   %-16s <缺失>" % k)
    bid = found.get("qcom,board-id")
    if not bid:
        print("!! 没有 qcom,board-id：ABL 可能挑不到（umi 应为 43）")
        ok = False
    elif bid[0] != 43:
        print("!! qcom,board-id 第一个值是 %d，umi 下游 DTS 用的是 43 —— 确认无误？" % bid[0])
        ok = False
    else:
        print("   OK  board-id = 43（umi）")
    mid = found.get("qcom,msm-id")
    if not mid or mid[0] != 356:
        print("!! qcom,msm-id 应为 <356 0x20001>（SM8250/kona v2.1）")
        ok = False
    else:
        print("   OK  msm-id = <356 0x%x>" % mid[1])
    return 0 if ok else 1


def cmd_props(a):
    root, tot = parse(open(a.dtb, "rb").read())
    want = a.name or ["model", "compatible", "chosen", "qcom,msm-id", "qcom,board-id"]
    print("== %s  (totalsize=%d)" % (a.dtb, tot))
    for n in root.walk():
        show = []
        for k, v in n.props.items():
            if a.name:
                if k == a.name:
                    show.append((k, v))
            elif k in want or (k in STR_PROPS):
                show.append((k, v))
        if n.name in ("chosen", "aliases") and not a.name:
            show = list(n.props.items())
        if show:
            print("%s%s" % ("  " * n.depth, n.path()))
            for k, v in show:
                print("%s  %-20s %s" % ("  " * n.depth, k, fmt(v)))
    return 0


def cmd_ls(a):
    root, _ = parse(open(a.dtb, "rb").read())
    for n in root.walk():
        if n.parent is None:
            continue
        st = n.props.get("status", b"okay")
        st = st.split(b"\0")[0].decode()
        print("%s%s%s" % ("  " * (n.depth - 1), n.name, "" if st == "okay" else "   [%s]" % st))
    return 0


def cmd_find(a):
    root, _ = parse(open(a.dtb, "rb").read())
    hits = 0
    for n in root.walk():
        if a.name.lower() in n.name.lower():
            hits += 1
            print("%s" % n.path())
            for k, v in n.props.items():
                print("     %-20s %s" % (k, fmt(v)))
    if not hits:
        print("没找到匹配 %r 的节点" % a.name)
    return 0


def cmd_check(a):
    data = open(a.dtb, "rb").read()
    root, tot = parse(data)
    print("== 结构自检 %s" % a.dtb)
    print("   totalsize 头部=%d 实际文件=%d %s" % (tot, len(data), "OK" if tot == len(data) else "不一致！"))
    nn = sum(1 for _ in root.walk())
    print("   节点数 %d" % nn)
    resv = []
    for n in root.walk():
        if n.name == "reserved-memory":
            for c in n.children:
                if "reg" in c.props and len(c.props["reg"]) >= 8:
                    r = u32s(c.props["reg"])
                    for i in range(0, len(r) - 1, 2):
                        resv.append((c.name, (r[i] << 32) | r[i + 1], (r[i + 2] << 32) | r[i + 3] if i + 3 < len(r) else 0))
    for name, base, size in resv:
        print("   reserved %-24s 0x%09x - 0x%09x (%d KiB)" % (name, base, base + size, size // 1024))
    ch = next((n for n in root.walk() if n.name == "chosen"), None)
    if ch:
        for k in ("bootargs", "stdout-path", "linux,initrd-start"):
            if k in ch.props:
                print("   chosen %-16s %s" % (k, fmt(ch.props[k])))
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="DTB 解析小工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, need_name in (("ids", cmd_ids, False), ("props", cmd_props, True),
                                ("ls", cmd_ls, False), ("find", cmd_find, True),
                                ("check", cmd_check, False)):
        p = sub.add_parser(name)
        p.add_argument("dtb")
        if need_name:
            p.add_argument("name", nargs="?")
        p.set_defaults(func=fn)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
