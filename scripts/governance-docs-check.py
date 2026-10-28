#!/usr/bin/env python3
"""Check forced-load budgets, routes, links, phase claims and ADR headers."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []

BUDGETS = [
    ('AGENTS.md', 85, 5200),
    ('CONTEXT.md', 45, 3000),
    ('LESSONS.md', 20, 1800),
    ('CLAUDE.md', 12, 800),
    ('.cursorrules', 12, 800),
]

REQUIRED_SECTIONS = {
    'AGENTS.md': ['## 开局与按需读取', '## 不可跨越的边界', '## 治理文档自治理', 'docs/GOVERNANCE.md'],
    'CONTEXT.md': ['## 当前决策', '## 近期优先级', '## 最近验证', '## 按需入口'],
    'LESSONS.md': [
        'docs/lessons/governance.md',
        'docs/lessons/build.md',
        'docs/lessons/arm64.md',
        'docs/lessons/windows.md',
    ],
}

ROUTED_TARGETS = [
    'docs/GOVERNANCE.md',
    'docs/AI_RULES.md',
    'docs/PRODUCT.md',
    'docs/QUALITY.md',
    'docs/RISK_REGISTER.md',
    'docs/TECH_DEBT.md',
    'docs/MAINTAINERS.md',
    'docs/ADR/README.md',
    'docs/platforms.md',
    'docs/ci.md',
    'docs/test-matrix.md',
]

ADR_STATUSES = {'提议', '已接受', '部分替代', '已替代', '已拒绝'}
ADR_INDEX_ROW = re.compile(
    r'^\|\s*\[(\d{4})\]\(([^)]+)\)\s*\|\s*([^|]+?)\s*\|\s*([^|]*?)\s*\|\s*$', re.M)


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def ignored_paths(root: Path) -> set[str]:
    result = subprocess.run(
        ['git', 'ls-files', '--others', '--ignored', '--exclude-standard', '--directory', '-z'],
        cwd=root, capture_output=True, check=False)
    return {item.replace('\\', '/') for item in result.stdout.decode().split('\0') if item}


def is_ignored(path: Path, ignored: set[str], root: Path) -> bool:
    rel = path.resolve().relative_to(root).as_posix()
    for item in ignored:
        if item.endswith('/'):
            directory = item[:-1]
            if rel == directory or rel.startswith(item):
                return True
        elif rel == item:
            return True
    return False


def check_phase_claims(root: Path, context: str) -> None:
    if '**阶段：**' not in context:
        ERRORS.append('CONTEXT.md: 缺少 **阶段：** 行')
        return
    phase = re.search(r'\*\*阶段：\*\*\s*Phase\s+(\d+)', context)
    phase_n = phase.group(1) if phase else None
    for file in ('README.md', 'SECURITY.md'):
        path = root / file
        if not path.is_file():
            continue
        text = read(path)
        for claim in re.finditer(r'(?:当前处于|仍处于|项目处于)\s*\*{0,2}Phase\s+(\d+)', text):
            claimed = claim.group(1)
            if phase_n is None:
                ERRORS.append(
                    f'{file}: 声明 Phase {claimed}，但 CONTEXT.md 阶段行未提供 Phase 编号；'
                    '请改为引用 CONTEXT.md')
            elif claimed != phase_n:
                ERRORS.append(f'{file}: 当前阶段与 CONTEXT.md 不一致，请改为引用唯一事实源')


def check_adrs(root: Path) -> None:
    adr_dir = root / 'docs' / 'ADR'
    if not adr_dir.is_dir():
        return

    index: dict[str, tuple[str, str]] = {}
    index_path = adr_dir / 'README.md'
    if index_path.is_file():
        for row in ADR_INDEX_ROW.finditer(read(index_path)):
            number, target, status = row.group(1), row.group(2), row.group(3).strip()
            if number in index:
                ERRORS.append(f'docs/ADR/README.md: ADR {number} 索引重复')
            index[number] = (target, status)
            if status not in ADR_STATUSES:
                ERRORS.append(f'docs/ADR/README.md: ADR {number} 状态“{status}”不合法')
            if not target.startswith(f'{number}-') or not target.endswith('.md'):
                ERRORS.append(f'docs/ADR/README.md: ADR {number} 链接目标“{target}”与编号不符')

    adr_root = adr_dir.resolve()
    found: set[str] = set()
    for entry in sorted(adr_dir.iterdir()):
        if not entry.is_file() or not re.match(r'^\d{4}-.+\.md$', entry.name):
            continue
        number = entry.name[:4]
        if number in found:
            ERRORS.append(f'docs/ADR/{entry.name}: ADR 编号 {number} 重复')
            continue
        found.add(number)
        content = read(entry)
        status_match = re.search(r'^- 状态：(.+)$', content, re.M)
        if not status_match:
            ERRORS.append(f'docs/ADR/{entry.name}: 缺少合法状态')
            continue
        status = status_match.group(1).strip()
        if status not in ADR_STATUSES:
            ERRORS.append(f'docs/ADR/{entry.name}: 状态“{status}”不合法')
        if not re.search(r'^- 日期：\d{4}-\d{2}-\d{2}$', content, re.M):
            ERRORS.append(f'docs/ADR/{entry.name}: 缺少 ISO 日期')
        if number not in index:
            ERRORS.append(f'docs/ADR/{entry.name}: 未出现在 docs/ADR/README.md 索引中')
        elif index[number][0] != entry.name:
            ERRORS.append(
                f'docs/ADR/{entry.name}: 索引链接目标“{index[number][0]}”不是该文件')
        elif index[number][1] != status:
            ERRORS.append(
                f'docs/ADR/{entry.name}: 文件状态“{status}”与索引状态“{index[number][1]}”不一致')
        if status in {'部分替代', '已替代'}:
            successor = re.search(r'^- (?:替代决定|superseded by)[：:]\s*(.+)$', content, re.M)
            link = re.search(r'\[[^\]]+\]\(([^)]+\.md)\)', successor.group(1)) if successor else None
            if not link:
                ERRORS.append(
                    f'docs/ADR/{entry.name}: 状态为“{status}”但缺少指向替代 ADR 的链接')
            else:
                target = (entry.parent / link.group(1)).resolve()
                if (not target.is_file() or target.parent != adr_root
                        or not re.match(r'^\d{4}-.+\.md$', target.name)
                        or target.name[:4] == number):
                    ERRORS.append(
                        f'docs/ADR/{entry.name}: 替代链接必须指向存在的、编号不同的 ADR 文件')
            if status == '部分替代' and not re.search(r'^- 替代范围：\S', content, re.M):
                ERRORS.append(f'docs/ADR/{entry.name}: 部分替代缺少“替代范围”说明')

    for number in sorted(set(index) - found):
        ERRORS.append(f'docs/ADR/README.md: 索引中的 ADR {number} 没有对应文件')


def main(root: Path = DEFAULT_ROOT) -> int:
    root = root.resolve()
    ERRORS.clear()
    contents: dict[str, str] = {}
    for file, max_lines, max_chars in BUDGETS:
        path = root / file
        if not path.is_file():
            ERRORS.append(f'缺少强制加载文件：{file}')
            continue
        text = read(path)
        contents[file] = text
        lines = len(text.rstrip('\n').splitlines())
        characters = len(text)
        if lines > max_lines or characters > max_chars:
            ERRORS.append(f'{file}: {lines}/{max_lines} 行，{characters}/{max_chars} 字符')

    context = contents.get('CONTEXT.md', '')
    check_phase_claims(root, context)

    priority = re.search(r'## 近期优先级\s+([\s\S]*?)(?=\n## |$)', context)
    priorities = len(re.findall(r'^\d+\. ', priority.group(1) if priority else '', re.M))
    if priorities > 3:
        ERRORS.append(f'CONTEXT.md: 近期优先级不得超过 3 项，当前为 {priorities} 项')

    verification = re.search(r'## 最近验证\s+([\s\S]*?)(?=\n## |$)', context)
    for item in (verification.group(1) if verification else '').splitlines():
        if item.startswith('- ') and not re.search(r'\[[^\]]+\]\([^)]+\)', item):
            ERRORS.append('CONTEXT.md: 每条最近验证必须包含指向证据的 Markdown 链接')

    for forbidden in ('当前分支', '## 常用命令', '## 常用文档', '完整变更历史'):
        if forbidden in context:
            ERRORS.append(f'CONTEXT.md: 不应包含“{forbidden}”')

    for file, sections in REQUIRED_SECTIONS.items():
        content = contents.get(file, '')
        for section in sections:
            if section not in content:
                ERRORS.append(f'{file}: 缺少必需路由或章节“{section}”')

    for target in ROUTED_TARGETS:
        if not (root / target).is_file():
            ERRORS.append(f'缺少路由目标：{target}')

    ignored = ignored_paths(root)
    for path in root.rglob('*.md'):
        if is_ignored(path, ignored, root) or '.git' in path.parts:
            continue
        text = read(path)
        for match in re.finditer(r'\[[^\]]*\]\(([^)]+)\)', text):
            link = match.group(1).strip().strip('<>')
            if re.match(r'^(https?:|mailto:|#)', link, re.I):
                continue
            target = link.split('#', 1)[0]
            if not target:
                continue
            resolved = (path.parent / Path(target)).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            if is_ignored(resolved, ignored, root):
                ERRORS.append(f'{path.relative_to(root).as_posix()}: 相对链接指向 Git 忽略路径 {match.group(1)}')
            elif not resolved.exists():
                ERRORS.append(f'{path.relative_to(root).as_posix()}: 失效相对链接 {match.group(1)}')

    check_adrs(root)

    if ERRORS:
        print('治理文档检查失败：', file=sys.stderr)
        for error in ERRORS:
            print(f'- {error}', file=sys.stderr)
        return 1
    print('治理文档检查通过。')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT,
                        help='repository root to check (default: this repository)')
    arguments = parser.parse_args()
    raise SystemExit(main(arguments.root))
