# 2026-10-29 机器人授权核对

CodeRabbit GitHub App 设置页已有 All repositories，覆盖 Ben8368/umi-mainline，没有更改这一授权。Google Labs Jules 与 Renovate 原本只选 DockDSM；维护者明确确认只增加 umi-mainline、保留 DockDSM、保持 Only select repositories，并随后确认两个配置均已保存。

保存 Jules 的工具操作曾被自动审核拒绝：请求落到与任务无关的 stitch.google.com。没有绕过该拒绝，也没有通过其它工具保存；最后由维护者手动完成两个 GitHub 设置。

仓库内已准备 CodeRabbit 治理 guideline/path instructions、Jules 精确任务表单/派单门禁和环境预检、Renovate dashboard 审批与并发/范围约束，标签已幂等应用。没有发起真实 Jules 任务、自动合并或发布，没有新增凭据。服务接单/审查成功仍需实际回执；默认分支事件工作流须先经本 PR 合入后才生效。
