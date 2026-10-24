#!/usr/bin/env python3
# 6.12 的 pci_pwrctl（单 r）绑定 wifi@0 这个 platform device，而它要等 PCI 枚举
# 完成才由 of_pci 创建。于是 pwrseq_power_on()（使能 regulator + 拉高 WLAN_EN）
# 永远发生在链路训练**之后** —— 死锁。
#
# 7.2 用新的 pci_pwrctrl 框架在 qcom_pcie_host_init 里主动
# pci_pwrctrl_power_on_devices()，在 PERST 释放之前给端点上电。
#
# 这里不搬整个框架，只在 host_init 里手动提前调一次 pwrseq_power_on()。
# consumer 用 qca6390-pmu 自己的 device：pwrseq_qcom_wcn_match() 只要求节点带
# vddaon-supply，它满足，因此能匹配到同一个 provider。
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

MARK = "early WLAN power-on"

if MARK in t:
    print("already patched")
    sys.exit(0)

# 确保 include
if "#include <linux/pwrseq/consumer.h>" not in t:
    anchor_inc = "#include <linux/phy/phy.h>"
    assert anchor_inc in t, "phy.h include not found"
    t = t.replace(anchor_inc,
                  anchor_inc + "\n#include <linux/pwrseq/consumer.h>", 1)

# 在 host_init 里，PERST 释放之前给端点上电
anchor = """	qcom_ep_reset_deassert(pcie);
"""
assert anchor in t, "reset deassert anchor not found"

insert = """	/*
	 * early WLAN power-on: the old pci_pwrctl in 6.12 binds wifi@0,
	 * which only exists after PCI enumeration - so pwrseq_power_on()
	 * (regulator_bulk_enable + WLAN_EN high) used to run *after* link
	 * training had already failed. Do it here, before PERST# is released.
	 * 7.2 solves this with the newer pci_pwrctrl framework; this is the
	 * minimal equivalent.
	 */
	{
		struct device_node *pmu_np;

		pmu_np = of_find_compatible_node(NULL, NULL,
						 "qcom,qca6390-pmu");
		if (pmu_np) {
			struct platform_device *pmu;
			struct pwrseq_desc *pwrseq;

			pmu = of_find_device_by_node(pmu_np);
			if (pmu) {
				pwrseq = devm_pwrseq_get(&pmu->dev, "wlan");
				if (IS_ERR(pwrseq)) {
					dev_info(pci->dev,
						 "early power-on: pwrseq unavailable (%ld)\\n",
						 PTR_ERR(pwrseq));
				} else {
					int pret = pwrseq_power_on(pwrseq);

					dev_info(pci->dev,
						 "early power-on: pwrseq_power_on -> %d\\n",
						 pret);
				}
			}
			of_node_put(pmu_np);
		} else {
			dev_info(pci->dev,
				 "early power-on: no qca6390-pmu node\\n");
		}
	}

	qcom_ep_reset_deassert(pcie);
"""
t = t.replace(anchor, insert, 1)
io.open(P, "w", encoding="utf-8").write(t)
print("early WLAN power-on added to qcom_pcie_host_init")
