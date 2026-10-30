## Summary

-

## Review scope

- 风险：低 / 中 / 高；理由与行为契约（供电、数据、权限影响）：
- base / head SHA（未提交改动单列）：
- 受影响调用链、故障与恢复路径：
- 专项复核者/会话与记录链接（高风险必填；作者自查与 CodeRabbit 不计独立复核）：

## 🚦 Audit Report

**总体评价：** [ 🔴 阻断 / 🟡 可通行 / 🟢 通过 ]

**1. 🔴 阻断项：**
- 无 / 具体问题

**2. 🟡 跟进项：**
- 无 / 具体问题及权威登记位置

**3. 验证计划：**
- 命令、真实路径与未覆盖项

## Evidence

- [ ] `python3 scripts/governance-docs-check.py`
- [ ] 相关 CI / 本地命令结果（未结束时标注“待核验”；合入前当前 HEAD 的 `CI result` 须 success，且 CodeRabbit 须已完成并发布最终反馈、有效意见已处理。queued / in_progress / cancelled / skipped / failure 或无最终反馈时保持 PR 开放；会话可结束，稍后续查。见 [AI_RULES](https://github.com/Ben8368/umi-mainline/blob/master/docs/AI_RULES.md#pr-推送与远端验证)）
- [ ] CONTEXT / RISK / TD / ADR 已更新到唯一事实源（如适用）
- [ ] AI / 依赖机器人的改动与建议未降低测试强度或绕过人工审查（如适用）
- [ ] 故障回归先确认正常前置状态；涉及时序时检查中间写入/顺序；关键缺陷的旧行为反例确实触发目标断言（不适用时说明）

## Review disposition

- CI result 链接 / 对应 HEAD：
- CodeRabbit 最终反馈链接 / 覆盖提交（含 review 正文、行内与 outside-diff）：
- 意见逐项处置：评论链接 → 触发条件 → 接受/部分接受/不适用及依据 → 修复 commit / 验证结果。
- 专项复核覆盖与未覆盖项；新 HEAD 是否影响先前结论：

审查与反例要求见 [QUALITY](https://github.com/Ben8368/umi-mainline/blob/master/docs/QUALITY.md#分层审查与反例验证)；复选框和机器人摘要不替代上述证据。

## Risk / Tech debt

- 无 / 链接到 `docs/RISK_REGISTER.md` 或 `docs/TECH_DEBT.md`
