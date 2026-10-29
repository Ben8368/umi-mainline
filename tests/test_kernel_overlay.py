#!/usr/bin/env python3
"""Test source patch failure handling and real libfdt overlay merge behavior."""
import ctypes
import ctypes.util
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('ubwc_patch', ROOT / 'patches/ubwc-sm8250-kona.py')
UBWC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UBWC)


class UbwcTests(unittest.TestCase):
    def test_alias_reuses_native_data_and_is_idempotent(self):
        for data in ['sm8250_data', 'upstream_sm8250_config']:
            source = ('static const struct of_device_id configs[] = {\n'
                      '\t{ .compatible = "qcom,sm8150", .data = &other_data },\n'
                      f'\t{{ .compatible = "qcom,sm8250", .data = &{data}, }},\n'
                      '};\n')
            updated = UBWC.patch(source)
            self.assertIn(f'"qcom,kona", .data = &{data}', updated)
            self.assertEqual(UBWC.patch(updated), updated)
            self.assertIn('"qcom,sm8150", .data = &other_data', updated)

    def test_unknown_or_conflicting_inputs_are_rejected_without_writes(self):
        native = '\t{ .compatible = "qcom,sm8250", .data = &sm8250_data, },\n'
        for source in ['', native * 2,
                       native + '\t{ .compatible = "qcom,kona", .data = &wrong_data },\n',
                       native + '/* "qcom,kona" in unknown syntax */\n']:
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'ubwc.c'
                path.write_text(source)
                result = subprocess.run(['python3', str(ROOT / 'patches/ubwc-sm8250-kona.py'),
                                         str(path)], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(path.read_text(), source)


@unittest.skipUnless(shutil.which('dtc') and shutil.which('fdtget') and
                     ctypes.util.find_library('fdt'), 'dtc/fdtget/libfdt required for real overlay test')
class SpmiOverlayTests(unittest.TestCase):
    def test_vendor_overlay_preserves_disabled_aliases_and_native_supplies(self):
        # The booted tree showed these exact names/USIDs; 8/9 are not duplicates.
        aliases = [('qcom,pm8150', 0), ('qcom,pm8150', 1),
                   ('qcom,pm8150b', 2), ('qcom,pm8150b', 3),
                   ('qcom,pm8150l', 4), ('qcom,pm8150l', 5),
                   ('qcom,pm8009', 10), ('qcom,pm8009', 11)]
        native = ''.join(f'pmic@{sid:x} {{ reg=<{sid} 0>; status="okay"; }};'
                         for _, sid in aliases)
        base = ('/dts-v1/; / { spmi_bus: spmi { #address-cells=<2>; #size-cells=<0>; '
                + native + ' }; };\n' + (ROOT / 'dts/umi-spmi-overlay-guard.dtsi').read_text())
        overlay = '/dts-v1/; /plugin/; &spmi_bus {\n'
        for vendor, sid in aliases + [('qcom,pmxprairie', 8), ('qcom,pmxprairie', 9)]:
            overlay += (f'{vendor}@{sid:x} {{ reg=<{sid} 0>; compatible="qcom,spmi-pmic"; '
                        'vendor-child { compatible="test,supplier"; }; };\n')
        overlay += '};\n'
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            blobs = []
            for name, source in [('base', base), ('overlay', overlay)]:
                dts = directory / f'{name}.dts'
                dtb = directory / f'{name}.dtb'
                dts.write_text(source)
                subprocess.run(['dtc', '-@', '-p', '16384', '-I', 'dts', '-O', 'dtb',
                                '-o', str(dtb), str(dts)], check=True, capture_output=True)
                blobs.append(ctypes.create_string_buffer(dtb.read_bytes()))
            lib = ctypes.CDLL(ctypes.util.find_library('fdt'))
            lib.fdt_overlay_apply.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.fdt_overlay_apply.restype = ctypes.c_int
            self.assertEqual(lib.fdt_overlay_apply(*blobs), 0)
            merged = directory / 'merged.dtb'
            merged.write_bytes(blobs[0].raw)
            for vendor, sid in aliases:
                status = subprocess.check_output(['fdtget', str(merged),
                                                   f'/spmi/{vendor}@{sid:x}', 'status'], text=True)
                self.assertEqual(status.strip(), 'disabled')
                status = subprocess.check_output(['fdtget', str(merged),
                                                   f'/spmi/pmic@{sid:x}', 'status'], text=True)
                self.assertEqual(status.strip(), 'okay')
            for sid in [8, 9]:
                result = subprocess.run(['fdtget', str(merged), f'/spmi/qcom,pmxprairie@{sid}',
                                         'status'], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                compatible = subprocess.check_output(['fdtget', str(merged),
                    f'/spmi/qcom,pmxprairie@{sid}', 'compatible'], text=True)
                self.assertEqual(compatible.strip(), 'qcom,spmi-pmic')


if __name__ == '__main__':
    unittest.main()
