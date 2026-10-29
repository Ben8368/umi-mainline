# PR #2 CodeRabbit 审查被关闭取消

日期：2026-10-29；仓库：Ben8368/umi-mainline。

## 事件

- PR #2 的 HEAD 为 `7383b6525b6ba2f43c8a85707c52da0be4421777`。合并时其 CI result、CodeQL、lint、governance 与两个架构的 offline 检查均为 success；CodeRabbit 仍处于 `in_progress`。
- PR 合并后，GitHub 将 CodeRabbit 检查标为 `cancelled`，原因是 `Pull request is closed`。该运行总计 12 分 52 秒；分析检查完成，但“Generate review feedback”和“Publish review results”均被跳过，未对该 HEAD 发布最终审查反馈。
- 因此这次状态不是 CodeRabbit 通过，也没有最终意见可供维护者处理。先前 HEAD 的可执行意见已修复，不等于当前 HEAD 有最终审查结果。

## 治理修正

- 推送后远端检查采用非阻塞会话流程：记录 PR、HEAD SHA 和 pending 状态后可以结束会话，稍后查询。
- 合并门禁要求目标 HEAD 的 CI result 成功，且 CodeRabbit 已完成并发布最终反馈；检查进行中、取消、跳过、失败或没有最终反馈时，PR 保持开放，不合并、不关闭。
- 处理最终反馈中有效意见后如产生新 HEAD，必须重新核对该 SHA 的 CI 与 CodeRabbit 结果。检查服务延迟或不可用不构成绕过门禁的理由。

权威规则见 [AI_RULES](../../AI_RULES.md#pr-推送与远端验证)、[CI](../../ci.md) 和 [PR 模板](../../../.github/PULL_REQUEST_TEMPLATE.md)。
