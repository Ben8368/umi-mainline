# 2026-10-30 PR #7 发布回滚与验收命令修复

## 评审与范围

PR [#7](https://github.com/Ben8368/umi-mainline/pull/7) 的 `7179d861711adbea40eaba1d283ee36fb8187528` 已通过 CI result、CodeQL 和 CodeRabbit 检查，但[最终评审](https://github.com/Ben8368/umi-mainline/pull/7#pullrequestreview-5707957265)仍提出两项有效意见：连续发布三个模块交付文件失败后会混用新旧产物，限充文档没有给出 PPS 回归的独立命令。本轮用户明确授权跟进，并在门禁满足且无有效问题时合并；不授权部署、发布镜像或手机操作。

## 修复与审查

- 导出器在任何替换前完成全部旧文件备份。三个替换中任一失败时，逆序恢复已发布文件，原先不存在的文件移除，并传播原错误。备份失败不改变交付组。
- 若恢复本身失败，继续尝试其余恢复；报错并保留独立 `.modules-backup-*` 目录中的原名备份，避免外层临时目录清理丢掉恢复材料。输出目录的符号链接/非普通交付目标拒绝，不复制其目标来伪造备份。
- 限充文档同时列出两条 unittest discover 命令，说明 PPS 测试抽取驱动 C 函数、使用模拟 TCPM/I/O 桩，属于 L1，不等于 L2 或 L3。
- 构建文档补充异常恢复方式与边界：只针对可捕获 I/O 错误回滚，不承诺断电、强制终止或并发读写下整体原子性。

🚦 Audit Report：源码合入门禁仍是新 HEAD 的 CI result、CodeRabbit 最终反馈及有效意见处理；未完成前为 🔴，PR 保持开放。L3/充电安全/固件发布边界继续受 RISK-001/002/004/005 与 TD-004/005/007/008 限制；源码合并不关闭这些记录或表示设备验收完成。

## 验证

Windows x64 / PowerShell 7.6.5；执行环境 WSL umi / Linux x86_64 / sh。

- `python3 -m unittest discover -s tests -p 'test_*.py' -v`：exit 0，67 项 passed，无 skipped。
- `python3 -m unittest discover -s tests -p test_delivery.py -v`：exit 0，15 项。新增 24 个组合（8 组旧文件存在状态 × 3 个失败位置），断言旧交付内容/缺失状态和无关文件完全恢复；另覆盖备份失败，以及回滚失败仍继续恢复其他文件并保留备份。备份采用原名后再次通过专项。
- `scripts/check-tree.py`、`scripts/governance-docs-check.py`、`tests/governance-docs.py`、`scripts/git-hooks-test.py`、`tests/ci-policy.py`（6 项）、`tests/bot-dispatch.py`（22 项）、`git diff --check`：均 exit 0，包含 ShellCheck error 级。

新导出器执行 `python3 scripts/export-modules.py --tree /root/linux-6.18.59 --out /root/linux-6.18.59/out-hardware --dest /root/umi-pr7-followup-export`，exit 0，实际导出 1372 模块。独立核对归档哈希与清单一致、模块数及全部成员 root 所有权，成功后无遗留备份目录。

本轮未改 C/DTS，沿用[上一轮](2026-10-30-pr7-review-fixes.md)固定 6.18 的编译证据，不重做内核编译；本轮不创建 boot 镜像。远端新 HEAD 的审查未完成时不合并。原始日志和导出核验只留忽略目录 `out/pr7-followup/`。
