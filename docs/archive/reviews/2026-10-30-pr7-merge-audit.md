# 2026-10-30：PR #7 合并前复核与修复

## 范围与授权

PR base `6527c5c80de4d00da283c7c6fc8165e5d220bbeb`；本轮增量起点 `837c7d5cb274e080b66f5ed0217d9638e8e74b1b`。用户明确授权检查、修复及按门禁合并，并另行明确授权启动只读独立审查子任务。所有改动在本地工作分支交付原 PR 分支，不操作设备、不自动合并、不扩大供电权限。

本报告记录上述起点后的修复；最终准备合并的 SHA、远端 CI 与 CodeRabbit 最终反馈链接须在 PR 正文核对。原 HEAD 的成功检查不能用于修复提交。

## 意见处置与调用链

| 来源 | 问题与影响 | 处置/证据 |
| --- | --- | --- |
| [CodeRabbit 4423023377](https://github.com/Ben8368/umi-mainline/pull/7#discussion_r4423023377) | ELF 夹具 e_type=0，验证器会接受无效类型、段范围或入口；显式 BB 可进入无法启动的 initramfs | 检查 ET_EXEC/ET_DYN、所有 PT_LOAD 文件范围、filesz<=memsz、64 位内存范围和可执行段内入口；更新两处有效夹具，增加反例 |
| [CodeRabbit 4423166025](https://github.com/Ben8368/umi-mainline/pull/7#discussion_r4423166025) | 模板相对链接填入 PR 正文后解析失效 | AI_RULES/QUALITY 改为仓库 master 的 GitHub blob 链接，保留章节锚点；发布前模板的新增章节在 master 上尚不存在，不称已上线 |
| [CodeRabbit 4423166030](https://github.com/Ben8368/umi-mainline/pull/7#discussion_r4423166030) | 三个旧行为反例缺少可复现入口 | [流程记录](2026-10-30-review-workflow.md)补齐完整内嵌 Python、精确字符串替换和运行失败断言；从文档提取命令执行成功 |
| 独立专项复核 | e_phentsize 允许大于 56，或程序头表超过 64 KiB；本地接受而固定 Linux 拒绝 exec | 对齐 [固定内核 load_elf_phdrs](https://github.com/gregkh/linux/blob/1253a6aa5d104312bf0992afacc15220ae35bdf9/fs/binfmt_elf.c#L487)，检查恰好 56 字节与 64 KiB 上限；覆盖 0/55/57/64 字节及 1170/1171 个头边界 |
| 独立专项复核 | 限充服务使用静态描述符的 pm8150b_charger，但 probe 会按 match data 注册为 pm8150b-charger；查找失败且不能停充 | 修正服务/夹具/当前文档；旧比较记录加更正。新增测试从 probe 命名格式和 match data 核对实际路径，并拒绝错误下划线设备回退；仅操作临时目录 |

BusyBox 路径：`mkinitramfs.sh` → `build-busybox.py --verify-binary` → 文件结构校验 → 暂存/打包。仅修复离线拒绝条件，不执行 AArch64 代码，不证明 applet 完整或真机可启动。

限充路径：驱动 `smb5_probe()` 覆盖 desc->name → power_supply 注册 → 用户态 Supplies 读 type/charging_enabled → Controller 请求停充 → 内核 setter/PD work。未改内核驱动、DTS、阈值或 PPS 合同参数；修复固定设备绑定，不引入自动发现或别名降级。

## 🚦 Audit Report 与验证

总体：本地 L0/L1 修复验证通过，准备推送后核验新 HEAD 远端门禁。

- 🔴 已发现的 ELF 与限充路径阻断均已修复，独立复核确认无剩余可定位源码阻断；新 HEAD 远端门禁未齐前不合并。
- 🟡 新配置效果与目标部署沿用 RISK-003/005、TD-008；本轮不关闭设备/充电安全风险。
- 验证计划及结果：下表为 Windows + WSL Ubuntu-24.04 / Linux x86_64 的离线执行，均 exit 0；内核 L2、真机 L3 与真实 BusyBox 产物核验 not-run（工作区无该二进制）。

| 命令 | 结果 |
| --- | --- |
| `python3 -m unittest discover -s tests -p 'test_*.py' -q` | 80 项通过，无 skipped |
| `python3 -m unittest discover -s tests -p test_charge_limit.py -v` | 18 项通过，含真实 probe 名称契约与错误别名拒绝 |
| 从流程记录内嵌命令提取 Python 并执行 | 三个 PPS 旧行为均由指定运行断言拒绝 |
| 导入旧 HEAD 的 verify_binary，执行新 load_ranges_and_entrypoints 测试 | 旧实现触发 11 个 ValueError-not-raised 运行断言，反例核验 exit 0 |
| `python3 scripts/governance-docs-check.py`、`python3 tests/governance-docs.py` | 通过，12 个治理 fixture 通过 |
| `python3 scripts/git-hooks-test.py` | 六类署名与外部 hooks 保留场景通过 |
| `python3 tests/ci-policy.py`、`python3 tests/bot-dispatch.py` | 6/22 项通过，不产生派单 |
| `python3 scripts/check-tree.py`、`git diff --check` | Python/JSON/YAML、ShellCheck error、29 个 Shell 文件与差异检查通过 |

首次全套检查因可靠性测试中另一处旧 ELF 夹具先触发类型拒绝而失败；修正该夹具后才取得上述 80 项通过。未将中途失败写成通过，原 cpio 失败回滚断言保留。

## 独立专项复核

审查会话 `/root/pr7_independent_review` 严格只读，于本轮最终反馈确认：上述两项独立发现均已修复，当前未发现剩余可定位源码合并阻断；最终提交 CI/CodeRabbit 仍须核验。开发者自查和 CodeRabbit 不冒充独立复核。

- 复核范围：完整 PR base 至 `837c7d5`，加本轮 ELF/限充/测试/模板和反例记录修复；报告后只更新证据与状态文档。未写入文件、提交、推送、评论或操作设备。
- 调用链：SMB5 probe/IRQ → 普通 BC1.2/PPS 更新 → 停充/降载/回退/锁存/恢复 → 属性通知与电量计卸载；SOC Controller → probe 导出名称 → setter；构建/模块导出 → 备份/发布/回滚；BusyBox 校验 → initramfs 输入。
- 审查者独立执行：WSL Ubuntu x86_64 限充 18、PPS 17、交付 21 项通过，`git diff --check` 通过。
- 既有 L2 证据抽核：本地 `out/pr7-review-fixes/build` 的八项产物 SHA 与 build-verification.json 一致；输入清单中 88 项 C/DT/patch/kernel-config 输入与当前仓库一致。本轮未重编内核，仅确认既有固定 6.18 编译证据仍覆盖未变的内核输入，不扩展为新用户态部署或 L3 验收。
- 未覆盖：L3 充电/温控/外设、跨版本完整编译与固件再分发许可风险保持开放；本报告不证明目标硬件安全或发布就绪。再次改变代码须增量复核，纯证据记录更新不改变上述代码结论。
