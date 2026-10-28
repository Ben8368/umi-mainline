# 开发环境

macOS 使用 zsh、Python ≥3.11、Node ≥20、Git、ShellCheck；只执行离线检查。Linux / WSL ext4 用于 arm64 内核交叉编译，具体要求见 [BUILD](BUILD.md)。所有文件 UTF-8 / LF，Windows PowerShell 中文输出显式 UTF-8。

轻量验证安装 PyYAML==6.0.3 后运行 python3 scripts/check-tree.py、python3 scripts/governance-docs-check.py、python3 scripts/git-hooks-test.py、python3 tests/governance-docs.py、python3 tests/ci-policy.py、python3 tests/bot-dispatch.py。不要求 Docker，不启动长期后台服务。
