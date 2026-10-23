#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
# -*- coding: utf-8 -*-
"""decode-panic-qr.py — 把 drm_panic 二维码里那串东西还原成内核日志

背景：内核开了 CONFIG_DRM_PANIC + DRM_PANIC_SCREEN="qr_code" 之后，
panic 时会把内核日志压缩后编进一个二维码画在屏幕上。手机扫一下就能拿走，
不用再对着屏幕拍照抄字。

二维码里的内容格式（drivers/gpu/drm/drm_panic.c + drm_panic_qr.rs）：

  设置了 CONFIG_DRM_PANIC_SCREEN_QR_CODE_URL 时：
      <URL>?a=<machine>&v=<kernel版本>&zl=<十进制数字串>
      数字串是「13 个 bit 一组、每组写成 4 位十进制数字」拼出来的，
      解出来的字节流是 zlib 压缩的内核日志（窗口 12 bit，标准 zlib 头）。

  URL 为空时：
      二维码里直接就是未压缩的日志文本，扫出来直接看，不需要本工具。

用法：
    # 手机扫码得到的整串 URL
    python tools/decode-panic-qr.py "https://umi.local/panic?a=aarch64&v=6.12.94-umi&zl=0123456789..."

    # 或者只给数字串
    python tools/decode-panic-qr.py 0123456789...

    # 从文件里读（扫码 App 导出的 txt）
    python tools/decode-panic-qr.py -f scanned.txt -o out/panic.txt

也支持官方那个 JS 解码器同样的输入（https://github.com/kdj0c/panic_report）。
"""
import argparse
import re
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def digits_from(text):
    """从扫码结果里把 &zl= 后面的数字串抠出来"""
    text = text.strip()
    m = re.search(r"[?&]zl=([0-9]+)", text)
    if m:
        return m.group(1)
    m = re.search(r"([0-9]{8,})", text)
    if m:
        return m.group(1)
    return ""


def bits_to_bytes(bits):
    out = bytearray()
    for i in range(0, len(bits) - len(bits) % 8, 8):
        b = 0
        for k in range(8):
            b = (b << 1) | bits[i + k]
        out.append(b)
    return bytes(out)


def decode(digits):
    """数字串 → 字节流。返回 (bytes, 说明) 或 (None, 原因)

    编码规则（drm_panic_qr.rs 的 get_next_13b + character_count）：
      原始字节流按 13 bit 一组切开（MSB first），每组的**值**写成十进制数字，
      位数 = 1（只有 1 bit 时）或 ceil(位数/3)。所以：
        完整组 = 13 bit → 4 位数字
        最后一组 = 剩多少 bit 就写多少位数字（可能是 1~4 位）
      注意：最后那 4 位数字也可能只代表 11 或 12 bit —— 不能当成完整组处理。
    """
    n = len(digits)

    def emit_full(d, cnt):
        bits = []
        for i in range(cnt):
            v = int(d[i * 4:(i + 1) * 4])
            if v > 8191:
                return None, "第 %d 组数字 %d 超出 13 bit（可能不是 drm_panic 的二维码）" % (i, v)
            bits.extend((v >> k) & 1 for k in range(12, -1, -1))
        return bits, None

    # 尾组可能占 0~4 位数字；再猜它对应多少 bit
    for tail_digits in (0, 1, 2, 3, 4):
        if tail_digits > n:
            continue
        body_len = n - tail_digits
        if body_len % 4:
            continue
        n_full = body_len // 4
        bits, err = emit_full(digits, n_full)
        if err:
            return None, err
        if tail_digits == 0:
            k_cands = (13,)          # 没有尾组：最后一组就是完整 13 bit
        else:
            k_cands = tuple(k for k in range(1, 14)
                            if (1 if k == 1 else (k + 1) // 3) == tail_digits)
        tail_val = int(digits[n - tail_digits:]) if tail_digits else 0
        for k in k_cands:
            cand = bits + [(tail_val >> b) & 1 for b in range(k - 1, -1, -1)]
            if len(cand) % 8:
                continue
            raw = bits_to_bytes(cand)
            if len(raw) < 16:
                continue
            for name, fn in (("zlib", zlib.decompress),
                             ("raw-deflate", lambda d: zlib.decompressobj(-15).decompress(d))):
                try:
                    txt = fn(raw)
                except Exception:
                    continue
                if txt and len(txt) > 32:
                    return txt, ("尾组 %d 位数字=%d bit、压缩方式 %s、压缩后 %d 字节"
                                 % (tail_digits, k, name, len(raw)))
    return None, ("解不出来（数字串 %d 位）—— 也可能是内核没开压缩模式。"
                  "如果二维码里直接是日志文本（URL 为空的那种），扫出来直接看就行。"
                  "官方解码器： https://github.com/kdj0c/panic_report" % n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="扫码得到的整串内容（URL 或纯数字串）")
    ap.add_argument("-f", "--file", help="从文件读扫码结果")
    ap.add_argument("-o", "--output", help="把日志写到文件")
    a = ap.parse_args()

    raw_text = ""
    if a.file:
        with open(a.file, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()
    elif a.text:
        raw_text = a.text
    else:
        print("从标准输入读扫码结果（Ctrl+Z 回车结束）：")
        raw_text = sys.stdin.read()

    digits = digits_from(raw_text)
    if not digits:
        print("!! 没找到数字串。drm_panic 的二维码 URL 形如 "
              "https://xxx/panic?a=aarch64&v=6.12.94-umi&zl=0123456789...")
        print("   如果你的二维码里直接是日志文本（URL 为空的那种），直接看扫出来的内容就行，不用解码。")
        return 2

    print("== 数字串 %d 位" % len(digits))
    data, note = decode(digits)
    if not data:
        print("!! " + note)
        return 3

    text = data.decode("utf-8", "replace")
    print("== " + note)
    if a.output:
        # 二进制写，避免 Windows 把 \n 变成 \r\n（日志要原样保存）
        with open(a.output, "wb") as f:
            f.write(data)
        print("== 写出 %s（%d 字节）" % (a.output, len(data)))
        print("---- 最后 30 行 ----")
        for line in text.strip().splitlines()[-30:]:
            print("   " + line[:160])
    else:
        print("---- 完整日志 ----")
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
