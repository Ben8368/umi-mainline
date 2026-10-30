#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# Prepare the pinned default kernel in Linux/WSL ext4; never replace an existing tree.
# SRC may be a local Git repository containing the pinned version tag.
set -eu
WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
# shellcheck source=../config/kernel.env
. "$WS/config/kernel.env"
SRC=${SRC:-$UMI_KERNEL_REPOSITORY}
DST=${DST:-/root/linux-$UMI_KERNEL_VERSION}

if [ -e "$DST" ]; then
	[ -d "$DST/.git" ] || { echo "!! Existing destination is not a Git tree: $DST" >&2; exit 1; }
else
	git clone --depth 1 --single-branch --branch "v$UMI_KERNEL_VERSION" "$SRC" "$DST"
fi
ACTUAL=$(git -C "$DST" rev-parse HEAD)
if [ "$ACTUAL" != "$UMI_KERNEL_REVISION" ]; then
	echo "!! Refusing kernel $ACTUAL; expected $UMI_KERNEL_REVISION ($UMI_KERNEL_VERSION)" >&2
	echo "   Use a new DST; existing files have not been reset or deleted." >&2
	exit 1
fi
for f in net/netfilter/xt_connmark.c net/netfilter/xt_CONNMARK.c \
         include/uapi/linux/netfilter/xt_connmark.h include/uapi/linux/netfilter/xt_CONNMARK.h; do
	[ -f "$DST/$f" ] || { echo "!! Missing case-sensitive kernel file: $f" >&2; exit 1; }
done
# build.sh owns the overlay and driver injection. Preparing a source tree does
# not overwrite local patches, generate artifacts, or touch any device.
echo "== Kernel ready: $DST ($ACTUAL)"
