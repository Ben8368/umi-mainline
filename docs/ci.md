# GitHub CI 与发布

CI 监听面向 master 的 PR、master push、merge_group 和手动触发；不自动发布镜像、不合并、不执行手机命令。统一门禁 CI result 汇总 governance、lint、offline 三个 job，所有结果必须 success，失败、取消、缺失或意外 skipped 均拒绝。

| Job | 内容 | 证据层级 |
| --- | --- | --- |
| governance | 文档预算/链接/ADR、署名钩子与新提交、CI/派单策略回归 | L0/L1 |
| lint | Python AST、Shell 语法、ShellCheck error、JSON/YAML、Actionlint 与 action 固定身份 | L0 |
| offline | Linux amd64/arm64 上的纯离线回归 | L1 |
| CodeQL | Python 与 Actions 安全补充 | L0，不替代 CI result |

PR 使用只读 token、固定完整 action commit、checkout 不保留凭据；从不使用 pull_request_target 执行 PR 内容。labeler / bot-dispatch / stale 只处理 GitHub 元数据，权限按任务最小化，不执行 Issue 验证命令，不向 Actions 注入 PAT。

Linux 目标内核编译通过手动 Kernel compile 工作流在固定输入上验证；不属于快门禁，不被解释为真机验收。每次 C/DTS 变更合入前应审阅该编译结果；若未运行，PR 明确 not-run 并登记风险。不得将缺失的编译检查描述为通过。

分支保护由维护者在默认分支具备工作流后配置 required check: CI result。CodeRabbit 使用流程审查门禁，不能设置为硬 required check；无自动合并。新工作流首次 PR 可以运行 pull_request CI，但 issues/schedule/pull_request_target 以默认分支为准：本 PR 未合并前不宣称这些机器人已在生产触发。

版本升级由依赖机器人提出 PR，固定身份和测试不可减弱，见 [依赖](dependency-locks.md)。本地验证见 [environment](environment.md)。
