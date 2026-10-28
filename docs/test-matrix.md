# 测试矩阵

| 环境 | 最低验证 | 证据边界 |
| --- | --- | --- |
| macOS arm64 / zsh | 治理、署名、模拟 API、脚本与 C 纯解析回归 | 不运行 Linux init，不访问真实块设备 |
| GitHub Ubuntu x86_64 / arm64 | 相同离线门禁和语法回归 | 不证明硬件或烧录能力 |
| Linux 固定 kernel | 编译面板、触摸、供电驱动及 DTB | 保存准确基线、config、工具链和错误日志 |
| umi 原作者配置 | fastboot 临时引导、屏幕/背光/恢复、触摸、Wi-Fi、串口与救援/切根 | 每项记录镜像哈希与设备变种，授权写盘另列 |
| 供电专门验收 | 传感器、阈值、寄存器读回、错误阻断、受控负载 | 未通过前不启用或声称主动快充安全 |

结果用 passed / failed / skipped / not-run 区分。历史日志见 [TESTLOG](TESTLOG.md)，本轮记录按日期进入 archive/reviews，不覆盖原始历史。
