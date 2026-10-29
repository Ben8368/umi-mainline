# 技术债

记录有意保留的实现妥协；外部不确定性见 [风险](RISK_REGISTER.md)。完成后移到 docs/archive/tech-debt。

## TD-001：开发调试高权限入口保留（P2）

维护者于 2026-10-28 明确排除本轮修复。保留 root 默认密码、SSH 密码登录和 USB root shell，避免改变硬件调试流程。发布镜像前另行设计 DEBUG/RELEASE 和凭据策略；本轮不收紧、不扩大。

## TD-002：遗留 ShellCheck 警告尚未逐项清理（P2）

既有脚本先采用 error 级整树门禁；不得通过禁用新增错误来过 CI。涉及变更的逻辑做功能回归，后续独立清理 warning 级告警。

## TD-003：机器人请求队列不持久化（P2）

继承 DockDSM 的仓库级 concurrency，GitHub 默认 pending 槽可能被后续请求替换。维护者逐单核对 Actions 与接单回执；取消或拒绝不会自动重试，不因标签存在而声称已接单。

## TD-004：PPS 暂使用受限 SMB5 通路（P2）

当前实现只提供显式 PPS 合同与 SMB5 主充电，电池端沿用 1.5A FCC，未移植 Android 电荷泵闭环、JEITA 标定或原厂满功率曲线。该妥协允许独立验证协议接线，不等同 25W/30W 快充；后续扩展须先解决 RISK-001/RISK-005，再实现电荷泵保护读回、看门狗服务与故障退出。控制契约见 [PPS](PPS.md)。
