#!/usr/bin/env python3
# 在 dw_pcie_host_init(pp) 之后加 LTSSM 读取（此时 link training 已经判定结束）
import io
import sys

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

if "LTSSM after training" in t:
    print("already patched")
    sys.exit(0)

anchor = """	ret = dw_pcie_host_init(pp);
	if (ret) {
		dev_err(dev, "cannot initialize host\\n");
		goto err_phy_exit;
	}
"""
assert anchor in t, "call site not found"

insert = """	ret = dw_pcie_host_init(pp);

	/*
	 * LTSSM after training: this is the state that matters. If the card is
	 * alive it answers during training and LTSSM parks in Poll.* or
	 * Config.*; if it is dead it stays at Detect.Quiet (0x0).
	 * The probe right after reset deassert always reads 0x0 because
	 * training has not started yet.
	 */
	{
		u32 stts = readl(pcie->elbi + ELBI_SYS_STTS);

		dev_info(dev, "LTSSM after training: raw=0x%08x state=0x%x\\n",
			 stts,
			 FIELD_GET(ELBI_SYS_STTS_LTSSM_STATE_MASK, stts));
	}

	if (ret) {
		dev_err(dev, "cannot initialize host\\n");
		goto err_phy_exit;
	}
"""
t = t.replace(anchor, insert, 1)
io.open(P, "w", encoding="utf-8").write(t)
print("post-training LTSSM probe installed")
