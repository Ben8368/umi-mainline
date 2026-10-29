# 测试矩阵

| 环境 | 最低验证 | 证据边界 |
| --- | --- | --- |
| macOS arm64 / zsh | 治理、署名、模拟 API、脚本与 C 纯解析回归 | 不运行 Linux init，不访问真实块设备 |
| GitHub Ubuntu x86_64 / arm64 | 相同离线门禁和语法回归 | 不证明硬件或烧录能力 |
| Linux 固定 kernel | 编译面板、触摸、供电驱动及 DTB | 保存准确基线、config、工具链和错误日志 |
| umi 原作者配置 | fastboot 临时引导、屏幕/背光/恢复、触摸、Wi-Fi、串口与救援/切根 | 每项记录镜像哈希与设备变种，授权写盘另列 |
| 供电专门验收 | 传感器、阈值、寄存器读回、错误阻断、受控负载；显式 PPS 实验按 [ADR 0005](ADR/0005-explicit-pps-bringup.md) | 未通过前不声称主动快充安全或满功率；BQ25970 仍禁用 |

结果用 passed / failed / skipped / not-run 区分。历史日志见 [TESTLOG](TESTLOG.md)，本轮记录按日期进入 archive/reviews，不覆盖原始历史。

## 6.18 追回历史能力的设备验收清单

以下是待执行的验收要求，不是完成声明。每次使用本轮镜像 SHA256、DTB 变体、真实 `uname -r` 和匹配模块包重新取证；历史观察不能替代该矩阵。本轮是否执行只见 [CONTEXT](../CONTEXT.md) 与链接记录。

| 能力 | 必须补齐的证据 |
| --- | --- |
| 救援启动 / USB / pstore | 明确 rescue root-dev=none；串口、报告盘、pstore；记录镜像和运行版本 |
| 面板 / 背光 / 恢复 | 同一面板启动亮屏、亮度、DPMS off/on、休眠恢复与长稳；不猜新供电值 |
| FTS 触摸 | 连续多点事件、短按、空闲后首触、显示休眠/恢复，区分既有短按问题 |
| GPU / 桌面 | GPU 初始化、渲染节点、Mesa Freedreno/Turnip GL/Vulkan 实际运行、Plasma 登录与恢复 |
| Wi-Fi | rootfs 匹配模块/索引/固件；PCIe 枚举、ath11k probe、关联、传输、断开/重连、休眠恢复 |
| rootfs / RTC / 通用模块 | 实际根分区另行确认并授权；新旧内核模块不混用、RTC 时间、必要 overlay/fuse 等 |
| 关机 / 充电 | 定位 6.18 软件关机回到旧镜像现象；充电依独立授权和 PPS/电荷泵安全门禁，不由启动成功推定 |
