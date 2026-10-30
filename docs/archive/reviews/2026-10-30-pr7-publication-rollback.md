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

## CodeRabbit 追加意见修复

CodeRabbit 于 `2879f4e1f88f3912779f6df0c0b550bb752edf39` 的最终评审又列出四项尚未处理意见。本轮逐项核实并修改：

- 默认 `TREE` 在修改内核树前用 `git -C "$TREE" rev-parse HEAD` 对比完整固定 SHA；非空显式 `TREE` 保留兼容行为，空值仍采用默认树，不检查 `.git` 类型。
- `export-modules.py` 可将模块归档、清单、kernelrelease、Image.gz、三个 DTB 和 config-effective 一并备份和发布；任何替换失败会回滚整组，manifest 的 Image SHA 对应同组发布的 Image.gz。
- BusyBox 的 ELF、配置和来源 JSON 采用相同回滚契约；回滚失败时继续尝试其他文件并保留 `.busybox-backup-*` 恢复副本。
- initramfs 打包前复用 `build-busybox.py --verify` 检查所有 BusyBox 输入的 ELF64/AArch64/静态链接约束。

🚦 Audit Report：本地代码审查无新增阻断，PR 合入仍因新 HEAD 的远端检查尚待运行而 🔴 阻断；不得沿用 `2879f4e` 的 CI/CodeRabbit 结果。保留 L2 与设备 L3 not-run，本轮没有编译内核或访问设备。

验证在 WSL umi / Linux x86_64 / ext4 的临时仓库副本执行：

- `python3 -m unittest discover -s tests -p 'test_*.py' -v`：exit 0，72 项通过、0 skipped；含 8 个文件组逐替换点回滚、BusyBox 三件套回滚、BusyBox ELF 拒绝和默认/显式 TREE 版本策略回归。
- `python3 scripts/check-tree.py`：exit 0，299 paths、29 个 shell 文件、0 errors，含 ShellCheck error 级。
- `python3 scripts/governance-docs-check.py`、`python3 tests/governance-docs.py`：均 exit 0。
- `python3 tests/ci-policy.py`（6 项）、`python3 tests/bot-dispatch.py`（22 项）、`python3 scripts/git-hooks-test.py`（6 actor/场景）：均 exit 0。
- `git diff --check`：exit 0。

全套内核编译、真实 BusyBox 源码构建和手机验证未运行；旧 HEAD 的编译结果不能代替新 HEAD 验收。推送后需等待同一 SHA 的 CI result 与 CodeRabbit 最终审查，并核对有效意见后再按已有授权决定合并。

## `f0518b9` 最终评审追加意见

`f0518b95665036669f23a9723e8ada2b14cd2a2a` 的 CI result、其他检查及 CodeRabbit 最终评审均完成。CodeRabbit 提出一个有效意见：完整构建交付组的 manifest 没有 DTB 哈希，遇到无法完成回滚的混合输出时无法对照识别 DTB 内容。本轮在收集构建产物后、生成清单前记录三个 DTB 的 SHA256；不扩展其他文件的哈希项，并在导出成功回归中校验名称集合与每个文件的哈希。

对应 72 项离线回归、仓库 ShellCheck、治理文档及 CI/派单测试均已在 WSL ext4 验证通过；详细命令与结果沿用上节，代码检查和治理检查在本次文档更新后再运行。该意见修复推送后，`f0518b9` 结果不能替代新 HEAD 的门禁；新 HEAD 检查 pending 时保持 PR 开放。L2/L3 继续 not-run。

## `c1dab8a` 最终评审追加意见

`c1dab8a5c48c9c415fb020385d7ded74f9b3fd80` 的 CI result 和 CodeRabbit 最终评审均完成。CodeRabbit 指出服务在中间 SOC 重启时把 `charging_enabled` 当前值复制为 `desired`，进而可能写入 `0` 并在重新连接 USB 后保持停充至下限。该意见有效。

修复后，中间区间启动只读 `charging_enabled` 并报告 `requested=unchanged`，不写入、不把瞬时硬件状态提升为策略；只有容量到达 `UPPER` 或 `LOWER` 才建立策略目标。服务已经在本进程建立的停充/许可策略仍按原逻辑保持和重申。`docs/CHARGE-LIMIT.md` 同步说明启动契约。

- `python3 -m unittest discover -s tests -p test_charge_limit.py -v`：exit 0，16 项通过；覆盖两种读回状态、中间重启后的 USB 重新接入，以及到上下限才建立目标。
- `python3 -m unittest discover -s tests -p 'test_*.py' -v`：exit 0，74 项通过，无 skipped。

这项修复尚待推送；推送后重新核验同一 HEAD 的 CI result 与 CodeRabbit 最终反馈。L2/L3 仍 not-run。
