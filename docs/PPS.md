# 小米 10 PPS 主充电通路

状态与本轮验证结果见 [CONTEXT](../CONTEXT.md) 和[移植记录](archive/reviews/2026-10-29-pps-port.md)。本实现是 Linux TCPM + PM8150B SMB5 的实验性主充电通路，不是 BQ25970 电荷泵快充，也不声明已达到 25W/30W。

## 来源与范围

- 小米官方 `umi-q-oss`，固定提交 [db67ca6001320efc1f945c270635434fc403a9d4](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/db67ca6001320efc1f945c270635434fc403a9d4)：`drivers/usb/pd/policy_engine.c`、`drivers/power/supply/ti/pd_policy_manager.c` 证明原机有 PPS/APDO 与未认证适配器处理流程。
- 同一提交的 `drivers/power/supply/qcom/smb5-reg.h`、`smb5-lib.c` 提供连续输入电压 allowance 与软件 ICL 控制定义；`qpnp-smb5.c:smb5_pm8150b_params` 提供浮充电压 3.6V 基值/10mV 步长及 FCC 50mA 步长。原驱动继承的 PMI8998 浮充编码已修正。
- SMB5 的四个 IRQ 按该提交 `smb5-lib.h:enum smb_irq_index` 与 peripheral 基地址修正：BATIF 0x12/bit2（bat-ov）、USBIN 0x13/bit4（plugin）、USBIN 0x13/bit7（ICL）、MISC 0x16/bit1（watchdog bark）。原 DT 顺序占位会把 ICL 等事件错当拔插，导致 PPS 自行取消。
- PD 报文、APDO 选择和合同接受由 Linux 6.12.94 `drivers/usb/typec/tcpm/tcpm.c` 处理；本驱动通过其 power_supply ABI 发出请求，没有复制 Android 的认证绕过逻辑。原驱动与原贡献者归属保留。

## 控制边界

Type-C connector 与 SMB5 节点一起放在电池 include 中，只对包含该文件的 Wi-Fi 全功能 DTB 生效，避免在没有本地限流驱动的基础 DTB 上启用 PD 协商。connector 配置为 sink/device，不接入 USB role-switch；保持当前 DWC3 外设调试接线。固定 PDO 只声明 5V/1.5A，PPS 声明 5–9V/1.5A，工作功率需求 2.5W。1.5A 沿用已有 battery DT 的电流预算，作为本轮受限 bring-up 上限，不代表重新核定板级能力。

默认关闭 PPS，请求初值为 5V/0.5A；需人工写 `pps_enable=1`。目标电压限定 5–9V、20mV 步长，目标输入电流限定 0.5–1.5A、50mA 步长，并受 battery DT 与实际源合同进一步限制。电池端 FCC 也明确编程为 DT 现有 1.5A；输入 9V×1.5A 不能等同电池充电功率。

