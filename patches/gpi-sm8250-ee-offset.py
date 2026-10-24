#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Add the sm8250 GPI DMA EE-offset variants to this tree's gpi driver.

sm8250 has two GPI DMA controllers whose EE register windows do not start at
the same place as the single "qcom,sm8250-gpi-dma" entry assumes.  Newer
mainline carries "qcom,sm8250-gpi-dma-0" (ee_offset 0x1000) and
"qcom,sm8250-gpi-dma-1" (ee_offset 0x6000); 6.12.94 only has the plain entry,
whose match data is 0, so wrap1's ee_base is computed wrong and every GPI
command goes unanswered:

    gpi a00000.dma-controller: cmd: EV ALLOCATE completion timeout:2
    gpi a00000.dma-controller: error alloc_ev_chan:-5
    geni_i2c a94000.i2c: error -ENODEV: Failed to setup GPI DMA mode

The two offsets were read straight out of the of_device_id data fields of a
working sm8250 kernel's gpi_of_match table.

Usage: gpi-sm8250-ee-offset.py <path to drivers/dma/qcom/gpi.c>
"""

import sys

if len(sys.argv) != 2:
    print("usage: %s <path to gpi.c>" % sys.argv[0])
    sys.exit(2)

path = sys.argv[1]
src = open(path).read()

if "sm8250-gpi-dma-0" in src:
    print("   gpi: already patched")
    sys.exit(0)

anchor = '\t{ .compatible = "qcom,sm8250-gpi-dma", .data = (void *)0x0 },\n'
if anchor not in src:
    print("   gpi: anchor not found in %s" % path)
    sys.exit(1)

add = (
    '\t{ .compatible = "qcom,sm8250-gpi-dma-0", .data = (void *)0x1000 },\n'
    '\t{ .compatible = "qcom,sm8250-gpi-dma-1", .data = (void *)0x6000 },\n'
)
src = src.replace(anchor, anchor + add, 1)
open(path, "w").write(src)
print("   gpi: added sm8250-gpi-dma-0 (ee 0x1000) / -1 (ee 0x6000)")
