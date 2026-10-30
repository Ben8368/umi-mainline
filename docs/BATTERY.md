# 电池 / 充电（电量计 + 充电器 + 快充）

## 安全边界

已增加可显式开启的 TCPM + SMB5 PPS 主充电实验通路，目标范围、限制、PM8150B 编码修正与人工验证步骤见 [PPS](PPS.md)。它不通过 BQ25970 电荷泵，不声明已达到原厂快充功率；当前决策与状态摘要见 CONTEXT。

BQ25970 节点默认 disabled，驱动拒绝主动 enable（-EOPNOTSUPP），Type-C 通知仅报告在线状态，不再睡眠 30 秒后自动启用充电。没有以猜测值补齐采样电阻或保护阈值；主充电器 SMB5/电量计继续保留，不能据此宣称整套充电安全已验收。

即使手动启用节点，解析也要求明确的 2 或 5 mOhm 采样电阻，以及原先被注释的过流/欠流阈值；任何保护 disable 标志都拒绝。恢复读取并不代表推荐这两个值中的任何一个，必须以本机电路依据为准。初始化逐项传播 I²C 错误，配置前关闭电荷泵，保留看门狗；主动快充仍需另行实现和验收服务策略。

原复制阈值仅作历史参考，不能据其启用快充。恢复前须核实传感器、板级参数、保护中断/寄存器读回、看门狗维护与故障停止路径，按 [风险台账](RISK_REGISTER.md) 和 [测试矩阵](test-matrix.md)完成受控真机验证。该电荷泵保护链仅有离线回归，本轮未操作 BQ25970 寄存器；SMB5 实机记录仅覆盖启动与节点读回，见 [PPS 设备记录](archive/reviews/2026-10-29-pps-device-flash.md)，不构成 PPS 合同、功率或温控验收证据。

以下保留最初移植来源与操作记录，不代表本轮验收。

## 普通 USB 充电契约

