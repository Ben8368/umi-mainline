#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""dts-check.py — 在没有 dtc 的 Windows 上做一次「廉价的」DeviceTree 静态检查。

能查出最常见的三类低级错误（真机盲调时这些错误最致命，因为没有任何反馈）：
  1. 引用了不存在的 label（&foo 写成 &fooo 之类）
  2. 花括号 / 尖括号不平衡
  3. /delete-node/ &label 指向的 label 不存在
  4. 同一个父节点下出现重复的节点名
  5. status 拼错（"ok"/"okay"/"disabled"）

用法:
    python tools/dts-check.py dts/sm8250-xiaomi-umi.dts
    python tools/dts-check.py --tree D:\\project\\linux-src dts/sm8250-xiaomi-umi.dts

--tree 会额外扫描树里 sm8250.dtsi / pm8150*.dtsi / pm8009.dtsi，把 SoC 层的
label 也算进定义集合（推荐，否则满屏误报）。
"""

import os
import re
import sys

try:  # Windows GBK 控制台下打印 ✓/✗ 会炸，强制 UTF-8
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# 匹配 `label: node@addr {`（注意不能误吃 `&ref {` 这种）
RE_LABEL_DEF = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*:\s*[\w,.\-+@]+\s*\{")
RE_REF = re.compile(r"&([A-Za-z_][\w]*)")
RE_DELETE = re.compile(r"/delete-node/\s*&([\w]+)")
RE_NODE_OPEN = re.compile(r"^\s*(?:[\w-]+\s*:\s*)?([\w,.\-+@]+)\s*\{")
RE_STATUS = re.compile(r'status\s*=\s*"([^"]*)"')

DEFAULT_INCLUDES = ["sm8250.dtsi", "pm8150.dtsi", "pm8150b.dtsi",
                    "pm8150l.dtsi", "pm8009.dtsi"]

INCLUDE_DIRS = [os.path.join("arch", "arm64", "boot", "dts", "qcom")]


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def collect_defs(text):
    out = set()
    for line in text.splitlines():
        m = RE_LABEL_DEF.match(line)
        if m:
            out.add(m.group(1))
    return out


def check_file(path, defs, problems):
    raw = read(path)
    text = strip_comments(raw)
    name = os.path.basename(path)

    # 1. 括号平衡
    for open_c, close_c, what in (("{", "}", "花括号"), ("<", ">", "尖括号"),
                                  ("(", ")", "圆括号")):
        if text.count(open_c) != text.count(close_c):
            problems.append("%s: %s不平衡: %d 个 %r vs %d 个 %r" %
                            (name, what, text.count(open_c), open_c,
                             text.count(close_c), close_c))

    # 2. 引用存在性
    refs = set(RE_REF.findall(text))
    # 引用后紧跟 { 的是节点覆写，必须在 defs 里
    missing = sorted(r for r in refs if r not in defs)
    for r in missing:
        problems.append("%s: &%s 没有对应的 label 定义" % (name, r))

    # 3. delete-node 目标
    for d in RE_DELETE.findall(text):
        if d not in defs:
            problems.append("%s: /delete-node/ &%s 目标不存在" % (name, d))

    # 4. 同一父节点下重复节点名
    stack = [set()]
    for lineno, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            continue
        m = RE_NODE_OPEN.match(line)
        if m and not s.startswith("&") and not s.startswith("/"):
            node = m.group(1)
            if node in stack[-1]:
                problems.append("%s:%d: 同一父节点下重复节点 %r" % (name, lineno, node))
            stack[-1].add(node)
            stack.append(set())
        elif s.startswith("}"):
            if len(stack) > 1:
                stack.pop()

    # 5. status 取值
    for v in RE_STATUS.findall(text):
        if v not in ("okay", "ok", "disabled", "reserved", "fail", "fail-sss"):
            problems.append("%s: status 取值可疑 %r（应为 okay/disabled）" % (name, v))


def main(argv):
    tree = None
    files = []
    i = 1
    while i < len(argv):
        if argv[i] == "--tree":
            tree = argv[i + 1]
            i += 2
        else:
            files.append(argv[i])
            i += 1
    if not files:
        print(__doc__)
        return 2

    defs = set()
    if tree:
        for sub in INCLUDE_DIRS:
            d = os.path.join(tree, sub)
            for inc in DEFAULT_INCLUDES:
                p = os.path.join(d, inc)
                if os.path.exists(p):
                    defs |= collect_defs(strip_comments(read(p)))
        # 我们自己 dtsi 里的 label 也算
        for f in files:
            if f.endswith(".dtsi"):
                defs |= collect_defs(strip_comments(read(f)))

    problems = []
    for f in files:
        if not os.path.exists(f):
            problems.append("%s: 文件不存在" % f)
            continue
        defs |= collect_defs(strip_comments(read(f)))
    # dts 里 include 的 dtsi 也要参与
    for f in list(files):
        for inc in re.findall(r'#include\s+"([^"]+)"', read(f)):
            p = os.path.join(os.path.dirname(f), inc)
            if os.path.exists(p) and p not in files:
                files.append(p)
                defs |= collect_defs(strip_comments(read(p)))

    for f in files:
        check_file(f, defs, problems)

    if problems:
        print("发现问题 %d 个:" % len(problems))
        for p in problems:
            print("  ✗ " + p)
        return 1
    print("✓ 静态检查通过（label/括号/delete-node/重复节点/status）")
    print("  注意：这不是 dtc，真正的语法/引用检查还是要 make dtbs。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
