# 当前状态

> **最后确认：** 2026-10-29
> **阶段：** 治理与离线修复已提交 PR #2；修复 CodeQL 告警，目标设备验收尚未完成。
> **代码基线：** umi-mainline master 39b6349；治理源 DockDSM bc77c7e。

## 当前决策

- 维护 Ben8368/umi-mainline，保留原贡献者与第三方归属，见 [来源](docs/PROVENANCE.md)。
- 采用 DockDSM 治理、署名和机器人约束，按 umi 内核/驱动证据分层；见 [ADR 0001](docs/ADR/0001-governance-port.md)。
- 本轮先提交治理/CI/机器人配置，再修复缺陷并提交；两次本地提交完成后一次推送一个 PR，不合并 master。
- 开发调试 root/SSH/USB 权限保留；主动快充在独立保护与硬件参数未验证前不能作为已验收能力。
- CodeRabbit 现有授权覆盖本仓库；维护者已确认 Jules / Renovate 仅增加本仓库并保留 DockDSM。授权与接单分开取证，见 [记录](docs/archive/reviews/2026-10-29-bot-access.md)。

## 近期优先级

1. 将 CodeQL 工作流修复追加到同一 PR #2，不合并 master。
2. 在新 HEAD 核对 CI / CodeQL / CodeRabbit；Issue 派单等默认分支工作流合入后再验收。
3. 按 [测试矩阵](docs/test-matrix.md)补充 Linux 编译与真机证据。

## 最近验证

- 2026-10-29：PR #2 的旧 HEAD 常规 CI 通过、CodeQL 告警；修复后本地策略与离线回归通过，远端新 HEAD 待核验，见 [记录](docs/archive/reviews/2026-10-29-codeql-fix.md)。
- 2026-10-29：11 项可靠性回归通过，实际 C 函数故障注入与脚本错误路径见 [记录](docs/archive/reviews/2026-10-29-reliability-fixes.md)。

- 2026-10-29：macOS / arm64 / zsh；源代码审查和隔离复现，未完整编译或真机测试，见 [审查记录](docs/archive/reviews/2026-10-28-source-review.md)。
- 2026-10-29：治理移植范围及远端源身份见 [移植记录](docs/archive/reviews/2026-10-28-governance-port.md)。

## 按需入口

- [质量](docs/QUALITY.md)、[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)、[实施计划](docs/implementation-plan.md)
- [CI](docs/ci.md)、[机器人](docs/bot-automation.md)、[文档索引](docs/README.md)
