# 2026-10-28 治理体系移植

来源 Ben8368/DockDSM master bc77c7e7f21e68dea6457568d8318b66452de280，目标 umi-mainline master 39b6349。不修改 DockDSM 工作区。

| 原体系 | umi 初始化 |
| --- | --- |
| AGENTS / Context / Lessons / Claude / Cursor | 唯一入口、三项优先级、按需经验与摘要 |
| GOVERNANCE / AI_RULES / QUALITY | 原预算、状态词、红绿灯、证据分层与提交署名 |
| PRODUCT / platforms / MAINTAINERS | umi、SM8250、独立内核树、供电/存储边界 |
| Risk / TD / ADR / archive | 初始化已知风险、调试权限延期和长期决定 |
| governance check / hook / tests | 保留预算、路由、链接、ADR、工具身份与拒绝回归 |
| CI result / CodeQL / label / stale | 适配双 Linux runner 的离线门禁，无自动发布 |
| CodeRabbit / Jules / Renovate | 本仓库审查指令、精确范围派单、依赖更新，无自动合并 |

原 DSM、QEMU、ARC 专题不迁入；其制度在平台、构建、测试矩阵与依赖文档中适配。现有 umi 硬件专题继续保留，不重写旧实测。新增配置不代表外部 App 安装、Jules 接单或真机验收。

本地验收：治理检查、11 项治理回归、署名钩子正反例、5 项 CI 策略回归、21 项实际派单 JavaScript 模拟与整树文本检查通过；外部 App 登录/授权仍待确认。CodeRabbit 按官方 code_guidelines.filePatterns 直接读取治理权威文件。
