# 当前状态

> **最后确认：** 2026-10-30
> **阶段：** 已补齐开源蓝牙、候选外设模块、八路板级 ADC→hwmon 测温及被动硬件盘点；41 项离线回归及 6.18/三 DTB/1372 模块/救援打包核验通过。本轮 L3 not-run。
> **代码基线：** 工作分支 `codex/umi-hardware-enablement`，基于 `11ebe89`；本轮已获提交并推送至 PR #7 授权，未授权合并。

## 当前决策

- 维护 Ben8368/umi-mainline，保留原贡献者与第三方归属，见 [来源](docs/PROVENANCE.md)。默认 Linux 6.18.59，驱动与固件分层见 [源码清单](docs/OPEN_SOURCE.md)；逐项缺口见 [硬件矩阵](docs/HARDWARE_SUPPORT.md)。
- Agent 改动经工作分支和 PR；当前 HEAD 的 CI 与 CodeRabbit 最终反馈仍是合并门禁，见 [规则](docs/AI_RULES.md)。本轮已获提交并推送至 PR #7 授权，未授权合并。
- 开发 root/SSH/USB 权限保留。历史 boot 写入与 PPS 实验授权不扩大为本轮；BQ25970 仍禁用，不猜保护参数，见 [PPS](docs/PPS.md)及 [ADR 0005](docs/ADR/0005-explicit-pps-bringup.md)。
- 默认打包 Wi-Fi DTB、救援 `ROOTDEV=none`；plus 是未验收实验变体。模块只导出到普通目录，真实 rootfs 安装、刷写、分区或供电操作须本轮明确授权。

## 近期优先级

1. 审阅 [硬件修复](docs/archive/reviews/2026-10-30-hardware-enablement.md)及 [测温补齐/马达候选](docs/archive/reviews/2026-10-30-board-thermistors.md)，跟踪 PR #7 的 CI 与 CodeRabbit 最终反馈。
2. 按 [测试矩阵](docs/test-matrix.md)核验八路温度和新镜像基础功能、蓝牙固件/NVM/配对与 Wi-Fi 共存；救援启动不能替代 rootfs 模块验收。
3. 依 [硬件矩阵](docs/HARDWARE_SUPPORT.md)收集音频/红外板级数据及 modem/传感器/相机身份和固件；供电仍按独立安全门禁，见 [风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)。

## 最近验证

- 2026-10-30：八路测温接入并增加被动硬件盘点，41 项回归及最终目标构建/打包核验通过，见 [补充审计](docs/archive/reviews/2026-10-30-board-thermistors.md)；此前蓝牙修复见 [硬件审计](docs/archive/reviews/2026-10-30-hardware-enablement.md)，L3 均 not-run。
- 2026-10-30：上一轮 6.18/三 DTB/1363 模块和源码 BusyBox 交付核验见 [迁移记录](docs/archive/reviews/2026-10-29-source-parity.md)，不能用于本轮产物验收。
- 2026-10-29：旧 6.18 fix1 临时启动的亮屏、128 触摸事件和 GPU 初始化证据见 [记录](docs/archive/reviews/2026-10-29-linux-6.18.59-boot-fixes.md)；未迁移为本轮实机结果。

## 按需入口

- [质量](docs/QUALITY.md)、[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)、[实施计划](docs/implementation-plan.md)
- [CI](docs/ci.md)、[机器人](docs/bot-automation.md)、[文档索引](docs/README.md)
