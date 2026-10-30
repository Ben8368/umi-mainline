#!/usr/bin/env python3
# SPDX-License-Identifier: CC0-1.0
"""Build a pinned GPL BusyBox from source for the arm64 rescue initramfs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'config/source-lock.json'
REQUIRED_APPLETS = ('ASH', 'SH_IS_ASH', 'MOUNT', 'UMOUNT', 'SWITCH_ROOT',
                    'MDEV', 'CTTYHACK', 'SETSID', 'REBOOT', 'POWEROFF',
                    'FEATURE_INSTALLER', 'MODPROBE', 'DEPMOD')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_binary(path):
    """Do not execute target code: require little-endian ELF64/AArch64, no PT_INTERP."""
    data = path.read_bytes()
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('BusyBox must be little-endian ELF64')
    if struct.unpack_from('<H', data, 18)[0] != 183:
        raise ValueError('BusyBox must target AArch64, not the build host')
    offset = struct.unpack_from('<Q', data, 32)[0]
    entry_size, count = struct.unpack_from('<HH', data, 54)
    if entry_size < 56 or count == 0 or offset + entry_size * count > len(data):
        raise ValueError('invalid ELF program headers')
    executable_load = False
    for i in range(count):
        header = offset + i * entry_size
        kind, flags = struct.unpack_from('<II', data, header)
        if kind == 3:
            raise ValueError('BusyBox must be static (no PT_INTERP)')
        if kind == 1 and flags & 1:
            executable_load = True
    if not executable_load:
        raise ValueError('BusyBox must have an executable PT_LOAD segment')


def publish_files(stage, dest, names):
    """Publish a related file set, restoring old outputs if replacement fails."""
    backup_dir = Path(tempfile.mkdtemp(prefix='.busybox-backup-', dir=dest))
    backups = {}
    keep_backups = False
    try:
        for name in names:
            previous = dest / name
            if previous.is_symlink() or (previous.exists() and not previous.is_file()):
                raise ValueError(f'not a regular BusyBox output: {previous}')
            backups[name] = None
            if previous.exists():
                backup = backup_dir / name
                shutil.copy2(previous, backup)
                backups[name] = backup
        published = []
        try:
            for name in names:
                os.replace(stage / name, dest / name)
                published.append(name)
        except OSError as error:
            failures = []
            for name in reversed(published):
                try:
                    if backups[name] is None:
                        (dest / name).unlink()
                    else:
                        os.replace(backups[name], dest / name)
                except OSError as rollback_error:
                    failures.append(f'{name}: {rollback_error}')
            if failures:
                keep_backups = True
                raise OSError(f'{error}; rollback failed: {"; ".join(failures)}; '
                              f'recovery backups retained at {backup_dir}') from error
            raise
    finally:
        if not keep_backups:
            shutil.rmtree(backup_dir)


def extract_source(archive, destination, version):
    expected = f'busybox-{version}'
    with tarfile.open(archive, 'r:bz2') as tar:
        if any(not member.name.startswith(expected + '/') and member.name != expected
               for member in tar.getmembers()):
            raise ValueError('unexpected source archive layout')
        # Python's data filter refuses traversal, devices and escaping symlinks.
        tar.extractall(destination, filter='data')
    return destination / expected


def build(args):
    if sys.platform != 'linux':
        raise ValueError('Build in Linux/WSL on a case-sensitive filesystem')
    lock = json.loads(LOCK.read_text(encoding='utf-8'))['busybox']
    cross = args.cross_compile
    compiler = shutil.which(cross + 'gcc')
    if not compiler:
        raise ValueError(f'{cross}gcc not found; install an arm64 Linux libc toolchain')
    target = subprocess.check_output([compiler, '-dumpmachine'], text=True).strip()
    if not target.startswith('aarch64') or 'linux' not in target:
        raise ValueError(f'aarch64 Linux libc toolchain required, got {target}')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='umi-busybox-', dir=args.work_dir) as tmp:
        work = Path(tmp)
        archive = work / 'source.tar.bz2'
        if args.source_archive:
            shutil.copyfile(args.source_archive, archive)
        else:
            with urllib.request.urlopen(lock['url'], timeout=60) as response:
                with archive.open('wb') as stream:
                    shutil.copyfileobj(response, stream)
        if sha256(archive) != lock['sha256']:
            raise ValueError('BusyBox source SHA256 mismatch; nothing built or published')
        source = extract_source(archive, work, lock['version'])
        env = {**os.environ, 'KCONFIG_NOTIMESTAMP': '1', 'SOURCE_DATE_EPOCH': '0',
               'KBUILD_BUILD_TIMESTAMP': '1970-01-01 00:00:00 UTC',
               'KBUILD_BUILD_USER': 'builder', 'KBUILD_BUILD_HOST': 'umi'}
        make = ['make', '-C', str(source), 'ARCH=arm64', f'CROSS_COMPILE={cross}']
        subprocess.run(make + ['defconfig'], env=env, check=True,
                       stdout=subprocess.DEVNULL)
        config = source / '.config'
        lines = config.read_text().splitlines()
        # BusyBox 1.37 tc refers to CBQ UAPI removed from current libc headers.
        # Rescue init never uses tc; a real rootfs can use source-built iproute2.
        # Use portable hashes: 1.37's default SHA-NI options assume x86.
        options = {'STATIC': 'y', 'TC': 'n', 'SHA1_HWACCEL': 'n',
                   'SHA256_HWACCEL': 'n', **{key: 'y' for key in REQUIRED_APPLETS}}
        for key, value in options.items():
            lines = [line for line in lines if not line.startswith(f'CONFIG_{key}=')
                     and line != f'# CONFIG_{key} is not set']
            lines.append(f'CONFIG_{key}=y' if value == 'y' else f'# CONFIG_{key} is not set')
        config.write_text('\n'.join(lines) + '\n')
        subprocess.run(make + ['oldconfig'], input='\n' * 2048, text=True, env=env,
                       check=True, stdout=subprocess.DEVNULL)
        for key, value in options.items():
            expected = f'CONFIG_{key}=y' if value == 'y' else f'# CONFIG_{key} is not set'
            if expected not in config.read_text().splitlines():
                raise ValueError(f'BusyBox config dropped required option {key}')
        log = output.with_name(output.name + '.build.log')
        with log.open('w') as stream:
            subprocess.run(make + [f'-j{args.jobs}'], env=env, check=True,
                           stdout=stream, stderr=subprocess.STDOUT)
        binary = source / 'busybox'
        verify_binary(binary)
        provenance = {
            **lock, 'binary_sha256': sha256(binary), 'config_sha256': sha256(config),
            'compiler': subprocess.check_output([compiler, '--version'], text=True).splitlines()[0],
            'target': target, 'validation': 'ELF64 AArch64 static; not executed on device',
        }
        # Keep the source identity and actual configuration with the executable.
        # A temporary sibling makes publication safe across filesystems.
        with tempfile.TemporaryDirectory(prefix='.busybox-', dir=output.parent) as staged:
            staged = Path(staged)
            shutil.copyfile(binary, staged / output.name)
            (staged / output.name).chmod(0o755)
            shutil.copyfile(config, staged / (output.name + '.config'))
            (staged / (output.name + '.json')).write_text(
                json.dumps(provenance, indent=2) + '\n', encoding='utf-8')
            publish_files(staged, output.parent,
                          (output.name + '.config', output.name + '.json', output.name))
    print(f'Source-built static arm64 BusyBox: {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cross-compile', default=os.environ.get('CROSS_COMPILE', 'aarch64-linux-gnu-'))
    parser.add_argument('--source-archive', type=Path, help='offline tar.bz2; still checked against lock')
    parser.add_argument('--work-dir', type=Path, help='Linux/WSL ext4 build parent (default system temp)')
    parser.add_argument('--output', type=Path, default=ROOT / 'out/busybox/busybox.static')
    parser.add_argument('--jobs', type=int, default=min(12, os.cpu_count() or 1))
    parser.add_argument('--verify', type=Path,
                        help='verify an existing ELF64 AArch64 static BusyBox without building')
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    if args.verify:
        try:
            verify_binary(args.verify)
        except (OSError, ValueError, struct.error) as exc:
            parser.exit(1, f'BusyBox verification failed: {exc}\n')
        return
    try:
        build(args)
    except (OSError, ValueError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        parser.exit(1, f'BusyBox source build failed: {exc}\n')


if __name__ == '__main__':
    main()
