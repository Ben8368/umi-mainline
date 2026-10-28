# Jules 开发环境

每个工作包先核实 Linux、Python ≥3.11、Node ≥20、Git、ShellCheck。在仓库 Configuration / Initial Setup 设置 bash scripts/jules-setup.sh，运行成功后保存快照；任务开始再执行 --check 并在同一个 Shell 激活 .venv/jules/bin/activate。

脚本仅在忽略目录创建 venv，安装与 CI 一致的 PyYAML 6.0.3，运行治理和派单模拟回归。不安装系统包、不启动 Docker、不访问手机/块设备、不改 Git 全局配置、不获取密钥或固件。缺依赖先由维护者准备 VM，不把环境修复混入功能任务。

快照、App 安装、标签与 Actions success 都不等于接单或交付；严格按 [机器人约定](bot-automation.md)保存回执、diff 与实际验收。Linux 编译/真机验收不在此轻量环境承诺范围。凭据、付费和真实硬件授权不得推断。
