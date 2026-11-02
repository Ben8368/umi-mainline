# PR #8 fwupdate IRQ depth / reset GPIO defer 修复（2026-11-02）

## 范围与状态

- 分支 `sync/upstream-5fa2e00`，base `e1e0c8c775f5fcc53104e43157ddf56b2173ab02`，开局 HEAD `f295b949bf7d5b9aa77c24a93ff0748b522ead9b`；本地和远端一致、工作区干净。
- 仅处理 fwupdate IRQ depth 失配与 reset GPIO defer/error 被吞。保持 PR #8 Draft/Open；不合并、不转 Ready、不关闭、不强推、不执行设备命令。本记录是开发自查，不是独立签核。
- 未修改 config、DTS、power、PPS、固件、CI 或设备安全策略。
- 修复与测试提交：`9cff5cdf89e1513b5032b40d02960ad9aa433f22`，直接 parent 为上述开局 HEAD；本记录所在提交仅补充验证证据。所有本地测试和 L2 覆盖该修复提交生产代码。

## IRQ 所有权

IRQ 内核 disable depth、驱动 owner 标记和控制器是否可扫描是独立状态。保留外部幂等域与 IRQ 恢复域，新增 fwupdate 单事务层：`fwupdate_lock` 串行 sysfs 事务，`irq_fwupdate_owner == current` 使同事务中的 reset/flash/powercycle/cleanUp 借用事务屏蔽；仅 `fts_fwupdate_end()` 释放。恢复线程不取该 mutex。begin 在 fts_int 外 drain；end 更新 owner 后在自旋锁外 enable。remove 移除 sysfs group、等待 writer 后才释放 IRQ/info。

| 路径 | 内核 depth D | 外部 owner | 恢复 owner | 事务 owner | 结果 |
|---|---:|---|---|---|---|
| 正常 begin → mode 0/end | 0→1→0 | false | false | current→null | 无额外 depth，不推断 sensing |
| mode 4 reset / mode 8 powercycle | 1 | false | false | current | helper 借用事务层 |
| mode 256 flash、嵌套 reset/cleanUp | 1 | false | false | current | 不改变 depth |
| 进入前已外部屏蔽 | 1→2→1 | true | false | current→null | 保留原屏蔽 |
| 事务中新外部 disable | 1→2 | false→true | false | current | end 仅减事务层，D=1 |
| 与 IRQ recovery 并发 | 事务/恢复层分别计数 | 保持 | true | current | 无自等待，各自释放 |
| reset/flash 失败 | 事务 depth 至共同 end | 保持 | 不擅自开启 | current→null | 不补发 idle/sense |

mode 0/所有退出仍 `fts_idle_release(info, false)`。ROM、bootloader、失败或未知状态不视为可扫描。检查调用链含 raw reset、4、8、256、`flashProcedure→flash_burn→fts_system_reset`、`cleanUp(0/1)`、production test/reset retry 和各早退。

## GPIO errno / unwind

6.18.59 legacy GPIO：属性不存在才设 `GPIO_NOT_DEFINED`；属性存在时 of_get_named_gpio 的负 errno 原样返回。7.x optional descriptor 的 IS_ERR 返回 PTR_ERR；合法 absent 仍允许。probe 检查 parse_dt 并跳 `ProbeErrorExit_1`：此时 regulator/GPIO 未获取，不释放未取得资源；清 drvdata/fts_info 的既有逻辑保留。

| 情形 | 控制流和清理 |
|---|---|
| reset 属性不存在 | OK、undefined，按合法配置继续；remove 不释放 reset GPIO |
| reset 正常解析 | 进入原 regulator/GPIO 路径；remove 配对释放 |
| reset defer / 其他负 errno | 原 errno 返回；ProbeErrorExit_1 只清 idle/drvdata/fts_info/info，不碰 regulator/rails/GPIO |
| IRQ GPIO defer / 其他 errno | reset 查询前保留错误，走同一早期 unwind |
| 后续阶段失败 | 原标签只清理已取得资源 |

未迁移 GPIO API，合法无 reset GPIO 配置不变。

## 回归和旧反例

