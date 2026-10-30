#!/usr/bin/env python3
"""Compile the board's thermistor DT include and resolve every IIO supplier.

Fixture register IDs are the numeric Xiaomi umi board contract, independently
of the source include's upstream macro names. No ADC conversions are performed.
"""
import ast
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ThermistorConfigTests(unittest.TestCase):
    def test_rescue_audit_rejects_missing_or_modular_monitoring(self):
        audit = ROOT / 'tools/config-audit.py'
        tree = ast.parse(audit.read_text(encoding='utf-8'))
        lists = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in {'MUST', 'MUST_NOT'}}
        baseline = {name: value for name, value, _ in lists['MUST']}
        baseline.update({name: 'n' for name, _ in lists['MUST_NOT']})
        required = ('QCOM_SPMI_ADC5', 'HWMON', 'SENSORS_IIO_HWMON')
        for symbol in required:
            self.assertEqual(baseline[symbol], 'y')
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'config'
            fragment = Path(tmp) / 'fragment'
            fragment.write_text(''.join(f'CONFIG_{symbol}=y\n' for symbol in required))
            for removed in (None, *required):
                for value in ('m', 'n'):
                    with self.subTest(symbol=removed, value=value):
                        values = dict(baseline)
                        if removed:
                            values[removed] = value
                        config.write_text(''.join(f'CONFIG_{k}={v}\n' for k, v in values.items()))
                        result = subprocess.run([sys.executable, str(audit), str(config),
                                                 '--fragment', str(fragment)],
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, int(removed is not None),
                                         result.stdout + result.stderr)


@unittest.skipUnless(all(shutil.which(name) for name in ('gcc', 'dtc', 'fdtget')),
                     'gcc/dtc/fdtget required for compiled DT checks')
class ThermistorDtTests(unittest.TestCase):
    def test_hwmon_consumers_resolve_to_board_channels_and_sampling(self):
        # Map order is hwmon temp1..temp8; addresses are PMIC SIDs 0, 2, 4.
        expected = [('/adc0', 0x4c, 'xo_therm'),
                    ('/adc0', 0x4d, 'skin_therm'),
                    ('/adc0', 0x4e, 'pa_therm1'),
                    ('/adc2', 0x4d, 'wireless_therm'),
                    ('/adc2', 0x4f, 'conn_therm'),
                    ('/adc4', 0x4d, 'camera_flash_therm'),
                    ('/adc4', 0x4e, 'skin_msm_therm'),
                    ('/adc4', 0x4f, 'pa_therm2')]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binding = base / 'dt-bindings/iio/qcom,spmi-vadc.h'
            binding.parent.mkdir(parents=True)
            binding.write_text('#define ADC5_XO_THERM_100K_PU 0x4c\n'
                               '#define ADC5_AMUX_THM1_100K_PU 0x4d\n'
                               '#define ADC5_AMUX_THM2_100K_PU 0x4e\n'
                               '#define ADC5_AMUX_THM3_100K_PU 0x4f\n')
            # Include real repository content, with minimal parent providers.
            shutil.copyfile(ROOT / 'dts/xiaomi-umi-thermistors.dtsi', base / 'board.dtsi')
            nodes = ''.join(f'{label}: adc{sid} {{ #address-cells=<1>; #size-cells=<0>; '
                            '#io-channel-cells=<1>; };'
                            for label, sid in [('pm8150_adc', 0), ('pm8150b_adc', 2),
                                               ('pm8150l_adc', 4)])
            source = base / 'test.dts'
            source.write_text('/dts-v1/; / { ' + nodes + ' };\n#include "board.dtsi"\n')
            preprocessed, dtb = base / 'test.cpp', base / 'test.dtb'
            subprocess.run(['gcc', '-E', '-P', '-nostdinc', '-undef', '-x',
                            'assembler-with-cpp', '-I', str(base), str(source),
                            '-o', str(preprocessed)], check=True, capture_output=True)
            subprocess.run(['dtc', '-@', '-I', 'dts', '-O', 'dtb',
                            '-o', str(dtb), str(preprocessed)], check=True, capture_output=True)

            def get(node, prop, kind='s'):
                return subprocess.check_output(['fdtget', '-t', kind, str(dtb), node, prop],
                                               text=True).strip()

            self.assertEqual(get('/board-thermistors', 'compatible'), 'iio-hwmon')
            consumer = [int(x, 16) for x in get('/board-thermistors', 'io-channels', 'x').split()]
            self.assertEqual(len(consumer), 16)
            pairs = list(zip(consumer[::2], consumer[1::2]))
            self.assertEqual(len(set(pairs)), 8)
            for (phandle, channel), (provider, reg, label) in zip(pairs, expected):
                with self.subTest(label=label):
                    self.assertEqual(phandle, int(get(provider, 'phandle', 'x'), 16))
                    self.assertEqual(channel, reg)
                    self.assertEqual(get(provider, '#io-channel-cells', 'u'), '1')
                    path = f'{provider}/channel@{reg:x}'
                    self.assertEqual(int(get(path, 'reg', 'x'), 16), reg)
                    self.assertEqual(get(path, 'label'), label)
                    self.assertEqual(get(path, 'qcom,ratiometric', 'x'), '')
                    self.assertEqual(get(path, 'qcom,hw-settle-time', 'u'), '200')
                    self.assertEqual(get(path, 'qcom,pre-scaling', 'u'), '1 1')
            children = subprocess.check_output(['fdtget', '-l', str(dtb), '/'], text=True).split()
            self.assertNotIn('thermal-zones', children, 'measurement must not invent thermal policy')


if __name__ == '__main__':
    unittest.main()