SMB5 用 TCPM 合同限制输入，PD/PPS 时关闭 APSD，HVDCP 自动升压保持关闭，不再改 TCPM 所有的 CC/VCONN 配置。普通非 PD 的零 CC 预算由独立 [BC1.2 路径](BATTERY.md#普通-usb-充电契约)处理，不能替代 PD 合同。进入 PPS 或改变工作点前先停充、降输入限流至 100mA；允许连续输入电压后才请求 PPS，接受并读回 `online=2`、电压、电流且硬件 health 为 GOOD 后才增加负载。每秒重新请求，维护 PPS 合同。通信/协议错误、health 读取错误、活动 PPS 期间 health 非 GOOD 或寄存器错误均停止充电、尝试退回固定合同并锁存故障；PPS 未启用时，固定合同路径遇到 health 非 GOOD 会停止充电但不锁存，health 恢复 GOOD 后自动恢复固定合同充电。普通路径的零电压预算视为协商等待，保持停充，不锁存。拔线和休眠取消 PPS 使能，恢复后不自动重新进入 PPS。休眠先停负载并退出 PPS，失败则阻止本次休眠。

保护状态读取失败不视为健康；过压、安全定时器、电池端缺失、过冷/过热及软温限均拒绝本实验通路。未新增猜测的热阈值或电荷泵参数，仍依赖现有 PMIC 保护配置，不能据此声称整套供电安全已验收。BQ25970 继续 disabled；缺少本机采样电阻和保护参数时仍拒绝主动电荷泵快充。

## 人工测试

可选 [SOC 限充服务](CHARGE-LIMIT.md)保留本 PPS 通路：到电量上限会停充并退出 PPS，下限仅恢复普通充电许可，不自动重启 PPS；运行期间不要叠加其他策略写入者。专门验证 PPS 时先明确是否启用 SOC 策略及测试电量区间。

救援内核需内建 `CONFIG_REGULATOR_QCOM_USB_VBUS=y`，并实例化 PM8150B ADC 的 USB_IN_I/USB_IN_V_16 通道；否则 Type-C deferred 或 SMB5 因 IIO 通道缺失拒绝绑定。实机修复与 boot 回退文件见[设备记录](archive/reviews/2026-10-29-pps-device-flash.md)。

只在 umi 上使用。镜像默认救援模式 `ROOTDEV=none`，不会自动选择真实根分区。临时引导加载到 RAM，退出测试后重启返回原安装系统；不需要刷写分区。PPS 充电器占用 USB 口，先准备独立串口或自行配置的无线 shell；救援镜像不保证现成 Wi-Fi SSH。不要在尚无控制通道时拔掉 USB 控制线。

主机临时引导（由人工执行）：

```powershell
fastboot boot out/boot-umi-pps.img
```

在手机主线 Linux 的 root shell 中检查接口，缺失或驱动报错时停止并保留日志：

```sh
P=/sys/class/power_supply/pm8150b-charger/device
cat "$P/pps_status"
cat /sys/class/power_supply/pm8150b-charger/health
cat /sys/class/power_supply/pm8150b-charger/charging_enabled
dmesg | grep -i -e typec -e tcpm -e pm8150b -e pps
```

接入带 PPS APDO 的充电器后，先使用初始的 5V/0.5A 档。以下写入是人工测试动作，构建和开机均不执行：

```sh
echo 5000000 > "$P/pps_voltage_uv"
echo 500000 > "$P/pps_current_ua"
echo 1 > "$P/pps_enable"
cat "$P/pps_status"
```

`enabled=1` 仅表示请求开启；只有 `active=1 fault=0 error=0 online=2`，且合同电压/电流符合请求，才是内核确认的活动 PPS 合同。应同时用支持 PD 报文的测试仪核验 PPS Request/APDO 与实际输入，不能只看充电动画或 `usb_type=PD_PPS`（该值也可能只表示源支持 PPS）。

初档检查无异常后，可人工测试更高电压或电流，例如先改 9V/0.5A，再按需提高电流。每次更改后均检查合同、温度、实际输入与 PMIC health；不要直接以最高档开始。适配器不满足目标电压或拒绝请求时预期锁存错误，不保证自动选择另一个 APDO。

```sh
echo 9000000 > "$P/pps_voltage_uv"
cat "$P/pps_status"
# 前一档检查完成后才进行下一步
echo 1000000 > "$P/pps_current_ua"
cat "$P/pps_status"
```

退出 PPS、退回固定 5V 普通充电：

```sh
echo 0 > "$P/pps_enable"
cat "$P/pps_status"
```

需要停止主充电时：

```sh
echo 0 > /sys/class/power_supply/pm8150b-charger/charging_enabled
```

错误会保留在 `pps_status` 的 error 中；不要连续盲目重试。保存错误和测试仪记录，先排除条件，随后显式 `pps_enable=0` 清理，再重新请求。写入返回错误时不得当成成功。回退写入也可能因 I/O 故障失败，此时拔掉充电器并重启；驱动不声称软件能保证物理切断。

验收至少覆盖：启动与 USB 调试、固定 PDO/非 PPS 源、5V PPS、9V PPS、持续超过 30 秒、适配器拒绝、拔插、人工停充、休眠恢复、重启。不要人为制造电池过压/过热，相关错误先由离线注入覆盖。记录设备变种、镜像 SHA256、充电器 APDO、线材、SOC、温度、合同与实测输入。禁止用原厂系统测试替代本镜像测试。
