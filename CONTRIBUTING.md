# Contributing

## What is welcome

* **Device variants.** Other panels (CSOT `j2_42_*`, Samsung `j2_38_*`, the
  `l3a_*`/`l10a_*` boards) and the Goodix GT9889 touch variant. The panel
  driver is already data driven from DT, so a new variant is usually a new
  node, not new C code.
* **Bring-up reports** for other `umi` units: panel id, touch controller
  (`/proc/bus/input/devices`), and the output of `dmesg | grep -Ei 'dsi|panel|fts'`.
* **Fixes.** Anything that makes the tree smaller, the boot quieter, or a
  comment less wrong.

## Rules that this port learned the hard way

1. **Never write a partition.** Everything is verified with `fastboot boot`.
   A patch that requires flashing is out of scope.
2. **Never change a voltage.** No regulator min/max edits, no OPP tables, no
   current limits. Rails are enabled and left at whatever the bootloader set.
3. **Kernel log strings are ASCII.** The framebuffer console has no CJK
   font, so any non-ASCII `dev_*` string becomes garbage on the panel.
   `tools/find-nonascii.py` and `tools/ascii-logs.py` enforce this.
4. **One `fastboot boot` per bootloader session.** Do not file bugs about
   `Failed to load/authenticate boot image` without a `reboot-bootloader`
   first.

## Style

* C: kernel style, `patches/*.c` carry an SPDX tag.
* Device tree: follow the upstream Qualcomm `arm64` conventions.
* Scripts: keep the PowerShell helpers ASCII-only, Windows PowerShell 5.1
  reads a BOM-less `.ps1` as ANSI and mangles anything else.

## License

By opening a pull request you agree to the per-path licensing described in
`LICENSE`: GPL-2.0-only for `patches/`, BSD-3-Clause for `dts/`, CC0-1.0 for
`scripts/` and `tools/`, CC-BY-4.0 for `docs/`.