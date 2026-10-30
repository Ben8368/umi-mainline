# 依赖身份与边界

治理源 DockDSM bc77c7e7f21e68dea6457568d8318b66452de280；详情见 [来源](PROVENANCE.md)。CI 的 action 固定完整 commit，自动依赖 PR 不自动合并。

内核核验输入：gregkh/linux v6.12.94 → 0b8f247169e487eff2d4c2dd531bc43f7efda2cb；v7.2.12 → cc9de5d4b5ab6459f5774946aa3195ad51236fa8。均于 2026-10-28 用 peeled tag 核对。版本存在不等于本项目已完成完整编译或真机验收。

默认版本与准备入口固定于 [kernel.env](../config/kernel.env)。6.18 目标：`gregkh/linux` v6.18.59 → `1253a6aa5d104312bf0992afacc15220ae35bdf9`，沿用[原构建身份](archive/reviews/2026-10-29-linux-6.18.59-build.md)，并加入独立固定 SHA 的手动编译矩阵。

BusyBox 1.37.0 官方源码与 SHA256 固定于 [source-lock.json](../config/source-lock.json)；仅其源包已锁定，宿主交叉编译器与 libc 不是完整可重现闭包。现有 GPU/内嵌触摸固件的字节身份见 [manifest.json](../firmware/manifest.json)，不自动授予再分发许可。

CI 使用 Python 3.13、PyYAML 6.0.3、Ubuntu 24.04。工作流未固定 Node 版本；GitHub Actions 使用 runner 镜像预装的 Node 运行时，版本会随镜像更新。系统 apt 包不是完整快照；工具环境不是 bit-for-bit 构建证明。固件哈希/来源仍按 firmware/README.md 与 GPU 专题核实，不自动更新供电参数、内核版本或固件。
