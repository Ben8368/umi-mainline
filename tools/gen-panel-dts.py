#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen-panel-dts.py — 把下游 DTB 里的面板节点转成主线用的 DTS include

为什么要这么干：
  下游 kona 把 28 个面板变体的全部参数（时序、DSC、上电序列、init 序列、
  亮度…）都塞在 `qcom,mdss_dsi_<名字> { ... }` 里。主线没有对应驱动，
  这些数据除了重新抄一遍没有别的来源。

本脚本把它转成"驱动从 DT 读数据"的形式：

    &mdss_dsi0 {
        umi-panel@0 {
            compatible = "xiaomi,umi-panel";
            reg = <0>;
            status = "okay";
            xiaomi,panel-id = <0x4a32 0x420201>;
            ...（时序 / DSC / 亮度，沿用下游语义，换成 xiaomi, 前缀）
            xiaomi,on-seq  = /bits/ 8 <39 01 00 00 00 00 06 f0 55 aa ...>;
            xiaomi,off-seq = /bits/ 8 <05 01 00 00 00 00 02 28 00 ...>;
            ports { port@0 { endpoint { remote-endpoint = <&mdss_dsi0_out>; }; }; };
        };
    };
    &mdss_dsi0_out { data-lanes = <0 1 2 3>; remote-endpoint = <&umi_panel_in>; };

★ 为什么 32 位单元要展开成 4 字节：
  下游 DT 写的是 <0x39010000 0x6f0 0x55aa5208 ...>。dtc 把它当 32 位单元，
  实际字节流是 39 01 00 00 | 00 00 06 f0 | 55 aa 52 08 …，
  也就是 dtype=0x39 last=1 vc=0 ack=0 wait=0 dlen=0x0006 payload=f0 55 aa 52 08 07。
  **必须按 4 字节大端展开**，不能按"有效位数"截断，否则整段错位。
  （验证工具：tools/parse-dsi-seq.py）

用法:
    python tools/gen-panel-dts.py dump/panels -o dts/xiaomi-umi-panels.dtsi \
        --enable qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd
