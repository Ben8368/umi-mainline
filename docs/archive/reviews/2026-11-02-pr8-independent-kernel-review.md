# PR #8 独立内核安全复核（2026-11-02）

## 身份、范围和结论

- 复核者：本次独立 Codex 审查会话，不是原 idle 移植开发会话；先完成独立调用链分析，再读取 CodeRabbit 最终意见。
- PR：https://github.com/Ben8368/umi-mainline/pull/8，base `e1e0c8c775f5fcc53104e43157ddf56b2173ab02`，开局远端/本地 HEAD 均为 `8761242997e24bb7f262e70544400a52089092f1`。开局工作区干净。
- 审查原完整 diff、fts.c/fts.h/ftsCore.c、全部 reset/scan/IRQ 调用者、ftsIO/ftsError/ftsGesture/ftsTool/ftsTest、probe/unwind/remove/shutdown、fb notifier、PM 及 tests/test_touch_idle.py。
- 原 HEAD：REQUEST CHANGES，两个 P1 缺陷，不因旧 CI 或 CodeRabbit success 放行。
- 上轮 P1 修复提交为 `06f47f656db64bcbe833f63ed8e060c3d8185568`，parent 为原始 HEAD `8761242997e24bb7f262e70544400a52089092f1`；下列 L0/L1/L2 针对该 parent 至上轮修复工作树的变化，不包含之后的 P2 修改；结论 CONDITIONAL，不是合并许可。新提交仍须同 HEAD CI/CodeRabbit、修复部分的外部专项复核和 L3。
- 独立性边界：本会话对原 HEAD 的复核独立；本会话实施的 IRQ/probe 修复不能冒充由另一个开发者以外的会话复核。须由维护者或另一个只读会话复核新增修复，CodeRabbit 不替代该门禁。

## 验证版本澄清（P3 后补，不改写历史结果）

| 轮次 | 代码版本及覆盖 | 是否包含本轮 P2 修改 |
| --- | --- | --- |
| 原始移植 | `8761242997e24bb7f262e70544400a52089092f1`；89 项及 L2 见[移植记录](2026-11-02-upstream-5fa2e00.md) | 否 |
| 上轮 P1 修复 | `06f47f656db64bcbe833f63ed8e060c3d8185568`；下文 94 项 L1、L0 和 L2 增量编译 | 否 |
| 本轮 P2 修复 | `62e14fc1d2e8609d8e2b3cb69c58f0ff38127fcc`，parent 为上轮修复 HEAD；本轮 99 项 L1、L0 和 L2 增量编译覆盖该代码提交，命令和结果见[P2 交付记录](2026-11-02-pr8-p2-fixes.md) | 是，不能引用上轮 94 项或旧镜像替代 |

前轮只读复核确认原 P1 具体缺陷已修复，但发现外部 IRQ 屏蔽可被恢复线程解除及 GPIO 方向失败泄漏两个 P2，结论 REQUEST CHANGES。该结论与本轮开发验收不同；P2 修复仍须另一独立会话签核。

## 发现及处置（缺陷行号指原 HEAD）

### P1-1：IRQ 恢复自等待、持自旋锁等待 IRQ

- `fts521/fts_lib/ftsCore.c:890-906`：fts_disableInterrupt 在 fts_int 自旋锁内调用 disable_irq。Linux 6.18.59 `kernel/irq/manage.c:710-715` 调用 synchronize_irq，后者等待 threads_active 归零。
- 调用链：request_threaded_irq(NULL, fts_event_handler, IRQF_ONESHOT) → fts_event_handler (`fts.c:2496`) → fts_error_event_handler (`fts.c:2010-2040`) → fts_chip_powercycle / fts_system_reset (`ftsCore.c:129`) → fts_disableInterrupt → disable_irq → synchronize_irq。
- 触发：正常启用中断后收到 ESD/watchdog/hard-fault，disable_irq_count 为 0。IRQ 线程将等待自己退出；同时处于自旋锁/关中断区域，不能合法睡眠。
- 另一交错：CPU A 持 fts_int 同步停 IRQ，CPU B 的 IRQ 恢复需要同一 fts_int；A 等 B，B 等 A。idle cancellation 之前/之后都不能解决这个等待环。
- 来源：base 已存在，PR 未引入；但本 PR 声明覆盖恢复和 teardown，且本轮明确要求完整调用链复核，故必须修复而不是隐藏为新 idle 锁问题。
- 修复：记录本设备正在执行的 IRQ 线程；屏蔽和计数更新在 fts_int 内用 disable_irq_nosync，外部调用者在解锁后 synchronize_irq，IRQ 本身不等待自己。已被屏蔽时外部调用仍排空线程；NoSync 使用 irqsave/irqrestore，避免原来的 IRQ 状态不配对。保留既有 enable/disable 计数政策，不改扫描/电源参数。
- 反例：提取实际 IRQ handler、reset、disable/enable C 函数，在 pthread 条件变量控制的 IRQ 模型中运行；原 HEAD 触发运行时断言。恢复自等待、持锁等待或取消外部 drain 分别触发断言；不是以编译失败替代捕获。

