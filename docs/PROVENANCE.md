# 来源与归属

本仓库保留原 umi-mainline 的 Git 历史、文件级许可证及原贡献者归属。既有 ST FTS、供电驱动、固件与面板数据的来源以文件头、[固件说明](../firmware/README.md)、[TOUCH](TOUCH.md)、[BATTERY](BATTERY.md)为准；不因独立维护或 AI 提交而改称原创。

治理体系移植自 [Ben8368/DockDSM](https://github.com/Ben8368/DockDSM/tree/bc77c7e7f21e68dea6457568d8318b66452de280)。基准为 bc77c7e7f21e68dea6457568d8318b66452de280（2026-10-28 核对），保留其 [MIT 许可](../LICENSES/MIT-DockDSM.txt)。直接衍生文件：governance-docs-check.py、install-git-hooks.py、git-hooks-test.py、commit-msg、bot-dispatch workflow 与回归、治理回归、Jules setup，以及标签/CodeQL/stale 工作流；项目边界与路由已改写为 umi。

既有 [LICENSE](../LICENSE) 的路径分类继续适用；新增 DockDSM 衍生治理文件依 MIT 来源许可，新的 Linux C 驱动改动沿用原文件 GPL。AI 工具贡献通过工具级 trailer 标记，不替换维护者主作者或第三方版权。完整移植对照见 [记录](archive/reviews/2026-10-28-governance-port.md)。
