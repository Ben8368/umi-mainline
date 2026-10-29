#!/usr/bin/env python3
"""Enable repository-local commit attribution hooks."""
from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import sys


def git(root: Path, args: list[str], allowed=(0,)) -> str:
    result = subprocess.run(['git', '-C', str(root), *args],
                            text=True, capture_output=True, check=False)
    if result.returncode not in allowed:
        raise RuntimeError(result.stderr.strip() or f'git {" ".join(args)} failed')
    return result.stdout.strip()


def install(root: Path | None = None) -> None:
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    repo = Path(git(root, ['rev-parse', '--show-toplevel'])).resolve()
    if repo != root:
        raise RuntimeError('Root must be the repository root')
    hook = root / '.githooks' / 'commit-msg'
    if not hook.is_file():
        raise RuntimeError('Missing .githooks/commit-msg')
    configured = git(root, ['config', '--get', 'core.hooksPath'], allowed=(0, 1))
    if configured and (root / configured).resolve() != (root / '.githooks').resolve():
        raise RuntimeError(f'Existing core.hooksPath is preserved: {configured}')
    if not configured:
        default_hooks = Path(git(root, ['rev-parse', '--git-path', 'hooks']))
        if not default_hooks.is_absolute():
            default_hooks = repo / default_hooks
        default_hooks = default_hooks.resolve()
        if default_hooks.is_dir():
            for entry in default_hooks.iterdir():
                if entry.is_file() and not entry.name.endswith('.sample'):
                    raise RuntimeError('Existing hooks are preserved. Integrate hooks manually.')
    mode = hook.stat().st_mode
    hook.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    git(root, ['config', '--local', 'core.hooksPath', '.githooks'])
    print('umi-mainline commit attribution hook enabled for this repository.')


if __name__ == '__main__':
    try:
        install(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None)
    except Exception as exc:  # noqa: BLE001
        print(f'Git hook installation FAILED: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
