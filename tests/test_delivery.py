#!/usr/bin/env python3
"""Offline delivery tests: source identity, ELF contracts, module staging failures."""
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULES = load('export-modules')
BUSYBOX = load('build-busybox')


def elf(machine=183, interpreter=False):
    data = bytearray(120)
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 18, machine)
    struct.pack_into('<Q', data, 32, 64)
    struct.pack_into('<HH', data, 54, 56, 1)
    struct.pack_into('<I', data, 64, 3 if interpreter else 1)
    return data


class DeliveryTests(unittest.TestCase):
    def test_tracked_firmware_inventory(self):
        self.assertEqual(load('check-firmware').check(), [])

    def test_changed_firmware_blocks_initramfs_without_overwriting_previous(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            shutil.copytree(ROOT / 'firmware', ws / 'firmware')
            (ws / 'stfts').mkdir()
            shutil.copyfile(ROOT / 'stfts/fts_fw.h', ws / 'stfts/fts_fw.h')
            (ws / 'scripts').mkdir()
            shutil.copyfile(ROOT / 'scripts/check-firmware.py', ws / 'scripts/check-firmware.py')
            shutil.copyfile(ROOT / 'scripts/build-busybox.py', ws / 'scripts/build-busybox.py')
            (ws / 'initramfs').mkdir()
            (ws / 'initramfs/init').write_text('#!/bin/sh\nexit 0\n')
            (ws / 'out').mkdir()
            previous = ws / 'out/initramfs.cpio.gz'
            previous.write_text('LAST_GOOD')
            bb = ws / 'busybox'
            bb.write_bytes(elf())
            bb.chmod(0o755)
            (ws / 'firmware/qcom/a650_sqe.fw').write_bytes(b'UNREVIEWED')
            env = {**os.environ, 'WS': str(ws), 'BB': str(bb), 'BUILD': str(ws / 'assembly')}
            run = subprocess.run(['sh', str(ROOT / 'scripts/mkinitramfs.sh')], env=env,
                                 capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('firmware identity changed', run.stdout)
            self.assertEqual(previous.read_text(), 'LAST_GOOD')
            self.assertFalse((ws / 'assembly').exists())

    def test_busybox_rejects_wrong_arch_dynamic_and_truncated_executables(self):
        for data, accepted in [(elf(), True), (elf(62), False),
                               (elf(interpreter=True), False), (b'#! /bin/sh', False),
                               (elf()[:80], False)]:
            with self.subTest(accepted=accepted), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'busybox'
                path.write_bytes(data)
                if accepted:
                    BUSYBOX.verify_binary(path)
                else:
                    with self.assertRaises(ValueError):
                        BUSYBOX.verify_binary(path)

    def test_source_archive_refuses_traversal_and_wrong_root(self):
        for name in ('../../escape', 'other/Makefile', 'busybox-1.37.0/../../escape'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                archive = base / 'source.tar.bz2'
                with tarfile.open(archive, 'w:bz2') as tar:
                    tar.addfile(tarfile.TarInfo(name))
                with self.assertRaises((ValueError, tarfile.TarError)):
                    BUSYBOX.extract_source(archive, base / 'extract', '1.37.0')

    def test_busybox_checksum_mismatch_preserves_previous_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / 'busybox'
            binary.write_text('OLD')
            source = base / 'wrong.tar.bz2'
            source.write_text('NOT THE PINNED SOURCE')
            args = type('Args', (), dict(cross_compile='aarch64-linux-gnu-',
                                        output=binary, work_dir=base,
                                        source_archive=source, jobs=1))()
            with patch.object(BUSYBOX.shutil, 'which', return_value='/fake/gcc'), \
                 patch.object(BUSYBOX.subprocess, 'check_output', return_value='aarch64-linux-gnu\n'), \
                 patch.object(BUSYBOX.subprocess, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                    BUSYBOX.build(args)
                run.assert_not_called()
            self.assertEqual(binary.read_text(), 'OLD')

    def test_busybox_rejects_bare_metal_toolchain(self):
        args = type('Args', (), dict(cross_compile='aarch64-none-elf-'))()
        with patch.object(BUSYBOX.shutil, 'which', return_value='/fake/gcc'), \
             patch.object(BUSYBOX.subprocess, 'check_output', return_value='aarch64-none-elf\n'):
            with self.assertRaisesRegex(ValueError, 'Linux libc toolchain'):
                BUSYBOX.build(args)

    def test_module_validator_checks_every_module_and_indexes(self):
        for fault in ('none', 'missing-ko', 'missing-index', 'incomplete-dep',
                      'wrong-order', 'duplicate-order', 'escape'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                moddir = base / 'lib/modules/6.18.59-umi'
                module = moddir / 'kernel/drivers/wifi.ko'
                module.parent.mkdir(parents=True)
                module.write_bytes(b'module')
                for name in ('modules.alias', 'modules.dep.bin', 'modules.alias.bin',
                             'modules.order', 'modules.builtin'):
                    (moddir / name).write_text('fixture\n')
                (moddir / 'modules.order').write_text('kernel/drivers/wifi.ko\n')
                (moddir / 'modules.dep').write_text('kernel/drivers/wifi.ko:\n')
                (moddir / 'build').symlink_to('/nonexistent/kernel-build')
                if fault == 'missing-ko':
                    module.unlink()
                elif fault == 'missing-index':
                    (moddir / 'modules.dep.bin').unlink()
                elif fault == 'incomplete-dep':
                    (moddir / 'modules.dep').write_text('')
                elif fault == 'wrong-order':
                    (moddir / 'modules.order').write_text('kernel/drivers/stale.ko\n')
                elif fault == 'escape':
                    (moddir / 'bad-link').symlink_to('/etc/passwd')
                if fault == 'none':
                    actual, count = MODULES.validate_modules(base, '6.18.59-umi', 'drivers/wifi.o\n')
                    self.assertEqual(actual, moddir)
                    self.assertEqual(count, 1)
                    self.assertFalse((moddir / 'build').is_symlink())
                else:
                    with self.assertRaises(ValueError):
                        order = 'drivers/wifi.o\n' * (2 if fault == 'duplicate-order' else 1)
                        MODULES.validate_modules(base, '6.18.59-umi', order)

    def test_actual_module_export_failure_and_success(self):
        for mode in ('success', 'install-failure', 'missing-index', 'bad-release'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                out, dest, tree = base / 'out', base / 'deliver', base / 'tree'
                tree.mkdir()
                dest.mkdir()
                qcom = out / 'arch/arm64/boot/dts/qcom'
                qcom.mkdir(parents=True)
                for name in ('.config', 'System.map', 'modules.builtin', 'arch/arm64/boot/Image.gz'):
                    (out / name).parent.mkdir(parents=True, exist_ok=True)
                    (out / name).write_text('CONFIG_MODULES=y\n')
                for name in MODULES.BUILD_ARTIFACTS:
                    if name.endswith('.dtb'):
                        (qcom / name).write_text('FIXTURE-' + name)
                (out / 'modules.order').write_text('drivers/wifi.o\n')
                archive = dest / 'modules-6.18.59-umi.tar.gz'
                archive.write_text('PREVIOUS')
                bindir = base / 'bin'
                bindir.mkdir()
                make = bindir / 'make'
                make.write_text('''#!/bin/sh
for arg do
    case "$arg" in
        kernelrelease) [ "$MODE" != bad-release ] || { echo '../escape'; exit; }; echo 6.18.59-umi; exit ;;
        INSTALL_MOD_PATH=*) stage=${arg#*=} ;;
    esac
done
[ "$MODE" != install-failure ] || exit 17
moddir="$stage/lib/modules/6.18.59-umi"
mkdir -p "$moddir/kernel/drivers"
printf module > "$moddir/kernel/drivers/wifi.ko"
printf 'kernel/drivers/wifi.ko\\n' > "$moddir/modules.order"
printf 'kernel/drivers/wifi.ko:\\n' > "$moddir/modules.dep"
for name in modules.alias modules.dep.bin modules.alias.bin modules.builtin; do
    printf index > "$moddir/$name"
done
[ "$MODE" != missing-index ] || rm "$moddir/modules.alias.bin"
''')
                make.chmod(0o755)
                git = bindir / 'git'
                git.write_text('#!/bin/sh\nprintf "fixture-kernel-revision\\n"\n')
                git.chmod(0o755)
                depmod = bindir / 'depmod'
                depmod.write_text('#!/bin/sh\nexit 0\n')
                depmod.chmod(0o755)
                env = {**os.environ, 'MODE': mode, 'PATH': str(bindir) + os.pathsep + os.environ['PATH']}
                run = subprocess.run(['python3', str(ROOT / 'scripts/export-modules.py'),
                                      '--tree', str(tree), '--out', str(out), '--dest', str(dest),
                                      '--collect-build-artifacts'],
                                     env=env, capture_output=True, text=True)
                if mode == 'success':
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    manifest = json.loads((dest / 'modules-manifest.json').read_text())
                    self.assertEqual(manifest['module_count'], 1)
                    self.assertEqual(manifest['archive_sha256'], MODULES.sha256(archive))
                    self.assertEqual((dest / 'Image.gz').read_text(), 'CONFIG_MODULES=y\n')
                    self.assertEqual(manifest['image_sha256'], MODULES.sha256(dest / 'Image.gz'))
                    self.assertEqual((dest / 'config-effective').read_text(), 'CONFIG_MODULES=y\n')
                    expected_dtb_names = {name for name in MODULES.BUILD_ARTIFACTS
                                           if name.endswith('.dtb')}
                    self.assertEqual(set(manifest['dtb_sha256']), expected_dtb_names)
                    for name in MODULES.BUILD_ARTIFACTS:
                        if name.endswith('.dtb'):
                            self.assertEqual((dest / name).read_text(), 'FIXTURE-' + name)
                            self.assertEqual(manifest['dtb_sha256'][name],
                                             MODULES.sha256(dest / name))
                    with tarfile.open(archive) as tar:
                        self.assertIn('lib/modules/6.18.59-umi/kernel/drivers/wifi.ko', tar.getnames())
                        for member in tar.getmembers():
                            self.assertEqual((member.uid, member.gid, member.uname, member.gname),
                                             (0, 0, 'root', 'root'))
                else:
                    self.assertNotEqual(run.returncode, 0)
                    self.assertEqual(archive.read_text(), 'PREVIOUS')
                    self.assertFalse((dest / 'kernelrelease').exists())
                self.assertFalse(any(dest.glob('.modules-*')))

    def test_initramfs_source_default_and_explicit_binary_failure(self):
        source = (ROOT / 'scripts/mkinitramfs.sh').read_text()
        selection = source[source.index('WS=${'):source.index('# ---- 设备侧文本')]
        for bb in (None, '', 'missing-prebuilt'):
            with self.subTest(bb=bb), tempfile.TemporaryDirectory() as tmp:
                ws = Path(tmp)
                (ws / 'scripts').mkdir()
                (ws / 'scripts/build-busybox.py').write_text(
                    'import pathlib,sys\np=pathlib.Path(sys.argv[-1]); p.parent.mkdir(parents=True, exist_ok=True); '
                    'p.write_text("SOURCE"); p.chmod(0o755)\n')
                env = {key: val for key, val in os.environ.items() if key != 'BB'}
                env['WS'] = str(ws)
                if bb is not None:
                    env['BB'] = str(ws / bb) if bb else ''
                run = subprocess.run(['sh', '-c', 'set -e\n' + selection], env=env,
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, 2 if bb else 0, run.stderr)
                self.assertEqual((ws / 'out/busybox/busybox.static').exists(), not bool(bb))

    def test_publication_failure_restores_each_previous_delivery_set(self):
        names = ('modules-test.tar.gz', 'modules-manifest.json', 'kernelrelease')
        for existing in range(8):
            for fail_at in range(1, 4):
                with self.subTest(existing=existing, fail_at=fail_at), \
                     tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    stage, dest = base / 'stage', base / 'dest'
                    stage.mkdir()
                    dest.mkdir()
                    expected = {}
                    for index, name in enumerate(names):
                        (stage / name).write_bytes(b'NEW-' + name.encode())
                        if existing & (1 << index):
                            expected[name] = b'OLD-' + name.encode()
                            (dest / name).write_bytes(expected[name])
                    (dest / 'unrelated').write_bytes(b'KEEP')
                    expected['unrelated'] = b'KEEP'
                    replace = os.replace
                    calls = 0

                    def fail_once(src, dst):
                        nonlocal calls
                        calls += 1
                        if calls == fail_at:
                            raise OSError('injected publication failure')
                        replace(src, dst)

                    with patch.object(MODULES.os, 'replace', side_effect=fail_once):
                        with self.assertRaisesRegex(OSError, 'injected publication failure'):
                            MODULES.publish_files(stage, dest, names)
                    self.assertEqual({p.name: p.read_bytes() for p in dest.iterdir()}, expected)

    def test_publication_backup_failure_never_changes_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            stage, dest = base / 'stage', base / 'dest'
            stage.mkdir()
            dest.mkdir()
            for name in ('archive', 'manifest'):
                (stage / name).write_bytes(b'NEW')
                (dest / name).write_bytes(b'OLD')
            copy = MODULES.shutil.copy2

            def fail_second_backup(src, dst):
                if src.name == 'manifest':
                    raise OSError('backup failure')
                return copy(src, dst)

            with patch.object(MODULES.shutil, 'copy2', side_effect=fail_second_backup):
                with self.assertRaisesRegex(OSError, 'backup failure'):
                    MODULES.publish_files(stage, dest, ('archive', 'manifest'))
            self.assertEqual({p.name: p.read_bytes() for p in dest.iterdir()},
                             {'archive': b'OLD', 'manifest': b'OLD'})

    def test_publication_retains_backups_and_attempts_remaining_rollback_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            stage, dest = base / 'stage', base / 'dest'
            stage.mkdir()
            dest.mkdir()
            names = ('archive', 'manifest', 'release')
            for name in names:
                (stage / name).write_bytes(b'NEW')
                (dest / name).write_bytes(b'OLD-' + name.encode())
            replace = os.replace

            def fail_publish_and_one_restore(src, dst):
                if src == stage / 'release' or (src.parent != stage and dst.name == 'manifest'):
                    raise OSError('injected persistent failure')
                replace(src, dst)

            with patch.object(MODULES.os, 'replace', side_effect=fail_publish_and_one_restore):
                with self.assertRaisesRegex(OSError, 'recovery backups retained'):
                    MODULES.publish_files(stage, dest, names)
            self.assertEqual((dest / 'archive').read_bytes(), b'OLD-archive')
            self.assertEqual((dest / 'release').read_bytes(), b'OLD-release')
            backup_dirs = list(dest.glob('.modules-backup-*'))
            self.assertEqual(len(backup_dirs), 1)
            self.assertEqual((backup_dirs[0] / 'manifest').read_bytes(), b'OLD-manifest')

    def test_build_delivery_publication_restores_all_eight_files(self):
        names = ('modules-test.tar.gz', 'modules-manifest.json', 'kernelrelease',
                 *MODULES.BUILD_ARTIFACTS.keys())
        for existing in (False, True):
            for fail_at in range(1, len(names) + 1):
                with self.subTest(existing=existing, fail_at=fail_at), \
                     tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    stage, dest = base / 'stage', base / 'dest'
                    stage.mkdir()
                    dest.mkdir()
                    expected = {'unrelated': b'KEEP'}
                    (dest / 'unrelated').write_bytes(expected['unrelated'])
                    for name in names:
                        (stage / name).write_bytes(b'NEW-' + name.encode())
                        if existing:
                            expected[name] = b'OLD-' + name.encode()
                            (dest / name).write_bytes(expected[name])
                    replace = os.replace
                    calls = 0

                    def fail_once(src, dst):
                        nonlocal calls
                        calls += 1
                        if calls == fail_at:
                            raise OSError('injected publication failure')
                        replace(src, dst)

                    with patch.object(MODULES.os, 'replace', side_effect=fail_once):
                        with self.assertRaisesRegex(OSError, 'injected publication failure'):
                            MODULES.publish_files(stage, dest, names)
                    self.assertEqual({p.name: p.read_bytes() for p in dest.iterdir()}, expected)

    def test_busybox_publication_restores_the_three_output_files(self):
        names = ('busybox.static.config', 'busybox.static.json', 'busybox.static')
        for existing in range(8):
            for fail_at in range(1, 4):
                with self.subTest(existing=existing, fail_at=fail_at), \
                     tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    stage, dest = base / 'stage', base / 'dest'
                    stage.mkdir()
                    dest.mkdir()
                    expected = {'unrelated': b'KEEP'}
                    (dest / 'unrelated').write_bytes(expected['unrelated'])
                    for index, name in enumerate(names):
                        (stage / name).write_bytes(b'NEW-' + name.encode())
                        if existing & (1 << index):
                            expected[name] = b'OLD-' + name.encode()
                            (dest / name).write_bytes(expected[name])
                    replace = os.replace
                    calls = 0

                    def fail_once(src, dst):
                        nonlocal calls
                        calls += 1
                        if calls == fail_at:
                            raise OSError('injected BusyBox publication failure')
                        replace(src, dst)

                    with patch.object(BUSYBOX.os, 'replace', side_effect=fail_once):
                        with self.assertRaisesRegex(OSError, 'injected BusyBox publication failure'):
                            BUSYBOX.publish_files(stage, dest, names)
                    self.assertEqual({p.name: p.read_bytes() for p in dest.iterdir()}, expected)

    def test_busybox_publication_keeps_recovery_copy_if_rollback_fails(self):
        names = ('busybox.static.config', 'busybox.static.json', 'busybox.static')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            stage, dest = base / 'stage', base / 'dest'
            stage.mkdir()
            dest.mkdir()
            for name in names:
                (stage / name).write_bytes(b'NEW-' + name.encode())
                (dest / name).write_bytes(b'OLD-' + name.encode())
            replace = os.replace

            def fail_publish_and_one_restore(src, dst):
                if src == stage / names[-1] or (src.parent != stage and dst.name == names[1]):
                    raise OSError('injected persistent BusyBox failure')
                replace(src, dst)

            with patch.object(BUSYBOX.os, 'replace', side_effect=fail_publish_and_one_restore):
                with self.assertRaisesRegex(OSError, 'recovery backups retained'):
                    BUSYBOX.publish_files(stage, dest, names)
            self.assertEqual((dest / names[0]).read_bytes(), b'OLD-' + names[0].encode())
            self.assertEqual((dest / names[-1]).read_bytes(), b'OLD-' + names[-1].encode())
            backup_dirs = list(dest.glob('.busybox-backup-*'))
            self.assertEqual(len(backup_dirs), 1)
            self.assertEqual((backup_dirs[0] / names[1]).read_bytes(), b'OLD-' + names[1].encode())

    def test_busybox_cli_verifies_prebuilt_architecture_and_static_linking(self):
        for data, expected in ((elf(), 0), (elf(62), 1), (elf(interpreter=True), 1)):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                binary = Path(tmp) / 'busybox'
                binary.write_bytes(data)
                run = subprocess.run([sys.executable, str(ROOT / 'scripts/build-busybox.py'),
                                      '--verify', str(binary)], capture_output=True, text=True)
                self.assertEqual(run.returncode, expected, run.stdout + run.stderr)


    def test_prepare_tree_refuses_existing_nonrepository_or_wrong_revision(self):
        for is_git in (False, True):
            with self.subTest(is_git=is_git), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                dst = base / 'existing'
                dst.mkdir()
                (dst / 'precious').write_text('PRESERVE')
                if is_git:
                    (dst / '.git').mkdir()
                bindir = base / 'bin'
                bindir.mkdir()
                git = bindir / 'git'
                git.write_text('#!/bin/sh\nprintf wrong-revision\\n\n')
                git.chmod(0o755)
                env = {**os.environ, 'WS': str(ROOT), 'DST': str(dst),
                       'PATH': str(bindir) + os.pathsep + os.environ['PATH']}
                result = subprocess.run(['sh', str(ROOT / 'scripts/prepare-tree.sh')],
                                        env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((dst / 'precious').read_text(), 'PRESERVE')
                self.assertFalse((dst / 'arch').exists())

    def test_fast_dtb_build_syncs_all_includes_and_defaults_to_three_variants(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ws, tree, out = base / 'ws', base / 'kernel', base / 'out'
            shutil.copytree(ROOT / 'dts', ws / 'dts')
            shutil.copytree(ROOT / 'config', ws / 'config')
            qcom = tree / 'arch/arm64/boot/dts/qcom'
            qcom.mkdir(parents=True)
            (qcom / 'umi-spmi-overlay-guard.dtsi').write_text('STALE')
            bindir = base / 'bin'
            bindir.mkdir()
            for name in ('gcc', 'dtc'):
                command = bindir / name
                command.write_text('''#!/bin/sh
[ "$1" != -print-file-name=include ] || { echo /tmp; exit; }
while [ "$#" -gt 0 ]; do
    if [ "$1" = -o ]; then shift; printf fresh > "$1"; exit; fi
    shift
done
exit 8
''')
                command.chmod(0o755)
            env = {**os.environ, 'WS': str(ws), 'TREE': str(tree), 'OUT': str(out),
                   'PATH': str(bindir) + os.pathsep + os.environ['PATH']}
            run = subprocess.run(['sh', str(ROOT / 'scripts/dtb-only.sh')], env=env,
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(len(list(out.glob('*.dtb'))), 3)
            for name in ('umi-spmi-overlay-guard.dtsi', 'xiaomi-umi-battery.dtsi',
                         'sm8250-xiaomi-umi-wifi.dts', 'xiaomi-umi-thermistors.dtsi'):
                self.assertEqual((qcom / name).read_bytes(), (ROOT / 'dts' / name).read_bytes())
            for name in ('umi-spmi-overlay-guard.dtsi', 'xiaomi-umi-thermistors.dtsi'):
                path = ws / 'dts' / name
                saved = path.read_bytes()
                path.unlink()
                run = subprocess.run(['sh', str(ROOT / 'scripts/dtb-only.sh')], env=env,
                                     capture_output=True, text=True)
                self.assertNotEqual(run.returncode, 0, 'must not reuse missing include from kernel tree')
                path.write_bytes(saved)


    def test_radio_build_gate_rejects_missing_features(self):
        # Execute the actual shell gate with synthetic olddefconfig output.
        # A successful kernel build must not hide missing BLE, serdev or UHID.
        source = (ROOT / 'scripts/build.sh').read_text()
        functions = source[source.index('cfgval() {'):source.index('for s in SERIAL_QCOM_GENI')]
        gate = source[source.index('# Radio drivers remain'):source.index('# 6.12 uses the old spelling')]
        modules = ('ATH11K ATH11K_PCI MHI_BUS QRTR QRTR_MHI QCOM_QMI_HELPERS '
                   'CFG80211 MAC80211 RTC_DRV_PM8XXX BT BT_HCIUART BT_QCA '
                   'BT_RFCOMM BT_BNEP BT_HIDP UHID HID_GENERIC '
                   'SND_SOC_CS35L41_I2C SPI_QCOM_GENI RC_CORE IR_SPI').split()
        booleans = ('SERIAL_DEV_BUS SERIAL_DEV_CTRL_TTYPORT BT_BREDR BT_LE '
                    'BT_HCIUART_SERDEV BT_HCIUART_QCA LIRC').split()
        cases = [(None, 'm'), (None, 'y')]
        cases += [(symbol, 'm') for symbol in modules + booleans]
        for removed, module_value in cases:
            with self.subTest(removed=removed, modules=module_value), tempfile.TemporaryDirectory() as tmp:
                lines = [f'CONFIG_{name}={module_value}' for name in modules if name != removed]
                lines += [f'CONFIG_{name}=y' for name in booleans if name != removed]
                if removed:
                    lines.append(f'# CONFIG_{removed} is not set')
                (Path(tmp) / '.config').write_text('\n'.join(lines) + '\n')
                result = subprocess.run(['sh', '-c', 'fail=0\n' + functions + gate + '\nexit "$fail"'],
                                        env={**os.environ, 'OUT': tmp}, capture_output=True, text=True)
                self.assertEqual(result.returncode, int(removed is not None), result.stdout + result.stderr)
                if removed:
                    self.assertIn('FAIL ' + removed, result.stdout)

if __name__ == '__main__':
    unittest.main()
