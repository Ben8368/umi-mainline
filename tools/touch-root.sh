# SPDX-License-Identifier: CC0-1.0
echo '### id'
id
echo '### dmesg touch'
dmesg | grep -i -e fts -e stmicro -e touch | tail -120
echo '### i2c devices'
ls -l /sys/bus/i2c/devices/
for d in /sys/bus/i2c/devices/*; do echo "$d: $(cat $d/name 2>/dev/null)"; done
echo '### i2c 13-0049'
ls -l /sys/bus/i2c/devices/13-0049/ 2>/dev/null
echo '### vendor firmware'
ls -l /vendor/firmware/ 2>/dev/null | head -60
echo '### data vendor tp'
ls -lR /data/vendor/tp/ 2>/dev/null | head -40
echo '### persist'
ls -l /mnt/vendor/persist/ 2>/dev/null | head -20
echo '### dt i2c node'
ls /proc/device-tree/soc/i2c@a94000/
for f in /proc/device-tree/soc/i2c@a94000/fts@49/*; do
  printf '%s = ' "$f"
  od -An -tx1 "$f" 2>/dev/null | tr -d ' \n'
  echo
done
echo '### touchpanel proc'
ls /proc/touchpanel/ 2>/dev/null
for f in /proc/touchpanel/*; do echo "$f = $(cat $f 2>/dev/null)"; done
echo '### sysfs fts'
find /sys/devices -maxdepth 8 -iname '*fts*' 2>/dev/null | head -40
echo '### input devices'
cat /proc/bus/input/devices
echo '### pinctrl 36/37/38/39/69'
cat /sys/kernel/debug/pinctrl/*/pinconf-groups 2>/dev/null | grep -E 'gpio(36|37|38|39|69)\b' | head
