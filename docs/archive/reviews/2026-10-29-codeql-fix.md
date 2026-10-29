# PR #2 CodeQL 工作流修复

日期：2026-10-29；宿主：macOS / arm64 / zsh。

## 失败证据与修复

- PR #2 原 HEAD：`ab81a6632cca6b7ee3ac39396e6c607c6808d8f3`。
- 常规 `CI result`、governance、lint、两个架构的 offline 均 success。
- [CodeQL 检查](https://github.com/Ben8368/umi-mainline/runs/122944621820)失败：`actions/cache-poisoning/poisonable-step`，指向 `.github/workflows/kernel.yml` 的外部 checkout 与后续编译。
- 原 `matrix.sha` 已是两个固定提交；官方查询 `ActionsSHACheckout` 的字段名启发式将包含 `sha` 的表达式视作不可信引用。本轮未发现任意 dispatch 输入流入 SHA 的证据。
- 将两个外部 checkout 的 ref 改为完整 SHA 字面量，以版本矩阵分别选择。保留原有两个内核版本、提交、手动触发、只读权限和 `persist-credentials: false`；没有关闭或抑制 CodeQL。
- 新增策略回归，约束每个版本恰好一个外部 checkout、固定来源与提交、先 checkout 后编译，并拒绝动态 ref。

参考：[CodeQL 规则说明](https://codeql.github.com/codeql-query-help/actions/actions-cache-poisoning-poisonable-step/)、[官方查询库](https://github.com/github/codeql/blob/main/actions/ql/lib/codeql/actions/security/UntrustedCheckoutQuery.qll)。

## 验证证据

以下命令退出码均为 0：

- `python3 scripts/governance-docs-check.py`
- `python3 tests/governance-docs.py`：11 个治理场景。
- `python3 scripts/git-hooks-test.py`：署名接受与拒绝场景。
- `python3 tests/ci-policy.py`：6 项策略回归。
- `python3 tests/bot-dispatch.py`：21 项模拟 API 回归，未实际派单。
- `python3 scripts/check-tree.py`：包含 ShellCheck error 级，0 错误。
- `/private/tmp/umi-actionlint/actionlint -color`：Actionlint 1.7.12，全部工作流通过。
- `python3 -m unittest discover -s tests -p 'test_*.py' -v`：11 项可靠性回归。
- `git diff --check`。

反向验证可复现（在仓库根目录执行；第一段预期退出 1，第二段预期退出 0）：

```sh
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git archive ab81a6632cca6b7ee3ac39396e6c607c6808d8f3 | tar -x -C "$tmp"
git show 733e9441ccb41643798538785517050b8046bfda:tests/ci-policy.py > "$tmp/tests/ci-policy.py"
set +e
(cd "$tmp" && python3 tests/ci-policy.py PolicyTests.test_kernel_build_uses_one_literal_pinned_checkout_per_version)
old_rc=$?
set -e
test "$old_rc" -eq 1
python3 tests/ci-policy.py PolicyTests.test_kernel_build_uses_one_literal_pinned_checkout_per_version
```

该策略回归来自 PR #2 的 `tests/ci-policy.py`：它要求 `version` 矩阵中的每个版本恰好对应一个固定 SHA 字面量的外部 checkout，并拒绝动态 `ref`。旧 HEAD `ab81a6632cca6b7ee3ac39396e6c607c6808d8f3` 使用 `include` / `matrix.sha`；测试先因矩阵结构与固定配置不符而失败。新 HEAD `733e9441ccb41643798538785517050b8046bfda` 使用按版本筛选的固定字面量，测试通过。

远端新 HEAD 的 CI / CodeQL / CodeRabbit 由推送后重新运行确认，本记录不将其计为已通过。完整 Linux 内核编译、手机启动及供电测试未运行，沿用 RISK-001/002。