"""
import argparse
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 下游属性 -> 主线属性（保留原语义，换成 xiaomi, 前缀，避免和 msm 的 binding 冲突）
RENAME = [
    ("qcom,mdss-dsi-panel-type", "xiaomi,panel-type"),
    ("qcom,mdss-dsi-bpp", "xiaomi,bpp"),
    ("qcom,mdss-dsi-traffic-mode", "xiaomi,traffic-mode"),
    ("qcom,mdss-dsi-lane-map", "xiaomi,lane-map"),
    ("qcom,mdss-dsi-reset-sequence", "xiaomi,reset-sequence"),
    ("qcom,mdss-pan-physical-width-dimension", "xiaomi,physical-width-mm"),
    ("qcom,mdss-pan-physical-height-dimension", "xiaomi,physical-height-mm"),
    ("qcom,mdss-dsi-panel-width", "xiaomi,panel-width"),
    ("qcom,mdss-dsi-panel-height", "xiaomi,panel-height"),
    ("qcom,mdss-dsi-panel-framerate", "xiaomi,framerate"),
    ("qcom,mdss-dsi-panel-clockrate", "xiaomi,clockrate"),
    ("qcom,mdss-dsi-h-front-porch", "xiaomi,h-front-porch"),
    ("qcom,mdss-dsi-h-back-porch", "xiaomi,h-back-porch"),
    ("qcom,mdss-dsi-h-pulse-width", "xiaomi,h-pulse-width"),
    ("qcom,mdss-dsi-h-sync-skew", "xiaomi,h-sync-skew"),
    ("qcom,mdss-dsi-v-back-porch", "xiaomi,v-back-porch"),
    ("qcom,mdss-dsi-v-front-porch", "xiaomi,v-front-porch"),
    ("qcom,mdss-dsi-v-pulse-width", "xiaomi,v-pulse-width"),
    ("qcom,mdss-dsi-panel-phy-timings", "xiaomi,phy-timings"),
    ("qcom,mdss-dsi-bl-pmic-control-type", "xiaomi,bl-type"),
    ("qcom,mdss-dsi-bl-min-level", "xiaomi,bl-min"),
    ("qcom,mdss-dsi-bl-max-level", "xiaomi,bl-max"),
    ("qcom,mdss-dsi-on-command", "xiaomi,on-seq"),
    ("qcom,mdss-dsi-off-command", "xiaomi,off-seq"),
    ("qcom,compression-mode", "xiaomi,compression"),
    ("qcom,mdss-dsc-version", "xiaomi,dsc-version"),
    ("qcom,mdss-dsc-slice-height", "xiaomi,dsc-slice-height"),
    ("qcom,mdss-dsc-slice-width", "xiaomi,dsc-slice-width"),
    ("qcom,mdss-dsc-slice-per-pkt", "xiaomi,dsc-slice-per-pkt"),
    ("qcom,mdss-dsc-bit-per-component", "xiaomi,dsc-bpc"),
    ("qcom,mdss-dsc-bit-per-pixel", "xiaomi,dsc-bpp"),
    ("qcom,dsi-ctrl-num", "xiaomi,dsi-ctrl"),
    ("qcom,dsi-phy-num", "xiaomi,dsi-phy"),
    ("qcom,mdss-dsi-te-pin-select", "xiaomi,te-pin-select"),
    ("qcom,mdss-dsi-te-dcs-command", "xiaomi,te-dcs-command"),
    ("qcom,mdss-dsi-wr-mem-start", "xiaomi,wr-mem-start"),
    ("qcom,mdss-dsi-wr-mem-continue", "xiaomi,wr-mem-continue"),
]

# 这些是布尔属性（下游写法没有 = 值）
BOOL_PROPS = {
    "qcom,mdss-dsc-block-prediction-enable": "xiaomi,dsc-block-prediction",
}

KEEP = {"mi,panel-id", "mi,panel-id1"}

# 这些下游属性依赖下游驱动，主线无意义，丢弃
DROP = re.compile(r'^(qcom,dsi-select-clocks|qcom,panel-supply-entries|qcom,dsi-display-active|'
                  r'qcom,dsi-ctrl-num-revision|qcom,display-topology|qcom,default-topology-index|'
                  r'qcom,mdss-mdp-transfer-time-us|qcom,mdss-dsi-timing-switch-command|'
                  r'qcom,mdss-dsi-panel-hdr|qcom,mdss-dsi-panel-peak-brightness|'
                  r'qcom,mdss-dsi-panel-blackness-level|qcom,bl-update-flag|'
                  r'qcom,mdss-dsi-color-order|qcom,mdss-dsi-underflow-color|qcom,mdss-dsi-border-color|'
                  r'qcom,mdss-dsi-dma-trigger|qcom,mdss-dsi-mdp-trigger|qcom,mdss-dsi-h-sync-pulse|'
                  r'qcom,mdss-dsi-h-left-border|qcom,mdss-dsi-h-right-border|'
                  r'qcom,mdss-dsi-v-top-border|qcom,mdss-dsi-v-bottom-border|'
                  r'qcom,mdss-dsi-panel-jitter|qcom,mdss-dsi-clk-strength|'
                  r'qcom,mdss-dsc-scr-version|qcom,mdss-dsi-virtual-channel-id|'
                  r'qcom,mdss-dsi-stream|'
                  r'qcom,mdss-brightness|mi,mdss-brightness|phandle|linux,phandle)')


def find_block(src, start):
    depth, i, n, s = 1, start, len(src), None
    while i < n:
        c = src[i]
        if s:
            if c == '\\':
                i += 2
                continue
            if c == s:
                s = None
        elif c in ('"', "'"):
            s = c
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def to_bytes_hex(val):
    """把 <0x39010000 0x6f0 ...> 或 [39 01 00 ...] 统一成字节序列。

    ★ 32 位单元一律补齐成 4 字节大端（见文件头说明），不要按有效位数截断。
    """
    v = val.strip()
    if v.startswith('['):
        return re.findall(r'[0-9a-fA-F]{2}', v.strip('[]'))
    if v.startswith('<'):
        body = v.strip()[1:-1]
        out = []
        for t in re.findall(r'0x([0-9a-fA-F]+)', body):
            n = int(t, 16)
            out += ["%02x" % b for b in n.to_bytes(4, 'big')]
        return out
    return None


def parse_props(body):
    """返回 [(key, value)]，value 为 None 表示布尔属性。"""
    out = []
    for m in re.finditer(r'(?m)^\s*([A-Za-z0-9,._+?#@-]+)\s*(=\s*[^;]+)?;', body):
        key = m.group(1)
        val = m.group(2)
        out.append((key, val[1:].strip() if val else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("panels_dir")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--enable", required=True, help="要启用的面板节点名（不带文件名后缀）")
    ap.add_argument("--status", default="okay", choices=["okay", "disabled"])
    ap.add_argument("--no-init", action="store_true",
                    help="加上 xiaomi,no-init：只 probe，不碰面板")
    a = ap.parse_args()

    fn = os.path.join(a.panels_dir, a.enable + ".dts")
    if not os.path.exists(fn):
        sys.exit("找不到 %s" % fn)
    src = open(fn, encoding="latin1").read()
    body_start = src.find('{')
    body_end = find_block(src, body_start + 1)
    body = src[body_start + 1:body_end]

    lines, seen, panel_id = [], set(), ""
    for k, v in parse_props(body):
        if k in seen:
            continue
        if k in KEEP:
            seen.add(k)
            panel_id = v
            lines.append('\t\txiaomi,panel-id = %s;' % v)
            continue
        if k in BOOL_PROPS:
            seen.add(k)
            lines.append('\t\t%s;' % BOOL_PROPS[k])
            continue
        if DROP.match(k) or v is None:
            continue
        new = None
        for old, nw in RENAME:
            if k == old:
                new = nw
                break
        if not new:
            continue
        seen.add(k)
        v = " ".join(v.split())
        if new in ("xiaomi,on-seq", "xiaomi,off-seq"):
            toks = to_bytes_hex(v)
            if not toks:
                continue
            # ★ <...> 里的单元只能用空白分隔，**不能写逗号**（那是 /bits/ 数组之外
            #   才有的语法），而且必须写 0xNN —— 裸写的 08/09 会被 dtc 当成非法八进制。
            toks = ["0x" + t for t in toks]
            rows = [" ".join(toks[i:i + 16]) for i in range(0, len(toks), 16)]
            lines.append("\t\t%s = /bits/ 8 <%s>;" % (new, "\n\t\t\t".join(rows)))
            continue
        lines.append("\t\t%s = %s;" % (new, v))

    if not any("xiaomi,on-seq" in l for l in lines):
        sys.exit("!! %s 里没解析出 on-seq，先别生成" % fn)

    extra = '\t\txiaomi,no-init;\n' if a.no_init else ""
    out = []
    out.append("// SPDX-License-Identifier: BSD-3-Clause")
    out.append("/*")
    out.append(" * xiaomi-umi-panels.dtsi — 自动生成，别手改")
    out.append(" *   生成: python tools/gen-panel-dts.py dump/panels \\")
    out.append(" *             -o dts/xiaomi-umi-panels.dtsi --enable %s%s"
               % (a.enable, " --no-init" if a.no_init else ""))
    out.append(" *")
    out.append(" * 数据全部来自设备自己的下游 DTB。驱动只认 \"xiaomi,umi-panel\"，")
    out.append(" * 时序 / init 序列 / DSC 参数都从 DT 读 —— 换屏只改 --enable，不用改驱动。")
    out.append(" *")
    out.append(" * ★ 面板节点必须是 &mdss_dsi0 的子节点（reg = <0> 选虚拟通道 0），")
    out.append(" *   否则 mipi_dsi 不会为它创建 mipi_dsi_device，驱动根本不会 probe。")
    out.append(" * ★ 22 个变体不要同时塞进来：同一父节点下只能有一个 panel@0。")
    out.append(" *   换屏 = 重新跑一次生成器 + dtb-only.sh（1 分钟，不用重编内核）。")
    out.append(" */")
    out.append("")
    out.append("&mdss_dsi0 {")
    out.append("\tumi-panel@0 {")
    out.append('\t\tcompatible = "xiaomi,umi-panel";')
    out.append("\t\treg = <0>;")
    out.append('\t\tstatus = "%s";' % a.status)
    out.append(extra.rstrip("\n") if extra else "\t\t/* xiaomi,no-init; */")
    out.append("\n".join(lines))
    out.append("")
    out.append("\t\tports {")
    out.append("\t\t\t#address-cells = <1>;")
    out.append("\t\t\t#size-cells = <0>;")
    out.append("")
    out.append("\t\t\tport@0 {")
    out.append("\t\t\t\treg = <0>;")
    out.append("")
    out.append("\t\t\t\tumi_panel_in: endpoint {")
    out.append("\t\t\t\t\tremote-endpoint = <&mdss_dsi0_out>;")
    out.append("\t\t\t\t};")
    out.append("\t\t\t};")
    out.append("\t\t};")
    out.append("\t};")
    out.append("};")
    out.append("")
    out.append("&mdss_dsi0_out {")
    out.append("\tdata-lanes = <0 1 2 3>;\t/* 下游 lane-0..3-state 全开 => 4 lane DPHY */")
    out.append("\tremote-endpoint = <&umi_panel_in>;")
    out.append("};")

    text = "\n".join(out) + "\n"
    if any(ord(ch) > 127 for ch in text):
        enc = "utf-8"
    else:
        enc = "utf-8"
    with open(a.output, "w", encoding=enc, newline="\n") as f:
        f.write(text)
    print("写出 %s：%d 个属性，status=%s%s，panel-id %s"
          % (a.output, len(lines), a.status,
             "，no-init" if a.no_init else "", panel_id or "<无>"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
