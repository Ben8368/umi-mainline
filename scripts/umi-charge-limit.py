#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""SOC hysteresis over SMB5's charging_enabled; TCPM retains PD/PPS ownership.

Reference: misaka-link/umi-linux cf83073887899f485a5c606f9842c5e691ea796c,
rootfs-config/battery-charge-limit (GPL-2.0). Python implementation with
readback, fault handling and a process lock; no vendor binary is required.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import signal
import threading

LOG = logging.getLogger('umi-charge-limit')


def integer(value, maximum):
    if not re.fullmatch(r'0|[1-9][0-9]{0,3}', value) or int(value) > maximum:
        raise ValueError(f'invalid integer: {value!r} (maximum {maximum})')
    return int(value)


@dataclass(frozen=True)
class Config:
    upper: int = 70
    lower: int = 65
    interval: int = 30
    sysfs_root: Path = Path('/sys')
    lock: Path = Path('/run/umi-charge-limit.lock')

    def __post_init__(self):
        if not 0 <= self.lower < self.upper <= 100:
            raise ValueError('require 0 <= LOWER < UPPER <= 100')
        if not 1 <= self.interval <= 3600:
            raise ValueError('require 1 <= INTERVAL <= 3600 seconds')
        if not self.sysfs_root.is_absolute() or not self.lock.is_absolute():
            raise ValueError('sysfs root and lock must be absolute paths')

    @classmethod
    def from_env(cls):
        return cls(
            upper=integer(os.environ.get('UMI_CHARGE_UPPER', '70'), 100),
            lower=integer(os.environ.get('UMI_CHARGE_LOWER', '65'), 100),
            interval=integer(os.environ.get('UMI_CHARGE_INTERVAL', '30'), 3600),
            sysfs_root=Path(os.environ.get('UMI_CHARGE_SYSFS_ROOT', '/sys')),
            lock=Path(os.environ.get('UMI_CHARGE_LOCK', '/run/umi-charge-limit.lock')),
        )


class Supplies:
    """Bind the actual names exported by this tree; never select the first psy."""
    def __init__(self, root):
        self.battery = root / 'class/power_supply/qcom-battery'
        self.charger = root / 'class/power_supply/pm8150b-charger'

    @staticmethod
    def verify_type(path, expected):
        if (path / 'type').read_text(encoding='ascii').strip() != expected:
            raise ValueError(f'unexpected power supply type: {path}')

    def capacity(self):
        self.verify_type(self.battery, 'Battery')
        return integer((self.battery / 'capacity').read_text(encoding='ascii').strip(), 100)

    def enabled(self):
        self.verify_type(self.charger, 'USB')
        return integer((self.charger / 'charging_enabled').read_text(encoding='ascii').strip(), 1)

    def set_enabled(self, enabled):
        self.verify_type(self.charger, 'USB')
        # No O_CREAT: a disappearing attribute must fail, never become a file.
        fd = os.open(self.charger / 'charging_enabled', os.O_WRONLY | os.O_CLOEXEC)
        with os.fdopen(fd, 'wb', buffering=0) as stream:
            if stream.write(f'{enabled}\n'.encode('ascii')) != 2:
                raise OSError('short charging_enabled write')


class Controller:
    def __init__(self, supplies, config):
        self.supplies = supplies
        self.config = config
        self.desired = None
        self.last_request = None

    def step(self):
        errors = []
        capacity = actual = None
        for name, read in (('capacity', self.supplies.capacity),
                           ('charging_enabled', self.supplies.enabled)):
            try:
                value = read()
                if name == 'capacity':
                    capacity = value
                else:
                    actual = value
            except (OSError, ValueError) as exc:
                errors.append(f'{name}: {exc}')
        if errors:
            self.desired = 0
        elif capacity >= self.config.upper:
            self.desired = 0
        elif capacity <= self.config.lower:
            self.desired = 1

        try:
            # Reassert inhibition while holding off, including before USB attach
            # when the hardware bit can be zero without user_inhibit being set.
            # An active PPS contract below UPPER is never periodically cancelled.
            if (self.desired is not None and
                    (self.desired == 0 or actual != 1 or self.last_request != 1)):
                self.supplies.set_enabled(self.desired)
                self.last_request = self.desired
            readback = self.supplies.enabled()
        except (OSError, ValueError) as exc:
            errors.append(f'control/readback: {exc}')
            self.desired = 0
            self.last_request = None
            try:
                self.supplies.set_enabled(0)
            except (OSError, ValueError) as stop_exc:
                errors.append(f'stop FAILED: {stop_exc}; disconnect source if unsafe')
            return 'ERROR ' + '; '.join(errors)

        if errors:
            return 'ERROR stop requested; ' + '; '.join(errors)
        if self.desired is None:
            return f'OK capacity={capacity} requested=unchanged enabled={readback}'
        if readback != self.desired:
            # Enable is asynchronous and can be blocked by kernel health/faults.
            # Never clear pps_fault or claim that accepting a write means charging.
            level = 'ERROR stop unconfirmed' if self.desired == 0 else 'WAIT enable pending'
            return f'{level}; capacity={capacity} enabled={readback}'
        return f'OK capacity={capacity} requested={self.desired} enabled={readback}'


@contextmanager
def exclusive_lock(path):
    import fcntl  # Linux runtime; importing the policy alone is side-effect free.
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('another umi-charge-limit process holds the lock') from exc
        yield
    finally:
        os.close(fd)  # Keep the inode: unlinking would allow two lock owners.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='read configuration and supplies only')
    mode.add_argument('--run', action='store_true', help='control charging until stopped')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='[charge-limit] %(message)s')
    try:
        config = Config.from_env()
        supplies = Supplies(config.sysfs_root)
        if args.check:
            LOG.info('upper=%s lower=%s interval=%ss capacity=%s enabled=%s (read-only)',
                     config.upper, config.lower, config.interval,
                     supplies.capacity(), supplies.enabled())
            return 0
        stopped = threading.Event()
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stopped.set())
        with exclusive_lock(config.lock):
            controller = Controller(supplies, config)
            previous = None
            while not stopped.is_set():
                result = controller.step()
                if result != previous:
                    LOG.log(logging.ERROR if result.startswith('ERROR') else logging.INFO, result)
                    previous = result
                stopped.wait(config.interval)
        # Stopping this service never grants permission to charge or enable PPS.
        return 0
    except (OSError, ValueError, ImportError) as exc:
        LOG.error('%s', exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
