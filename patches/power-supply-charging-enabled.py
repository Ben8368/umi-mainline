#!/usr/bin/env python3
"""给 6.12 的 power_supply 核心加一个属性：POWER_SUPPLY_PROP_CHARGING_ENABLED。

厂商 smb5 充电驱动（qcom_pm8150b_charger.c，来自 zhaoyuanwang123/armbian 的
sm8250-7.2 补丁 0037）用了这个属性，主线没有。补法就是两行：枚举里加一个，
sysfs 属性表里加一个（顺序和枚举一致）。

    python3 patches/power-supply-charging-enabled.py \
        include/linux/power_supply.h drivers/power/supply/power_supply_sysfs.c

幂等：已经有了就什么都不做。
"""
import sys


def patch(path, anchor, ins, what):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if "CHARGING_ENABLED" in text:
        print(f"   {path}: 已经有 CHARGING_ENABLED，跳过")
        return
    if anchor not in text:
        raise SystemExit(f"!! {path}: 找不到锚点 {what}: {anchor!r}")
    text = text.replace(anchor, anchor + ins, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"   {path}: 已插入 CHARGING_ENABLED")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    hdr, sysfs = sys.argv[1], sys.argv[2]

    # include/linux/power_supply.h: 枚举
    patch(hdr,
          "\tPOWER_SUPPLY_PROP_MANUFACTURE_DAY,\n",
          "\tPOWER_SUPPLY_PROP_CHARGING_ENABLED,\n",
          "enum power_supply_property")
    # drivers/power/supply/power_supply_sysfs.c: 属性表
    patch(sysfs,
          "\tPOWER_SUPPLY_ATTR(MANUFACTURE_DAY),\n",
          "\tPOWER_SUPPLY_ATTR(CHARGING_ENABLED),\n",
          "power_supply_attrs[]")