### P1-2：probe 部分失败返回成功并保留已释放 drvdata

- `fts521/fts.c:3834-3865,4092-4100`：board 分配、fts_get_reg、fts_enable_reg、fts_set_gpio 失败时没有给 error 赋真实错误码。info 释放后 probe 可返回 0；drvdata 仍指向它。
- 调用链：probe → 早期分配/依赖失败 → ProbeErrorExit_* → kfree(info) → return 0 → 已绑定设备的 idle PM prepare/complete、shutdown/remove → 访问已释放对象。
- 来源：丢错误码是 base 既存问题；本 PR 新 PM/shutdown 回调扩展了悬空指针的访问入口。`-EPROBE_DEFER` 也会被吞掉，设备不会正常延期重试。
- 修复：保留 -ENOMEM/实际 retval，最终释放前清空 drvdata/fts_info；get_reg 失败经过 regulator_put。GPIO 设置失败关闭已启用 rails；后期失败仅释放已成功申请的 GPIO，避免释放未申请/已经回滚的 GPIO。控制器初始化失败保留诊断节点的既有策略不变。
- 反例：提取实际早期 acquisition 分支及公共 unwind，注入 board/依赖/上电/GPIO/后续阶段失败，断言返回码、drvdata、释放次数、idle 停止。恢复旧 HEAD 以及逐项错误码/清指针/资源释放变异均由运行时断言拒绝。中间 input/DT/core 初始化未被该片段模型模拟。

### P2：原测试不能证明真实 workqueue/IRQ 并发安全

- `tests/test_touch_idle.py:59-64` 的 cancel_delayed_work_sync 仅清 pending；不记录 running，不等待 worker。原 pthread stop 测试主要证明 idle_lock 等待 I/O，不能证明 kernel cancellation 的运行中/尚未取得 mutex 情形。
- current 在原测试中是手动设置的全局指针，多线程重叠测试不是完整 Linux current/workqueue 模型。IRQ、fts_disableInterrupt、真实 reset 和 probe 回滚原先没有被组合执行；因此全部旧测试通过仍能漏掉 P1-1/P1-2。
- 补充 `tests/test_touch_irq.py`：5 项测试，使用线程本地 current、可控 IRQ drain、运行中但 pending=false/尚未取得 idle_lock 的 workqueue 模型；分别覆盖 hold、PM prepare/complete、stop 的同步取消和针对性反例。原 C 函数被提取执行，并非单纯重写 Python 状态机。
- 边界：仍是 L1 模型，不是 Linux 内核运行；没有证明所有 IRQ/PM/诊断交错、真实中断控制器或 I²C adapter。KASAN/KCSAN/lockdep 和 L3 仍未运行。

### P3：状态摘要过度概括 strict checkpatch

- 原 `CONTEXT.md:22` 统称静态检查通过，但原归档明确记录 strict 模式退出 1、3 条既有 CamelCase CHECK、0 errors/0 warnings。
- 接受 CodeRabbit 意见，摘要保留非零退出和历史适用范围；本轮也分别记录普通和 strict 结果，不降低检查规则。

## 未发现新缺陷的调用链及限制

- idle_hold/stop/PM prepare：修改状态后先释放 idle_lock 再 cancel_delayed_work_sync；idle worker 只取得 idle_lock 并直接 fts_write → i2c_transfer，没有调用 hold/reset、fts_int、fts_disableInterrupt 或等待 FTS IRQ。未找到 idle callback ↔ cancel 的自等待环。mutex 内进行可睡眠 I²C 是合法行为，不是 spinlock 内睡眠。
- fts_system_reset/setScanMode、init/init_flow/init_sensing、mode、IRQ recovery/controller-ready、resume/suspend、powercycle、enable_reg、fwupdate 的 hold/release 成对检查；所有现有可达退出中未找到计数下溢/重复 release。idle_holds/owner/conflict/ready/stopping 的更新受同一 mutex 保护；不同线程交叠保守拒绝重排队。
- 初始化的最终 release 仅在整体成功后以 3000ms 排队；reset/scan 内层 release 不提前发命令。失败聚合阻止旧成功覆盖失败。idle 写失败仅告警、不重试；不改变 C0 0A、sense off/on、首触事件解析或多点上报。
- remove：stop idle → 移除 sysfs 并等待活动访问 → 注销实际注册的 notifier → drain resume/suspend → free_irq（等待 handler）→ 释放 table/input/workqueue/info。stopping 阻止恢复路径重新排队 idle；未发现新 idle UAF。
- notifier 在当前目标内核无 FB_EVENT_BLANK；兼容分支也只忽略 blank，不调度 resume/suspend。shutdown 仅停止可选 idle 和已有 work，不虚称它实现完整系统 PM/停 IRQ 策略。
- PM prepare/complete 只屏障新增可选命令，不改变既有 sensing/IRQ wakeup；并不保证已有 IRQ 恢复绝不在系统睡眠期间访问 I²C。不得据此声称完整触摸 PM 已验收。
- fwupdate 退出 ready=false，交叠恢复 conflict 后不自动重试，可能一直没有 idle 优化直到新的已知成功模式恢复/rebind；这是既有 TD-009，不对未知 bootloader/诊断状态盲目发命令。
- 自发固件 reset 至 IRQ 被识别的窗口、I²C 实际命令含义和真实首触改善仍由 RISK-002 阻断；静态检查不能排除硬件窗口。

