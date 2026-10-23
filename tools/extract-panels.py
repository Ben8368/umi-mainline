#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""extract-panels.py — 从下游 DTB 反编译出的 .dts 里提取所有面板节点

下游 kona 的 mdss 面板全写成 `qcom,mdss_dsi_<名字> { ... }` 这样的节点，
里面装的是完整的上电/初始化序列、时序、DSC 参数。要写主线面板驱动，
这些数据就是唯一的来源。

用法:
    python tools/extract-panels.py dump/downstream.dts            # 列表
    python tools/extract-panels.py dump/downstream.dts --dump-dir dump/panels
"""
import argparse
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NODE_RE = re.compile(r'^(\s*)(qcom,mdss_dsi_[A-Za-z0-9_]+)\s*\{', re.M)
PROP_RE = re.compile(r'^\s*([A-Za-z0-9,._+?#-]+)\s*=\s*(.+?);\s*$', re.M | re.S)


def find_block(src, start):
    """从 start（节点名后）开始，按花括号配对找到节点体结束位置。"""
    depth = 1
    i = start
    n = len(src)
    in_str = None
    while i < n:
        c = src[i]
        if in_str:
            if c == '\\':
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ('"', "'"):
            in_str = c
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def get_prop(body, key, limit=None):
    m = re.search(r'(?m)^\s*' + re.escape(key) + r'\s*=\s*([^;]+);', body)
    if not m:
        return ""
    v = " ".join(m.group(1).split())
    if limit:
        v = v[:limit]
    return v


def parse_all(path):
    src = open(path, "r", encoding="latin1").read()
    out = []
    for m in NODE_RE.finditer(src):
        indent, name = m.group(1), m.group(2)
        end = find_block(src, m.end())
        if end < 0:
            continue
        body = src[m.end():end]
        out.append(dict(
            name=name,
            offset=m.start(),
            body=body,
            panel_name=get_prop(body, "qcom,mdss-dsi-panel-name"),
            panel_type=get_prop(body, "qcom,mdss-dsi-panel-type"),
            panel_id=get_prop(body, "mi,panel-id"),
            width=get_prop(body, "qcom,mdss-dsi-panel-width"),
            height=get_prop(body, "qcom,mdss-dsi-panel-height"),
            fps=get_prop(body, "qcom,mdss-dsi-panel-framerate"),
            clockrate=get_prop(body, "qcom,mdss-dsi-panel-clockrate"),
            phy=get_prop(body, "qcom,mdss-dsi-panel-phy-timings"),
            compression=get_prop(body, "qcom,compression-mode"),
            bl_type=get_prop(body, "qcom,mdss-dsi-bl-pmic-control-type"),
            bl_min=get_prop(body, "qcom,mdss-dsi-bl-min-level"),
            bl_max=get_prop(body, "qcom,mdss-dsi-bl-max-level"),
            has_on=bool(get_prop(body, "qcom,mdss-dsi-on-command")),
            has_off=bool(get_prop(body, "qcom,mdss-dsi-off-command")),
            n_timings=body.count("qcom,mdss-dsi-display-timings"),
            n_dsc=body.count("qcom,mdss-dsi-dsc"),
        ))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dts")
    ap.add_argument("--dump-dir", default=None)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    panels = parse_all(a.dts)
    print("共找到 %d 个 qcom,mdss_dsi_* 面板节点\n" % len(panels))

    # 区分：umi 真正用的（名字里带 j2/j3/k81/m82/l3a 这类小米代号或带 mi,panel-id）
    real = [p for p in panels if p["panel_id"] or re.search(r'_(j\d|k\d\d|l\d+[a-z]?|m\d\d)', p["name"])]
    ref = [p for p in panels if p not in real]

    def show(lst, title):
        print("=" * 110)
        print(title)
        print("%-46s %-7s %-14s %-11s %-6s %-6s %s"
              % ("节点名", "类型", "panel-id", "分辨率", "fps", "DSC", "panel-name"))
        for p in lst:
            t = "cmd" if "cmd" in p["panel_type"] else ("video" if "video" in p["panel_type"] else "?")
            print("%-46s %-7s %-14s %-11s %-6s %-6s %s" % (
                p["name"], t, p["panel_id"] or "-",
                ("%sx%s" % (p["width"], p["height"])) if p["width"] else "?",
                p["fps"] or "-", "yes" if p["n_dsc"] else "-",
                p["panel_name"][:44]))
        print()

    show(real, "★ umi 相关（有 mi,panel-id 或小米代号）")
    show(ref, "Qualcomm 参考面板（不是 umi 的，但结构可参考）")

    if a.dump_dir:
        os.makedirs(a.dump_dir, exist_ok=True)
        for p in panels:
            with open(os.path.join(a.dump_dir, p["name"] + ".dts"), "w",
                      encoding="latin1") as f:
                f.write("%s {\n%s\n};\n" % (p["name"], p["body"]))
        print("已把每个面板节点单独写到 %s/（%d 个文件）" % (a.dump_dir, len(panels)))

    if a.json:
        slim = [{k: v for k, v in p.items() if k != "body"} for p in panels]
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=1)
        print("索引写到 %s" % a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
