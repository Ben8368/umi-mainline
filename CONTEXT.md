# 当前状态

> **最后确认：** 2026-10-29
> **阶段：** 6.18 已临时亮屏，触摸事件、SPMI 去重与 GPU 初始化已有实机证据；24 项回归通过，未持久刷写 6.18。设备经 bootloader 命令并拔线确认关机，Wi-Fi、恢复与充电待测。
> **代码基线：** 6.18 交付分支 `codex/umi-linux-6.18.59` 继承 PR #5 的 `ab33fd8`；新 PR 直接面向 master `8900f31`，包含尚未合并的 PPS 基线，当前 HEAD 的 CI / CodeRabbit 待核验。

## 当前决策

- 维护 Ben8368/umi-mainline，保留原贡献者与第三方归属，见 [来源](docs/PROVENANCE.md)。
- 采用 DockDSM 治理、署名和机器人约束，按 umi 内核/驱动证据分层；见 [ADR 0001](docs/ADR/0001-governance-port.md)。Agent 改动必须经工作分支与 PR；允许将简单低风险工作派给 Jules，授权与账户额度见[机器人约定](docs/bot-automation.md)及 [ADR 0004](docs/ADR/0004-agent-pr-and-jules-delegation.md)。
- 开发调试 root/SSH/USB 权限保留；此前已授权 TCPM + SMB5 PPS 主充电实验，BQ25970 仍禁用，真实参数与硬件保护尚未验收。见 [PPS](docs/PPS.md) 与 [ADR 0005](docs/ADR/0005-explicit-pps-bringup.md)。
- PR #2 的 10 条既有 CodeRabbit 可执行意见已修复；但新 HEAD `7383b6525b6ba2f43c8a85707c52da0be4421777` 的审查在合并关闭 PR 后被取消，未生成最终反馈。以后必须等准备合并的当前 HEAD 获得 CodeRabbit 最终反馈并处理有效意见；检查未完成时 PR 保持开放，会话可先结束。详见 [AI_RULES](docs/AI_RULES.md#pr-推送与远端验证) 与[事件记录](docs/archive/reviews/2026-10-29-coderabbit-cancel.md)。
- 救援镜像默认 `ROOTDEV=none`；此前已授权并完成 PPS boot 写入/读回验证，原 boot 已保存匹配回退文件；范围与证据见 [设备记录](docs/archive/reviews/2026-10-29-pps-device-flash.md)。

## 近期优先级

1. 人工验证已刷入的 PPS 修复版；当前 PPS/主充电均关闭，尚未建立 PPS 合同。步骤见 [PPS](docs/PPS.md)，实机与回退见 [设备记录](docs/archive/reviews/2026-10-29-pps-device-flash.md)。
2. 按[测试矩阵](docs/test-matrix.md)补齐 6.18 屏幕恢复、长稳、Wi-Fi 和供电证据；PR 合并前核验当前 HEAD 的 CI 与 CodeRabbit 最终反馈。
3. 核实默认分支上的机器人工作流触发和权限边界，按[风险台账](docs/RISK_REGISTER.md)记录结果。

## 最近验证

- 2026-10-29：6.18 fix1 已临时启动，用户确认亮屏；128 个触摸事件、GPU 初始化与八个 SPMI 别名禁用已取证，见[启动修复记录](docs/archive/reviews/2026-10-29-linux-6.18.59-boot-fixes.md)。
- 2026-10-29：`codex/umi-linux-6.18.59` 本地改动完成内核/三个 DTB 编译、打包与 21 项回归，见[构建记录](docs/archive/reviews/2026-10-29-linux-6.18.59-build.md)；随后临时启动读回 `6.18.59-umi-dirty`，黑屏已定位 UBWC，见[实机记录](docs/archive/reviews/2026-10-29-linux-6.18.59-device-boot.md)。
- 2026-10-29：PR #5 CodeRabbit 意见修复 `c12a773`（有效电流比较、BATTERY 证据范围、测试宏提取）已推送；本地 WSL PPS 7/7、reliability 11/11、governance/check-tree 通过；远端 CI/CodeRabbit 待对当前 tip 核验，未重编/未真机。见 [PR #5](https://github.com/Ben8368/umi-mainline/pull/5)。
- 2026-10-29：PPS 修复版 18 项回归与 boot 写入读回已核验，充电未测；见 [设备记录](docs/archive/reviews/2026-10-29-pps-device-flash.md)。
- 2026-10-29：源码基线 `fd469d9` 内核/DTS 编译与打包通过，见[构建记录](docs/archive/reviews/2026-10-29-image-build.md)。
- 2026-10-29：PR #2 CodeRabbit 在关闭后取消，见[事件记录](docs/archive/reviews/2026-10-29-coderabbit-cancel.md)。
- 2026-10-29：治理可靠性回归见[修复记录](docs/archive/reviews/2026-10-29-reliability-fixes.md)；master CI 见 [CI result](https://github.com/Ben8368/umi-mainline/actions/runs/40807337474)。
- 2026-10-29：治理移植范围见[移植记录](docs/archive/reviews/2026-10-28-governance-port.md)。

## 按需入口

- [质量](docs/QUALITY.md)、[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)、[实施计划](docs/implementation-plan.md)
- [CI](docs/ci.md)、[机器人](docs/bot-automation.md)、[文档索引](docs/README.md)
