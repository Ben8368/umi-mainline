#!/usr/bin/env python3
"""Apply the actual commit hook to new non-merge commits; leave old history intact."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = os.environ.get('BASE_SHA', '')
    if base and base != '0' * 40:
        if not re.fullmatch('[0-9a-f]{40}', base):
            raise SystemExit('BASE_SHA must be a full commit SHA')
        subprocess.run(['git', 'cat-file', '-e', base + '^{commit}'], cwd=ROOT, check=True)
        args = ['git', 'rev-list', '--no-merges', base + '..HEAD']
    else:
        args = ['git', 'rev-list', '--no-merges', '-1', 'HEAD']
    commits = subprocess.check_output(args, cwd=ROOT, text=True).splitlines()
    for sha in commits:
        message = subprocess.check_output(['git', 'show', '-s', '--format=%B', sha], cwd=ROOT)
        with tempfile.NamedTemporaryFile() as stream:
            stream.write(message)
            stream.flush()
            result = subprocess.run(['sh', str(ROOT / '.githooks/commit-msg'), stream.name], cwd=ROOT)
        if result.returncode:
            raise SystemExit(f'Commit attribution rejected: {sha}')
    print(f'Attribution checked: {len(commits)} new non-merge commits')


if __name__ == '__main__':
    main()
