# 设备与运行契约

目标设备 umi / M2001J2C / Qualcomm SM8250；原作者测试面板 CSOT j2_mp_42_02_0b、ST FTS。其他面板/触摸必须单独取证。

内核树由 TREE 指定，OUT 是 kbuild 输出，WS 是本适配层；默认工作流在 Linux / WSL ext4 交叉编译 arm64。macOS 只承担离线开发验证。历史文档包含 6.12.94 / 7.2.12 调试轨迹，6.18.59 为迁移目标，不声明任意新内核兼容，固定 CI 输入见 [依赖](dependency-locks.md)。

镜像契约：Image.gz + 含 __symbols__ 的设备 DTB + initramfs，Android boot header v2。Wi-Fi DTB 是默认全功能打包输入。cmdline 由 CONFIG_CMDLINE_FORCE 控制，boot 头参数不是实际覆盖入口。

fastboot boot 只描述加载镜像这一操作；initramfs 或真实 rootfs 仍可能写盘。救援模式与真实根模式必须明确区分，不以 /dev/sda34 在所有设备上的位置为保证。刷写、切根及回退见 [ARCH-ROOTFS](ARCH-ROOTFS.md)，真机操作需要具体授权。