## CodeRabbit（原 HEAD 的真实最终反馈）

最终 review：https://github.com/Ben8368/umi-mainline/pull/8#pullrequestreview-5731986349，2026-11-02 04:06:55 UTC，覆盖 `8761242997e24bb7f262e70544400a52089092f1`，state COMMENTED，check COMPLETED/SUCCESS。读取 review 全文、行内评论和 issue comments；该 review 无 outside-diff comments，不用顶部 actionable 数量代替逐条阅读。

| 评论 | 独立判断 | 处置 |
| --- | --- | --- |
| https://github.com/Ben8368/umi-mainline/pull/8#discussion_r4438825432 | P1，成立；与独立分析一致，probe false success/UAF，详见 P1-2 | 本记录所在修复提交；错误码/资源/指针回归验证 |
| https://github.com/Ben8368/umi-mainline/pull/8#discussion_r4438825423 | P3，成立；历史 strict 结果需要在摘要保留 | CONTEXT 摘要修正 |

CodeRabbit 未报告 P1-1，未报告不代表安全。原 HEAD 的最终 review 和 CI success 不覆盖本次修复提交；发布新提交后须重新取得同 HEAD 最终结果，Draft 不自动转 Ready。

## 验证环境、命令和结果

宿主 Windows x64 / PowerShell 7.6.5；执行 C/编译为 WSL umi，Linux x86_64 / /bin/sh。Linux 树固定 `1253a6aa5d104312bf0992afacc15220ae35bdf9`（6.18.59）。本轮复用 `/root/umi-upstream-5fa2e00-20261102/linux` 和 `out` 的已配置隔离 ext4 树执行全目标增量重编译，未修改 `/root/linux-6.18.59` 原工作树；不冒充 clean-room 全量构建。日志位于 `/root/umi-pr8-independent-20261102/`，未提交长日志或构建产物。

| 结果 | 实际命令 | 边界 |
| --- | --- | --- |
| PASS | python3 -m unittest discover -s tests -p 'test_touch_irq.py' -v | 5 项实际 C/片段模型和变异反例；NOT kernel runtime |
| PASS | 原 HEAD 的 IRQ/probe C 输入同一 harness，以 success=False 验证 | 两项均编译成功并由目标运行时断言拒绝 |
| PASS | python3 -m unittest discover -s tests -p 'test_*.py' -v | 94 项，退出 0；包括原 89 项与新增 5 项 |
| PASS | python3 scripts/governance-docs-check.py；python3 tests/governance-docs.py；python3 scripts/git-hooks-test.py；python3 tests/ci-policy.py；python3 tests/bot-dispatch.py；python3 scripts/check-tree.py；git diff --check | 均退出 0；包含 ShellCheck error 级，未降低门禁 |
| PASS | make -C "$TREE" ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- O="$OUT" -j12 Image.gz dtbs modules | 退出 0；三份修改源文件 cmp 一致；已有厂商宏重复定义/原型等警告，不声称零警告 |
| PASS | checkpatch.pl --no-tree driver.patch | base 至工作树 C diff；退出 0，0 errors / 0 warnings |
| FAIL（非行为风格） | checkpatch.pl --no-tree --strict driver.patch | 退出 1，0 errors / 0 warnings / 6 CHECK，均引用既有 CamelCase API/错误标签；不为消提示扩大重命名范围 |
| PASS | git diff --exit-code e1e0c8c -- config dts power firmware scripts contrib .github .coderabbit.yaml | 退出 0，BQ/PPS/保护参数及门禁无差异 |
| NOT RUN | 真机首触/短按/多点、睡眠/恢复、reset/rebind、诊断恢复、IRQ 压力、KASAN/KCSAN/lockdep | 无本轮设备授权，不刷写/临时启动/改分区；L1/L2 不代替 |

本轮 Image.gz SHA256：`9e6249758cddb065afbf7a39f03b175f07e595b90ebe6f1272d948b5a394f980`；三个 DTB 与原记录的字节哈希一致。仅更新内核树/out 中普通文件，不进行模块安装到设备、镜像启动或充电实验。

## 交付和剩余门禁

只修改实际缺陷、回归和审查记录；保持原作者/许可、BQ25970 disabled、PPS/充电保护与调试权限配置不变。修复提交 SHA 与远端检查状态以本轮交付消息及 PR 记录为准；本记录不通过反复文档提交制造新 HEAD 检查循环。

必须补齐：修复部分开发者以外的专项复核、准备合并的当前 HEAD CI result success、同 HEAD CodeRabbit 最终反馈及有效意见处理、RISK-002 要求的受控硬件验收。未经新授权不合并、不转 Ready、不关闭、不自动合并。
