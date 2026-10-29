# 当前状态

> **最后确认：** 2026-10-29
> **阶段：** PPS 修复版已按本轮授权写入 boot 并启动救援环境，镜像读回一致；实际 PPS 充电/供电验收待人工执行。
> **代码基线：** 工作分支基于 master `8900f313d5792e52e051f592dd7a1931c90237cf`（含 PR #4）；PPS 经 PR #5（`codex/umi-pps-charging`）交付，CodeRabbit 意见待提交后复审。

## 当前决策

- 维护 Ben8368/umi-mainline，保留原贡献者与第三方归属，见 [来源](docs/PROVENANCE.md)。
- 采用 DockDSM 治理、署名和机器人约束，按 umi 内核/驱动证据分层；见 [ADR 0001](docs/ADR/0001-governance-port.md)。Agent 改动必须经工作分支与 PR；允许将简单低风险工作派给 Jules，授权与账户额度见[机器人约定](docs/bot-automation.md)及 [ADR 0004](docs/ADR/0004-agent-pr-and-jules-delegation.md)。
- 开发调试 root/SSH/USB 权限保留；本轮授权显式开启 TCPM + SMB5 PPS 主充电实验，BQ25970 仍禁用，真实参数与硬件保护尚未验收。见 [PPS](docs/PPS.md) 与 [ADR 0005](docs/ADR/0005-explicit-pps-bringup.md)。
- PR #2 的 10 条既有 CodeRabbit 可执行意见已修复；但新 HEAD `7383b6525b6ba2f43c8a85707c52da0be4421777` 的审查在合并关闭 PR 后被取消，未生成最终反馈。以后必须等准备合并的当前 HEAD 获得 CodeRabbit 最终反馈并处理有效意见；检查未完成时 PR 保持开放，会话可先结束。详见 [AI_RULES](docs/AI_RULES.md#pr-推送与远端验证) 与[事件记录](docs/archive/reviews/2026-10-29-coderabbit-cancel.md)。
- 救援镜像默认 `ROOTDEV=none`；本轮已获明确 boot 写入授权并完成写入/读回验证，原 boot 已保存匹配回退文件；范围与证据见 [设备记录](docs/archive/reviews/2026-10-29-pps-device-flash.md)。

## 近期优先级

1. 人工验证已刷入的 PPS 修复版；当前 PPS/主充电均关闭，尚未建立 PPS 合同。步骤见 [PPS](docs/PPS.md)，实机与回退见 [设备记录](docs/archive/reviews/2026-10-29-pps-device-flash.md)。
2. 按[测试矩阵](docs/test-matrix.md)补齐显示、触控、Wi-Fi 和供电证据；PR 合并前核验同一 HEAD 的 CI result 与 CodeRabbit 最终反馈。
3. 核实默认分支上的机器人工作流触发和权限边界，按[风险台账](docs/RISK_REGISTER.md)记录结果。

## 最近验证

- 2026-10-29：PR #5 CodeRabbit 意见已改（有效电流比较、BATTERY 证据范围、测试宏提取）；WSL 下 PPS 7/7、reliability 11/11、governance/check-tree 通过；未提交未推送，未重编/未真机。见 [PR #5](https://github.com/Ben8368/umi-mainline/pull/5)。
- 2026-10-29：PPS 修复版 18 项回归与 boot 写入读回已核验，充电未测；见 [设备记录](docs/archive/reviews/2026-10-29-pps-device-flash.md)。
- 2026-10-29：源码基线 `fd469d9` 内核/DTS 编译与打包通过，见[构建记录](docs/archive/reviews/2026-10-29-image-build.md)。
- 2026-10-29：PR #2 CodeRabbit 在关闭后取消，见[事件记录](docs/archive/reviews/2026-10-29-coderabbit-cancel.md)。
- 2026-10-29：治理可靠性回归见[修复记录](docs/archive/reviews/2026-10-29-reliability-fixes.md)；master CI 见 [CI result](https://github.com/Ben8368/umi-mainline/actions/runs/40807337474)。
- 2026-10-29：治理移植范围见[移植记录](docs/archive/reviews/2026-10-28-governance-port.md)。

## 按需入口

- [质量](docs/QUALITY.md)、[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)、[实施计划](docs/implementation-plan.md)
- [CI](docs/ci.md)、[机器人](docs/bot-automation.md)、[文档索引](docs/README.md)
