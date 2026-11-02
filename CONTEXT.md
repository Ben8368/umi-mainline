# 当前状态

> **最后确认：** 2026-11-02
> **阶段：** PR #8 原 P1 修复复核后发现 IRQ 所有权/GPIO 回滚 P2；本轮最小修复与离线验证完成，待提交交付，保持 Draft，新修复独立签核、同 HEAD 远端门禁及 L3 未全齐。
> **代码基线：** origin/master e1e0c8c775f5fcc53104e43157ddf56b2173ab02；工作分支 sync/upstream-5fa2e00。

## 当前决策

- 维护 Ben8368/umi-mainline，默认 Linux 6.18.59，原作者/第三方归属保留；能力边界见 [硬件矩阵](docs/HARDWARE_SUPPORT.md)。
- idle 同步及 ADC 取舍见 [同步审查](docs/archive/reviews/2026-11-02-upstream-5fa2e00.md)；独立发现与 IRQ/probe 最小修复见 [专项记录](docs/archive/reviews/2026-11-02-pr8-independent-kernel-review.md)。
- 用户授权本分支修改、离线编译、提交、推送及 Draft PR；不合并、不关闭 PR、不部署设备。高风险独立专项复核及同 HEAD CI/CodeRabbit 门禁仍适用。
- 开发 root/SSH/USB 权限保留。BQ25970 禁用，PPS 显式开启、限充与保护参数不变。旧设备授权不延伸为本轮授权。

## 近期优先级

1. 完成 [P2 修复](docs/archive/reviews/2026-11-02-pr8-p2-fixes.md) 的外部专项复核及新 HEAD CI/CodeRabbit 最终反馈；旧结果不覆盖新修改。
2. 取得新授权后按 [触摸](docs/TOUCH.md) 与 [测试矩阵](docs/test-matrix.md) 验收 idle 首触、睡眠/恢复及 reset/rebind。
3. 普通充电/PPS 的剩余风险仍依 [风险台账](docs/RISK_REGISTER.md) 和 [充电审计](docs/archive/reviews/2026-10-30-charging-audit.md) 单独推进；不自动启用电荷泵。

## 最近验证

- 2026-11-02：P2 修复后 99 项离线（包含原 P1/P2 运行时反例）、治理及 6.18.59 Image.gz/dtbs/modules 增量编译通过；普通 checkpatch 通过，strict 退出 1（6 条既有命名 CHECK，0 errors / 0 warnings）；版本和未覆盖项见 [P2 记录](docs/archive/reviews/2026-11-02-pr8-p2-fixes.md)，非 clean-room / 真机验收。
- 2026-10-30：PR #7 的既有审查证据见 [合并前复核](docs/archive/reviews/2026-10-30-pr7-merge-audit.md)，不作为本轮新增 C 代码的验收。

## 按需入口

- [质量](docs/QUALITY.md)、[风险](docs/RISK_REGISTER.md)、[技术债](docs/TECH_DEBT.md)、[CI](docs/ci.md)
