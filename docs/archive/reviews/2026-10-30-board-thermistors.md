# 2026-10-30 板级温度接入与马达候选审查

## 范围与依据

延续硬件可用性目标，上一轮实际补齐蓝牙和模块交付属于 progress，本轮以工作区及产物为准继续查缺。分支仍为 codex/umi-hardware-enablement，未提交、推送、合并或操作手机。Windows x64 / PowerShell 7.6.5；构建使用 umi WSL x86_64 的 ext4。

查阅固定 MiCode/kernel_devicetree 提交 2aa073826fa357cc672c1e0f590d9dbe904203b0 的 qcom/umi-sm8250.dtsi：PM8150 的 XO、THM1、THM2，PM8150B 的 THM1、THM3，以及 PM8150L 的 THM1、THM2、THM3 均有 board label、ratiometric、1:1 pre-scaling 和 200us hw-settle-time。厂商头文件 ADC_*_PU2 的 0x4c–0x4f 编号与固定主线 ADC5_*_100K_PU 对应；不是从别的机型猜电阻/传感器值。

固定 Linux 6.18.59 / 1253a6aa5d104312bf0992afacc15220ae35bdf9 的 drivers/iio/adc/qcom-spmi-adc5.c 已有上述通道温度类型及转换表，并解析这三项采样配置。原 PMIC include 只实例化参考电压/芯片温度，板级通道未实例化；原配置也没有 SENSORS_IIO_HWMON。缺的是板级接入，不需要另写闭源 ADC 驱动。

## 实施

- 新增 dts/xiaomi-umi-thermistors.dtsi 并从 common include 引用，三个 DTB 均得到八路通道和 board-thermistors IIO→hwmon 消费者。
- QCOM_SPMI_ADC5、HWMON、SENSORS_IIO_HWMON 内建；build.sh 和 config-audit.py 检查内建依赖。无需新模块、固件或用户态守护程序即可在驱动绑定后读取 hwmon 温度。
- 完整构建和 DTB 快编同步新 include，缺文件拒绝复用内核树旧副本。
- 新回归用真实 include 编译 DTB，独立按厂商数字通道检查八个 consumer 的 phandle/provider/channel/label 和采样参数；配置故障注入验证 =m/=n 都无法充当救援的内建依赖。
- 没有复制厂商 user_space governor 的 125000m°C passive trip，也没有增加充电/降频/关机阈值。温度可读不证明温控策略完整或传感器位置/精度已验收。

## AW8697 候选

额外审阅 2026-10-13 的 [AW8697 v3 投稿](https://lkml.iu.edu/hypermail/linux/kernel/2610.1/12414.html)，消息 ID 20261013-mainlining-v3-2-fca981f62b57@proton.me。它提供 FF_RUMBLE，并在 probe 中调用 aw8697_f0_calibrate()；失败时 dev_warn 后仍注册 input。hw_init 还调整电机保护位及模拟限流字段，IRQ 对故障只打印日志。不能仅因为 F0=1700 与本机 DTS 一致，就把其功率/校准路径视为本机已验证。

该候选目前只存本地 out/hardware-audit/haptics/ 供审查；没有并入驱动或启用设备节点。归档 HTML 的 SHA256 为 6c34c629561cb1b77b4302bc8fd921e04e14164c3dd3e452c98d4a848caeb77e。网页邮件地址被归档服务脱敏，若后续引入必须取得原始补丁并保留完整版权/出处。没有声称该投稿已经合入固定内核或是最终版本。仍需解决故障停机、校准失败策略、并发/卸载生命周期，并结合本机电路和标定进行受控验证。

## 🚦 Audit Report

总体：补齐有本机来源的上游测温接入，运行依赖内建；不修改供电值。

🔴：没有 L3 温度读数、故障注入或外部测温对照；不能关闭热保护、充电安全或整机硬件可用性目标。马达候选未达到默认启用条件。

🟡：RISK-006、TD-006 继续记录板级温度校验与保护策略，以及马达候选接入前置条件。RISK-005 的旧“本轮授权”措辞更正为历史授权，避免误延伸设备操作权限。

## 验证

```sh
cd /root/umi-hardware-work
python3 -m unittest discover -s tests -p 'test_*.py' -v
TREE=/root/linux-6.18.59 OUT=/root/linux-6.18.59/out-hardware JOBS=12 TC=gcc sh scripts/build.sh
BUILD=/tmp/umi-thermistors-initramfs sh scripts/mkinitramfs.sh --root none
python3 tools/pack-umi.py --dtb out/sm8250-xiaomi-umi-wifi.dtb -o out/boot-umi-thermistors.img
python3 /mnt/c/umi-mainline/out/hardware-audit/thermistors/verify-delivery.py
```

上述均 exit 0，38 项回归全部通过，无 skipped。完整构建继续复用增量对象，重新生成 Image.gz/三个 DTB/模块，不称 clean build。最终导出 1372 模块；新 hwmon 在内核中，模块数未增加。保留已有 FTS/DTC 警告，不声称零 warning。

独立核验实际三个 DTB：每个八路 IIO consumer 均指向正确 PMIC SID 0/2/4、ADC 节点及 channel@4c..4f；provider/祖先启用、label、ratiometric、1:1 和 200us 均匹配。蓝牙串口/supply/GPIO、SPMI 防重复别名和 BQ25970 禁用门禁仍通过。模块包/索引、内核/配置哈希、boot v2 内容、ARM64 magic、init、已核验来源的 BusyBox 和 root-dev=none 亦通过。

172 个构建输入与 Windows 工作区逐字节一致。产物和本地核验脚本/JSON/日志位于 out/hardware-audit/thermistors/，保留上一轮 out/hardware-audit/ 产物作对照；不会将长日志、镜像、模块包或厂商材料提交。

文档预算/链接、治理回归、署名钩子、CI 策略 6 项、机器人策略 22 项、scripts/check-tree.py 和 git diff --check 均 exit 0；文本检查 288 路径、28 Shell 文件、0 errors。

6.12/7.2 完整矩阵、全量 DT schema、远端 CI/CodeRabbit 及真机测试 not-run。ADC 通道和 hwmon 源码存在、编译成功，都不能替代毫摄氏度读数/物理位置/校准和闭环保护验收。

| 最终产物 | 字节数 | SHA256 |
| --- | ---: | --- |
| `Image.gz` | 16,279,772 | `78eb519fcf71fe09184e8482e77c35547c23b0279317b3b2d3251363c501e818` |
| `sm8250-xiaomi-umi.dtb` | 193,736 | `e0d32b0787f39334baaa8a794abbdc0701d90b13154ba4fac7f2ebb0253be648` |
| `sm8250-xiaomi-umi-plus.dtb` | 189,774 | `56d1e3057f7f0fb28fbf168eff0cfe26042591d04b5a66149b2e0a1a0b83b820` |
| `sm8250-xiaomi-umi-wifi.dtb` | 196,508 | `08dc25ddd2fd5a3d1ecf6eedd4bef8c0bf1d907caed6328a63a646801bcbc489` |
| `initramfs.cpio.gz` | 1,290,083 | `0d4e5395f9bdb1757a2842f212d9606388d171901732f3c8df07abd094d129cf` |
| `boot-umi-thermistors.img` | 17,772,544 | `4d65c5942b6bd8da56963067278692c2cd061b3e06fd5206c1b0eda6ab9c523a` |
| `modules-6.18.59-umi-dirty.tar.gz` | 18,442,135 | `4da85d58bb68db41e58069655e2c83093aea1bcdc997736a824bd67308699752` |
