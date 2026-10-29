# 2026-10-28 源码核查

基线 39b63496d6f11d8f7802907d49af5abaac7bb195；macOS / arm64 / zsh。

确认：mkimage 缺 initramfs 步骤；构建管道丢退出码、复用旧 Wi-Fi DTB；快充配置关闭保护、初始化忽略错误、sense_r_mohm 为零；devm 重复注销与 notifier 清理缺失；Type-C 回调延迟与读取错误；DSI 多行解析重复；状态读取未初始化值；配置审计规则过时；文档写盘/电压保证过度。

隔离模拟：make 返回 2 时构建收集段返回 0 并复制旧 Wi-Fi DTB。DSI 原循环输入 01 02 换行 03 04 得到 512 字节，后续重复 03。原 ASCII 检查含真实 Tab 0x09，完整 init 无非法字符命中，该 review 指控为误报。

检查过的 37 个 Python 和 23 个 Shell 语法通过，ShellCheck error 级通过。未完整编译、未接入手机、未进行寄存器/充电验证。维护者明确保留调试权限，见 [TD-001](../../TECH_DEBT.md)。
