# AI 开发与审查规则

入口见 [AGENTS](../AGENTS.md)，状态见 [CONTEXT](../CONTEXT.md)，文档约束见 [GOVERNANCE](GOVERNANCE.md)。

## 工作顺序

读取 Context / Lessons → 确认 OS、CPU 架构、Shell → 确认事实源与范围 → 修改 → 红绿灯审查 → 客观验证 → 更新权威文档 → 汇报。

Unix 先运行 uname -s、uname -m 并确认 Shell；WSL 标记 Windows + WSL。macOS 不假设 GNU sed、Linux mount、块设备或交叉编译器可用。不得在宿主上执行手机 init、刷写脚本或充电寄存器操作以模拟真机。

## 红绿灯审查

产品源码改变后、完整验证前输出 🚦 Audit Report，包含总体评价、🔴 阻断项、🟡 跟进项和验证计划。审查真实性、范围、数据/供电/凭据安全、错误路径和可测试性。🔴 不得合并；🟡 必须登记 RISK_REGISTER 或 TECH_DEBT。用户明确排除的调试权限不顺手修改。

## 最低验证

| 修改 | 验证 |
| --- | --- |
| 治理文档 | governance-docs-check.py、tests/governance-docs.py、git diff --check |
| 治理/CI/机器人 | 上述 + git-hooks-test.py、tests/ci-policy.py、tests/bot-dispatch.py |
| Shell / Python | 上述 + scripts/check-tree.py、相关离线回归；ShellCheck 至少 error 级 |
| C 驱动 / DTS | 上述 + tests/test_reliability.py、Linux 目标内核编译；真机另按 test-matrix |

每个结果列命令、退出结果和未覆盖项。静态或合成通过不等于完整编译；完整编译不等于真机安全。

## 文档与 Git

一个请求可包含多个可分别审查的 commit，但默认一个直接面向 master 的 PR。工作分支用 codex/ 前缀。默认不提交、推送、合并或发布；用户明确要求时执行对应动作。保留无关本地修改，不重写已推送历史，不把构建产物或敏感数据提交。

### 提交与署名

Conventional Commit 类型前缀英文，标题和正文中文。主作者保持维护者身份；工具参与实质改动时，在末尾空行后追加工具级 trailer，不记录模型：

| 工具 | trailer |
| --- | --- |
| Codex | Co-authored-by: Codex <codex@openai.com> |
| Claude Code | Co-authored-by: Claude Code <noreply@anthropic.com> |
| Cursor | Co-authored-by: Cursor <cursoragent@cursor.com> |
| Jules | Co-authored-by: Google Labs Jules <161369871+google-labs-jules[bot]@users.noreply.github.com> |

依赖机器人 Renovate 使用固定 Bot-authored-by: Renovate <29139614+renovate[bot]@users.noreply.github.com>，不能冒充纯人工。纯人工提交使用 Human-authored: true，不得与 AI trailer 混用。运行 python3 scripts/install-git-hooks.py 安装仓库级 commit-msg 钩子，不改全局配置。多段提交信息用独立 -m 参数或文件，不能把字面量反斜杠 n 当换行。提交后用 git show -s --format=%B HEAD | git interpret-trailers --parse 核对署名。CI 只检查新提交，不重写历史署名。

### PR 推送与远端验证

本地验证与提交完成后，仅在用户授权时一次性推送工作分支并开 PR，不创建依赖堆叠 PR。推送后不阻塞会话等待远端检查：汇报 PR、HEAD SHA 和待核验项后，可以结束会话或转做其他工作，之后再查询结果。

合并是独立门禁，不能因用户要求本轮合并、等待时间过长或检查服务不可用而跳过：

1. 对准备合并的**当前 HEAD SHA**，确认 `CI result` 为 success。
2. 等待 CodeRabbit 对同一 HEAD 完成审查并发布最终反馈。`queued`、`in_progress`、`cancelled`、`skipped`、失败或没有最终反馈都不算通过。PR 被合并或关闭会取消尚未发布的 CodeRabbit 审查，因此审查未完成时保持 PR 开放，不合并、不关闭。
3. 逐项核对最终反馈中的有效意见。修复后推送新 commit 时，回到第 1 步，等新 HEAD 的 CI 与 CodeRabbit 最终结果；所有有效意见处理完毕后才可合并。

远端检查未结束时，记录 PR、HEAD SHA 和 pending 状态即可结束会话，不需要让会话保持运行。稍后续作时先查询该 SHA 的检查和 CodeRabbit 已发布反馈，再决定修复或合并。CodeRabbit 尚无结果不能以书面备注、人工推断或“服务不可用”为由绕过此门禁；若长期不可用，PR 保持开放并报告阻塞。CodeRabbit 不设为硬 required check，但它是人工合并的流程门禁。无自动合并、无自动发布。只有用户明确授权合并，且上述门禁满足后才执行。

## 机器人协作

维护者逐单明确授权，采用 [机器人约定](bot-automation.md)的 Issue 表单与独占路径门禁。没有从其他仓库继承任何派单常设授权。核心内核、供电、真实磁盘、CI 权限和治理权限不交给自动派单。读取 AGENTS / CONTEXT / LESSONS 是必要条件；标签不等于文件级权限或接单。一个分支同一时刻只允许一个写入者，机器人不能自行扩大范围、降低测试、递归派单、合并或发布。
