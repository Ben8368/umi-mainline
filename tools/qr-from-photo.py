#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""qr-from-photo.py — 从手机拍照里把 panic 二维码解出来

drm_panic 的二维码是 Version 40（177x177 模块，最密的一档），手机照片常常
一次检测不到，所以这里做多种预处理轮一遍：
  原图 / 灰度 / 自适应阈值 / Otsu / 反色 / 不同缩放 / 裁掉边缘留白

用法：
    python tools/qr-from-photo.py photo.jpg
    python tools/qr-from-photo.py photo.jpg -o out/panic-qr.txt
"""
import argparse
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("-o", "--output", default=None)
    a = ap.parse_args()

    import cv2
    import numpy as np

    img = cv2.imread(a.photo, cv2.IMREAD_COLOR)
    if img is None:
        print("!! 读不了图片：%s" % a.photo)
        return 2
    h, w = img.shape[:2]
    print("图片 %dx%d" % (w, h))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    variants = []
    def add(name, im):
        variants.append((name, im))

    add("原图-灰度", gray)
    add("原图-彩色", img)

    # 裁掉上下各 10%（二维码一般在中间），再多给几个裁剪比例
    for frac in (0.0, 0.08, 0.15, 0.22, 0.3):
        y0 = int(h * frac); y1 = int(h * (1 - frac))
        if y1 - y0 < 200:
            continue
        crop = gray[y0:y1, :]
        add("裁剪frac=%.2f" % frac, crop)
        add("裁剪frac=%.2f+upscale2x" % frac, cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        add("裁剪frac=%.2f+Otsu" % frac, cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
        add("裁剪frac=%.2f+Otsu+inv" % frac, cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1])
        # 自适应阈值（对屏幕拍照的渐变很有效）
        add("裁剪frac=%.2f+adaptive" % frac,
            cv2.adaptiveThreshold(crop, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY, 51, 10))

    # 全图也来一套阈值
    add("全图+Otsu", cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
    add("全图+adaptive", cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                              cv2.THRESH_BINARY, 51, 10))

    det = cv2.QRCodeDetector()
    found = None
    for name, im in variants:
        try:
            data, pts, _ = det.detectAndDecode(im)
        except Exception as e:  # noqa: BLE001
            continue
        if data:
            print("  [命中] %s  -> %d 字符" % (name, len(data)))
            found = data
            break
        else:
            # 只检测到位置没解出来也算有点用
            try:
                ok, pts2 = det.detect(im)
                if ok and pts2 is not None:
                    print("  [只检测到位置] %s" % name)
            except Exception:  # noqa: BLE001
                pass

    # 试试 OpenCV 的 WeChat 检测器（对密集二维码更强）
    if not found:
        try:
            wd = cv2.wechat_qrcode_WeChatQRCode()
            for name, im in variants[:12]:
                try:
                    texts, _ = wd.detectAndDecode(im)
                except Exception:  # noqa: BLE001
                    continue
                for t in texts:
                    if t:
                        print("  [命中/WeChat] %s -> %d 字符" % (name, len(t)))
                        found = t
                        break
                if found:
                    break
        except Exception as e:  # noqa: BLE001
            print("  (没有 wechat_qrcode 模块: %s)" % e)

    if not found:
        print("\n!! 没解出来。可以试试：")
        print("   1) 重拍一张：让二维码尽量占满画面、正对屏幕、别开闪光灯")
        print("   2) 或者用手机扫码 App 扫，把文本贴过来")
        return 1

    print("\n原始内容（%d 字符）:" % len(found))
    print(found[:400] + ("..." if len(found) > 400 else ""))
    if a.output:
        os.makedirs(os.path.dirname(a.output) or ".", exist_ok=True)
        with open(a.output, "w", encoding="ascii", errors="replace") as f:
            f.write(found)
        print("\n已写到 %s" % a.output)
        print("下一步： python tools\\decode-panic-qr.py \"$(cat %s)\"" % a.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
