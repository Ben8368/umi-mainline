# SPDX-License-Identifier: CC0-1.0
#
# Convenience entry points.  Every target is a thin wrapper around a script in
# scripts/ or tools/ so that nothing here is the single source of truth.
#
#   make build      full kernel + DTB build (inside WSL)
#   make dtb        device tree only (fast, ~20 s)
#   make initramfs  rebuild initramfs.cpio.gz only
#   make pack       pack out/boot-umi-<NAME>.img
#   make sizes      show what the last build produced
#   make config     print the effective config of the last build
#
# Override on the command line:  make build TREE=/root/linux JOBS=24

WSL_DISTRO ?= umi
TREE       ?= /root/linux
JOBS       ?= 20
TC         ?= gcc
NAME       ?= local

WSL      := wsl -d $(WSL_DISTRO) -u root -e sh
ENV      := TREE=$(TREE) JOBS=$(JOBS) TC=$(TC)

.PHONY: help build dtb initramfs pack sizes config clean

help:
	@sed -n '2,14p' Makefile | sed 's/^# \{0,1\}//'

build:
	$(WSL) -c 'cd scripts && $(ENV) sh ./build.sh'

dtb:
	$(WSL) -c 'cd scripts && TREE=$(TREE) sh ./dtb-only.sh'

initramfs:
	$(WSL) -c 'cd scripts && sh ./mkinitramfs.sh'

pack:
	python tools/pack-umi.py --name $(NAME)

sizes:
	@ls -l out/Image.gz out/*.dtb 2>/dev/null || echo "nothing built yet"

config:
	@grep -E 'CONFIG_(DRM_MSM|DRM_PANEL_XIAOMI_UMI|TOUCHSCREEN_FTS_UMI|I2C_QCOM_GENI)=' out/config-effective 2>/dev/null | sort -u

clean:
	rm -rf out/*.img out/Image.gz out/*.dtb