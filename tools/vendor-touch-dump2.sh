#!/system/bin/sh
# SPDX-License-Identifier: CC0-1.0
mount -t debugfs none /sys/kernel/debug 2>/dev/null
echo '### gpio lines'
grep -E 'gpio-(36|37|38|39) ' /sys/kernel/debug/gpio
echo '### gpio chip header'
grep -n 'f000000' /sys/kernel/debug/gpio
echo '### regulators'
for d in /sys/class/regulator/*; do
    n=$(cat "$d/name" 2>/dev/null)
    case "$n" in
        *l1*|*vddio*|*touch*|*ts_*)
            echo "$n state=$(cat "$d/state" 2>/dev/null) uV=$(cat "$d/microvolts" 2>/dev/null)"
            ;;
    esac
done
echo '### fts sysfs'
ls /sys/bus/i2c/devices/3-0049/ 2>/dev/null
echo '### fts dmesg (first 40)'
dmesg | grep -i fts | head -40
