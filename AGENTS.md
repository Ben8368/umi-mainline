# AI 协作规范

AGENTS.md 是 AI 协作唯一入口；CLAUDE.md 与 .cursorrules 只做摘要。规则以权威文档为准。

## 开局与按需读取

每轮先读 [CONTEXT](CONTEXT.md) 和 [LESSONS](LESSONS.md)，实施前按 [AI_RULES](docs/AI_RULES.md) 确认宿主 OS、架构和 Shell。仅按实际任务加载下表，不递归加载全部链接。

| 任务 | 必读 |
| --- | --- |
| 产品、设备、功能声明 | [PRODUCT](docs/PRODUCT.md)、[平台契约](docs/platforms.md)、[README](README.md) |
| 任意源码修改 | [AI_RULES](docs/AI_RULES.md)、[QUALITY](docs/QUALITY.md) |
| 内核、DT、驱动、固件 | [构建](docs/BUILD.md)、对应 DISPLAY / TOUCH / GPU / WIFI / BATTERY 专题、[测试矩阵](docs/test-matrix.md) |
| CI、依赖、发布 | [CI](docs/ci.md)、[依赖](docs/dependency-locks.md) |
| 机器人、任务交接 | [机器人约定](docs/bot-automation.md)、[Jules 环境](docs/jules-environment.md) |
| 风险、延期实现 | [RISK_REGISTER](docs/RISK_REGISTER.md)、[TECH_DEBT](docs/TECH_DEBT.md) |
| 治理、署名、长期决策 | [GOVERNANCE](docs/GOVERNANCE.md)、[MAINTAINERS](docs/MAINTAINERS.md)、[ADR](docs/ADR/README.md) |

## 不可跨越的边界

- 本项目是小米 10 umi / SM8250 的 Linux 适配层，不是完整内核仓库；源码存在、编译通过、原作者实测与本轮真机证据必须区分。
- 不执行刷写、格式化、分区、真实块设备写入或修改供电参数来完成离线验证。此类真机动作必须有本轮明确授权及回退方案。
- 不猜测电压、电流、温控或采样电阻参数；保护配置不完整时拒绝主动快充。
- 不删除原贡献者、固件来源或许可证；不提交凭据、原厂分区、镜像、长原始日志或构建产物。
- 当前开发调试 root/SSH/USB 权限策略按维护者明确决定保留，参见 TECH_DEBT；不得擅自收紧或扩大。
- 默认不提交、不推送、不发布、不合并；仅执行用户明确授权的动作。不得直接修改远端 master。

## 执行与汇报

- 源码改动后、完整验证前输出 🚦 Audit Report，写明阻断、跟进及验证计划；格式见 AI_RULES。
- 当前阶段只写 CONTEXT，开放假设写 RISK_REGISTER，实现妥协写 TECH_DEBT，长期决定写 ADR。
- 提交标题与正文使用中文，类型前缀与 trailer 保持英文；Codex 使用 Co-authored-by: Codex <codex@openai.com>。
- PR 推送后非阻塞汇报链接与待核验项；人工合并前核对 CI result 和 CodeRabbit，禁止自动合并。
- 默认中文汇报，文件使用 UTF-8 / LF；验证结果不得把未运行写成通过。

## 治理文档自治理

遵守 [docs/GOVERNANCE.md](docs/GOVERNANCE.md) 的单一事实源、预算、状态和归档规则。修改后运行 python3 scripts/governance-docs-check.py；超预算先拆分归档，不提高上限。
