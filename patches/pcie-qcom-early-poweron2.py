#!/usr/bin/env python3
# 修正 consumer：pwrseq_qcom_wcn_match() 要求 consumer 节点的 "vddaon-supply"
# 指向的 regulator，其 parent 必须是 PMU 节点本身。
#   qca6390-pmu 自己的 vddaon-supply 指向 PMIC 的 vreg_s6a_0p95  -> parent 是 PMIC，不匹配
#   wifi@0 的 vddaon-supply 指向 vreg_pmu_aon_0p59               -> parent 是 PMU，匹配
# 所以必须用 wifi@0 当 consumer。它平时要等 PCI 枚举后由 of_pci 创建，
# 这里在 host_init 里手动建一个（已存在时 of_platform_device_create 返回 NULL，安全）。
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

OLD = "early power-on"
if "early WLAN power-on (wifi@0 consumer)" in t:
    print("already patched")
    sys.exit(0)

# 找到旧块并整段替换
start = t.find("\t/*\n\t * early WLAN power-on:")
assert start > 0, "old block not found"
end = t.find("\n\tqcom_ep_reset_deassert(pcie);", start)
assert end > start, "end of old block not found"

new_block = """	/*
	 * early WLAN power-on (wifi@0 consumer).
	 *
	 * 6.12's old pci_pwrctl binds wifi@0, a platform device that of_pci only
	 * creates *after* PCI enumeration. So pwrseq_power_on() - which does
	 * regulator_bulk_enable() plus driving WLAN_EN high - used to run after
	 * link training had already given up. That is a hard cycle:
	 *
	 *     link training needs wifi powered
	 *     wifi power-on needs wifi@0 device
	 *     wifi@0 device needs enumeration
	 *     enumeration needs link training
	 *
	 * 7.2 breaks it with the newer pci_pwrctrl framework calling
	 * pci_pwrctrl_power_on_devices() right here. We do the minimal
	 * equivalent: create the wifi@0 platform device early from the DT node
	 * and call pwrseq_power_on() before PERST# is released.
	 *
	 * Note the consumer must be wifi@0, not qca6390-pmu: pwrseq_qcom_wcn_match()
	 * checks that vddaon-supply resolves to a regulator whose parent is the
	 * PMU node itself (-> -EPROBE_DEFER otherwise).
	 */
	{
		struct device_node *port_np, *wifi_np;

		port_np = of_get_child_by_name(pcie->pci->dev->of_node,
					       "pcie@0");
		wifi_np = port_np ? of_get_child_by_name(port_np, "wifi@0")
				  : NULL;

		if (wifi_np) {
			struct platform_device *wdev;
			struct pwrseq_desc *pwrseq;

			wdev = of_platform_device_create(wifi_np, NULL,
							 pcie->pci->dev);
			if (wdev) {
				pwrseq = devm_pwrseq_get(&wdev->dev, "wlan");
				if (IS_ERR(pwrseq)) {
					dev_info(pci->dev,
						 "early power-on: pwrseq %ld\\n",
						 PTR_ERR(pwrseq));
				} else {
					dev_info(pci->dev,
						 "early power-on: ret=%d\\n",
						 pwrseq_power_on(pwrseq));
				}
			} else {
				dev_info(pci->dev,
					 "early power-on: wifi@0 device create failed\\n");
			}
			of_node_put(wifi_np);
		} else {
			dev_info(pci->dev, "early power-on: no wifi@0 node\\n");
		}
		if (port_np)
			of_node_put(port_np);
	}
"""

t = t[:start] + new_block + t[end + 1:]
io.open(P, "w", encoding="utf-8").write(t)
print("consumer switched to wifi@0")
