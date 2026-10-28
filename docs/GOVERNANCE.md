# 治理文档维护规则

采用 DockDSM 的单一事实源、按需加载、证据分级、预算检查与归档机制，来源见 [PROVENANCE](PROVENANCE.md)。

## 单一事实源

| 事实 | 权威位置 |
| --- | --- |
| AI 入口与读取路由 | AGENTS.md |
| 当前阶段、决策、三项优先级、最近验证 | CONTEXT.md |
| 可复发经验 | LESSONS.md 与 docs/lessons/ |
| 产品与非目标 | docs/PRODUCT.md |
| 设备、内核与运行契约 | docs/platforms.md |
| 工作包与依赖 | docs/implementation-plan.md |
| 测试组合与证据层级 | docs/test-matrix.md、docs/QUALITY.md |
| 构建与硬件专题 | docs/BUILD.md、DISPLAY/TOUCH/GPU/WIFI/BATTERY |
| CI 与机器人 | docs/ci.md、docs/bot-automation.md |
| 未验证假设与外部风险 | docs/RISK_REGISTER.md |
| 有意保留的实现妥协 | docs/TECH_DEBT.md |
| 提交、审查、署名 | docs/AI_RULES.md |
| 长期决定与历史 | docs/ADR/、docs/archive/ |

其他位置只用稳定摘要和链接，不复制当前状态与完整任务单。历史实测笔记保留时间与适用版本，不冒充最新验收。

## 状态词

设计中：只有方案。计划：排入路线未实施。已实现未验证：代码存在但目标证据不足。已验证：有指定环境、命令、结果和证据。不支持：明确拒绝。源码审查、离线合成、完整编译与真机验证不得混同。

## 强制加载预算

| 文件 | 最大行数 | 最大字符数 |
| --- | ---: | ---: |
| AGENTS.md | 85 | 5200 |
| CONTEXT.md | 45 | 3000 |
| LESSONS.md | 20 | 1800 |
| CLAUDE.md / .cursorrules | 12 | 800 |

超预算先拆分或归档，不提高预算。CONTEXT 最多三项近期优先级，每条最近验证链接证据。ADR 编号唯一、状态与索引一致，替代必须指向不同 ADR 并写清范围。

## 更新与验收

改变阶段、优先级或证据时只更新权威位置。风险关闭与债务偿还移入带日期的 archive；影响长期边界新增 ADR。运行 python3 scripts/governance-docs-check.py 和 git diff --check，人工确认未把未测写成通过。
