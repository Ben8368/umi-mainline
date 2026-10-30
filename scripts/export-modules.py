#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Export matching kernel modules to a tarball without mounting any image/device."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def root_owner(info):
    """Give installed modules root ownership regardless of the build user."""
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    return info


def validate_modules(base, release, source_order):
    """Reject missing modules/indexes and links escaping the staged release."""
    moddir = base / 'lib/modules' / release
    if not moddir.is_dir():
        raise ValueError(f'modules_install did not create {moddir}')
    for name in ('build', 'source'):
        link = moddir / name
        if link.is_symlink():
            link.unlink()
    for path in moddir.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'unexpected module symlink: {path}')
    for name in ('modules.dep', 'modules.alias', 'modules.dep.bin', 'modules.alias.bin',
                 'modules.order', 'modules.builtin'):
        if not (moddir / name).is_file():
            raise ValueError(f'missing module index: {name}; install a working depmod')
    dep = (moddir / 'modules.dep').read_text()
    expected = []
    expected_order = []
    for line in source_order.splitlines():
        rel = PurePosixPath(line.strip())
        if rel.is_absolute() or '..' in rel.parts or rel.suffix not in ('.o', '.ko'):
            raise ValueError(f'invalid modules.order entry: {line!r}')
        installed = 'kernel/' + str(rel.with_suffix('.ko'))
        if installed in expected_order:
            raise ValueError(f'duplicate modules.order entry: {line!r}')
        expected_order.append(installed)
        candidates = [installed + ext for ext in ('', '.gz', '.xz', '.zst')]
        matches = [name for name in candidates if (moddir / name).is_file()]
        if len(matches) != 1 or (moddir / matches[0]).stat().st_size == 0:
            raise ValueError(f'missing/ambiguous installed module: {installed}')
        expected.append(matches[0])
    if not expected:
        raise ValueError('empty modules.order: run make modules first')
    if (moddir / 'modules.order').read_text().splitlines() != expected_order:
        raise ValueError('installed modules.order does not match this build')
    indexed = {line.split(':', 1)[0] for line in dep.splitlines() if ':' in line}
    if set(expected) - indexed:
        raise ValueError('modules.dep is incomplete for this kernel release')
    return moddir, len(expected)


def export(tree, out, dest, tc):
    tree, out, dest = (Path(p).resolve() for p in (tree, out, dest))
    for name in ('.config', 'System.map', 'modules.order', 'modules.builtin',
                 'arch/arm64/boot/Image.gz'):
        if not (out / name).is_file() or not (out / name).stat().st_size:
            raise ValueError(f'missing build input: {out / name}')
    if 'CONFIG_MODULES=y' not in (out / '.config').read_text().splitlines():
        raise ValueError('CONFIG_MODULES=y is required')
    if not shutil.which('depmod'):
        raise ValueError('depmod is required to export a usable module tree')
    make = ['make', '-s', '-C', str(tree), 'ARCH=arm64', f'O={out}']
    make += ['LLVM=1'] if tc == 'llvm' else ['CROSS_COMPILE=aarch64-none-elf-']
    release = subprocess.check_output(make + ['kernelrelease'], text=True).strip()
    if not re.fullmatch(r'[0-9][A-Za-z0-9._+-]*', release):
        raise ValueError(f'invalid kernelrelease: {release!r}')
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.modules-', dir=dest) as tmp:
        tmp = Path(tmp)
        stage = tmp / 'root'
        stage.mkdir()
        # Kbuild's depmod wrapper can skip indexing with exit 0, hence the
        # independent completeness check below. No rootfs or existing module
        # version is ever deleted or modified by this exporter.
        with (dest / 'modules-install.log').open('w') as log:
            subprocess.run(make + [f'INSTALL_MOD_PATH={stage}', 'INSTALL_MOD_STRIP=1',
                                   'modules_install'], check=True,
                           stdout=log, stderr=subprocess.STDOUT)
        moddir, count = validate_modules(stage, release, (out / 'modules.order').read_text())
        archive = tmp / f'modules-{release}.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(moddir, arcname=f'lib/modules/{release}', filter=root_owner)
        manifest = {
            'kernelrelease': release, 'module_count': count,
            'archive': archive.name, 'archive_sha256': sha256(archive),
            'image_sha256': sha256(out / 'arch/arm64/boot/Image.gz'),
            'config_sha256': sha256(out / '.config'),
            'source_revision': subprocess.check_output(
                ['git', '-C', str(tree), 'rev-parse', 'HEAD'], text=True).strip(),
            'note': 'Adaptation patches modify the kernel tree. Not a hardware acceptance record.',
        }
        (tmp / 'modules-manifest.json').write_text(
            json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        (tmp / 'kernelrelease').write_text(release + '\n', encoding='utf-8')
        # Publish only after modules_install, index checks and archiving succeed.
        for name in (archive.name, 'modules-manifest.json', 'kernelrelease'):
            os.replace(tmp / name, dest / name)
    print(f'Exported {count} modules for {release}: {dest / archive.name}')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--dest', required=True)
    parser.add_argument('--tc', choices=('gcc', 'llvm'), default='gcc')
    args = parser.parse_args()
    try:
        export(args.tree, args.out, args.dest, args.tc)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        parser.exit(1, f'module export failed: {exc}\n')


if __name__ == '__main__':
    main()
