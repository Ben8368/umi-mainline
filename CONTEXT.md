# 当前状态

> **最后确认：** 2026-10-30
> **阶段：** 6.18 内核、三个 DTB、1363 个模块及源码 BusyBox 救援镜像已完成 L2 构建和打包核验；35 项离线回归通过。本轮未操作手机；上轮亮屏、触摸及 GPU 初始化证据不作为新产物验收。
> **代码基线：** 工作分支 `codex/umi-6.18-open-source-parity`，基于已合并 PR #6 的 `6527c5c`；用户已授权本地提交、推送并创建 PR；未授权合并。

## 当前决策

- 维护 Ben8368/umi-mainline，保留原贡献者与第三方归属，见 [来源](docs/PROVENANCE.md)。默认 Linux 6.18.59，共用 [kernel.env](config/kernel.env)；驱动、源码用户态与独立固件分层见[源码清单](docs/OPEN_SOURCE.md)。
- Agent 改动经工作分支和 PR；低风险 Jules 派单按[机器人约定](docs/bot-automation.md)。当前 HEAD 的 CI 与 CodeRabbit 最终反馈仍是合并门禁，不能因关闭 PR 取消审查，见[规则](docs/AI_RULES.md#pr-推送与远端验证)。
- 开发 root/SSH/USB 权限保留。此前授权的 TCPM + SMB5 PPS 实验及 boot 写入不扩大为本轮授权；BQ25970 仍禁用，不猜保护参数。见 [PPS](docs/PPS.md)、[ADR 0005](docs/ADR/0005-explicit-pps-bringup.md)与[设备及回退](docs/archive/reviews/2026-10-29-pps-device-flash.md)。
- 救援默认 `ROOTDEV=none`。模块只导出到普通目录，真实 rootfs 安装、刷写、分区或供电操作须本轮明确授权。

## 近期优先级

1. 按授权提交并推送本轮工作分支、创建 PR，核验该 HEAD 的 CI 与 CodeRabbit 最终反馈，过程见[迁移记录](docs/archive/reviews/2026-10-29-source-parity.md)。
2. 按[测试矩阵](docs/test-matrix.md)补齐本轮镜像的屏幕恢复、触摸短按、Wi-Fi、GL/Vulkan/Plasma、关机与长稳证据；供电另按 PPS 安全门禁。
3. 核实固件精确来源/分发条件，收敛源码用户态体积和工具链锁定；远端结果以 PR 的当前 HEAD 为准。见[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)。

## 最近验证

- 2026-10-30：最终内核/三个 DTB/1363 模块与源码 BusyBox 救援打包 exit 0，171 输入与工作区一致；35 回归及离线门禁通过，详见[迁移记录](docs/archive/reviews/2026-10-29-source-parity.md)。
- 2026-10-29：6.18 fix1 临时启动，用户确认亮屏；128 个触摸事件、GPU 初始化与八个 SPMI 别名禁用已取证；停止测试后经 bootloader 并拔线关机。见[启动修复记录](docs/archive/reviews/2026-10-29-linux-6.18.59-boot-fixes.md)。
- 2026-10-29：此前 6.18 内核/三个 DTB 编译与打包、21 项回归及首次黑屏分析见[构建记录](docs/archive/reviews/2026-10-29-linux-6.18.59-build.md)和[实机记录](docs/archive/reviews/2026-10-29-linux-6.18.59-device-boot.md)。
- 2026-10-29：PPS 修复版 18 项回归与 boot 写入读回已核验，充电未测；见[设备记录](docs/archive/reviews/2026-10-29-pps-device-flash.md)。

## 按需入口

- [质量](docs/QUALITY.md)、[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)、[实施计划](docs/implementation-plan.md)
- [CI](docs/ci.md)、[机器人](docs/bot-automation.md)、[文档索引](docs/README.md)
