#!/usr/bin/env python3
# sm8250 (qcom,pcie-sm8250 -> cfg_1_9_0 -> ops_1_9_0 -> init_2_7_0 / post_init_2_7_0)
# 这条路径**从来不配置 PARF_PHY_REFCLK**。只有老的 post_init_2_1_0（ipq8064）配。
#
# downstream 驱动是明确配的：
#     val = readl(parf + PCIE20_PARF_PHY_REFCLK);
#     val &= ~PHY_REFCLK_USE_PAD;
#     val |=  PHY_REFCLK_SSP_EN;
#     writel(val, parf + PCIE20_PARF_PHY_REFCLK);
#
# 如果 ABL 留下的 USE_PAD=1，PHY 会等板上 PAD 的外部参考时钟；没人驱动它，
# 端点就拿不到参考时钟，LTSSM 永远停在 Detect.Quiet —— 正是实测的 state=0x0。
#
# 注意上一版补丁写错了：它检查 "PARF_PHY_REFCLK" 是否出现过就判定"已打过"，
# 而上游在 ipq8064 那段里本来就有这个字符串，于是补丁什么也没加就退出了。
# 这次用独特的标记字符串来判断。
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

MARK = "sm8250 REFCLK wa"

if MARK in t:
    print("already patched")
    sys.exit(0)

# 寄存器定义（若上游 ipq8064 已有则复用）
if "#define PARF_PHY_REFCLK" not in t:
    anchor_def = "#define PARF_DEVICE_TYPE"
    assert anchor_def in t
    t = t.replace(anchor_def,
                  "#define PARF_PHY_REFCLK\t\t\t\t0x4C\n" + anchor_def, 1)

if "#define PHY_REFCLK_SSP_EN" not in t:
    anchor_f = "/* PARF_PHY_CTRL register fields */"
    assert anchor_f in t
    t = t.replace(anchor_f,
                  "/* PARF_PHY_REFCLK register fields */\n"
                  "#define PHY_REFCLK_SSP_EN\t\t\tBIT(16)\n"
                  "#define PHY_REFCLK_USE_PAD\t\t\tBIT(12)\n\n" + anchor_f, 1)

# 插入到 init_2_7_0 里：regulator/clk 都使能之后，开始写 parf 之前
anchor = """	ret = clk_bulk_prepare_enable(res->num_clks, res->clks);
	if (ret < 0)
		goto err_disable_regulators;
"""
assert anchor in t, "init_2_7_0 clk anchor not found"

insert = anchor + """
	/*
	 * sm8250 REFCLK wa: this ops path never programs PARF_PHY_REFCLK
	 * (only the old ipq8064 post_init_2_1_0 does). Downstream does it
	 * explicitly, and without it the PHY may be waiting for an external
	 * pad clock that nobody drives -> endpoint never gets a reference
	 * clock -> LTSSM stays in Detect.Quiet.
	 */
	{
		u32 refclk = readl(pcie->parf + PARF_PHY_REFCLK);

		dev_info(dev, "PHY_REFCLK before: 0x%08x\\n", refclk);
		refclk &= ~PHY_REFCLK_USE_PAD;
		refclk |= PHY_REFCLK_SSP_EN;
		writel(refclk, pcie->parf + PARF_PHY_REFCLK);
		dev_info(dev, "PHY_REFCLK after:  0x%08x\\n",
			 readl(pcie->parf + PARF_PHY_REFCLK));
	}
"""
t = t.replace(anchor, insert, 1)
io.open(P, "w", encoding="utf-8").write(t)
print("sm8250 REFCLK programming added to init_2_7_0")
