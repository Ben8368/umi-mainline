# 2026-10-30 PR #7 已知意见修复

## 范围

基线为 PR [#7](https://github.com/Ben8368/umi-mainline/pull/7) 的 `309ea0be85e8e4c07f8d32fda845f505859c9a7e`。该 HEAD 的 CI result 为 success，CodeRabbit 已对同一 HEAD 发布[最终反馈](https://github.com/Ben8368/umi-mainline/pull/7#pullrequestreview-5707709460)，仍有三条未解决行内意见及一条正文意见。本轮仅本地修复，分支 `codex/charging-policy-and-pps`；已有 SOC 限充改动保留，未提交、推送、编辑远端讨论或合并。

## 修复

- `mkinitramfs.sh` 将空 `BB` 与未设置一致处理，默认程序缺失时允许源码构建；显式非空且无效的程序仍拒绝。
- `CONTEXT` 的测温记录按所链接审计修正为 38 项，不把其他轮次的测试归入该记录；RISK-002 更新当前 1372 模块并链接对应构建证据，历史 1363 模块记录保留。
- SMB5 在 `pd_lock` 内通过实际属性 getter 采样 STATUS、HEALTH、CURRENT_NOW、VOLTAGE_NOW、ONLINE、USB_TYPE、CURRENT_MAX 和 CHARGING_ENABLED。只在首次有效快照、可变属性变化、采样失败或策略错误时通知。采样失败使快照失效，不提交部分缓存；完整恢复后再次通知。IRQ 通知及原充电限流/故障策略保留。
- 两个 CI offline 架构均安装并检查 gcc、dtc、fdtget 与可加载的 libfdt，避免已观察到的 amd64 测温 DT/真实 overlay 两项跳过。保留本地缺依赖时的显式 skipped，未将其冒充 passed。
- 模块归档用 tar filter 将每个成员的 uid/gid 设为 0、uname/gname 设为 root，目录结构和原子发布保持原契约。

## 🚦 Audit Report

总体：六项已知意见均有本地修改和对应验证；源码、L1 合成、L2 构建与 L3 证据分开。

🔴：修复尚未提交/推送，远端 CI 与 CodeRabbit 未覆盖本轮工作区，不能据旧 HEAD 成功结果合并。普通充电保护、净电流、温升及 PPS 真机验收仍缺失，不声明日用充电安全或原厂快充可用。

🟡：RISK-001/002/005 和 TD-004/005/007 保持开放；辅助配置审计的跨版本符号别名问题未在本轮扩大修复。硬件限制见原台账。

验证计划：完成下述本地门禁及固定 6.18 编译；取得提交/推送授权后，核验新 HEAD 的 CI result、CodeRabbit 最终反馈并逐项同步讨论。手机测试仍须本轮明确授权和回退方案。

## 本地验证

宿主 Windows x64 / PowerShell 7.6.5；测试和编译为 WSL umi / Alpine Linux 3.24.3 / x86_64，Shell 为 sh。日志、核验脚本、输入清单和产物仅留忽略目录 `out/pr7-review-fixes/`。

| 命令/检查 | 结果与覆盖 |
| --- | --- |
| `python3 -m unittest discover -s tests -p 'test_*.py' -v` | exit 0，64 项 passed，无 skipped，包含限充、真实 C 故障注入、可靠性及两项 DT 回归 |
| `python3 -m unittest discover -s tests -p test_pps.py -v` | exit 0，16 项；逐一改变八个属性、相同采样去重、各采样失败/恢复、不提交部分缓存、策略故障与 teardown；补加公开属性覆盖断言后再次通过 |
| `python3 -m unittest discover -s tests -p test_delivery.py -v` | 非 root uid/gid 65534，exit 0，12 项；验证非 root 构建的归档仍全部 root 所有，覆盖空/未设置/无效 BB |
| `python3 scripts/governance-docs-check.py`、`python3 tests/governance-docs.py` | exit 0，预算、链接及治理回归通过 |
| `python3 scripts/git-hooks-test.py`、`python3 tests/ci-policy.py`、`python3 tests/bot-dispatch.py` | exit 0，署名、6 项 CI 策略、22 项机器人策略通过 |
| `python3 scripts/check-tree.py`、`actionlint -color`、`git diff --check` | exit 0，包含 ShellCheck error 级、语法和 workflow 检查 |
| CI 依赖预检 | 实际 workflow 脚本通过 bash 语法及本地已安装依赖检查；分别移除 gcc/dtc/fdtget 或模拟 libfdt 缺失均非零退出。未在 Alpine 执行 Ubuntu apt 安装步骤，远端双架构执行待推送 |
| `git diff -- power/qcom_pm8150b_charger.c` 输入 `checkpatch.pl --no-tree -` | exit 0，81 lines，0 errors、0 warnings |

## L2 构建

固定 Linux 6.18.59 / `1253a6aa5d104312bf0992afacc15220ae35bdf9`，GCC aarch64-none-elf 16.1.0：

```sh
WS=/root/umi-pr7-review-work TREE=/root/linux-6.18.59 \
  OUT=/root/linux-6.18.59/out-hardware JOBS=12 TC=gcc sh scripts/build.sh
python3 out/pr7-review-fixes/verify-build.py
```

均 exit 0。使用独立 ext4 工作区、复用既有增量对象，不称 clean build。重新生成 Image.gz/三个 DTB，完成 modules 目标和 1372 模块导出。保留既有 FTS/DTC 警告，不称完整构建零 warning。

核验 134 个实际构建输入与 Windows 工作区逐字节一致，修改后的 SMB5 与内核树副本一致；独立验证 ARM64 magic、版本、配置/内核/归档哈希、模块索引及每个成员 root 所有权。三个 DTB 均检查 BQ25970 禁用，Wi-Fi 变体的 TCPM/充电接线、ADC 通道及 1.5A 预算保持。

| 产物 | SHA256 |
| --- | --- |
| Image.gz | `76ebd25fc8c8e93f606c3a719c312a4c6b65c9e10201e6a5ff3ceba30ff07d45` |
| modules-6.18.59-umi-dirty.tar.gz | `9779ccdf03694b0abc304007d817e4ce26e21767068dd4da586a5323a864be8e` |

三个 DTB 与[上轮充电构建](2026-10-30-charging-audit.md)字节一致；完整哈希清单留本地 `build/build-verification.json`。本轮未创建 boot 镜像，6.12/7.2 编译、远端新代码检查及全部 L3 均 not-run。
