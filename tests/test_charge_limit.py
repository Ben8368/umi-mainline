#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""SOC control against fake supplies only; never use the host /sys."""
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/umi-charge-limit.py'
SPEC = importlib.util.spec_from_file_location('umi_charge_limit', SCRIPT)
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)


class FakeSupplies:
    def __init__(self, capacity=60, enabled=1):
        self.soc = capacity
        self.actual = enabled
        self.writes = []
        self.cap_error = self.state_error = self.write_error = False
        self.defer = False

    def capacity(self):
        if self.cap_error:
            raise ValueError('bad capacity')
        return self.soc

    def enabled(self):
        if self.state_error:
            raise OSError('read failed')
        return self.actual

    def set_enabled(self, value):
        self.writes.append(value)
        if self.write_error:
            raise OSError('write failed')
        if not self.defer:
            self.actual = value


class ChargeLimitTests(unittest.TestCase):
    def test_window_and_boundaries_preserve_active_pps_below_upper(self):
        supply = FakeSupplies()
        controller = policy.Controller(supply, policy.Config())
        for cap, expected in [(60, 1), (68, 1), (70, 0), (68, 0), (65, 1), (69, 1)]:
            supply.soc = cap
            self.assertTrue(controller.step().startswith('OK'))
            self.assertEqual(supply.actual, expected)
        self.assertEqual(supply.writes, [1, 0, 0, 1])

    def test_restart_inside_window_reads_back_without_committing_a_strategy(self):
        for actual in (0, 1):
            supply = FakeSupplies(68, actual)
            controller = policy.Controller(supply, policy.Config())
            result = controller.step()
            self.assertEqual(result, f'OK capacity=68 requested=unchanged enabled={actual}')
            self.assertIsNone(controller.desired)
            self.assertIsNone(controller.last_request)
            self.assertEqual(supply.writes, [])
            self.assertEqual(supply.actual, actual)

    def test_mid_window_restart_does_not_inhibit_after_usb_reattach(self):
        supply = FakeSupplies(68, 0)
        controller = policy.Controller(supply, policy.Config())
        self.assertIn('requested=unchanged enabled=0', controller.step())
        # No prior policy is inferred from a no-source/readback zero state.
        supply.actual = 1
        self.assertIn('requested=unchanged enabled=1', controller.step())
        self.assertIsNone(controller.desired)
        self.assertEqual(supply.writes, [])

    def test_mid_window_restart_establishes_policy_only_at_a_boundary(self):
        for capacity, expected in ((70, 0), (65, 1)):
            supply = FakeSupplies(68, 0)
            controller = policy.Controller(supply, policy.Config())
            controller.step()
            supply.soc = capacity
            controller.step()
            self.assertEqual(controller.desired, expected)
            self.assertEqual(supply.writes, [expected])

    def test_off_is_inhibited_even_when_unplugged_hardware_already_zero(self):
        supply = FakeSupplies(80, 0)
        controller = policy.Controller(supply, policy.Config())
        controller.step()
        self.assertEqual(supply.writes, [0])
        # USB reset, manual PPS enable or another writer must not fool a cache.
        supply.actual = 1
        controller.step()
        self.assertEqual(supply.actual, 0)
        self.assertEqual(supply.writes, [0, 0])

    def test_invalid_capacity_stops_and_only_resumes_at_lower(self):
        supply = FakeSupplies()
        controller = policy.Controller(supply, policy.Config())
        controller.step()
        supply.cap_error = True
        self.assertTrue(controller.step().startswith('ERROR'))
        self.assertEqual(supply.actual, 0)
        supply.cap_error = False
        supply.soc = 68
        controller.step()
        self.assertEqual(supply.actual, 0)
        supply.soc = 65
        controller.step()
        self.assertEqual(supply.actual, 1)

    def test_read_failure_never_grants_charge_permission(self):
        supply = FakeSupplies()
        supply.state_error = True
        controller = policy.Controller(supply, policy.Config())
        result = controller.step()
        self.assertTrue(result.startswith('ERROR'))
        self.assertEqual(set(supply.writes), {0})

    def test_failed_stop_is_reported_and_retried(self):
        supply = FakeSupplies(80)
        supply.write_error = True
        controller = policy.Controller(supply, policy.Config())
        self.assertIn('stop FAILED', controller.step())
        self.assertIsNone(controller.last_request)
        supply.write_error = False
        self.assertTrue(controller.step().startswith('OK'))
        self.assertEqual(supply.actual, 0)

    def test_deferred_or_rejected_writes_are_not_reported_as_success(self):
        supply = FakeSupplies(60, 0)
        supply.defer = True
        controller = policy.Controller(supply, policy.Config())
        self.assertIn('WAIT enable pending', controller.step())
        supply.soc = 80
        supply.actual = 1
        self.assertIn('ERROR stop unconfirmed', controller.step())
        self.assertEqual(supply.writes, [1, 0])

    def test_readback_error_after_enable_attempts_stop(self):
        supply = FakeSupplies(60, 0)
        original = supply.set_enabled

        def lose_readback(value):
            original(value)
            supply.state_error = True

        supply.set_enabled = lose_readback
        controller = policy.Controller(supply, policy.Config())
        self.assertIn('control/readback', controller.step())
        self.assertEqual(supply.writes, [1, 0])
        self.assertEqual(supply.actual, 0)

    def test_config_rejects_invalid_ranges_and_zero_interval_before_io(self):
        for key, value in [('UPPER', '101'), ('UPPER', '65'), ('UPPER', '-1'),
                           ('UPPER', '070'), ('LOWER', '70'), ('LOWER', 'oops'),
                           ('INTERVAL', '0'), ('INTERVAL', '3601')]:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {
                'UMI_CHARGE_UPPER': '70', 'UMI_CHARGE_LOWER': '65',
                'UMI_CHARGE_INTERVAL': '30', f'UMI_CHARGE_{key}': value,
            }, clear=True):
                with self.assertRaises(ValueError):
                    policy.Config.from_env()

    def fixture(self, root):
        battery = root / 'class/power_supply/qcom-battery'
        charger = root / 'class/power_supply/pm8150b-charger'
        battery.mkdir(parents=True)
        charger.mkdir(parents=True)
        (battery / 'type').write_text('Battery\n')
        (battery / 'capacity').write_text('70\n')
        (charger / 'type').write_text('USB\n')
        (charger / 'charging_enabled').write_text('1\n')
        # These must never be opened by the SOC controller.
        for name in ('pps_enable', 'pps_voltage_uv', 'pps_current_ua'):
            (charger / name).write_text('UNCHANGED\n')
        return battery, charger

    def test_charger_binding_matches_probe_name_not_descriptor_default(self):
        source = (ROOT / 'power/qcom_pm8150b_charger.c').read_text(encoding='utf-8')
        probe = source.split('static int smb5_probe(', 1)[1]
        naming = re.search(r'desc->name\s*=\s*devm_kasprintf\(chip->dev, GFP_KERNEL,\s*'
                           r'"([^"]+)",\s*\(const char \*\)device_get_match_data\(chip->dev\)\)',
                           probe)
        match = re.search(r'\.compatible\s*=\s*"qcom,pm8150b-charger",\s*'
                          r'\.data\s*=\s*"([^"]+)"', source)
        self.assertIsNotNone(naming)
        self.assertIsNotNone(match)
        exported = naming.group(1) % match.group(1)
        self.assertEqual(exported, 'pm8150b-charger')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, charger = self.fixture(root)
            self.assertEqual(charger.name, exported)
            supply = policy.Supplies(root)
            self.assertEqual(supply.charger.name, exported)
            self.assertTrue(policy.Controller(supply, policy.Config()).step().startswith('OK'))
            self.assertEqual((charger / 'charging_enabled').read_text(), '0\n')

    def test_missing_driver_supply_never_falls_back_to_descriptor_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, charger = self.fixture(root)
            decoy = charger.with_name('pm8150b_charger')
            charger.rename(decoy)
            controller = policy.Controller(policy.Supplies(root), policy.Config())
            self.assertIn('stop FAILED', controller.step())
            self.assertEqual((decoy / 'charging_enabled').read_text(), '1\n')

    def test_real_file_backend_limits_writes_and_never_creates_missing_attribute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            battery, charger = self.fixture(root)
            supply = policy.Supplies(root)
            controller = policy.Controller(supply, policy.Config())
            self.assertTrue(controller.step().startswith('OK'))
            self.assertEqual((charger / 'charging_enabled').read_text(), '0\n')
            for name in ('pps_enable', 'pps_voltage_uv', 'pps_current_ua'):
                self.assertEqual((charger / name).read_text(), 'UNCHANGED\n')
            for bad in ('101', '-1', 'oops', '', '08'):
                (battery / 'capacity').write_text(bad)
                with self.assertRaises(ValueError):
                    supply.capacity()
            control = charger / 'charging_enabled'
            control.unlink()
            with self.assertRaises(FileNotFoundError):
                supply.set_enabled(0)
            self.assertFalse(control.exists())

    def test_wrong_charger_identity_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, charger = self.fixture(root)
            (charger / 'type').write_text('Battery\n')
            controller = policy.Controller(policy.Supplies(root), policy.Config())
            self.assertIn('stop FAILED', controller.step())
            self.assertEqual((charger / 'charging_enabled').read_text(), '1\n')

    def test_check_mode_is_read_only_and_explicit_run_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, charger = self.fixture(root)
            env = {k: v for k, v in os.environ.items() if not k.startswith('UMI_CHARGE_')}
            env['UMI_CHARGE_SYSFS_ROOT'] = str(root)
            env['UMI_CHARGE_LOCK'] = str(root / 'lock')
            result = subprocess.run([sys.executable, str(SCRIPT), '--check'], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('read-only', result.stderr)
            self.assertEqual((charger / 'charging_enabled').read_text(), '1\n')
            self.assertFalse((root / 'lock').exists())
            result = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)

    @unittest.skipIf(sys.platform == 'win32', 'fcntl is a Linux runtime dependency')
    def test_single_writer_lock_and_release_without_unlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / 'lock'
            with policy.exclusive_lock(lock):
                inode = lock.stat().st_ino
                with self.assertRaises(ValueError):
                    with policy.exclusive_lock(lock):
                        self.fail('second process acquired lock')
            with policy.exclusive_lock(lock):
                self.assertEqual(lock.stat().st_ino, inode)

    @unittest.skipIf(sys.platform == 'win32', 'Linux service process integration')
    def test_daemon_stops_without_automatically_reenabling_charge(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, charger = self.fixture(root)
            env = {k: v for k, v in os.environ.items() if not k.startswith('UMI_CHARGE_')}
            env.update(UMI_CHARGE_SYSFS_ROOT=tmp, UMI_CHARGE_LOCK=str(root / 'lock'),
                       UMI_CHARGE_INTERVAL='1')
            process = subprocess.Popen([sys.executable, str(SCRIPT), '--run'], env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while (charger / 'charging_enabled').read_text() != '0\n':
                    self.assertIsNone(process.poll())
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.02)
                second = subprocess.run([sys.executable, str(SCRIPT), '--run'], env=env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(second.returncode, 1)
                self.assertIn('holds the lock', second.stderr)
                process.terminate()
                process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0)
                self.assertEqual((charger / 'charging_enabled').read_text(), '0\n')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
