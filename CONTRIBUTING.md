# 贡献指南

先读 [AGENTS](AGENTS.md)、[当前状态](CONTEXT.md)、[产品范围](docs/PRODUCT.md)。工作分支用 codex/ 前缀，PR 面向 master，由维护者审查合并。

Conventional Commit 类型英文、标题与正文中文。AI 实质参与附工具级 Co-authored-by；纯人工用 Human-authored: true。规则唯一见 [AI_RULES](docs/AI_RULES.md)，安装钩子：python3 scripts/install-git-hooks.py。

验证最低要求与证据分级见 [QUALITY](docs/QUALITY.md)，CI 入口见 [ci](docs/ci.md)。治理文档至少运行 python3 scripts/governance-docs-check.py 和 git diff --check；源码变化先输出 🚦 Audit Report，覆盖失败路径。完整编译和真机验证分别报告。

不提交镜像、原厂分区、凭据或长日志，不伪造硬件就绪，不猜电压或充电参数。刷写/格式化/真实块设备写入必须有具体授权。当前调试权限策略见 [技术债](docs/TECH_DEBT.md)。保留 [许可证](LICENSE) 与 [来源归属](docs/PROVENANCE.md)。

PR 写明变更、验证命令/结果、未覆盖项、Risk/TD/ADR。推送后 CI result / CodeRabbit 可待核验，不自动合并；合入门禁见 AI_RULES。
