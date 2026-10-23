#!/bin/sh
# SPDX-License-Identifier: CC0-1.0
# collect-facts.sh — 把「审计启动链时需要的内核源码事实」一次性 dump 出来
#
# 不是构建步骤，是诊断工具。RISK-AUDIT-2.md 里每一条带出处的结论都能用这个脚本复现。
#
#   wsl -d umi -u root -e sh <repo>/scripts/collect-facts.sh
#   wsl -d umi -u root -e sh .../collect-facts.sh | tee facts.txt
set -e
TREE=${TREE:-/root/linux}
WS=${WS:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
Q=$TREE/arch/arm64/boot/dts/qcom
cd "$TREE"

say() { printf '\n=== %s ===\n' "$1"; }

say "arm64 还有没有 machine_desc 列表（没有 → compatible 不影响启动）"
echo "grep -rn DT_MACHINE_START arch/arm64/ -> $(grep -rl 'DT_MACHINE_START' arch/arm64/ 2>/dev/null | wc -l) 个文件"
sed -n '/^static void __init setup_machine_fdt/,/^}/p' arch/arm64/kernel/setup.c

say "看门狗：qcom-wdt probe 会不会接管 ABL 留下的狗"
sed -n '/If WDT is already running/,/^	}/p' drivers/watchdog/qcom-wdt.c
grep -n 'watchdog_need_worker\|watchdog_hw_running' drivers/watchdog/watchdog_dev.c | head -12

say "看门狗节点（必须没有 status=disabled，且 clocks 是 fixed-clock）"
grep -n -A6 'watchdog@17c10000' "$Q/sm8250.dtsi"
grep -n -A4 'sleep_clk: sleep-clk' "$Q/sm8250.dtsi"

say "earlycon：compatible 必须两边对上"
grep -n 'OF_EARLYCON_DECLARE' drivers/tty/serial/qcom_geni_serial.c
grep -n -A4 'uart12: serial@a90000' "$Q/sm8250.dtsi"
grep -n -A4 'qup_uart12_default:' "$Q/sm8250.dtsi"

say "/chosen 下 simple-framebuffer 的创建路径"
grep -n -B2 -A6 'of_get_compatible_child(of_chosen, "simple-framebuffer")' drivers/of/platform.c

say "arm64 的 VA_BITS 默认值（52 = 5 级页表 + LPA2）"
sed -n '/prompt "Virtual address space size"/,/^endchoice/p' arch/arm64/Kconfig | head -8

say "ramoops 参考：elish / pipa 用在哪、多大"
grep -n -A8 'ramoops@' "$Q/sm8250-xiaomi-elish-common.dtsi" "$Q/sm8250-xiaomi-pipa.dts"

say "我们最终 DTB 的内存图（和下游 DTB 对比）"
if [ -f "$WS/out/sm8250-xiaomi-umi.dtb" ]; then
	dtc -I dtb -O dts "$WS/out/sm8250-xiaomi-umi.dtb" 2>/dev/null > /tmp/umi.dts || true
	grep -n -A3 'reserved-memory {' /tmp/umi.dts | head -5
	echo "-- reserved 区间 --"
	grep -n -A2 '@0x' /tmp/umi.dts | grep -E 'reg = ' | head -40
else
	echo "（先跑 scripts/dtb-only.sh）"
fi

say "完成"
