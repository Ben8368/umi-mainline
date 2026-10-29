#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Reuse SM8250 UBWC data when umi's ABL replaces root compatible with kona."""
from pathlib import Path
import re
import sys


def patch(source):
    def entries(compatible):
        return list(re.finditer(
            r'^(?P<indent>[ \t]*)\{\s*\.compatible\s*=\s*"' + re.escape(compatible) +
            r'",\s*\.data\s*=\s*&(?P<data>\w+)\s*,?\s*\},[ \t]*$', source, re.M))

    native = entries('qcom,sm8250')
    if len(native) != 1:
        raise ValueError('expected exactly one SM8250 UBWC data entry')
    alias = entries('qcom,kona')
    if '"qcom,kona"' in source:
        if len(alias) != 1 or alias[0]['data'] != native[0]['data']:
            raise ValueError('existing kona entry does not match SM8250 UBWC data')
        return source
    entry = native[0]
    addition = (f'\n{entry["indent"]}/* umi ABL uses the downstream SM8250 SoC name. */\n'
                f'{entry["indent"]}{{ .compatible = "qcom,kona", .data = &{entry["data"]}, }},')
    return source[:entry.end()] + addition + source[entry.end():]


def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: ubwc-sm8250-kona.py drivers/soc/qcom/ubwc_config.c')
    path = Path(sys.argv[1])
    try:
        source = path.read_text(encoding='utf-8')
        updated = patch(source)
    except (OSError, ValueError) as exc:
        raise SystemExit(f'UBWC patch refused: {exc}') from exc
    if updated != source:
        path.write_text(updated, encoding='utf-8', newline='\n')
    print('   ubwc: kona uses the existing SM8250 data')


if __name__ == '__main__':
    main()
