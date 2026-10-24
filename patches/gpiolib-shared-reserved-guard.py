#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Stop 7.x shared-GPIO setup from claiming reserved (invalid) lines.

linux 7.x grew a "shared GPIO" mechanism: gpiochip_setup_shared() walks every
DT property that looks like a GPIO phandle and, for pins referenced more than
once, turns them into shared-GPIO proxies by calling gpiod_request_commit().

On sm8250 the TLMM exposes three tiles, and this board cannot access the NORTH
one, so the DTS marks those lines with "gpio-reserved-ranges".  One of them
(GPIO 66) still gets referenced from the DT, so the shared-GPIO path tries to
request it, gpiod_request_commit() rejects an invalid line with -EINVAL, and
the whole gpiochip registration fails:

    gpiolib_shared: failed to setup shared GPIOs
    gpiochip_add_data_with_key: GPIOs 550..730 (f100000.pinctrl) failed to register, -22
    sm8250-pinctrl f100000.pinctrl: probe with driver sm8250-pinctrl failed with error -22

...which in turn leaves every GPIO (and with it GENI i2c and touch) dead.

Reserved lines must simply be skipped here.

Usage: gpiolib-shared-reserved-guard.py <path to drivers/gpio/gpiolib-shared.c>
"""

import sys

if len(sys.argv) != 2:
    print("usage: %s <path to gpi.c>" % sys.argv[0])
    sys.exit(2)

path = sys.argv[1]
src = open(path).read()

if "gpiochip_line_is_valid" in src:
    print("   gpiolib-shared: already patched")
    sys.exit(0)

anchor = """			desc = &gdev->descs[entry->offset];

			__set_bit(GPIOD_FLAG_SHARED, &desc->flags);"""

replacement = """			/*
			 * 无效 / 被 "gpio-reserved-ranges" 标掉的引脚不能被做成
			 * shared-GPIO 代理：gpiod_request_commit() 对这类行直接返回
			 * -EINVAL，会让整个 gpiochip 注册失败（sm8250 的 NORTH tile
			 * 就是这么被标掉的）。直接跳过。
			 */
			if (entry->offset >= gc->ngpio ||
			    !gpiochip_line_is_valid(gc, entry->offset))
				continue;

			desc = &gdev->descs[entry->offset];

			__set_bit(GPIOD_FLAG_SHARED, &desc->flags);"""

if anchor not in src:
    print("   gpiolib-shared: anchor not found in %s" % path)
    sys.exit(1)

src = src.replace(anchor, replacement, 1)
open(path, "w").write(src)
print("   gpiolib-shared: reserved lines are skipped")