扩展 `tests/test_touch_irq.py`，提取真实 fwupdate_store、IRQ/reset helpers、flashProcedure、flash_burn、cleanUp、parse_dt、probe acquisition/unwind、GPIO helper、remove/shutdown。18 项覆盖 mode 0/4/8/256/268/诊断组合，IRQ 注册与否、原外部屏蔽、逐点 flash I/O 失败、reset poll 失败、恢复交错、新外部 disable、remove/shutdown 和 7.x defer。

历史 fixture 源为固定 HEAD `f295b949bf7d5b9aa77c24a93ff0748b522ead9b` 的 `fts521/fts.c`；函数及 probe 片段逐字匹配，不依赖 Git 历史/网络。负例必须编译成功后运行 SIGABRT 且 stderr 命中目标断言：旧 fwupdate 命中 `irq_depth==0`，旧 parse/probe 命中 `ret==expected`。原两个 P1 与之前两个 P2 fixtures 也仍由目标运行时断言拒绝。复制到无 `.git` 目录运行专项 18 项通过。

模型限制：pthread IRQ/gpiolib/I2C/firmware/kernfs 均是离线替身，不证明 kernel runtime 或真实控制器扫描/flash 状态。

## 验证证据

Windows 10 x64 / PowerShell 7.6.5；WSL umi Alpine x86_64，Python 3.14.10、GCC 15.2.0、aarch64-none-elf-gcc 16.1.0。Linux 6.18.59 固定源码 SHA `1253a6aa5d104312bf0992afacc15220ae35bdf9`。日志在 `/root/umi-pr8-fwupdate-defer-20261102/`，不入库。

| 结果 | 命令/证据 | 说明 |
|---|---|---|
| PASS | `python3 -B -m unittest discover -s tests -p test_touch_irq.py -v` | 18 项真实 C 提取与 POSIX 模型 |
| PASS | `python3 -B -m unittest discover -s tests -p 'test_*.py' -v` | 107 项全套离线回归 |
| PASS | 指定旧源码/去 guard 变异反例 | 编译成功，由目标断言拒绝旧行为 |
| PASS | 无 .git 临时副本专项 | 18 项；无历史/网络依赖 |
| PASS | governance-docs-check、governance-docs、git-hooks-test、ci-policy、bot-dispatch、check-tree、git diff --check | 全部退出 0；313 paths / 29 shell / 0 errors |
| PASS | checkpatch 普通 | base 至驱动 diff：0 errors / 0 warnings |
| FAIL（风格 CHECK） | checkpatch strict | 退出 1；0 errors / 0 warnings / 7 CamelCase CHECK；本轮新增仅既有 ProbeErrorExit_1 标签 |
| PASS | `make -C "$TREE" ARCH=arm64 CROSS_COMPILE=aarch64-none-elf- O="$OUT" -j12 Image.gz dtbs modules` | 固定树增量构建，非 clean-room；最终 config 与此前有效 config 逐字一致，DTB 哈希未变；保留既有 vendor macro/missing-prototype warnings |
| PASS | config hash `120208d5a730874965e52a44991280de9d6e339e0cd40e10c483a14f25529db5`；Image.gz `c41d00956d126746f96c3757bef2ff4d67a0c94dca16009061e0ec70b4c0430b` | config/dts/power/firmware/scripts/contrib/.github 与 base 无差异 |
| NOT RUN | clean-room 构建、kernel runtime/KASAN/KCSAN/lockdep、真机和 fwupdate/reset/flash、分区/rootfs/充电/PPS | 安全限制；L1/L2 不等于 L3 |

首次构建的 PATH 中 rustup 改变 Kconfig 探测；已恢复先前有效 .config 并在无 Rust PATH 下重编，最终 config hash 一致。首次构建不算最终配置证据。

## 交付与门禁

最终交付 HEAD 为本记录所在提交，提交后由 PR 评论和交付报告记录精确 SHA/CI/CodeQL/CodeRabbit 状态，避免反复修改文档制造新 HEAD。推送只更新现有 PR #8；保持 Draft/Open。新 HEAD 独立专项复核、CI result、CodeRabbit 最终意见及有效意见处置、RISK-002 受控真机验收仍是合并阻断。不启动设备、不写分区/rootfs、不做充电/PPS 实验；BQ25970、PPS、保护参数、root/SSH/USB 策略及固件来源/许可不变。
