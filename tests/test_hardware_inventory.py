#!/usr/bin/env python3
"""Execute passive inventory against isolated sysfs fixtures, never real devices."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/hardware-inventory.sh'


class HardwareInventoryTests(unittest.TestCase):
    def test_reports_bindings_and_unknowns_without_touching_controls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write(path, data):
                dest = root / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
                return dest

            write('proc/sys/kernel/osrelease', b'6.18.59-fixture\n')
            write('sys/firmware/devicetree/base/model', b'Xiaomi Mi 10\0')
            write('sys/firmware/devicetree/base/compatible', b'xiaomi,umi\0qcom,sm8250\0')
            pci = 'sys/bus/pci/devices/0000:01:00.0/'
            write(pci + 'vendor', b'0x17cb\n')
            write(pci + 'device', b'0x1101\n')
            write(pci + 'modalias', b'pci:v000017CBd00001101\n')
            driver = root / 'sys/bus/pci/drivers/ath11k_pci'
            driver.mkdir(parents=True)
            (root / pci / 'driver').symlink_to('../../drivers/ath11k_pci')
            write('sys/bus/i2c/devices/3-0049/name', b'fts-umi\n')
            write('sys/class/remoteproc/remoteproc0/name', b'adsp\n')
            write('sys/class/remoteproc/remoteproc0/firmware', b'qcom/umi/adsp.mdt\n')
            state = write('sys/class/remoteproc/remoteproc0/state', b'offline\n')
            write('sys/class/hwmon/hwmon1/name', b'board_thermistors\n')
            write('sys/class/hwmon/hwmon1/temp1_label', b'xo_therm\n')
            # Fail/hang if the collector starts reading hardware sensor values.
            os.mkfifo(root / 'sys/class/hwmon/hwmon1/temp1_input')
            write('sys/kernel/debug/devices_deferred', b'998000.serial: supply unavailable\n')
            controls = [state, write(pci + 'remove', b'UNCHANGED\n'),
                        write('sys/bus/pci/rescan', b'UNCHANGED\n')]
            before = {path: path.read_bytes() for path in controls}
            # These commands must never run, including getprop in fixture mode.
            bindir = root / 'bin'
            bindir.mkdir()
            sentinel = root / 'unexpected-command'
            for command in ('getprop', 'modprobe', 'insmod', 'mount', 'i2cdetect', 'reboot'):
                stub = bindir / command
                stub.write_text('#!/bin/sh\nprintf called > "$SENTINEL"\nexit 99\n')
                stub.chmod(0o755)
            env = {**os.environ, 'PATH': str(bindir) + ':' + os.environ['PATH'],
                   'SENTINEL': str(sentinel)}
            result = subprocess.run(['sh', str(SCRIPT), '--root', tmp],
                                    capture_output=True, text=True, timeout=10, env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            for expected in ('6.18.59-fixture', 'xiaomi,umi qcom,sm8250',
                             'driver=ath11k_pci', 'device=0x1101', 'name=fts-umi',
                             'firmware=qcom/umi/adsp.mdt', 'state=offline',
                             'temp1_label=xo_therm', 'supply unavailable',
                             '[unavailable]', 'functionality is NOT tested'):
                self.assertIn(expected, result.stdout)
            self.assertEqual({path: path.read_bytes() for path in controls}, before)
            self.assertFalse(sentinel.exists())

    def test_empty_snapshot_does_not_claim_absent_hardware_or_use_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['sh', str(SCRIPT), '--root', tmp],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('kernel=[unavailable]', result.stdout)
            self.assertIn('unknown, not evidence of missing hardware', result.stdout)
            self.assertNotIn('ro.product.', result.stdout)

    def test_invalid_arguments_fail_without_collecting(self):
        for args in (['--root', 'relative'], ['--write'], ['--root', '/nonexistent-umi-fixture']):
            with self.subTest(args=args):
                result = subprocess.run(['sh', str(SCRIPT), *args],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn('umi hardware inventory v1', result.stdout)


if __name__ == '__main__':
    unittest.main()
