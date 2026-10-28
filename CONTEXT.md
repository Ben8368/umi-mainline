# 当前状态

> **最后确认：** 2026-10-28
> **阶段：** 治理初始化与已知缺陷修复；目标设备验收尚未完成。
> **代码基线：** umi-mainline master 39b6349；治理源 DockDSM bc77c7e。

## 当前决策

- 维护 Ben8368/umi-mainline，保留原贡献者与第三方归属，见 [来源](docs/PROVENANCE.md)。
- 采用 DockDSM 治理、署名和机器人约束，按 umi 内核/驱动证据分层；见 [ADR 0001](docs/ADR/0001-governance-port.md)。
- 本轮先提交治理/CI/机器人配置，再修复缺陷并提交；两次本地提交完成后一次推送一个 PR，不合并 master。
- 开发调试 root/SSH/USB 权限保留；主动快充在独立保护与硬件参数未验证前不能作为已验收能力。
- 外部 App 的仓库授权与接单必须有实际回执；仓库配置存在不等于服务已启用，见 [机器人约定](docs/bot-automation.md)。

## 近期优先级

1. 完成治理、署名钩子、CI 与机器人离线门禁的初始化。
2. 修复构建假成功、initramfs 缺失、充电保护和驱动错误路径。
3. 在 PR 中复核 CI，再按 [测试矩阵](docs/test-matrix.md)补充 Linux 编译与真机证据。

## 最近验证

- 2026-10-28：macOS / arm64 / zsh；源代码审查和隔离复现，未完整编译或真机测试，见 [审查记录](docs/archive/reviews/2026-10-28-source-review.md)。
- 2026-10-28：治理移植范围及远端源身份见 [移植记录](docs/archive/reviews/2026-10-28-governance-port.md)。

## 按需入口

- [质量](docs/QUALITY.md)、[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)、[实施计划](docs/implementation-plan.md)
- [CI](docs/ci.md)、[机器人](docs/bot-automation.md)、[文档索引](docs/README.md)
