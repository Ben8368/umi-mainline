#!/bin/sh
# SPDX-License-Identifier: MIT
# Passive inventory only: no bus probing, module loading or device writes.
# Run with sh on the target. --root accepts a trusted offline filesystem fixture.
set -eu
export LC_ALL=C

usage() {
	printf 'Usage: sh hardware-inventory.sh [--root ABSOLUTE_DIRECTORY]\n'
}

root=/
case $# in
	0) ;;
	1) case $1 in --help|-h) usage; exit 0 ;; *) usage >&2; exit 2 ;; esac ;;
	2)
		[ "$1" = --root ] || { usage >&2; exit 2; }
		case $2 in /*) root=$2 ;; *) usage >&2; exit 2 ;; esac
		;;
	*) usage >&2; exit 2 ;;
esac
[ -d "$root" ] || { printf 'Root directory unavailable\n' >&2; exit 2; }
root=$(CDPATH= cd -- "$root" && pwd -P)
[ "$root" != / ] || root=

# Bound each attribute; avoid raw logs, addresses, serial numbers and firmware data.
# A readable attribute that fails during access is not reported as an empty success.
field() {
	key=$1
	path=$2
	printf '  %s=' "$key"
	if [ ! -r "$path" ]; then
		printf '[unavailable]\n'
	elif value=$(head -c 4096 "$path" 2>/dev/null); then
		printf '%s' "$value" | tr '\000\n\r\t' '    '
		printf '\n'
	else
		printf '[read-error]\n'
	fi
}

# Read DT string lists before shell substitution, which cannot preserve NULs.
dt_field() {
	printf '  %s=' "$1"
	if [ -r "$2" ]; then
		# DT properties are small, immutable files, not hardware probe interfaces.
		tr '\000\n\r\t' '    ' < "$2"
		printf '\n'
	else
		printf '[unavailable]\n'
	fi
}

driver() {
	if target=$(readlink "$1/driver" 2>/dev/null); then
		printf '  driver=%s\n' "${target##*/}"
	else
		printf '  driver=[no local driver link; not a probe verdict]\n'
	fi
}

printf 'umi hardware inventory v1\n'
printf 'Evidence: enumeration/binding only; functionality is NOT tested.\n'
field kernel "$root/proc/sys/kernel/osrelease"
dt="$root/sys/firmware/devicetree/base"
[ -d "$dt" ] || dt="$root/proc/device-tree"
dt_field model "$dt/model"
dt_field compatible "$dt/compatible"
# Never query host Android properties while inspecting an offline fixture.
if [ -z "$root" ] && command -v getprop >/dev/null 2>&1; then
	for prop in ro.product.device ro.product.vendor.device ro.product.model ro.build.version.release; do
		printf '  %s=%s\n' "$prop" "$(getprop "$prop")"
	done
fi

for bus in pci i2c spi serial; do
	printf '\n[bus %s]\n' "$bus"
	found=no
	for dev in "$root/sys/bus/$bus/devices/"*; do
		[ -d "$dev" ] || continue
		found=yes
		printf '%s\n' "${dev##*/}"
		driver "$dev"
		field modalias "$dev/modalias"
		if [ "$bus" = pci ]; then
			for attr in vendor device subsystem_vendor subsystem_device class; do
				field "$attr" "$dev/$attr"
			done
		else
			field name "$dev/name"
			dt_field compatible "$dev/of_node/compatible"
		fi
	done
	[ "$found" = yes ] || printf '[no visible entries; absent, disabled or inaccessible]\n'
done

for class in remoteproc bluetooth sound rc input iio hwmon video4linux; do
	printf '\n[class %s]\n' "$class"
	found=no
	for dev in "$root/sys/class/$class/"*; do
		[ -d "$dev" ] || continue
		found=yes
		printf '%s\n' "${dev##*/}"
		field name "$dev/name"
		driver "$dev/device"
		case $class in
			remoteproc)
				field firmware "$dev/firmware"
				field state "$dev/state"
				;;
			hwmon)
				for label in "$dev"/temp*_label; do
					[ -e "$label" ] || continue
					field "${label##*/}" "$label"
				done
				;;
		esac
	done
	[ "$found" = yes ] || printf '[no visible entries; absent, disabled or inaccessible]\n'
done

printf '\n[existing diagnostics; no debugfs mount]\n'
field deferred "$root/sys/kernel/debug/devices_deferred"
field alsa_cards "$root/proc/asound/cards"
printf '\nEnd. Unavailable data is unknown, not evidence of missing hardware.\n'
