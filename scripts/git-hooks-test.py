#!/usr/bin/env python3
"""Regression tests for commit attribution hooks in an isolated repository."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CODEX = 'Co-authored-by: Codex <codex@openai.com>'
CURSOR = 'Co-authored-by: Cursor <cursoragent@cursor.com>'
CLAUDE = 'Co-authored-by: Claude Code <noreply@anthropic.com>'
JULES = 'Co-authored-by: Google Labs Jules <161369871+google-labs-jules[bot]@users.noreply.github.com>'


def run(repo: Path, args: list[str], env: dict[str, str]):
    return subprocess.run(['git', '-C', str(repo), *args], text=True,
                          capture_output=True, env=env, check=False)


def main() -> int:
    failures = 0
    with tempfile.TemporaryDirectory(prefix='umi-git-hooks-') as tmp:
        fixture = Path(tmp)
        repo = fixture / 'repo'
        (repo / '.githooks').mkdir(parents=True)
        shutil.copy2(ROOT / '.githooks' / 'commit-msg', repo / '.githooks' / 'commit-msg')
        empty_config = fixture / 'empty-git-config'
        empty_config.write_text('')
        env = os.environ.copy()
        env['GIT_CONFIG_GLOBAL'] = str(empty_config)
        env['GIT_CONFIG_NOSYSTEM'] = '1'

        def checked(args: list[str]) -> str:
            result = run(repo, args, env)
            if result.returncode != 0:
                raise AssertionError(result.stderr or result.stdout)
            return result.stdout.strip()

        checked(['init', '--quiet'])
        for key, value in (
            ('user.name', 'Hook Fixture'),
            ('user.email', 'fixture@example.invalid'),
            ('commit.gpgsign', 'false'),
            ('core.autocrlf', 'false'),
        ):
            checked(['config', '--local', key, value])

        # install script
        install = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'install-git-hooks.py'), str(repo)],
            text=True, capture_output=True, env=env, check=False)
        if install.returncode != 0:
            print(install.stderr)
            return 1
        if checked(['config', '--local', '--get', 'core.hooksPath']) != '.githooks':
            print('hooksPath not set')
            return 1

        (repo / 'content.txt').write_text('fixture\n', encoding='utf-8')
        checked(['add', 'content.txt'])
        cases = [
            ('missing', 'fix: fixture\n', False),
            ('literal-escapes', f'fix: fixture\\n\\n{CODEX}', False),
            ('wrong-email', 'fix: fixture\n\nCo-authored-by: Codex <wrong@example.invalid>\n', False),
            ('contradictory', f'fix: fixture\n\n{CODEX}\nHuman-authored: true\n', False),
            ('codex', f'fix: fixture\n\n{CODEX}\n', True),
            ('cursor', f'fix: fixture\n\n{CURSOR}\n', True),
            ('claude', f'fix: fixture\n\n{CLAUDE}\n', True),
            ('jules', f'fix: fixture\n\n{JULES}\n', True),
            ('jules-wrong-email', 'fix: fixture\n\nCo-authored-by: Google Labs Jules <wrong@example.invalid>\n', False),
            ('jules-contradictory', f'fix: fixture\n\n{JULES}\nHuman-authored: true\n', False),
            ('renovate', 'ci: fixture\n\nBot-authored-by: Renovate <29139614+renovate[bot]@users.noreply.github.com>\n', True),
            ('human', 'fix: fixture\n\nHuman-authored: true\n', True),
        ]
        message_path = fixture / 'message.txt'
        for name, message, accepted in cases:
            message_path.write_text(message, encoding='utf-8', newline='\n')
            before = run(repo, ['rev-parse', '--verify', 'HEAD'], env)
            result = run(repo, ['commit', '--allow-empty', '--cleanup=verbatim', '-F', str(message_path)], env)
            ok = result.returncode == 0
            if ok != accepted:
                print(f'FAIL {name}: expected accepted={accepted}, rc={result.returncode}')
                print(result.stderr or result.stdout)
                failures += 1
            elif not accepted:
                after = run(repo, ['rev-parse', '--verify', 'HEAD'], env)
                if after.stdout != before.stdout or after.returncode != before.returncode:
                    print(f'FAIL {name}: rejected commit still moved HEAD')
                    failures += 1
            else:
                print(f'PASS {name}')
    if failures:
        print(f'{failures} git-hooks tests failed')
        return 1
    print('git-hooks tests passed')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
