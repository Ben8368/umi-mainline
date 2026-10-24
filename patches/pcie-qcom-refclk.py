#!/usr/bin/env python3
# 移植 downstream 的 PHY REFCLK 配置：
#     val = readl(parf + PCIE20_PARF_PHY_REFCLK);
#     val &= ~PHY_REFCLK_USE_PAD;
#     val |=  PHY_REFCLK_SSP_EN;
#     writel(val, parf + PCIE20_PARF_PHY_REFCLK);
# 主线 6.12/7.2 都不碰这个寄存器，于是继承了 bootloader 留下的值。
# 若 USE_PAD 置位，PHY 等的是板上 PAD 上的外部时钟，没人驱动 -> 端点拿不到
# 参考时钟 -> LTSSM 永远停在 Detect.Quiet（正是我们看到的 state=0x0）。
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

if "PARF_PHY_REFCLK" in t:
    print("already patched")
    sys.exit(0)

# 加寄存器定义
old_def = """#define ELBI_SYS_CTRL				0x04
#define ELBI_SYS_STTS				0x08
"""
assert old_def in t, "ELBI defines not found (did the LTSSM patch apply?)"
new_def = """#define ELBI_SYS_CTRL				0x04
#define ELBI_SYS_STTS				0x08

/* PARF PHY REFCLK control (from the downstream driver) */
#define PCIE20_PARF_PHY_REFCLK			0x4C
#define PHY_REFCLK_SSP_EN			BIT(16)
#define PHY_REFCLK_USE_PAD			BIT(12)
"""
t = t.replace(old_def, new_def, 1)

# 在 host_init 里、控制器初始化之前配置
anchor = """	qcom_ep_reset_assert(pcie);

	ret = pcie->cfg->ops->init(pcie);
"""
assert anchor in t, "host_init anchor not found"

insert = """	qcom_ep_reset_assert(pcie);

	/*
	 * PHY REFCLK source. Ported from the downstream driver, which does:
	 *
	 *     val = readl(parf + PCIE20_PARF_PHY_REFCLK);
	 *     val &= ~PHY_REFCLK_USE_PAD;     // no external pad clock
	 *     val |=  PHY_REFCLK_SSP_EN;      // spread-spectrum on
	 *     writel(val, parf + PCIE20_PARF_PHY_REFCLK);
	 *
	 * Mainline never programs this register (checked 6.12 and 7.2), so we
	 * inherit whatever ABL left behind. With USE_PAD set the PHY expects a
	 * reference clock on the pad that nothing drives, the endpoint gets no
	 * clock at all, and LTSSM sits in Detect.Quiet forever - exactly the
	 * state=0x0 we measured.
	 */
	{
		u32 refclk = readl(pcie->parf + PCIE20_PARF_PHY_REFCLK);

		dev_info(pci->dev, "PHY_REFCLK before: 0x%08x\\n", refclk);

		refclk &= ~PHY_REFCLK_USE_PAD;
		refclk |= PHY_REFCLK_SSP_EN;
		writel(refclk, pcie->parf + PCIE20_PARF_PHY_REFCLK);

		dev_info(pci->dev, "PHY_REFCLK after:  0x%08x\\n",
			 readl(pcie->parf + PCIE20_PARF_PHY_REFCLK));
	}

	ret = pcie->cfg->ops->init(pcie);
"""
t = t.replace(anchor, insert, 1)
io.open(P, "w", encoding="utf-8").write(t)
print("PHY REFCLK configuration ported from downstream")
