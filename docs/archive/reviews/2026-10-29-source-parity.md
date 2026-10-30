# 6.18 源码优先与交付补齐记录

日期：2026-10-29 至 2026-10-30。适配层基线 `6527c5c`（已合并 PR #6），工作分支 `codex/umi-6.18-open-source-parity`；本轮未提交、推送、刷写或操作手机。本记录区分继承证据、源码审查、合成回归和实际构建。

## 修改范围

- 共用 `config/kernel.env` 固定默认 Linux 6.18.59，保留显式 `TREE=` 兼容输入；准备脚本校验 SHA，拒绝覆盖错误版本或非 Git 目录。
- 补齐 DTB 快编的 Wi-Fi、电池与 SPMI 去重 include；默认编译三个变体，缺源码拒绝复用树内旧副本。Wi-Fi DTS 只改说明，不改板级供电值或引脚。
- 内核构建包含 modules，导出同 release 的完整模块包和 depmod 索引；失败不收集新内核产物，不挂载 rootfs、不删旧版模块。
- BusyBox 改为校验官方固定源包后交叉编译静态 arm64 ELF；显式 BB 可选预编译文件，不静默回退。源码、配置、编译器和二进制哈希保存在本地产物旁。
- 逐项[源码清单](../../OPEN_SOURCE.md)和[固件哈希](../../../firmware/manifest.json)区分开放驱动与不透明固件，含禁用的触摸固件 C 数组；既有原贡献者和许可文字保留。
- 6.18 固定 SHA 加入手动 Kernel compile CI；尚未触发远端工作流。

## 环境与输入

- 宿主：Windows x64 / PowerShell 7.6.5；所有文件 UTF-8 / LF。
- 内核：WSL umi / Alpine 3.24.3 / x86_64 / POSIX sh；源码 `/root/linux-6.18.59`，HEAD `1253a6aa5d104312bf0992afacc15220ae35bdf9`。沿用已核验源码树并同步本仓库适配层，独立全新输出 `/root/linux-6.18.59/out-source-parity`，未复用旧 Image/DTB/模块。
- 适配层构建工作区 `/root/umi-6.18-open-source-work`，JOBS=12，aarch64-none-elf GCC 16.1.0；kmod 34.2 提供模块索引。
- BusyBox：WSL Ubuntu 24.04，aarch64-linux-gnu GCC 13.3.0 + 静态 glibc；官方 1.37.0 源码 SHA256 `3311dff32e746499f4df0d5df04d7eb396382d7e108bb9250e7b519b837043a4`，与官方摘要相符。

## 验证过程与结果

已完成的离线命令（均 exit 0）：

- `python3 -m unittest discover -s tests -p 'test_*.py' -v`：35 项通过，包括既有内核/供电回归、交付/来源回归和固件拒绝路径。
- `python3 scripts/governance-docs-check.py`、`python3 tests/governance-docs.py`、`python3 scripts/git-hooks-test.py`、`python3 tests/ci-policy.py`、`python3 tests/bot-dispatch.py`：通过。
- `python3 scripts/check-firmware.py`、`python3 scripts/check-tree.py`、`actionlint`、`git diff --check`：通过。
- 官方 `git ls-remote` 再核对 v6.18.59 标签对象 `16d7cd88b5357b25076bceaa37f011b79f4939d0` 与 peeled commit `1253a6aa5d104312bf0992afacc15220ae35bdf9`，符合 `config/kernel.env`。
- 独立副本中执行 `scripts/dtb-only.sh`：三个 DTB 编译通过，各含 8 个 disabled SPMI 别名；符号数 base 818 / plus 813 / wifi 825，Wi-Fi 供电属性存在且 BQ25970 节点禁用（base/plus 无此节点）。保留上游重复 unit-address 等既有 DTC 警告，不宣称零警告或真机效果。
- `python3 scripts/build-busybox.py --jobs 4 --output .../busybox.static`：第三次构建通过。QEMU user 验证 402 个 applet 可枚举、15 个必要 applet 存在，`sh -n initramfs/init`、shell 算术、SHA256 与 gzip roundtrip 通过；没有运行 init、mount、poweroff 等设备动作。
- 源码 BusyBox 的救援 initramfs 打包通过，`root-dev=none`；压缩后 1,290,075 B，小于既有硬上限 1,382,400 B，但超过 1,126,400 B 预警线（约 93.3% 硬上限），没有提高安全阈值。

### 2026-10-30 最终源码验证

首次全量 `Image.gz dtbs modules` 编译与导出完成，但外层旧 WSL 命令的退出码转发不可靠。后续通过 Python `subprocess.run` 保存真实退出码；最终核对发现构建副本尚缺默认版本入口、固件校验等后续修改，已同步后再完整运行同一构建入口。最终 `out/final-build.exit` 为 `0`，不是从日志末尾或旧产物推断。171 个脚本、配置、DTS、驱动、init、固件与工具输入与工作区逐字节一致，哈希保存在本地 `out/source-parity/build-inputs.json`。

最终运行：

```sh
TREE=/root/linux-6.18.59 OUT=/root/linux-6.18.59/out-source-parity \
  JOBS=12 TC=gcc sh /root/umi-6.18-open-source-work/scripts/build.sh
BUILD=/tmp/umi-source-parity-initramfs \
  sh /root/umi-6.18-open-source-work/scripts/mkinitramfs.sh --root none
cd /root/umi-6.18-open-source-work
python3 tools/pack-umi.py --dtb out/sm8250-xiaomi-umi-wifi.dtb \
  -o out/boot-umi-6.18-source-parity.img
```