默认 Wi-Fi DTB 使用 TCPM + SMB5。TCPM 的 `CURRENT_NOW` 是源允许的电流预算，不是实际测量；PM8150B Type-C 驱动没有 `get_current_limit` 回调，Rp-default/传统 USB 源可能报告 0mA，不能据此判断充电器不支持供电。接口依据见 [Linux TCPM](https://github.com/torvalds/linux/blob/v6.18/drivers/usb/typec/tcpm/tcpm.c)。

- 非 PD、TCPM 预算为零时才启用 BC1.2；重新检测后的 DCP/CDP 预算至多 1.5A，并受本地上限约束。SDP 未接入 USB 枚举预算，只允许 100mA；高负载时可能仍净放电，见 [TD-007](TECH_DEBT.md#td-007普通-usb-枚举预算与遗留充电路径尚未接通p1)。
- 未完成识别、FLOAT/OCP/未知或冲突结果不允许提升负载。PD 固定合同和明确 CC 电流优先，不能用旧 BC1.2 结果替代零电流 PD 合同；HVDCP 自动升压保持关闭。
- 插入/复位瞬间电压预算为零时停充等待，不锁存为永久协议故障。真实通信/寄存器错误仍停充并锁存；健康状态非 GOOD 按 [PPS](PPS.md) 的普通/PPS 分支处理。
- 启动、拔插与故障回退先停充，将输入限流降至 100mA。轮询结果通知电量计；拔插清理旧识别，不自动开启 PPS。
- USB_IN_I 是电压 ADC，PM8150B buck 模式按厂商 0.2V/A 转换为 µA（读数乘 5），来源是固定小米提交的 [smblib_get_prop_usb_current_now](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/db67ca6001320efc1f945c270635434fc403a9d4/drivers/power/supply/qcom/smb5-lib.c)。在线但停充/充满时仍可读输入；读取失败传播错误，不伪造 0。

上述是软件契约，不是实际充电或温控验收。输入功率不能只由 TCPM 合同相乘得到；需要同步记录电池电压/电流/SOC、温度、SMB5 状态及外部输入测量。Gen4 电池温度解码与 USB 电压 ADC 的本机对照仍须按 [RISK-001](RISK_REGISTER.md#risk-001充电参数与硬件保护尚未验收p1) 核验。

## 历史移植来源与操作记录

来源：<https://github.com/zhaoyuanwang123/armbian> 的 `sm8250-7.2` 补丁序列

| 补丁 | 内容 |
|---|---|
| 0024 | `drivers/power/supply/qcom_fg.c`（Qualcomm PMIC 电量计，gen3） |
| 0025 | qcom_fg 的 pm8150b 支持 |
| 0028 | `drivers/power/supply/qcom_pm8150b_charger.c`（SMB5 主充电器） |
| 0037 | SMB5 加充电控制 + `POWER_SUPPLY_PROP_CHARGING_ENABLED`（改 power_supply 核心） |
| 0039 / 0041 | SMB5 清理 / 编译修复 |
| 0511 | `bq25970_charger.c`（TI BQ25970 40W 快充） |
| 0044 | 板级 DT：`battery` / `pm8150b_fg` / `pm8150b_charger` / `bq25970` |

已经搬进本仓库并**编过**：

```
power/qcom_fg.c                   电量计（CONFIG_BATTERY_QCOM_FG）
power/qcom_pm8150b_charger.c      SMB5 主充电器（CONFIG_CHARGER_QCOM_SMB5）
power/bq25970_charger.c           TI 快充（CONFIG_CHARGER_BQ25970）
power/bq25970_reg.h
patches/power-supply-charging-enabled.py   给 power_supply 核心加 CHARGING_ENABLED
dts/xiaomi-umi-battery.dtsi       电池 + fg + charger + bq25970 的 DT
```

产物：`out/boot-umi-batt.img`（等上机验证）。

## 移植时改了什么

1. **power_supply 核心属性**：0037 用了 `POWER_SUPPLY_PROP_CHARGING_ENABLED`，
   6.12 没有。`patches/power-supply-charging-enabled.py` 往
   `include/linux/power_supply.h` 的枚举和 `power_supply_sysfs.c` 的属性表里
   各插一行（幂等）。
2. **`devm_power_supply_get_by_reference()` 不存在**：6.12 只有
   `devm_power_supply_get_by_phandle()`。在 `qcom_fg.c` 头部加了个 `#ifndef`
   兼容宏。
3. **DT**：
   - `battery`（`simple-battery`，4.68 Ah / 4.4 V，抄他们的近似值）；
   - `pmic@2` 下加 `pm8150b_fg: fuel-gauge@4000` 和
     `pm8150b_charger: charger@1000`（带 8 个 IRQ 名，驱动实际只用到
     `bat-ov` / `usbin-icl-change` / `wdog-bark`）；
   - `&pm8150b_vbus` 打开（500 mA..3 A）；
   - `&i2c15` 上挂 `bq25970@0x66`（`ti,bq2597x-standalone`，irq = GPIO68），
     外加 `bq2597x_master_int_default` pinctrl。
4. **config**：`CONFIG_BATTERY_QCOM_FG=y` / `CONFIG_CHARGER_QCOM_SMB5=y` /
   `CONFIG_CHARGER_BQ25970=y`，并把 `CONFIG_QCOM_SPMI_ADC5` 从 `=m` 改成
   `=y`（charger 在 probe 时就要 `usb_in_v_div_16` / `usb_in_i_uv` 两个 IIO
   通道，模块化会 EPROBE_DEFER）。

## 上机后怎么验

```sh
# 1. 驱动有没有 probe
dmesg | grep -i -e pm8150b -e qcom_fg -e bq25970 -e smb5

# 2. 设备出现没有
ls /sys/class/power_supply/          # 期望：battery / pm8150b-charger(或类似)

# 3. 读数据
cat /sys/class/power_supply/*/capacity
cat /sys/class/power_supply/*/voltage_now
cat /sys/class/power_supply/*/status
upower -d 2>/dev/null || true       # 如果装了 upower

# 4. 充电器状态（插 USB 时）
cat /sys/class/power_supply/*/online
```

## 已知风险 / 还没做

- **电量曲线是抄的近似值**（`simple-battery` + fg 内部 SOC），不是原厂 BMS
  标定；百分比可能不准，充放几轮看漂移再调。
- `bq25970` 的 IRQ 是 **GPIO68**，而 umi 的 NORTH tile 早先读不了 —— 我们
  现在按 wifi.dts 那份把 NORTH 放开了，但 68 是否可读要上机确认；
  它 probe 失败**不影响**主充电器和电量计。
- **USB-C 角色切换 / DP**（`fsa4480` mux）未移植；PPS 主充电已单独使用
  sink/device connector 接入 TCPM，保留原 DWC3 外设调试方式，见 [PPS](PPS.md)。
- 主充电器已按 battery DT 编程浮充与 FCC；原厂完整 JEITA/热降额/电荷泵曲线未接入，不可把这些限值当成温控策略，见 [TD-004](TECH_DEBT.md#td-004pps-暂使用受限-smb5-通路p2)。
