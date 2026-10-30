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

## TD-005：源码用户态与模块发布闭包仍需收敛（P2）

BusyBox 1.37.0 静态构建禁用救援不用且与新 libc 头文件不兼容的 tc，以及依赖 x86 的 SHA-NI 配置，保留通用哈希；这不是 rootfs 全部包的源码重建。完整 rootfs 用 iproute2，用户态编译器/libc 固定及可重现归档另行收敛。模块包仅导出到普通目录；旧 `install-modules.sh` 挂载镜像的路径仍属显式设备准备流程，本轮没有执行或据此宣称已安装。见 [BUILD](BUILD.md)。

源码 BusyBox 使用 defconfig 和静态 glibc，救援 initramfs 已超过既有体积预警线，距离硬上限余量有限（具体字节见[构建记录](archive/reviews/2026-10-29-source-parity.md)）。暂保留已通过 applet 检查的配置；后续按 init 的真实命令闭包裁剪或评估源码 musl 工具链，重新验证救援命令，不提高打包安全阈值。

`config-audit.py` 的逐项片段核对尚不识别 6.12 的 PCI_PWRCTL_PWRSEQ 与 6.18 的 PCI_PWRCTRL_PWRSEQ 是版本替代符号：同时保留两项的跨版本片段在 6.18 会因旧名缺失返回 1。实际新名为 m、模块已导出，build.sh 已有双名门禁；辅助审计不能写成全通过。后续补充版本别名验证并分别拒绝两名皆缺失、保留实际选项丢失检查，见 [充电审计](archive/reviews/2026-10-30-charging-audit.md)。

## TD-006：部分扩展驱动仅交付模块，尚未接通设备（P2）

CS35L41 I²C、SPI 红外模块先由固定主线源码编译交付；本机音频图、共享 reset、保护/校准与红外电源/极性尚未核验，因此不新增可主动探测的节点。AW8697 厂商源码与 NXP NFC 仅列候选，未把旧 Android API 或错误型号直接接入。蓝牙在 Wi-Fi DTB 接入，但 BlueZ/控制器固件及 UHID 运行验收仍依赖 rootfs。恢复这些工作以前先关闭 RISK-006 相应前置项；详见 [硬件矩阵](HARDWARE_SUPPORT.md)。

板级八路温度已接入测量接口；完整 thermal zone/冷却映射和充电闭环策略仍延后至本机读数与安全阈值核验，不能用未配策略的 hwmon 接口替代热保护。AW8697 v3 FF_RUMBLE 投稿作为后续移植候选记录，尚未引入其自动校准/功率配置路径。

## TD-007：普通 USB 枚举预算与遗留充电路径尚未接通（P1）

默认 TCPM 路径已区分 CC/PD 与 BC1.2，但 SDP 尚无 USB gadget 枚举/挂起预算通知，先限制为未取得枚举预算的 100mA；不能保证电脑 USB 下净充电。FLOAT/OCP/未知结果不提升负载。没有 TCPM phandle 的遗留分支仍无完整的普通充电安全策略，不用于默认 Wi-Fi DTB，也不作为已支持的充电模式。关闭要求：接通 USB 配置/挂起/复位事件与预算撤销，限制所有入口，并覆盖 SDP 枚举、挂起、拔插及错误注入；非 TCPM 路径须统一策略或显式退役。不得简单把 TCPM 的零预算替换为 500mA/1.5A。见 [充电审计](archive/reviews/2026-10-30-charging-audit.md)。
