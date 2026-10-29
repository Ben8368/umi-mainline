# 2026-10-29 已知问题修复与验证

基线为治理 commit 293c884（产品基线 39b6349）；宿主 macOS / arm64 / zsh。没有连接手机、刷写分区或写充电寄存器，保留开发 root/SSH/USB 权限。

## 变更

- build.sh 在日志管道之外判断 make 结果，清理并强制检查 Image.gz 与三个 DTB；关键补丁失败立即停止。
- mkimage 顺序为 build → fresh initramfs → pack。cpio/gzip 分步检查，大小门禁通过后原子替换，失败不覆盖旧 initramfs。
- 新构建默认 root none，安装 rootfs 必须显式选择；修正文档不写盘、不改电压的过度保证。
- BQ25970 节点默认禁用、主动 enable 返回 EOPNOTSUPP；拒绝关闭保护、恢复要求真实板级参数，初始化传播每次 I²C 错误。
- Type-C 回调仅更新在线状态，去掉延时自动充电。devm 对象单次清理，注销 notifier 后释放 Type-C 引用，失败路径也清理。
- DSI parser 逐个推进 token，限制字节值与容量，拒绝非法/溢出输入；充电状态读取失败返回错误，成功使用正确 STATUS 枚举。
- config-audit 对齐 DRM_MSM / ARM_PSCI_CPUIDLE，支持显式 SMMU cmdline 开关。ASCII 检查含真实 Tab，本身正确，保持原字节。

## 已运行的离线验证

python3 -m unittest discover -s tests -p 'test_*.py' -v：11 项通过，实际执行脚本片段与提取的 C 函数，不访问硬件。

- make 失败/缺 Wi-Fi DTB 不收集旧产物；成功收集全新产物。
- mkimage 顺序与 initramfs 失败阻断；cpio 失败保留旧归档并清理临时文件。
- 原始 ASCII 正则接受 Tab、拒绝 UTF-8 和控制字符。
- config 审计接受当前显示/PSCI/SMMU 契约并拒绝缺少 SMMU 参数。
- C 编译并执行实际 DSI 函数，覆盖多行、非法值、512/513 字节边界。
- C 编译并执行实际保护/ADC/初始化函数，对每个调用位置注入 I²C 失败并确认立即停止。
- C 编译并执行实际状态 getter，覆盖读取失败、充电与未充电。
- 默认隔离、无 double-unregister、notifier 释放顺序与无延迟自动启用契约。

治理、署名、CI 策略、机器人模拟和整树检查另按 [CI](../../ci.md)执行。未完成完整 Linux 内核编译、DTS 编译与真机回归；L0/L1 结果不能关闭 [RISK-001/002](../../RISK_REGISTER.md)。

额外校验：固定 Actionlint 1.7.12，从官方 release 下载并核验 SHA256 后检查全部工作流，退出 0；相同校验已接入 CI lint。
