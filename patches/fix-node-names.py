#!/usr/bin/env python3
# of_get_child_by_name() 比对的是 np->name（简单名，不含 unit address）：
#   pcie@0 的 name 属性是 "pcie"
#   wifi@0 的 name 属性是 "wifi"
# 所以必须用 "pcie" / "wifi"，用 "pcie@0" / "wifi@0" 永远匹配不上。
import io

P = "/root/linux/drivers/pci/controller/dwc/pcie-qcom.c"
t = io.open(P, encoding="utf-8").read()

before_pcie = t.count('"pcie@0"')
before_wifi = t.count('"wifi@0"')

t = t.replace('"pcie@0"', '"pcie"')
t = t.replace('"wifi@0"', '"wifi"')

io.open(P, "w", encoding="utf-8").write(t)
print(f"replaced pcie@0 x{before_pcie}, wifi@0 x{before_wifi}")
print(f"remaining: pcie@0={t.count(chr(34)+'pcie@0'+chr(34))} wifi@0={t.count(chr(34)+'wifi@0'+chr(34))}")

# 顺便把日志文案也改一下，免得再被误导
t = io.open(P, encoding="utf-8").read()
t = t.replace('"early power-on: no wifi@0 node\\n"',
              '"early power-on: no wifi node under pcie\\n"')
io.open(P, "w", encoding="utf-8").write(t)
print("log message updated")
