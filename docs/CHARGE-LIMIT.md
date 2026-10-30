# 电量区间限充与 PPS

此服务为 systemd rootfs 提供 SOC 滞回策略，默认上限 70%、下限 65%、轮询 30 秒。实现与服务文件可交付，是否完成真机验收只见 [CONTEXT](../CONTEXT.md)。它不替代 [普通充电保护](BATTERY.md)、[PPS 验收](PPS.md)或 BQ25970 安全门禁。

## 双方方案与取舍

参考仓库固定于 [misaka-link/umi-linux cf830738](https://github.com/misaka-link/umi-linux/tree/cf83073887899f485a5c606f9842c5e691ea796c)，不能把对方镜像观察当成本仓库实测。

| 层次 | umi-linux | 本仓库采用的方案 |
| --- | --- | --- |
| 底层 | Armbian `qcom_fg` / `qcom_pm8150b_charger` 及 0037 控制补丁 | 保留同源驱动及本仓库错误处理、BC1.2、ADC 换算修复 |
| SOC 策略 | Bash 服务，70% 停、65% 复充，30 秒轮询 | 吸收滞回区间，增加状态读回、失败停充、进程独占锁 |
| PD / PPS | 板级 connector 声明固定 5V/3A，没有 APDO；限充脚本不实现 PPS | 保留开源 Linux TCPM + SMB5，PPS 仍显式开启；不提高既有预算 |
| BQ25970 | 板级节点注释且 I²C 禁用；示例含关闭保护项 | 继续 disabled，不复制保护关闭项或据此启用电荷泵 |
| 测量依据 | 文档称停充时输入电流/电压归零 | 不以零读数代替独立测量；旧同源驱动会在非充电状态直接返回零 |
| 源码与部署 | 原创脚本/服务 GPL-2.0，依赖外部 Armbian 补丁 | Python 标准库 + systemd + 现有 GPL 内核驱动，不引入闭源 daemon、Android 用户态或新固件 |

原作者记录只能支持“其设备曾观察到停充”，不足以证明完整循环、PPS 功率或温控。其 37 项测试针对滞回和假 sysfs；本轮没有复跑对方测试。核对来源和具体问题见[对比记录](archive/reviews/2026-10-30-charging-comparison.md)。

## 控制契约

- `capacity >= UPPER` 请求停充；`capacity <= LOWER` 允许充电；中间区间保持本进程上一次策略。进程重启且电量在中间时，从硬件 `charging_enabled` 读回初始化，不保存持久化猜测值。
- 固定绑定本树的 `qcom-battery` 和 **`pm8150b_charger`（下划线）**，并验证 `type=Battery/USB`。不按目录顺序选择首个设备；对方文档中的连字符名字不能直接套用。
- 每轮重读状态；停充期间反复确认/重申禁止，避免 USB 插入前硬件使能为零却没有软件禁止位。读数非法或读取失败时尝试停充，恢复有效读数后须到下限才恢复许可。写入/读回失败明确报错并重试；无法确认或物理切断时软件不作保证。
- `charging_enabled=1` 只授予许可：内核 health、预算或锁存故障仍可拒绝负载。异步读回为零时报告等待，不清除 `pps_fault`。电流、电压、温控及故障退出仍归内核管理。
- 低于上限的活动 PPS 不被周期性取消。到上限写零后，现有 SMB5 退出 PPS、降载并设置 `user_inhibit`；到下限只允许普通充电，不自动重新进入 PPS。PPS 接口、APDO、续约与原有限值全部保留，再次 PPS 按 [PPS](PPS.md) 人工开启。
- 固定锁 `/run/umi-charge-limit.lock` 防止本服务重复运行；它不能约束其他 daemon 或手工 sysfs 写入。不要同时运行 `battery-charge-limit`、`umi-charge-limit` 的其他实现或其他充电策略程序。运行期间手动开启 PPS 会与上限策略冲突，最多下一轮重新停充。
- 停服务不自动恢复充电、不改 PPS；服务崩溃由 systemd 重启，重启期间不保证 SOC 上限。30 秒轮询与 SOC 更新/误差会造成过冲，不能保证“最多 1%”。不根据电量计温度猜测新的安全阈值。

## 部署与检查

需要目标 Linux rootfs 的 Python >=3.11（标准库含 `fcntl`）及 systemd；不放进 BusyBox 救援 initramfs，不随构建或启动脚本自动开启。服务启动本身会控制手机充电，以下供后续获授权的设备验收使用，本轮离线验证不得执行这些设备侧操作。

从本仓库目录安装文件（已有配置保留）：

```sh
install -d /usr/local/libexec
install -m 644 scripts/umi-charge-limit.py /usr/local/libexec/umi-charge-limit.py
install -m 644 config/umi-charge-limit.service /etc/systemd/system/umi-charge-limit.service
if [ ! -e /etc/default/umi-charge-limit ]; then
    install -m 644 config/umi-charge-limit.env /etc/default/umi-charge-limit
fi
systemctl daemon-reload
```

人工先确认其他充电控制服务已停用，再只读检查（配置由 systemd 传入；手动检查须显式加载环境）：

```sh
set -a
. /etc/default/umi-charge-limit
set +a
python3 /usr/local/libexec/umi-charge-limit.py --check
```

`--check` 不写 sysfs、不开锁、不启动循环。无参数只显示用法；只有 `--run` 才控制充电。正式服务读取 `/etc/default/umi-charge-limit`，要求 `0 <= LOWER < UPPER <= 100`、`1 <= INTERVAL <= 3600`，非法配置拒启。普通运行不设置 `UMI_CHARGE_SYSFS_ROOT/UMI_CHARGE_LOCK`，它们仅用于隔离离线测试。

完成前置检查并获得设备操作授权后，人工启用：

```sh
systemctl enable --now umi-charge-limit.service
journalctl -u umi-charge-limit.service -f
```

停用/回退策略服务：

```sh
systemctl disable --now umi-charge-limit.service
```

上述停用保留最后充电许可，避免退出时意外恢复负载。如需恢复普通充电，确认设备条件允许后人工写 `1` 到 `/sys/class/power_supply/pm8150b_charger/charging_enabled`；这不会重新请求 PPS，也不会清除内核故障。若停充失败、异常升温或无法确认状态，断开输入并排查，不能只反复重启服务。

## 验收

离线验收分别运行两组回归：

```sh
python3 -m unittest discover -s tests -p test_charge_limit.py -v
python3 -m unittest discover -s tests -p test_pps.py -v
```

覆盖上下限、区间重启、错误读写、启用异步读回、停充重试、独占、退出不复充及 PPS 接口不被用户态改写。`test_pps.py` 从驱动源码抽取 C 函数，在模拟 TCPM/I/O 桩环境中验证 setter 和控制循环；属于 L1 合成回归，不等同于内核编译或真机验收。

真机：按 [测试矩阵](test-matrix.md) 记录本轮镜像、设备、SOC、充电器与温度；验证上下限完整循环、反复拔插、服务重启/停止、读写故障、PPS 在上限前持续及到上限退出、下限普通复充且不自动 PPS。同时采集电池端净电流/SOC 趋势、PMIC 状态、保护读回和外部输入测量，不能用 `enabled=1`、`health=Good` 或输入电流为零单项验收。
