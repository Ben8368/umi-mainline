# 机器人自动化操作约定

边界见 [ADR 0002](ADR/0002-ci-and-bot-boundaries.md) 与 [ADR 0004](ADR/0004-agent-pr-and-jules-delegation.md)，当前启用/验收状态只写 [CONTEXT](../CONTEXT.md)。本仓库授权与账户额度由维护者明确提供，不从 DockDSM 继承任何授权、额度或活跃任务。

## 分工与门禁

CodeRabbit 自动审查 base 为 master 的非 draft PR，按 .coderabbit.yaml 读取本项目规则，聚焦构建错误、供电安全、资源生命周期、固件来源与真机证据。所有自动写入 finishing_touches 默认关闭。维护者在评估实际 diff 后合并；禁止自动合并或发布。合并前须确认当前 HEAD 的 CI result 成功，并且 CodeRabbit 已完成、发布最终反馈且有效意见已处理。审查待运行、运行中、失败、取消、跳过或没有最终反馈时，不得合并或关闭 PR；保持 PR 开放即可结束会话，后续再查。服务故障不构成绕过门禁的理由，详见 [AI_RULES](AI_RULES.md#pr-推送与远端验证)。

CodeRabbit 服务端 Triage Rules 不能由 YAML 创建。若启用低风险 autofix，只限定本仓库、非 draft、Risk/Blast radius/Review effort=Low、Security risk=Minimal、已审查；最多两轮，单写入者且不可碰内核、供电、磁盘、固件、CI/治理权限。本轮默认仅审查，不授予持续自动写入权限。收费、App 新授权或范围扩大须维护者确认。

## CodeRabbit 暂停与手动触发

常规分层审查见 [QUALITY](QUALITY.md#分层审查与反例验证)。保留 chill，以缺陷证据和路径指令提高信噪比；assertive 按官方定义增加反馈量，不作为漏报率改善的证据。固件只排除二进制，清单、来源和许可文本应参与审查。

连续提交可能使 CodeRabbit 自动暂停，检查显示 `skipped / Review paused`。先读取机器人说明，核对最后已审查提交和当前 HEAD；CI 成功、旧提交的最终反馈或旧线程自动解决都不能替代新 HEAD 的审查。

- 已获得在该 PR 发送机器人命令评论的明确授权时，在完成本轮修改并推送后发送 `@coderabbitai review`，请求一次增量审查。只有需要恢复后续自动审查且获得相应授权时，才使用 `@coderabbitai resume`；不为绕过暂停而改 YAML、扩大权限或开启自动修复。
- 评论发送成功只表示请求已发出。须核对 CodeRabbit 的 `Review triggered` 回执、检查状态与审查覆盖的 HEAD，再等待最终反馈；不要重复刷同一请求。GitHub 检查重跑接口可能不可用，返回 404 不代表审查通过，也不能代替机器人触发命令。
- 同一 PR、同一跟进任务内已明确授权的必要机器人评论，无需逐条重复确认；授权不扩展到其他 PR、人工消息、额外计费或权限变更。尚无评论授权时只就该动作询问一次，说明评论内容、用途和阻塞原因，不重新索取已取得的提交、推送或条件合并授权。
- 触发后若继续推送，旧 HEAD 的回执和反馈不能用于合并新 HEAD。核对是否已有针对新 HEAD 的审查，必要时在现有授权内重新请求；合并条件仍以 [AI_RULES](AI_RULES.md#pr-推送与远端验证) 为准，未完成时保持 PR 开放。

跨文件重构、审查规则变更或多轮增量修复后，可在已有评论授权内集中发送一次 `@coderabbitai full review`，从头复核 PR 的全部变更文件；它不是整个仓库审计，也不替代专项复核。普通修复继续用增量 review；不重复刷请求或添加使用额外额度的参数。命令须独占一行，以回执和实际覆盖提交确认完成。官方语义见 [review commands](https://docs.coderabbit.ai/reference/review-commands)，profile 与路径过滤见 [configuration](https://docs.coderabbit.ai/reference/configuration)。

## Issue → Jules

维护者于 2026-10-29 授权：开发 Agent 可在已授权任务内，将简单、低风险、可独立验收且符合下述路径准入的工作包派给 Jules，无需再逐单询问维护者。适用例子是普通文档修订、小型离线测试与已准入工具；复杂、风险不明或涉及受保护路径的工作由开发 Agent 本地处理。派单 Agent 负责拆分、排除文件冲突、检查回执、审阅 diff、复跑验证和 PR 交付；Jules 不递归派单。治理规则修改属于受保护范围，不能因改动简单而派给 Jules。

维护者于 2026-10-29 提供的账户额度为每日 100 条任务；这是账户总额度，不代表当日剩余额度、并发量或必须用满的目标。派单前核对账户实际剩余额度；无法确认时暂停派单。每日重置时点以账户实际显示为准。日额度不改变下述在途容量门禁，不能因日额度提升而扩大同时在途规模或重复派发。

使用 Small task for Jules 表单，填写 Documentation / Tests / Tooling、精确文件清单、改动、可观察正反例、验证命令，由派单 Agent 在上述常设授权范围内勾选本单授权，并确认依赖已合入、剩余额度与本地独占文件；超出范围须维护者另行授权。Agent 使用维护者已授权且具有仓库写权限的账户提交 Issue，不绕过机器人 actor 禁令或获取新凭据。bot-dispatch 用最新 Issue 校验作者及触发者当前 write/maintain/admin 权限；公开 Issue、机器人 actor、关闭 Issue、保护标签、重复/通配/越界路径、缺字段与 API 失败均拒绝。

Documentation/Tests 最多三个精确文件；Tooling 最多六个，只开放 scripts/dev/summarize-test-results.py、tests/dev/summarize-test-results.py、docs/dev/test-results.md，必须含实现文件。它们只是未来允许的新建路径，不代表工具已经实现。测试不可更改治理/署名/CI/派单门禁或内核/充电/镜像验收测试；不能修改 dts、patches、power、fts521、stfts、initramfs、固件或构建入口。机器路径规则以 workflow 为权威源。

仓库级 concurrency 串行检查，最多四个打开的 Jules Issue、五个 Jules PR；分页检查所有打开 PR 的实际路径及改名前路径，重叠或文件 API 达到 3000 上限时拒绝。加标签前重新读取 Issue，内容/状态/标签变化则停止。Actions 不 checkout、不运行 Issue 命令，无内容写权限/PAT。

加 jules 只表示已请求。必须有 google-labs-jules[bot] 回执及任务链接才能报告已接单；无回执先核查 App/账户任务，不循环重加标签。Jules 安装与标签触发以默认分支为准，本 PR 未合并前不派发依赖本分支的任务。外部会话未能确认时记录待确认，不能新建凭据绕过。

## 独占、验收与停止

Codex 活跃 PR 标 agent:codex，Jules 产出 PR 标 jules；同分支只有一个写入者。交接前在服务端停止旧任务，移除标签本身不会停止运行。未知本地占用、已关闭但仍运行的外部任务无法由 Actions 完全观察，维护者必须逐单检查。

任务读取 AGENTS / CONTEXT / LESSONS；输出命令、结果和未覆盖项，不弱化断言、不扩大范围，Jules 不递归派单。所有 Agent 的开发改动均在工作分支提交；一个任务一个面向 master 的 PR，依赖串行合入，不直接写主分支。维护者审阅最终增删改名 diff、重跑检查，记录首次验收、返工和越界；十个样本后再考虑扩容，不填额度。额外计费由维护者处理。

队列 pending 可能被后来的请求替换，不自动重试；运行取消/无回执须逐单核对。出现越界或无法确认写入者时停止新派单、先停服务端任务再接管。缺失或失败不是通过。

## 依赖机器人

Renovate 配置周一 Asia/Shanghai 维护 GitHub Actions，dashboard 先批准、并发三项、无自动合并、不更新内核/固件/供电参数。Dependabot 配置保留为零并发备用，避免双机器人重复提交；外部 App 未授权时明确记录未启用，不以 YAML 冒充激活。

## 配置与回归

Jules VM 先运行 [环境预检](jules-environment.md)。离线执行 python3 tests/bot-dispatch.py，测试实际 workflow JavaScript 与模拟 API，禁止产生真实派单。标签清单在 .github/labels.json，幂等配置工具 scripts/configure-repository.py 只在明确 --apply 时更新本仓库标签，不修改保护/默认分支/外部 App 授权。

官方依据：[CodeRabbit](https://docs.coderabbit.ai/)、[Jules tasks](https://jules.google/docs/running-tasks/)、[Renovate](https://docs.renovatebot.com/)、[GitHub concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)。
