#!/usr/bin/env python3
# PERST# 释放后只等 1ms 就开始 link training，而 PCIe 规范要求 T_PVPERL >= 100ms。
# 把 deassert 之后的等待拉长，给 QCA6390 的 PLL 留出锁定时间。
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

if "T_PVPERL" in t:
    print("already patched")
    sys.exit(0)

old = """static void qcom_ep_reset_deassert(struct qcom_pcie *pcie)
{
	/* Ensure that PERST has been asserted for at least 100 ms */
	msleep(100);
	gpiod_set_value_cansleep(pcie->reset, 0);
	usleep_range(PERST_DELAY_US, PERST_DELAY_US + 500);
}
"""

new = """static void qcom_ep_reset_deassert(struct qcom_pcie *pcie)
{
	/* Ensure that PERST has been asserted for at least 100 ms */
	msleep(100);
	gpiod_set_value_cansleep(pcie->reset, 0);

	/*
	 * PCIe spec T_PVPERL: after PERST# is deasserted the reference clock
	 * must be stable (and the card's PLL locked) before link training
	 * starts. That budget is up to 100 ms. The upstream driver waits only
	 * PERST_DELAY_US (1 ms), which is why the QCA6390 here stays in
	 * LTSSM Detect.Quiet (state 0x0) - it simply is not awake yet when
	 * training begins.
	 */
	msleep(120);
}
"""

assert old in t, "qcom_ep_reset_deassert not found in expected form"
t = t.replace(old, new, 1)
io.open(P, "w", encoding="utf-8").write(t)
print("PERST deassert delay widened to 120 ms (T_PVPERL)")
