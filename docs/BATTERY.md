# 电池 / 充电（电量计 + 充电器 + 快充）

## 当前安全边界（2026-10-29）

BQ25970 节点默认 disabled，驱动拒绝主动 enable（-EOPNOTSUPP），Type-C 通知仅报告在线状态，不再睡眠 30 秒后自动启用充电。没有以猜测值补齐采样电阻或保护阈值；主充电器 SMB5/电量计继续保留，不能据此宣称整套充电安全已验收。

即使手动启用节点，解析也要求明确的 2 或 5 mOhm 采样电阻，以及原先被注释的过流/欠流阈值；任何保护 disable 标志都拒绝。恢复读取并不代表推荐这两个值中的任何一个，必须以本机电路依据为准。初始化逐项传播 I²C 错误，配置前关闭电荷泵，保留看门狗；主动快充仍需另行实现和验收服务策略。

原复制阈值仅作历史参考，不能据其启用快充。恢复前须核实传感器、板级参数、保护中断/寄存器读回、看门狗维护与故障停止路径，按 [风险台账](RISK_REGISTER.md) 和 [测试矩阵](test-matrix.md)完成受控真机验证。当前只有离线回归，未写手机寄存器。

以下保留最初移植来源与操作记录，不代表本轮验收。

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
- **USB-C 角色切换 / PD**（`pm8150b_typec`、`fsa4480` mux）没搬 —— 原厂 DT 里
  还有一整套 typec/DP 接线，等需要 OTG/PD 再说。
- 充电限流/温控策略（`qcom,fcc-max-ua` 之类）没配，默认值由驱动决定。
