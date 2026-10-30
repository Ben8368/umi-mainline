#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Check reviewed binary firmware identities; this is not a licensing approval."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(root=ROOT):
    manifest = json.loads((root / 'firmware/manifest.json').read_text(encoding='utf-8'))
    errors = []
    seen = set()
    for entry in manifest['files']:
        name = entry['path']
        if name in seen:
            errors.append(f'duplicate firmware entry: {name}')
        seen.add(name)
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            errors.append(f'firmware path escapes repository: {name}')
            continue
        if not path.is_file():
            errors.append(f'missing firmware: {name}')
            continue
        data = path.read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            errors.append(f'firmware identity changed, review source/license first: {name}')
        if entry['source_status'] != 'binary-only-in-repository':
            errors.append(f'unsupported source claim for opaque payload: {name}')
    actual = {str(path.relative_to(root).as_posix())
              for path in (root / 'firmware/qcom').iterdir() if path.is_file()}
    actual.add('stfts/fts_fw.h')
    if actual != seen:
        errors.append(f'firmware inventory mismatch: {sorted(actual ^ seen)}')
    return errors


def main():
    errors = check()
    for error in errors:
        print(error)
    print(f'Firmware inventory: {len(errors)} errors; redistribution rights remain separate')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