三条命令均 exit 0。BusyBox 使用本轮源码构建的 ELF，事先比对其来源 JSON 中的 SHA256；放到构建工作区默认 `out/busybox/` 路径。最终 initramfs 打包实际运行固件清单门禁（0 errors），`root-dev=none`；大小 1,290,070 B，仍在原硬上限内。

最终模块导出为 `6.18.59-umi-dirty`，1363 个模块；安装后的 `modules.order` 与源构建顺序逐项匹配，重复条目、旧顺序、缺模块/索引均失败。tar 包独立检查模块数、文本/二进制 depmod 索引、无符号链接，并核对 ath11k、MHI、QRTR、PCI pwrctrl、cfg80211/mac80211、PM8xxx RTC 模块存在。配置/内核/模块包 SHA256 与导出 manifest 相符。

boot v2 打包自检通过；独立解析确认 kernel、DTB、ramdisk 与输入逐字节一致，解压内核含 ARM64 magic，ramdisk 的 init 与源码、BusyBox 与源码产物一致。三个最终 DTB 的符号数为 818 / 813 / 825，各有 8 个 disabled SPMI 别名；base/plus 不含 BQ25970，Wi-Fi 变体含该节点且禁用，Wi-Fi 供电属性存在。校验脚本曾误假设 base/plus 都有 BQ25970 符号，改为核对“缺省不存在 / Wi-Fi 禁用”后 exit 0，未为迎合检查新增硬件节点。

本地产物和验证 JSON 复制到 Windows `C:/umi-mainline/out/source-parity/`，由 Git 忽略，不提交镜像、模块包或长日志。构建日志中的 rustfmt 缺失提示没有导致最终编译失败；保留现有 DTC 警告，不宣称零警告。完整 6.12 / 7.2 兼容矩阵及远端手动 Kernel compile 本轮未运行。

| 最终产物 | 字节数 | SHA256 |
| --- | ---: | --- |
| `Image.gz` | 16,276,790 | `9990cf366ec97f1889f43ea808e7950b7f55273745a7e13b4b8a37d13e7e73b6` |
| `sm8250-xiaomi-umi.dtb` | 192,687 | `f941f277e7120fc00a3371dbf0c44746f124b34d904c25582ead037119de3ac3` |
| `sm8250-xiaomi-umi-plus.dtb` | 188,725 | `78071f933f024eb805981ce0d47bb5f3956becf1cba7b34b88619ae26bafc4b9` |
| `sm8250-xiaomi-umi-wifi.dtb` | 195,251 | `bab93a07e5bf6fe625d44dde4551fa22696401496a3691ce099ae6405cb2e322` |
| `initramfs.cpio.gz` | 1,290,070 | `98718a92c5c615631a8f52ce6694f1e63ecdb57a0d2b00011362ea9e0aaa7d5d` |
| `boot-umi-6.18-source-parity.img` | 17,768,448 | `c56615db71169488344a8b093291f657cd643f2a3097d0093114094e2074808c` |
| `modules-6.18.59-umi-dirty.tar.gz` | 18,326,838 | `f16257a4e6ea30c16572337cc1e3f1ce46802ba043369ee42486bffd098beba6` |


BusyBox 前两次编译分别暴露 1.37.0 tc 对已移除 CBQ UAPI 的引用、SHA-NI 默认配置与 AArch64 不匹配。通过只调整用户态配置（禁用救援不用的 tc、改用通用哈希）解决，没有改供应商固件或内核供电参数。随后源码构建 exit 0，产物经 ELF64/AArch64/无 PT_INTERP 检查；尚未在手机执行。

首次 31 项离线回归输出全部 OK，但外层 WSL 调用转义使退出码转发失败，不能据该调用宣称 exit 0。改用 `wsl --exec` 后，32 项回归明确 exit 0；后续新增默认基线和 DTB 快编回归以最终结果为准。

## 未覆盖与继承证据

旧 6.18 临时启动的亮屏、触摸事件和 GPU 初始化证据仍属于[上一轮记录](2026-10-29-linux-6.18.59-boot-fixes.md)，不转记成本轮产物的 L3 验收。屏幕恢复、短按/长稳、Wi-Fi/PCIe 时序、GL/Vulkan/Plasma、真实 rootfs 模块安装、关机目标异常、充电/PPS 及 BQ25970 安全均未在本轮真机执行。模块完整只证明交付链，不证明 Wi-Fi 连通。

固件精确再分发权、部分历史引入提交与完整工具链/libc 锁定尚未补齐，见 RISK-004 / TD-005。没有可核验的等价固件源码时保留现有字节，不把同类文件的许可当作当前提取件的授权。

## 2026-10-30 提交前复验

用户授权本地提交、推送工作分支并创建 PR。Windows 原生 Python 缺少 Linux 工具链，直接运行完整回归出现环境失败；未作为通过证据。首次在 WSL 工作副本复跑时，副本中测试仍旧，只有 24 项且两项因缺夹具辅助脚本失败。同步 Windows 工作区源码及测试后，在 `umi:/root/umi-6.18-open-source-work` 运行 `python3 -m unittest discover -s tests -p 'test_*.py' -v`，35 项全部通过、真实 exit 0。未因该副本问题改动产品实现或扩大设备操作范围。
