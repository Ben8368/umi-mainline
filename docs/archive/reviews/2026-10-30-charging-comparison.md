# 2026-10-30 umi-linux 充电方案对比与取优

## 范围与来源

维护者要求对比 misaka-link/umi-linux，取优且保留 PPS、开源优先。本轮宿主 Windows x64 / PowerShell；离线验证使用 WSL umi / Linux x86_64 / sh。工作分支 `codex/charging-policy-and-pps`，起点 `309ea0be85e8e4c07f8d32fda845f505859c9a7e`。无手机操作、供电/刷写、提交、推送或合并。

对方固定 HEAD：[cf83073887899f485a5c606f9842c5e691ea796c](https://github.com/misaka-link/umi-linux/tree/cf83073887899f485a5c606f9842c5e691ea796c)。核对：

- [脚本](https://github.com/misaka-link/umi-linux/blob/cf83073887899f485a5c606f9842c5e691ea796c/rootfs-config/battery-charge-limit)、同字节 overlay、service、70/65/30 默认配置、37 项测试源码及[作者设备记录](https://github.com/misaka-link/umi-linux/blob/cf83073887899f485a5c606f9842c5e691ea796c/rootfs-config/充电区间控制-README.md)。没有复跑其测试、下载或启动其镜像。
- [板级 DTS](https://github.com/misaka-link/umi-linux/blob/cf83073887899f485a5c606f9842c5e691ea796c/rootfs-build/patch/kernel/archive/sm8250-6.18/dt/sm8250-xiaomi-umi-common.dtsi)与发布 DTS、`apply-umi-port.sh`、构建文档：驱动依赖外部 Armbian，并非新增完整充电栈。connector 仅固定 PDO，BQ25970 注释且总线 disabled。
- [Armbian 0028](https://github.com/armbian/build/blob/main/patch/kernel/archive/sm8250-6.18/0028-From-Teguh-Sobirin-teguh-sobir.in-Date-Sun-24-Nov-20.patch)、[0037](https://github.com/armbian/build/blob/main/patch/kernel/archive/sm8250-6.18/0037-power-supply-qcom_pm8150b_charger-adds-charging-cont.patch)、0039：核对当前公开补丁行为，不声称与对方发布镜像二进制逐字节对应。0037 直接控制 SMB5 enable；0028 的 `smb5_get_iio_chan` 在非 CHARGING 或状态读取失败时返回零，不能把作者所述停充后 I/V=0 当成独立测量证明。
- [NOTICE](https://github.com/misaka-link/umi-linux/blob/cf83073887899f485a5c606f9842c5e691ea796c/NOTICE-许可与出处.md)明确服务与脚本 GPL-2.0；README 许可表尚有“原创待定”的旧描述。保留 GPL 条款和出处，新脚本显式 GPL-2.0-only，不按本仓库脚本默认 CC0 处理。

## 审查结论

值得吸收的是 SOC 滞回及唯一服务的运维经验。对方脚本只做数字格式检查，未严格拒绝 0..100 之外、上下限倒置或零间隔；只记内存 STATE，未持续核对实际 enable，其他写入者或硬件重置会破坏状态。capacity 失败时只是跳过，可能无限继续原有充电；写成功就宣称启停，未覆盖内核异步许可。原生路径只设置 end threshold，不能保证其 LOWER 语义。对方也明示电量计 current/status 不可信，不能当成可直接替换测量方案。

保留本树普通 USB/TCPM/SMB5 的全部限制、PPS 手动接口、续约、错误锁存、休眠/拔插退出和 BQ25970 禁用。新增 GPL Python 标准库策略服务，固定本树下划线 psy 名称，读回核对、错误停充、严格配置校验和 Linux 进程锁。仅主动写现有 charging_enabled，不写 APDO、PPS 目标、电芯/热保护参数，不引入闭源 daemon 或固件。运行、部署与回退契约见 [限充专题](../../CHARGE-LIMIT.md)。

## 🚦 Audit Report

总体：本轮只增加可选用户态策略与离线回归，不修改 C/DTS、内核预算或默认救援流程。开源实现和参考归属可审查。

🔴：普通充电/温升/保护及 PPS 真机证据仍缺，RISK-001/005 保持开放；不能声称安全日用或原厂功率。

🟡：SOC 可信性及策略/人工 PPS 交互需目标设备验收；用户态轮询、依赖与服务崩溃窗口见 TD-008。锁只约束本实现，其他写入程序仍须人工停用。

验证计划：执行假 sysfs、错误注入、独占/进程退出与真实 C setter 回归；全套离线、文本和治理门禁。未改内核无需重做相同目标编译；本轮不运行设备服务，不将历史 L2/L3 迁移为本轮证据。

## 验证结果

- WSL umi / Linux x86_64：`python3 -m unittest discover -s tests -p test_charge_limit.py -v`，exit 0，14 项 passed。只使用临时目录/假设备，包含进程独占和 SIGTERM 退出。
- 同环境 `python3 -m unittest discover -s tests -p 'test_*.py' -v`，exit 0，62 项 passed，无 skipped，包含 14 项 PPS 回归。新增项提取实际 `smb5_set_property` 编译执行，验证禁止位退出 PPS、恢复许可不自动 PPS/不清故障、已有 PPS 在允许充电时保留、停充 I/O 错误传播。
- `python3 scripts/check-tree.py`，exit 0，Python AST、Shell 语法及 ShellCheck error 级门禁通过。
- `python3 scripts/governance-docs-check.py`、`python3 tests/governance-docs.py`、`python3 scripts/git-hooks-test.py`、`python3 tests/ci-policy.py`（6 项）、`python3 tests/bot-dispatch.py`（22 项）、`git diff --check`：exit 0。
- Ubuntu-24.04 WSL 的 `systemd-analyze verify config/umi-charge-limit.service`，exit 0。首次直接从 Windows 挂载目录检查有可执行/全局可写权限警告，来自挂载权限映射；部署契约要求 `install -m 644`，随后在普通临时目录按此权限复核。检查不启动服务，不代表目标手机 Python/systemd 已满足。
- 未修改 C/DTS/config 内核输入，不重做内核目标编译；目标 Python/systemd、真实 rootfs 安装、上限/下限循环、充电/保护/温升/PPS、远端 CI/CodeRabbit 均 not-run。本轮没有下载/操作镜像，也未操作手机。
