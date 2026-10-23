#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""ascii-logs.py — 把驱动里**会打印出来的**字符串换成纯 ASCII。

为什么要这么干：控制台字体是 8x16 的 ASCII 字体，中文一律显示成 `?`。
注释里的中文可以留（不打印），但 dev_info/dev_warn/dev_err 里的必须换成英文。

    python tools/ascii-logs.py patches/panel-xiaomi-umi.c          # 只列出
    python tools/ascii-logs.py patches/panel-xiaomi-umi.c --apply  # 直接改
"""
import re
import sys

# 老字符串里任意一段中文 -> 英文。按"最长匹配优先"逐条替换。
MAP = [
    ("PPS 长度 ", "PPS length "),
    (" 不是 ", " != "),
    ("未知 dtype 0x%02x，已跳过", "unknown dtype 0x%02x, skipped"),
    ("偏移 %d 处越界", "overrun at offset %d"),
    ("第 %d 个包 dtype 0x%02x 失败", "packet %d dtype 0x%02x failed"),
    ("发了 %d 个包 / %d 字节", "sent %d packets / %d bytes"),
    ("（跳过 sleep-in：没有 reset 唤不醒）",
     " (sleep-in skipped: no reset, cannot wake)"),
    ("尾部剩 %d 字节没解析", "%d trailing bytes not parsed"),
    ("DSC 缺 slice 尺寸", "DSC: missing slice dimensions"),
    ("DSC 使能失败", "DSC enable failed"),
    ("复位序列已执行：%d 段（高%ums 低%ums 高%ums）",
     "reset sequence done: %d steps (hi %ums, lo %ums, hi %ums)"),
    ("复位序列：默认 低1ms -> 高10ms",
     "reset sequence: default low 1ms -> high 10ms"),
    ("缺 xiaomi,panel-width", "missing xiaomi,panel-width"),
    ("缺 xiaomi,panel-height", "missing xiaomi,panel-height"),
    ("xiaomi,no-init 已置位：只 probe，不碰面板",
     "xiaomi,no-init set: probing only, panel untouched"),
    ("no-init: 只验证 DPU/DSI/PHY 通路，不碰面板",
     "no-init: verifying DPU/DSI/PHY path only, panel untouched"),
    ("NORTH TLMM: 只放出了 gpio12(reset)，其余仍 reserved",
     "NORTH TLMM: only gpio12(reset) freed, rest still reserved"),
    ("复位脚已拿到（熄屏再亮需要它）",
     "reset-gpios acquired (needed to wake the panel)"),
    ("reset-gpios 取不到 (%ld)，退化为无复位模式",
     "no reset-gpios (%ld), running without reset"),
    ("复位脚不可用（GPIO12 在 TLMM NORTH tile），将跳过 sleep-in",
     "reset-gpios unavailable (GPIO12 in TLMM NORTH tile), will skip sleep-in"),
    ("没有 reset-gpios（umi 的 GPIO12 在 TLMM NORTH tile，暂时读不了），",
     "no reset-gpios (GPIO12 lives in the TLMM NORTH tile, unreadable for now), "),
    ("跳过复位脉冲，直接按 ABL 留下的面板状态继续",
     "skipping the reset pulse and using whatever state ABL left"),
    ("轨取不到", "supply not found"),
    ("背光注册失败", "backlight registration failed"),
    ("panel 已挂上（4 lane, cmd mode, RGB888）",
     "panel attached (4 lane, cmd mode, RGB888)"),
    ("preparing panel", "preparing panel"),
]


def main():
    path = sys.argv[1]
    apply = "--apply" in sys.argv

    src = open(path, encoding="utf-8").read()

    # 只处理"看起来像打印格式串"的字面量：含 % 或整行是日志
    lits = []
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', src):
        s = m.group(1)
        if any(ord(c) > 127 for c in s):
            lits.append((m.start(), m.end(), s))

    changed = 0
    out = []
    for start, end, s in lits:
        new = s
        for old, nw in MAP:
            if old in new:
                new = new.replace(old, nw)
        if new != s:
            changed += 1
            print("改: %r\n -> %r" % (s, new))
            out.append((start, end, new))

    if not apply:
        print("\n共 %d 处待改（加 --apply 写回）" % len(out))
        return 0

    for start, end, new in sorted(out, reverse=True):
        src = src[:start] + '"' + new + '"' + src[end:]

    left = [s for _, _, s in lits if any(ord(c) > 127 for c in s)]
    open(path, "w", encoding="utf-8", newline="\n").write(src)

    # 复查：不应该还剩非 ASCII 字面量
    lits2 = [m.group(1) for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', src)
             if any(ord(c) > 127 for c in m.group(1))]
    print("\n改完 %d 处；剩余非 ASCII 字面量 %d 个" % (len(out), len(lits2)))
    for s in lits2:
        print("  还剩:", repr(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
