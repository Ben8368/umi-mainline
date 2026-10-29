# 当前状态

> **最后确认：** 2026-10-29
> **阶段：** 治理、离线修复与目标内核编译已完成；真实设备启动/供电验收待设备重新连接。
> **代码基线：** umi-mainline master `fd469d999a365bbfec0c0caa6eac4363a70ec70c`；PR #2 已合并，PR #1 因配置被取代关闭。

## 当前决策

- 维护 Ben8368/umi-mainline，保留原贡献者与第三方归属，见 [来源](docs/PROVENANCE.md)。
- 采用 DockDSM 治理、署名和机器人约束，按 umi 内核/驱动证据分层；见 [ADR 0001](docs/ADR/0001-governance-port.md)。Agent 改动必须经工作分支与 PR；允许将简单低风险工作派给 Jules，授权与账户额度见[机器人约定](docs/bot-automation.md)及 [ADR 0004](docs/ADR/0004-agent-pr-and-jules-delegation.md)。
- 开发调试 root/SSH/USB 权限保留；主动快充保持禁用，真实参数与硬件保护尚未验收。
- PR #2 的 10 条既有 CodeRabbit 可执行意见已修复；但新 HEAD `7383b6525b6ba2f43c8a85707c52da0be4421777` 的审查在合并关闭 PR 后被取消，未生成最终反馈。以后必须等准备合并的当前 HEAD 获得 CodeRabbit 最终反馈并处理有效意见；检查未完成时 PR 保持开放，会话可先结束。详见 [AI_RULES](docs/AI_RULES.md#pr-推送与远端验证) 与[事件记录](docs/archive/reviews/2026-10-29-coderabbit-cancel.md)。
- 已生成救援启动镜像，默认 `ROOTDEV=none`；镜像仅供 `fastboot boot` 核验，不写设备分区。设备重新连接前不做真机结论。

## 近期优先级

1. 将 CodeRabbit 完成门禁纳入治理文档并经 PR 审查合入；未完成的审查不得通过关闭或合并 PR 结束。动机与取消证据见[事件记录](docs/archive/reviews/2026-10-29-coderabbit-cancel.md)。
2. 设备重新连接后，以当前镜像执行 `fastboot boot`，按[测试矩阵](docs/test-matrix.md)记录显示、触控、启动和供电证据。
3. 核实默认分支上的机器人工作流触发和权限边界，按[风险台账](docs/RISK_REGISTER.md)记录结果。

## 最近验证

- 2026-10-29：源码基线 `fd469d9`；Linux 6.12.94 目标内核/DTS 编译及 `sh scripts/mkimage.sh` 通过，使用 WSL x86_64，未连接/写入手机；镜像 SHA256 与产物记录见[构建记录](docs/archive/reviews/2026-10-29-image-build.md)。
- 2026-10-29：PR #2 的 `CI result`、CodeQL、lint、governance 与 amd64/arm64 offline 检查通过；CodeRabbit 对 HEAD `7383b65` 在 PR 关闭后取消，原因与证据见[事件记录](docs/archive/reviews/2026-10-29-coderabbit-cancel.md)。
- 2026-10-29：治理 commit `293c884` 上 11 项可靠性回归通过，实际 C 函数故障注入与脚本错误路径见[修复记录](docs/archive/reviews/2026-10-29-reliability-fixes.md)。
- 2026-10-29：master `fd469d9` 的 governance / lint / offline（含策略与派单回归）经 [CI result](https://github.com/Ben8368/umi-mainline/actions/runs/40807337474) 通过。
- 2026-10-29：治理移植范围及远端源身份见[移植记录](docs/archive/reviews/2026-10-28-governance-port.md)。

## 按需入口

- [质量](docs/QUALITY.md)、[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)、[实施计划](docs/implementation-plan.md)
- [CI](docs/ci.md)、[机器人](docs/bot-automation.md)、[文档索引](docs/README.md)
