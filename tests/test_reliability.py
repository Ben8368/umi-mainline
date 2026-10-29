#!/usr/bin/env python3
"""Offline regression: execute actual script sections and actual C functions with fault injection.

These are host simulations, not complete kernel compilation or hardware acceptance.
"""
import ast
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    start = re.search(r'^static [^\n]*\b' + re.escape(name) + r'\(', source, re.M).start()
    return source[start:source.index('\n}', start) + 2]


class ReliabilityTests(unittest.TestCase):
    def run_c(self, source):
        compiler = shutil.which('cc') or shutil.which('clang')
        self.assertIsNotNone(compiler, 'C compiler required for the actual driver function tests')
        with tempfile.TemporaryDirectory(prefix='umi-c-regression-') as tmp:
            path = Path(tmp)
            (path / 'test.c').write_text(source)
            compiled = subprocess.run([compiler, '-std=c11', '-Wall', '-Werror',
                                       '-Wno-unused-function', str(path / 'test.c'), '-o', str(path / 'test')],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            result = subprocess.run([str(path / 'test')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

    def test_build_failure_and_missing_wifi_never_collect_stale_artifacts(self):
        source = (ROOT / 'scripts/build.sh').read_text()
        section = 'set -e\n' + source[source.index('echo "== [5/6]'):]
        for mode, expected in [('fail', 3), ('missing-wifi', 3), ('success', 0)]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix='umi-build-test-') as tmp:
                base = Path(tmp)
                out = base / 'kernel/out'
                ws = base / 'workspace'
                dtbs = out / 'arch/arm64/boot/dts/qcom'
                dtbs.mkdir(parents=True)
                (ws / 'out').mkdir(parents=True)
                (base / 'bin').mkdir()
                (out / '.config').write_text('fixture\n')
                (dtbs / 'sm8250-xiaomi-umi-wifi.dtb').write_text('OLD_WIFI')
                make = base / 'bin/make'
                make.write_text('''#!/bin/sh
printf NEW_KERNEL > "$OUT/arch/arm64/boot/Image.gz"
printf NEW_BASE > "$OUT/arch/arm64/boot/dts/qcom/sm8250-xiaomi-umi.dtb"
printf NEW_PLUS > "$OUT/arch/arm64/boot/dts/qcom/sm8250-xiaomi-umi-plus.dtb"
[ "$MODE" != fail ] || exit 2
[ "$MODE" != success ] || printf NEW_WIFI > "$OUT/arch/arm64/boot/dts/qcom/sm8250-xiaomi-umi-wifi.dtb"
exit 0
''')
                make.chmod(0o755)
                env = dict(os.environ, OUT=str(out), TREE=str(base / 'kernel'), WS=str(ws),
                           MODE=mode, JOBS='1', TC='gcc', MAKEFLAGS_TC='ARCH=arm64',
                           PATH=str(base / 'bin') + os.pathsep + os.environ['PATH'])
                result = subprocess.run(['sh', '-c', section], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                if expected:
                    self.assertEqual(list((ws / 'out').iterdir()), [])
                else:
                    self.assertEqual((ws / 'out/sm8250-xiaomi-umi-wifi.dtb').read_text(), 'NEW_WIFI')

    def test_mkimage_generates_fresh_initramfs_and_stops_if_it_fails(self):
        for failed in [False, True]:
            with self.subTest(failed=failed), tempfile.TemporaryDirectory(prefix='umi-image-test-') as tmp:
                ws = Path(tmp)
                (ws / 'scripts').mkdir()
                (ws / 'tools').mkdir()
                (ws / 'out').mkdir()
                (ws / 'out/initramfs.cpio.gz').write_text('OLD')
                (ws / 'scripts/build.sh').write_text('echo build >> "$TEST_LOG"\n')
                (ws / 'scripts/mkinitramfs.sh').write_text('''echo "init $*" >> "$TEST_LOG"
[ "$FAIL_INIT" != 1 ] || exit 7
printf NEW > "$WS/out/initramfs.cpio.gz"
''')
                (ws / 'tools/pack-umi.py').write_text('''import os,sys
from pathlib import Path
ws=Path(os.environ['WS'])
assert (ws/'out/initramfs.cpio.gz').read_text()=='NEW'
with open(os.environ['TEST_LOG'],'a') as f: f.write('pack\\n')
Path(sys.argv[sys.argv.index('-o')+1]).write_text('fixture')
''')
                env = dict(os.environ, WS=str(ws), TEST_LOG=str(ws / 'calls'), FAIL_INIT=str(int(failed)))
                env.pop('ROOTDEV', None)
                result = subprocess.run(['sh', str(ROOT / 'scripts/mkimage.sh')], env=env,
                                        capture_output=True, text=True)
                calls = (ws / 'calls').read_text().splitlines()
                self.assertEqual(calls[:2], ['build', 'init --root none --rootfstype ext4'])
                self.assertEqual(result.returncode, 7 if failed else 0, result.stderr)
                self.assertEqual('pack' in calls, not failed)

    def test_failed_cpio_preserves_previous_initramfs(self):
        with tempfile.TemporaryDirectory(prefix='umi-cpio-test-') as tmp:
            ws = Path(tmp)
            (ws / 'out').mkdir()
            (ws / 'initramfs').mkdir()
            (ws / 'initramfs/init').write_text('#!/bin/sh\n\techo fixture\n')
            (ws / 'bin').mkdir()
            bb = ws / 'busybox'
            bb.write_text('#!/bin/sh\nexit 0\n')
            bb.chmod(0o755)
            cpio = ws / 'bin/cpio'
            cpio.write_text('#!/bin/sh\nexit 7\n')
            cpio.chmod(0o755)
            (ws / 'out/initramfs.cpio.gz').write_text('LAST_GOOD')
            env = dict(os.environ, WS=str(ws), BB=str(bb), BUILD=str(ws / 'assembly'),
                       PATH=str(ws / 'bin') + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['sh', str(ROOT / 'scripts/mkinitramfs.sh')], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
            self.assertEqual((ws / 'out/initramfs.cpio.gz').read_text(), 'LAST_GOOD')
            self.assertFalse(list((ws / 'out').glob('.initramfs.*')))

    def test_actual_ascii_pattern_accepts_tab_and_rejects_utf8(self):
        source = (ROOT / 'scripts/mkinitramfs.sh').read_bytes()
        pattern = re.search(br"grep -q '([^']+)'", source).group(1)
        self.assertIn(b'\x09', pattern)
        for value, expected in [(b'ASCII\tindent\n', 1), ('中文\n'.encode(), 0), (b'\x01\n', 0)]:
            result = subprocess.run([b'grep', b'-q', pattern], input=value,
                                    env=dict(os.environ, LC_ALL='C'))
            self.assertEqual(result.returncode, expected)

    def test_config_audit_matches_current_display_psci_and_smmu_contract(self):
        source = ast.parse((ROOT / 'tools/config-audit.py').read_text())
        lists = {node.targets[0].id: ast.literal_eval(node.value) for node in source.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in {'MUST', 'MUST_NOT'}}
        values = {name: value for name, value, _ in lists['MUST']}
        values.update({name: 'n' for name, _ in lists['MUST_NOT']})
        values['ARM_SMMU_DISABLE_BYPASS_BY_DEFAULT'] = 'y'
        values['CMDLINE'] = '"arm-smmu.disable_bypass=0"'
        with tempfile.TemporaryDirectory(prefix='umi-config-test-') as tmp:
            base = Path(tmp)
            (base / 'fragment').write_text('CONFIG_DRM_MSM=y\nCONFIG_ARM_PSCI_CPUIDLE=y\n# CONFIG_ARM_SMMU_DISABLE_BYPASS_BY_DEFAULT is not set\n')
            for broken in [False, True]:
                candidate = dict(values)
                if broken:
                    candidate['CMDLINE'] = '""'
                (base / 'config').write_text(''.join(f'CONFIG_{k}={v}\n' for k, v in candidate.items()))
                result = subprocess.run([sys.executable, str(ROOT / 'tools/config-audit.py'),
                                         str(base / 'config'), '--fragment', str(base / 'fragment')],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, int(broken), result.stdout + result.stderr)

    def test_actual_panel_parser_multiline_invalid_and_capacity(self):
        body = function((ROOT / 'patches/panel-xiaomi-umi.c').read_text(), 'umi_panel_dsi_store')
        preamble = r'''
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <sys/types.h>
typedef unsigned char u8;
struct device {int unused;}; struct device_attribute {int unused;};
struct mipi_dsi_device {int unused;}; struct umi_panel {int unused;};
static struct umi_panel panel; static u8 actual[512]; static int length;
#define to_mipi_dsi_device(dev) ((struct mipi_dsi_device *)0)
#define mipi_dsi_get_drvdata(dsi) ((void)(dsi), &panel)
#define dev_info(...) ((void)0)
static int umi_panel_send_seq(struct umi_panel *ctx, const char *label, u8 *seq, int n) {
 memcpy(actual,seq,n); length=n; return 0;
}
'''
        main = r'''
int main(void) {
 const char *valid="01 02\n03 04\r\n";
 if(umi_panel_dsi_store(NULL,NULL,valid,strlen(valid))!=(ssize_t)strlen(valid)) return 1;
 if(length!=4 || memcmp(actual,"\1\2\3\4",4)) return 2;
 const char *bad[]={"gg", "100", "100000000", "01z", "", " \n\t"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(*bad);i++)
  if(umi_panel_dsi_store(NULL,NULL,bad[i],strlen(bad[i]))!=-EINVAL) return 3;
 char huge[1600]; memset(huge,0,sizeof huge);
 for(int i=0;i<512;i++) strcat(huge,"01 ");
 if(umi_panel_dsi_store(NULL,NULL,huge,strlen(huge))<0 || length!=512) return 4;
 strcat(huge,"01");
 if(umi_panel_dsi_store(NULL,NULL,huge,strlen(huge))!=-EINVAL) return 5;
 return 0;
}
'''
        self.run_c(preamble + body + main)

    def test_actual_power_init_stops_on_every_injected_i2c_failure(self):
        source = (ROOT / 'power/bq25970_charger.c').read_text()
        names = ['bq2597x_init_protection', 'bq2597x_init_adc', 'bq2597x_init_int_src',
                 'bq2597x_init_regulation', 'bq2597x_init_device']
        bodies = '\n'.join(function(source, name) for name in names)
        fields = sorted(set(re.findall(r'bq->cfg->(\w+)', bodies)))
        constants = set(re.findall(r'\b[A-Z][A-Z_0-9]+\b', bodies)) - {'TODO', 'EINVAL'}
        calls = set(re.findall(r'\b((?:bq2597x|sc8551)_\w+)\(', bodies)) - set(names)
        preamble = '#include <stdbool.h>\n#include <stdio.h>\n#include <errno.h>\ntypedef unsigned char u8;\n'
        preamble += 'struct cfg {' + ''.join('int ' + key + ';' for key in fields) + '};\n'
        preamble += 'struct bq2597x {struct cfg *cfg; int chip_vendor;};\n'
        preamble += 'static int count, fail_at;\nstatic int step(void){return ++count==fail_at?-EIO:0;}\n'
        preamble += 'static int read_reg(u8 *value){*value=0; return step();}\n'
        preamble += '#define bq_info(...) ((void)0)\n#define bq_err(...) ((void)0)\n'
        for key in constants:
            preamble += '#define ' + key + (' 99\n' if key == 'BQ25968_DEV_ID' else ' 1\n')
        for name in calls:
            preamble += ('#define bq2597x_read_byte(b,r,v) read_reg(v)\n' if name == 'bq2597x_read_byte'
                         else '#define ' + name + '(...) step()\n')
        main = '''
int main(void){struct cfg cfg={0}; struct bq2597x bq={.cfg=&cfg,.chip_vendor=1};
 fail_at=0;count=0;if(bq2597x_init_device(&bq))return 1;int total=count;
 for(int i=1;i<=total;i++){count=0;fail_at=i;
  if(bq2597x_init_device(&bq)!=-EIO || count!=i)return 2;}
 printf("Injected failures checked: %d\\n",total);return 0;}
'''
        self.assertIn('Injected failures checked:', self.run_c(preamble + bodies + main))

    def test_actual_status_getter_propagates_read_error(self):
        source = (ROOT / 'power/bq25970_charger.c').read_text()
        body = function(source, 'bq2597x_charger_get_property')
        preamble = r'''
#include <stdbool.h>
#include <errno.h>
enum power_supply_property {POWER_SUPPLY_PROP_STATUS,POWER_SUPPLY_PROP_PRESENT,POWER_SUPPLY_PROP_MODEL_NAME};
enum {BQ25970_ROLE_MASTER=1,BQ25970_ROLE_SLAVE=2,POWER_SUPPLY_STATUS_CHARGING=1,POWER_SUPPLY_STATUS_NOT_CHARGING=3};
union power_supply_propval {int intval; const char *strval;};
struct power_supply {int unused;}; struct bq2597x {bool usb_present;int mode;};
static struct bq2597x chip; static int read_error; static bool charging;
#define power_supply_get_drvdata(p) (&chip)
static int bq2597x_check_charge_enabled(struct bq2597x *b,bool *v){if(read_error) {return -EIO;}
 *v=charging;return 0;}
static int bq2597x_get_work_mode(struct bq2597x *b,int *mode){*mode=0;return 0;}
'''
        main = r'''
int main(void){union power_supply_propval v={.intval=77}; read_error=1;
 if(bq2597x_charger_get_property(0,POWER_SUPPLY_PROP_STATUS,&v)!=-EIO || v.intval!=77)return 1;
 read_error=0;charging=false;
 if(bq2597x_charger_get_property(0,POWER_SUPPLY_PROP_STATUS,&v)||v.intval!=3)return 2;
 charging=true;
 if(bq2597x_charger_get_property(0,POWER_SUPPLY_PROP_STATUS,&v)||v.intval!=1)return 3;
 return 0;}
'''
        self.run_c(preamble + body + main)

    def test_actual_charge_enable_guard_never_writes_enable(self):
        body = function((ROOT / 'power/bq25970_charger.c').read_text(), 'bq2597x_enable_charge')
        preamble = r'''
#include <stdbool.h>
#include <errno.h>
typedef unsigned char u8;
struct bq2597x {int unused;};
enum {BQ2597X_CHG_DISABLE=0,BQ2597X_CHG_EN_SHIFT=7,BQ2597X_REG_0C=12,BQ2597X_CHG_EN_MASK=128};
static int writes,err;static int last;
static int bq2597x_update_bits(struct bq2597x *b,int r,int mask,int val){writes++;last=val;return err;}
'''
        main = r'''
int main(void){struct bq2597x b={0};
 if(bq2597x_enable_charge(&b,true)!=-EOPNOTSUPP || writes)return 1;
 if(bq2597x_enable_charge(&b,false) || writes!=1 || last)return 2;
 err=-EIO;
 if(bq2597x_enable_charge(&b,false)!=-EIO)return 3;
 return 0;}
'''
        self.run_c(preamble + body + main)

    def test_actual_notifier_ignores_failed_reads_and_never_sleeps(self):
        body = function((ROOT / 'power/bq25970_charger.c').read_text(), 'bq2597x_notifier_call')
        preamble = r'''
#include <stdbool.h>
#include <errno.h>
struct notifier_block {int unused;}; struct power_supply {int unused;};
union power_supply_propval {int intval;};
struct bq2597x {struct power_supply *typec_psy,*fc2_psy;int data_lock;bool usb_present;int charge_state;};
static struct bq2597x fixture_chip;static int fail,changes,online;
enum {POWER_SUPPLY_PROP_ONLINE,NOTIFY_DONE,NOTIFY_OK};
#define container_of(n,t,f) (&fixture_chip)
#define mutex_lock(p) ((void)0)
#define mutex_unlock(p) ((void)0)
static int power_supply_get_property(struct power_supply *p,int prop,union power_supply_propval *v){
 if(fail) {return -EIO;}
 v->intval=online;return 0;}
static void power_supply_changed(struct power_supply *p){changes++;}
'''
        main = r'''
int main(void){struct power_supply p={0};fixture_chip.typec_psy=&p;fixture_chip.charge_state=77;fail=1;
 if(bq2597x_notifier_call(0,0,&p)!=NOTIFY_DONE||changes||fixture_chip.charge_state!=77)return 1;
 fail=0;online=1;
 if(bq2597x_notifier_call(0,0,&p)!=NOTIFY_OK||changes!=1||!fixture_chip.usb_present)return 2;
 online=0;
 if(bq2597x_notifier_call(0,0,&p)!=NOTIFY_OK||changes!=2||fixture_chip.usb_present)return 3;
 return 0;}
'''
        self.run_c(preamble + body + main)

    def test_charge_pump_is_default_off_and_managed_objects_are_not_unregistered_twice(self):
        source = (ROOT / 'power/bq25970_charger.c').read_text()
        dt = (ROOT / 'dts/xiaomi-umi-battery.dtsi').read_text().split('bq25970:')[1].split('\n\t};')[0]
        self.assertIn('status = "disabled";', dt)
        self.assertNotRegex(dt, r'ti,bq2597x,[\w-]+-disable;')
        self.assertNotIn('power_supply_unregister(', source)
        self.assertIn('devm_add_action_or_reset(bq->dev, bq2597x_cleanup, bq)', source)
        cleanup = function(source, 'bq2597x_cleanup')
        self.assertLess(cleanup.index('power_supply_unreg_notifier'), cleanup.index('power_supply_put'))
        notifier = function(source, 'bq2597x_notifier_call')
        self.assertNotIn('msleep(', notifier)
        self.assertNotIn('bq2597x_enable_charge(', notifier)
        self.assertIn('if (ret)', notifier)


if __name__ == '__main__':
    unittest.main()
