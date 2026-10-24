#!/usr/bin/env python3
# 把 7.2 的 LTSSM 诊断移植到 6.12 的 pcie-qcom.c
# 目的：分清 "卡根本没回应" 和 "卡回应了但没初始化"
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

if "ELBI_SYS_STTS" in t:
    print("already patched")
    sys.exit(0)

# 1) 加寄存器定义（跟在 ELBI_SYS_CTRL 那组后面）
old_def = """#define ELBI_SYS_CTRL				0x04
"""
assert old_def in t, "ELBI_SYS_CTRL define not found"
new_def = """#define ELBI_SYS_CTRL				0x04
#define ELBI_SYS_STTS				0x08
"""
t = t.replace(old_def, new_def, 1)

old_field = """/* ELBI_SYS_CTRL register fields */
#define ELBI_SYS_CTRL_LT_ENABLE			BIT(0)
"""
assert old_field in t, "ELBI_SYS_CTRL fields block not found"
new_field = """/* ELBI_SYS_CTRL register fields */
#define ELBI_SYS_CTRL_LT_ENABLE			BIT(0)

/* ELBI_SYS_STTS register fields (port from 7.2) */
#define ELBI_SYS_STTS_LTSSM_STATE_MASK		GENMASK(17, 12)
"""
t = t.replace(old_field, new_field, 1)

# 2) 在 reset deassert 之后读一次 LTSSM，把状态打进日志
anchor = """	qcom_pcie_clear_aspm_l0s(pcie->pci);

	qcom_ep_reset_deassert(pcie);
"""
assert anchor in t, "reset deassert anchor not found"
insert = """	qcom_pcie_clear_aspm_l0s(pcie->pci);

	qcom_ep_reset_deassert(pcie);

	/*
	 * LTSSM diagnostic ported from 7.2 (pcie-designware.c reads it on
	 * link timeout). The Qcom ELBI block exposes the Link Training and
	 * Status State Machine in ELBI_SYS_STTS[17:12]:
	 *
	 *   Detect.Quiet/Active -> nothing on the bus at all (card silent)
	 *   Poll.Active/Compliance -> card answers, but is not initialized
	 *   Config.*/L0 -> link trained
	 *
	 * This one line tells us which of those we are in, instead of the
	 * generic "Phy link never came up".
	 */
	{
		u32 stts = readl(pcie->elbi + ELBI_SYS_STTS);

		dev_info(pci->dev, "LTSSM: raw=0x%08x state=0x%lx\\n",
			 stts,
			 FIELD_GET(ELBI_SYS_STTS_LTSSM_STATE_MASK, stts));
	}
"""
t = t.replace(anchor, insert, 1)

io.open(P, "w", encoding="utf-8").write(t)
print("LTSSM diagnostic installed")
