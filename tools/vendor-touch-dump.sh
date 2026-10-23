#!/system/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Dump everything the vendor Android kernel knows about the touch controller.
# Read-only.  Run as root:  adb shell su -c '/data/local/tmp/vendor-touch-dump.sh'

mount -t debugfs none /sys/kernel/debug 2>/dev/null

echo '### pin mux / config for 36,37,38,39'
for f in /sys/kernel/debug/pinctrl/*/pinmux-pins; do
    [ -f "$f" ] || continue
    echo "== $f"
    grep -E 'pin (36|37|38|39) ' "$f"
done

echo
echo '### pinconf (drive/bias) for the same pins'
for f in /sys/kernel/debug/pinctrl/*/pinconf-groups; do
    [ -f "$f" ] || continue
    echo "== $f"
    grep -E -A3 'pin (36|37|38|39) ' "$f" | head -40
done

echo
echo '### gpiolib state of the touch lines'
cat /sys/kernel/debug/gpio 2>/dev/null | grep -E 'fts|touch|gpio-(36|37|38|39) ' | head -20

echo
echo '### regulators that could feed the touch IC'
for d in /sys/class/regulator/*; do
    n=$(cat "$d/name" 2>/dev/null)
    case "$n" in
        *l1*|*touch*|*vddio*|*ts_*)
            echo "$n  state=$(cat "$d/state" 2>/dev/null) uV=$(cat "$d/microvolts" 2>/dev/null) num_users=$(cat "$d/num_users" 2>/dev/null)"
            ;;
    esac
done

echo
echo '### i2c busses and the touch client'
ls -l /sys/bus/i2c/devices/ 2>/dev/null | head -25
echo "name: $(cat /sys/bus/i2c/devices/3-0049/name 2>/dev/null)"
echo "fw_version: $(cat /sys/bus/i2c/devices/3-0049/fts_fw_version 2>/dev/null)"
ls /sys/bus/i2c/devices/3-0049/ 2>/dev/null

echo
echo '### vendor driver probe log'
dmesg | grep -i -E 'fts|st_fts|touch' | head -50

echo
echo '### device tree pins node'
for f in /proc/device-tree/soc/i2c@a94000/fts@49/pinctrl-0 \
         /proc/device-tree/soc/i2c@a94000/fts@49/fts,irq-gpio \
         /proc/device-tree/soc/i2c@a94000/fts@49/fts,reset-gpio; do
    [ -f "$f" ] || continue
    printf '%s = ' "$f"
    od -An -tx1 "$f" | tr -d ' \n'
    echo
done
