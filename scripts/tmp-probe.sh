#!/bin/bash
# SPDX-License-Identifier: CC0-1.0
WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
# shellcheck source=../config/kernel.env
. "$WS/config/kernel.env"
TREE=${TREE:-/root/linux-$UMI_KERNEL_VERSION}
OUT=${OUT:-$TREE/out-cfg}
cd "$TREE" || exit 1
echo "=== 谁 select 了 CPU_IDLE ==="
grep -rn "select CPU_IDLE" --include=Kconfig . | head -20
echo
echo "=== CPU_IDLE 的 Kconfig 定义 ==="
grep -n -A12 "^config CPU_IDLE$" drivers/cpuidle/Kconfig
echo
echo "=== ACPI / arm64 defconfig 里的 ACPI ==="
grep -n "^CONFIG_ACPI" arch/arm64/configs/defconfig
echo
echo "=== 我们在 out-cfg 里的 ACPI / CPU_IDLE ==="
grep -n "^CONFIG_ACPI\|^CONFIG_CPU_IDLE\|^CONFIG_ARM_PSCI_CPUIDLE" "$OUT/.config"
echo
echo "=== RUST 依赖 ==="
grep -n -B4 -A12 "^config RUST$" init/Kconfig | head -40
