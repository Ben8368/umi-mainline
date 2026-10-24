#!/usr/bin/env python3
# 撤掉之前那个 sm8250 REFCLK 补丁。
# 依据：7.2.12 里根本没有 PHY_REFCLK 相关代码，作者的 7.2.7 内核不碰这个寄存器，
# 保持 ABL 留下的 0x1019 就能让 WiFi 工作。我们把它改成 0x10019 反而破坏了
# bootloader 配置好的值。
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

MARK = "sm8250 REFCLK wa"
if MARK not in t:
    print("patch not present, nothing to do")
    sys.exit(0)

start = t.find("\n\t/*\n\t * " + MARK)
if start < 0:
    start = t.find("\t/*\n\t * " + MARK)
assert start >= 0, "block start not found"
end = t.find("\t}\n", start)
assert end > start, "block end not found"
end += len("\t}\n")

removed = t[start:end]
t = t[:start] + t[end:]

io.open(P, "w", encoding="utf-8").write(t)
print("removed REFCLK block:")
print(removed[:200] + "...")
