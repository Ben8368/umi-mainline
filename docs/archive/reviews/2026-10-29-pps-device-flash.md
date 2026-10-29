# PPS 实机启动与 boot 写入记录

日期：2026-10-29。用户本轮明确要求为已连接 fastboot 的设备刷入 PPS 镜像。工作分支 `codex/umi-pps-charging`；本记录形成于首次提交前，后续通过 PR 交付，不代表已合并。

## 身份、授权与回退

Windows x64 / PowerShell 7.6.5，fastboot 37.0.1；选定单台设备。读取确认 `product=umi`、`unlocked=yes`、`is-userspace=no`、`partition-size:boot=0x8000000`（128 MiB）。槽位查询不支持，因此使用已确认存在的精确分区名 `boot`，不指定或切换槽位。

bootloader 不支持 `fetch`；未因获取备份失败直接写盘。先 `fastboot boot` 临时引导 root=none 救援镜像，通过 USB CDC-ACM 读取 sysfs，确认 `/sys/class/block/sde50/uevent` 的 `PARTNAME=boot`、大小 262144 个 512-byte 扇区，并只读计算整个 `/dev/sde50` 的 SHA256。

设备原 boot 的完整 SHA256 为 `71acc2eb62b74d47da4d7ea856b21075073d8f767c6e74ae5780446a2b6fef6d`，与本地已存在的 134217728-byte umi 镜像一致；复制到忽略目录 `out/boot-before-pps-20261029.img` 并重新校验。该文件是与真机当前 boot 的长度和全分区哈希匹配的回退文件，不把另一个未知版本的固件当作当前备份。原镜像和长串口日志均不提交。

恢复入口（人工确认设备回到 fastboot 后）：`fastboot -s <本机序列号> flash boot out/boot-before-pps-20261029.img`，成功后正常重启。测试镜像只进入救援环境，不选择 userdata/rootfs；本轮未授权也未操作其他分区。

## 实机发现与修复

1. 初始镜像 SHA256 `1dfe45bdc91165c6e15f223424d1f9137139e352383ed4cf8e3ca37aa3bead2f` 成功临时启动 Linux 6.12.94，USB 串口可用，`root-dev=none`。PPS 节点缺失；Type-C 等待未加载的 VBUS provider，SMB5/电量计随之 deferred。
2. 原有效配置 `CONFIG_REGULATOR_QCOM_USB_VBUS=m`；救援镜像没有模块加载器。改为内建 `y`，并在 build.sh 与 config-audit.py 强制校验 TCPM、PMIC Type-C、VBUS provider 为内建；新增回归拒绝 provider=m/n。清理 config/umi.config 中一行 GBK 历史注释为 UTF-8，不改变该注释对应的配置值。
3. 修复后 Type-C power_supply 成功注册，SMB5 报 `-EINVAL: Couldn't get usb_in_v_div_16 IIO channel`。补充 PM8150B ADC 的 USB_IN_I（0x07）、USB_IN_V_16（0x08）子节点。编号及缩放沿用目标内核 `qcom-spmi-adc5.c` 和 dt-bindings，不增加猜测的电阻/温控/校准参数。
4. 再次临时启动后 PPS 节点出现，`enabled=0 active=0 fault=0 error=0`，health 为 `Good`。只读检查发现 `max_ua=1450016`：Linux `round_down()` 只能按 2 的幂舍入，50mA 步长必须使用 `rounddown()`。首轮测试替身曾把前者近似定义为除法，掩盖了错误；改为真实位运算语义后 3 项回归失败，修复驱动 4 处调用后全部 18 项通过。添加精确 1500000uA 上限断言，既有目标限值未扩大。

🚦 Audit Report：不新增板级限值，修复救援依赖、ADC 通道与电流舍入；完整充电安全与 PPS 实际合同仍需独立验收。18 项离线回归及脚本检查通过；完整目标内核与最终 DTB 重建、root=none initramfs 打包及 boot payload 核对通过。持久写入前已确认主充电器/PPS 节点。

## 最终镜像与执行结果

- ADC 通道修复后的中间测试镜像：SHA256 `e346d816ffd00270126adc3457e345eb11b11a7d10b8a680cc2f889a36aac6eb`；临时启动和 PPS 节点可见性已确认，但有上述电流舍入问题，没有持久写入。
- 最终舍入修复镜像 `out/boot-umi-pps.img`：16,322,560 bytes，SHA256 `66c52d9a787d43d916a003dc385c6158d8a8a8eab326eb43575d0a5bb7a4a520`。
- 最终内核 Image.gz：SHA256 `f39cd19e0fa6ea719cf3cd68688890aaab9baf01414d589361ec013983a70b1f`；Wi-Fi DTB：`4aabb73790d51389d5c48416ef09dd3643a4eed9d8029307de0db9dd3b314c9a`。
- `fastboot -s <本机序列号> flash boot out/boot-umi-pps.img`：exit 0，Sending / Writing 均 OKAY。随后按设备启动约定 `fastboot boot` 同一镜像：exit 0，Sending / Booting 均 OKAY。只写 boot，没有写 userdata/dtbo/vbmeta 或其他分区。
- 最终启动读回：USB CDC-ACM 为 COM4；`uname -r=6.12.94-umi-dirty`，`root-dev=none`。PPS 节点 `enabled=0 active=0 fault=0 error=0 inhibited=0`，`max_ua=1500000`，health=`Good`。
- 电脑 USB 连接下 `online=1 contract_uv=5000000 contract_ua=0`，`charging_enabled=0`；这不是活动 PPS 合同，也不代表实测可充电。本轮未人工开启充电，不将缺少有效电流合同时的停充改为强制取电。
- 持久写入校验：再次从 sysfs 的 PARTNAME=boot 定位 `/dev/sde50`，只读其前 3985 个 4096-byte 块（恰为镜像长度），SHA256 为 `66c52d9a787d43d916a003dc385c6158d8a8a8eab326eb43575d0a5bb7a4a520`，与主机镜像逐长度匹配。
- PPS APDO 合同/外置测试仪/温控/持续功率：not-run；本轮不主动写 pps_enable 或请求电压/电流。

最终检查：18 项离线回归通过；ShellCheck error 级/文本检查通过；C/DTS checkpatch 842 lines、0 errors、0 warnings；治理预算/链接与治理回归、git diff --check 通过。原始刷写、串口和读回输出保存在忽略目录 out，不把长日志提交。
