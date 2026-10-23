#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""parse-dsi-seq.py — 解析下游 `qcom,mdss-dsi-on-command` 的 DSI 包流

下游格式（downstream-kernel/drivers/video/fbdev/msm/mdss_dsi_cmd.h）：

    struct dsi_ctrl_hdr {           /* __packed, 7 字节 */
        char  dtype;                /* 0 */
        char  last;                 /* 1  ★ 不是终止符 */
        char  vc;                   /* 2 */
        char  ack;                  /* 3 */
        char  wait;                 /* 4  单字节！ */
        short dlen;                 /* 5  大端 */
    };
    payload[dlen]

DT 里是 32 位单元数组，按大端展开成字节流后即可解析。

    python3 tools/parse-dsi-seq.py dump/panels/qcom,mdss_dsi_j2_mp_42_02_0b_dsc_cmd.dts
"""
import re
import sys

DTYPE = {
    0x03: "GEN_WRITE",
    0x04: "GEN_READ",
    0x05: "DCS_WRITE",
    0x06: "DCS_READ",
    0x07: "COMPRESSION_MODE",
    0x09: "GEN_LREAD",
    0x0A: "PPS",
    0x13: "GEN_WRITE1",
    0x15: "DCS_WRITE1",
    0x1A: "GEN_READ1",
    0x1C: "DCS_READ1",
    0x23: "GEN_WRITE2",
    0x29: "GEN_LWRITE",
    0x37: "COMPRESSION_MODE?",  # 0x07 | 0x30 (param)
    0x39: "DCS_LWRITE",
}

DCS_NAME = {
    0x01: "soft-reset", 0x10: "sleep-in", 0x11: "sleep-out",
    0x13: "normal-mode-on", 0x20: "invert-off", 0x28: "display-off",
    0x29: "display-on", 0x2A: "set-column-addr", 0x2B: "set-page-addr",
    0x2C: "write-mem-start", 0x35: "set-tear-on", 0x3C: "write-mem-continue",
    0x44: "set-tear-scanline", 0x51: "set-brightness", 0x53: "write-ctrl-display",
    0xB0: "panel-reg-b0", 0xB2: "panel-reg-b2", 0xB4: "panel-reg-b4",
    0xB5: "panel-reg-b5", 0xB7: "panel-reg-b7", 0xB8: "panel-reg-b8",
    0xB9: "panel-reg-b9", 0xBB: "panel-reg-bb", 0xCD: "panel-reg-cd",
    0xD2: "panel-reg-d2", 0xF0: "manufacturer-cmd-set", 0xF3: "panel-reg-f3",
    0xFC: "panel-reg-fc", 0xFD: "panel-reg-fd", 0xFF: "panel-reg-ff",
}


def cells_to_bytes(body):
    out = []
    for tok in re.findall(r"0x([0-9a-fA-F]+)", body):
        n = int(tok, 16)
        width = (len(tok) + 1) // 2
        width = 4 if width > 4 else width
        out += list(n.to_bytes(width, "big"))[-4:] if width == 4 else [0] * (4 - width) + list(n.to_bytes(width, "big"))
    return out


def parse(seq, verbose=True):
    i, n, pkts = 0, len(seq), []
    while i + 7 <= n:
        dtype, last, vc, ack, wait = seq[i], seq[i + 1], seq[i + 2], seq[i + 3], seq[i + 4]
        dlen = (seq[i + 5] << 8) | seq[i + 6]
        if i + 7 + dlen > n:
            pkts.append(("TRUNCATED", i, dtype, dlen))
            break
        payload = seq[i + 7:i + 7 + dlen]
        pkts.append((DTYPE.get(dtype, "??0x%02x" % dtype), last, wait, payload))
        i += 7 + dlen
    if verbose:
        for k, (name, *rest) in enumerate(pkts):
            if name == "TRUNCATED":
                print("  [%2d] %-18s %s" % (k, name, rest))
                continue
            last, wait, pl = rest
            head = " ".join("%02x" % b for b in pl[:16])
            if len(pl) > 16:
                head += " ...(%d B)" % len(pl)
            note = ""
            if pl:
                dcs = DCS_NAME.get(pl[0])
                if dcs and "DCS" in name:
                    note = "  <- " + dcs
            print("  [%2d] %-18s last=%d wait=%-3d dlen=%-4d %s%s"
                  % (k, name, last, wait, len(pl), head, note))
        print("  共 %d 字节，%d 个包，消费 %d 字节"
              % (len(seq), len(pkts), i))
        kinds = {}
        for name, *_ in pkts:
            kinds[name] = kinds.get(name, 0) + 1
        print("  类型统计:", ", ".join("%s x%d" % (k, v) for k, v in kinds.items()))
    return pkts, i


def main():
    src = open(sys.argv[1], encoding="latin1", errors="replace").read()
    for key in ("qcom,mdss-dsi-on-command", "qcom,mdss-dsi-off-command"):
        m = re.search(re.escape(key) + r"\s*=\s*([^;]+);", src)
        if not m:
            continue
        raw = m.group(1).strip()
        if raw.startswith("["):
            seq = [int(t, 16) for t in re.findall(r"[0-9a-fA-F]{2}", raw.strip("[]"))]
        else:
            seq = cells_to_bytes(raw)
        print("== %s (%d B)" % (key, len(seq)))
        parse(seq)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
