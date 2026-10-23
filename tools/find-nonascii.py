#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""find-nonascii.py PATH — 列出文件里所有含非 ASCII 的**字符串字面量**，用 \\uXXXX 转义打印。

控制台是 GBK 的，直接 print 中文会变乱码，所以这里一律 ascii() 转义。
"""
import re
import sys

path = sys.argv[1]
src = open(path, encoding="utf-8").read()
n = 0
for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', src):
    s = m.group(1)
    if any(ord(c) > 127 for c in s):
        line = src[:m.start()].count("\n") + 1
        print("%4d  %s" % (line, ascii(s)))
        n += 1
print("-- %d non-ASCII string literals" % n)
