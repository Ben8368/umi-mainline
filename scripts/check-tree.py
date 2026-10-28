#!/usr/bin/env python3
"""Validate repository text without importing tools or executing device scripts."""
import ast
import json
from pathlib import Path
import shutil
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = subprocess.check_output(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT)
    names = sorted(set(output.decode().split('\0')) - {''})
    shells = []
    errors = []
    for name in names:
        path = ROOT / name
        if not path.is_file():
            continue
        try:
            if path.suffix == '.py':
                ast.parse(path.read_bytes(), filename=name)
            if path.suffix == '.json':
                json.loads(path.read_text(encoding='utf-8'))
            if path.suffix in {'.yml', '.yaml'}:
                yaml.safe_load(path.read_text(encoding='utf-8'))
            if path.suffix == '.sh' or name in {'initramfs/init', '.githooks/commit-msg'}:
                shells.append(name)
                subprocess.run(['bash' if b'bash' in path.read_bytes().splitlines()[0] else 'sh', '-n', str(path)], check=True)
        except (SyntaxError, ValueError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
            errors.append(f'{name}: {exc}')
    checker = shutil.which('shellcheck')
    if not checker:
        errors.append('ShellCheck is required; install it before verification')
    elif shells:
        for name in shells:
            flags = [] if (ROOT / name).read_bytes().startswith(b'#!') else ['--shell=sh']
            result = subprocess.run([checker, '--severity=error', *flags, name], cwd=ROOT)
            if result.returncode:
                errors.append(f'ShellCheck error-level validation failed: {name}')
    for error in errors:
        print(error)
    print(f'Text validation: {len(names)} paths, {len(shells)} shell files, {len(errors)} errors')
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
