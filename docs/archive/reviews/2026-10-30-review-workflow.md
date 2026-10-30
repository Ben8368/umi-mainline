# 2026-10-30：分层审查流程与 PPS 回归补强

## 范围与依据

基于 `d9d0b516d45eac8da39794df890c3f45983574af`，本地工作分支 `codex/review-workflow`，覆盖该基线后的本轮审查优化改动；用户随后授权提交并推送至现有 PR #7 的 `codex/umi-6.18-open-source-parity`。读取用户引用的“评估CodeRabbit审查能力”讨论；历史 PR 评价作为线索，本轮未重新逐条核验所有远端 PR，不沿用主观 8/10 评分为准确率。

本地确认两个覆盖缺口：health 测试从默认停充状态注入错误，不能证明已运行的普通充电会停止；PPS 心跳只检查调用数和最终限流，不能排除中间先降载再恢复，也不能证明发送了续约请求。未据此断言当前驱动存在对应故障。

## 改动与自查

- [QUALITY](../../QUALITY.md#分层审查与反例验证) 按行为风险分级，高风险由开发者以外的合格维护者或只读审查会话复核；[ADR 0006](../../ADR/0006-layered-review.md) 记录长期决定。
- AI_RULES 与 PR 模板要求 base/head、专项复核范围、CI/最终反馈链接和逐项处置，保留当前 HEAD 门禁，不新增自动合并、付费服务或外部消息授权。
- CodeRabbit 保留 chill，要求触发条件、调用链、影响和反例；firmware 改为只排除二进制扩展名，保留清单/来源/许可文本。官方 [configuration](https://docs.coderabbit.ai/reference/configuration) 说明 assertive 增加反馈量，不证明漏报率下降；[review commands](https://docs.coderabbit.ai/reference/review-commands) 区分增量 review 与 PR 全量 full review。本轮未发送机器人评论。
- PPS 桩记录限流写入尝试和成功的电流/电压请求次数；正常状态后注入 health 异常，验证普通合同可恢复、PPS 保持锁存。连续三次 capped 心跳必须续约且无临时降载或停充。

自查调用链为合成 TCPM/health → 实际 `smb5_pd_work()` → `smb5_pps_update()` / `smb5_pps_stop()` → 合成限流/充电 setter 和通知。只改测试桩与断言，未改驱动、DTS、供电参数或设备部署。自查不计独立专项复核；本轮治理/充电测试改动须在合并前取得该记录。

## 🚦 Audit Report

总体：本地 L0/L1 验证通过，远端及独立复核待核验。

- 🔴 本地自查未发现新增阻断缺陷；没有独立专项复核记录与当前 diff 的远端结果，不能据本报告合并。
- 🟡 新配置服务端生效、审查效果与复核独立性属于 [RISK-003](../../RISK_REGISTER.md#risk-003外部机器人端到端未验收p2)，不以本地 YAML 检查证明。
- 验证计划：离线回归、旧行为反例、治理/钩子/CI/派单策略、文本与 ShellCheck。结果如下；L2/L3 不在本轮范围。

## 验证结果

Windows x64 / PowerShell 7.6.5；执行环境 Windows + WSL Ubuntu-24.04 / Linux x86_64 / bash。使用 python3、gcc、dtc、fdtget、libfdt 与 ShellCheck。以下在仓库根目录执行，退出码均为 0：

| 命令 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -p test_pps.py -v` | 17 项通过 |
| `python3 -m unittest discover -s tests -p 'test_*.py' -v` | 76 项通过，无 skipped |
| `python3 scripts/governance-docs-check.py` | 预算、链接与 ADR 通过 |
| `python3 tests/governance-docs.py` | 12 个 fixture 通过 |
| `python3 scripts/git-hooks-test.py` | 六类署名与外部 hooks 保留场景通过 |
| `python3 tests/ci-policy.py` | 6 项通过 |
| `python3 tests/bot-dispatch.py` | 22 项通过，无真实派单 |
| `python3 scripts/check-tree.py` | Python/JSON/YAML/29 个 Shell 文件及 ShellCheck error 通过 |
| `git diff --check` | 通过 |

### 旧行为反例

只在导入的 `test_pps.SOURCE` 内存字符串中改变下列行为，以原有 gcc `-Werror` 选项执行同一测试；原文件不变。三个变体均成功编译，被指定运行断言拒绝；反例核验脚本最终退出 0：

| 变体 | 测试 | 目标失败 |
| --- | --- | --- |
| health 异常时普通分支直接返回 0，省略 stop | `test_health_fault_stops_running_charge_and_fixed_contract_recovers` | C 返回 2：运行中的普通充电未停止 |
| health 异常时普通/PPS 一律返回 `-ERANGE` | 同上 | C 返回 2：普通合同被错误锁存 |
| 活动 PPS 的 expected_ua 改为未 capped 的用户目标 | `test_heartbeat_sends_new_request_and_stop_attempts_all_operations` | C 返回 7：中间停充/降载；最终值检查仍通过 |

初次心跳反例直接替换比较表达式，因 expected_ua 未使用而触发编译错误；该次不算捕获缺陷。改为只替换 expected_ua 的 capped 赋值后，确认由运行断言拒绝。

L2 内核编译、L3 真机均 not-run；本记录初验时远端 CI/CodeRabbit 为 not-run。按后续授权提交推送后，须重新核验新 HEAD；基线的远端结果不覆盖本轮改动。合并前须核验独立专项复核及新 HEAD 完整门禁。
