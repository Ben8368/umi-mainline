# 合并后救援启动镜像构建

日期：2026-10-29；仓库：Ben8368/umi-mainline。

## 构建来源与命令

- 仓库 master：`fd469d999a365bbfec0c0caa6eac4363a70ec70c`，包含 PR #2（HEAD `7383b6525b6ba2f43c8a85707c52da0be4421777`）。
- 宿主：WSL Linux x86_64；目标内核：Linux `0b8f247169e487eff2d4c2dd531bc43f7efda2cb`（6.12.94）。
- 从仓库根目录运行 `sh scripts/mkimage.sh`，默认 `ROOTDEV=none`。
- 构建完整内核与 Umi / Umi Plus / Umi Wi-Fi 三个 DTB；重新生成 initramfs 后打包 Android boot header v2 镜像。

## 结果与边界

- 产物：`out/GZTD-03-00272`，16,322,560 字节。
- SHA256：`FF45E4607E23C35575246F1F604BB645C2DC7D0BDBBCD63A78537E2475F978DB`。
- 打包脚本自检通过：kernel gzip / AArch64、DTB 的 FDT 与板级属性、boot header v2 与分区偏移。
- initramfs 为 root=none 救援模式，764,801 字节，低于大小上限；包含 A650 GPU 固件。
- 未连接或写入手机；构建成功不是设备启动、显示、触控或充电验收证据。
