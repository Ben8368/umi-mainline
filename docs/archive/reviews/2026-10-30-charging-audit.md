# 2026-10-30 充电优先审计

## 范围与证据

用户要求优先排查和解决普通充电，其次快充/PPS，并确认尚无实测。本轮在 Windows x64 / PowerShell 7.6.5 上开发，起点 `4dfe7e9258791fe19b188688cb4c33d39ef9a8b7`，本地分支 `codex/umi-hardware-enablement`。开发完成后用户明确授权提交并推送到现有 [PR #7](https://github.com/Ben8368/umi-mainline/pull/7)，远端工作分支为 `codex/umi-6.18-open-source-parity`。未授权合并、临时启动、刷写或供电参数操作；未执行手机命令。

历史电脑 USB 记录为 `online=1 contract_uv=5000000 contract_ua=0 charging_enabled=0`，见 [旧设备记录](2026-10-29-pps-device-flash.md)。这只证明该次停充，不能证明所有适配器都不能充电。

## 发现与修复

1. **普通 USB 的零预算缺口**：上游 TCPM 的 Rp-default 依赖 TCPC `get_current_limit`，目标 PM8150B 未提供该回调，因此可得到 0mA。SMB5 此前在 TCPM 模式无条件关闭 APSD，普通 DCP/CDP 没有识别路径。增加仅限非 PD 且 CC 预算为零的 BC1.2 检测；首次 rerun 等待新结果，DCP/CDP 限制至多 1.5A，SDP 限制 100mA；未知/FLOAT/OCP/冲突结果不提高负载。真实 PD 零预算不由 BC1.2 替代，CC 1.5A/3A 仍按已公布预算与本地上限限制。重检命令失败时仍保存检测器已开启的状态，后续 PD 重试先关闭它，避免错误恢复时遗漏互斥。
2. **插入过渡被锁存为故障**：普通路径把 `VOLTAGE_NOW=0` 当成永久错误。改为停充等待，后续有效预算可恢复；真实 I/O 错误仍停充锁存，未取消安全门禁。
3. **PPS 工作点切换仍带充电负载**：此前只降低 ICL。改为先清充电使能、降输入限流至 100mA，再请求工作点，合同/health 读回通过后恢复负载；相同工作点续约不反复停充。
4. **输入电流少算 5 倍及读错伪零**：USB_IN_I 在上游 ADC5 中是电压通道；按固定小米厂商 PM8150B buck 0.2V/A 换算 µA。USB 插入状态读取失败直接返回错误，在线但停充/充满仍读取输入，不再由充电状态强制置零。仅用于 sink/buck，不声明 OTG/boost 支持。
5. **电量计状态更新滞后与卸载回调悬空**：SMB5 轮询后通知 power_supply，电量计在卸载时先注销 notifier，再同步取消延迟工作，最后释放数据。补测真实函数的退出顺序。
6. **硬温限遗漏**：PMIC health 同时检查 TOO_HOT/TOO_COLD 的 AFP 位，避免仅有这些状态位时返回 Good；不增加温度阈值。

启动、拔插、故障退出限流从 500mA 降为未取得枚举预算的 100mA；PPS 人工目标初值仍为 5V/0.5A，最高范围/FCC 均未扩大。BQ25970 节点与主动 enable 拒绝保持原样。

## 未解决的验收阻断

- 基础充电仍缺本轮实际净充入电流、温升、保护配置/寄存器读回与持续运行证据。编译和健康位为 Good 都不能替代这些证据。
- 原有 4.4V/1.5A DT 参数是历史移植值，未核验本机电芯；SMB5 watchdog 初始化存在关闭写入，JEITA/安全定时器的配置继承不能当作保护已验收。本轮不以猜测新参数修补。
- Gen4 电池温度读取 RRADC 后直接乘 10；固定厂商实现读 SRAM 的有符号 10-bit/0.25°C 值，不能把该解码直接套到 RRADC。需确认 RRADC 数据格式/有效位和实温对照，再决定修复，不将当前温度当成可信安全依据。
- 固定小米 `smblib_get_prop_usb_voltage_now()` 指出 PM8150B USBIN 高压 ADC 异常并改用 MID_CHG；当前驱动未实现该 workaround。PPS 验收须有独立输入测量，不能只看 sysfs 电压。
- SDP 未接枚举/挂起预算，100mA 下可能净放电；无 TCPM phandle 的旧分支不在默认模式验收范围。见 [TD-007](../../TECH_DEBT.md#td-007普通-usb-枚举预算与遗留充电路径尚未接通p1)。
- PPS 真正 APDO 合同、持续超过 30 秒、拒绝/拔插/休眠及完整电荷泵快充均未实测；RISK-001/005、TD-004 不关闭。

## 🚦 Audit Report

总体：基础充电软件缺口可修复且限值不提高；保持未知预算不提升负载、失败停充。目标是可审查的离线修复，不构成日用充电安全声明。

🔴：L3 普通充电、热保护及 PPS 验收缺失；禁止把测试通过解释为实际可充电或原厂快充已可用。

🟡：SDP/旧分支策略登记 TD-007，保护与测量不确定性登记 RISK-001，辅助配置审计的版本别名误报登记 TD-005；其余 PPS 前置条件保留原台账。

验证计划：提取真实 C 函数，覆盖 BC1.2 识别等待/未知源/PD 优先、每个 I/O 失败点、PPS 切换卸载、输入换算、保护位和 notifier 清理；运行全部离线及治理门禁，并编译固定目标内核。

## 验证结果

- `python3 -m unittest discover -s tests -p test_pps.py -v`：exit 0，13 项 passed。
- `python3 -m unittest discover -s tests -p 'test_*.py' -v`：exit 0，47 项 passed，无 skipped；覆盖 `tests/test_reliability.py`。只执行宿主模拟，不访问手机。
- `python3 scripts/check-tree.py`：exit 0，ShellCheck error 级及 Python/Shell/JSON/YAML 文本检查通过。
- Linux 6.18.59 固定 SHA `1253a6aa5d104312bf0992afacc15220ae35bdf9`，WSL umi / Linux x86_64 / sh，GCC aarch64-none-elf 16.1.0：`WS=/root/umi-charging-work TREE=/root/linux-6.18.59 OUT=/root/linux-6.18.59/out-hardware JOBS=12 TC=gcc sh scripts/build.sh` exit 0。复用既有对象作增量缓存，重新生成 Image.gz/三个 DTB 并完成 modules 目标与 1372 模块导出，不称 clean build。
- `python3 out/charging-audit/verify-build.py`：exit 0。134 个 config/DTS/驱动/脚本/固件输入与 Windows 工作区逐字节一致；两份修改驱动与实际内核树中的副本一致。独立核对 ARM64 magic、模块/配置/内核哈希与索引、SMB5/电量计/TCPM/Type-C/VBUS/ADC 内建、三个 DTB、Wi-Fi 充电接线与 1.5A 预算、BQ25970 disabled。
- `python3 scripts/governance-docs-check.py`、`python3 tests/governance-docs.py`、`python3 scripts/git-hooks-test.py`、`python3 tests/ci-policy.py`（6 项）、`python3 tests/bot-dispatch.py`（22 项）、`git diff --check`：均 exit 0。C diff 的 `checkpatch.pl --no-tree`：222 lines，0 errors、0 warnings；完整构建保留既有 FTS/DTC 警告，不称零 warning。
- `python3 tools/config-audit.py out/charging-audit/config-effective --fragment config/umi.config`：**exit 1**。80 个必须项均通过，唯一片段差异是旧 `CONFIG_PCI_PWRCTL_PWRSEQ=m` 在 6.18 不存在，新 `CONFIG_PCI_PWRCTRL_PWRSEQ=m` 及对应模块已存在。属辅助审计未识别版本别名的既有问题，记录 TD-005，未降低检查或将该命令标为通过。
- 本轮未创建 boot 镜像；内核/DTB/模块及原始日志保存在忽略目录 `out/charging-audit/`。远端 CI/CodeRabbit、6.12/7.2 编译和全部 L3 not-run。

| 最终产物 | 字节数 | SHA256 |
| --- | ---: | --- |
| Image.gz | 16,281,600 | `e7f4ee68d96dc8bfd06b151e10f2d755ef1113feb19ceba2b4312e842c5feffc` |
| sm8250-xiaomi-umi-wifi.dtb | 196,508 | `08dc25ddd2fd5a3d1ecf6eedd4bef8c0bf1d907caed6328a63a646801bcbc489` |
| modules-6.18.59-umi-dirty.tar.gz | 18,441,990 | `7cac1f896d39d08628fa3d6066405818523ed020727f9cc7afbc7af837deb392` |

## 核对来源

- [Linux v6.18 TCPM](https://github.com/torvalds/linux/blob/v6.18/drivers/usb/typec/tcpm/tcpm.c)：`tcpm_get_current_limit`、`tcpm_psy_get_current_now`；同时核对本地固定 6.18.59 源码与 PMIC Type-C provider。
- [小米 umi-q-oss smb5-lib.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/db67ca6001320efc1f945c270635434fc403a9d4/drivers/power/supply/qcom/smb5-lib.c)：APSD/PD 互斥、检测表、PM8150B buck current scaling、USB 电压 ADC workaround。
- [小米 umi-q-oss qpnp-fg-gen4.c](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/db67ca6001320efc1f945c270635434fc403a9d4/drivers/power/supply/qcom/qpnp-fg-gen4.c)：`fg_gen4_get_battery_temp`，数据源是 SRAM，与本实现 RRADC 不同。

下载核对的厂商源码及原始日志只留在忽略目录 `out/charging-audit/`，不提交这些文件、镜像或模块包。
