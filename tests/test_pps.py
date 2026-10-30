#!/usr/bin/env python3
"""Execute the SMB5 policy with a simulated TCPM source and injected I/O failures.

No phone, PD messages, PMIC registers or kernel modules are used by these tests.
"""
from pathlib import Path
import ast
import subprocess
import sys
import tempfile
import re
import unittest

import test_reliability as reliability

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'power/qcom_pm8150b_charger.c').read_text(encoding='utf-8')
SOURCE = re.sub(r'^static (?:void smb5_pd_work|bool smb5_poll_changed)\([^\n]+;\n',
                '', SOURCE, flags=re.M)


class PpsTests(unittest.TestCase):
    run_c = reliability.ReliabilityTests.run_c

    def test_soc_inhibit_exits_pps_and_resume_cannot_enable_pps_or_clear_faults(self):
        self.run_c(r'''
#include <stdbool.h>
#include <errno.h>
#define mutex_lock(p) ((void)0)
#define mutex_unlock(p) ((void)0)
#define READ_ONCE(x) (x)
#define dev_err(...) ((void)0)
#define system_wq ((void *)0)
enum power_supply_property {POWER_SUPPLY_PROP_CURRENT_MAX,POWER_SUPPLY_PROP_CHARGING_ENABLED};
union power_supply_propval {int intval;};
struct smb5_chip {void *tcpm_psy,*dev;int pd_lock,status_change_work;
 bool user_inhibit,pps_enabled,pps_fault,pd_stopping;};
struct power_supply {struct smb5_chip *chip;};
static int stops,scheduled,stop_error;
static struct smb5_chip *power_supply_get_drvdata(struct power_supply *p) {return p->chip;}
static int smb5_set_current_limit(struct smb5_chip *c,int v) {return 0;}
static int smb5_set_prop_charging_enabled(struct smb5_chip *c,int v) {return 0;}
static int smb5_pps_stop(struct smb5_chip *c) {stops++;return stop_error;}
static void mod_delayed_work(void *q,int *w,int n) {scheduled++;}
''' + reliability.function(SOURCE, 'smb5_set_property') + r'''
int main(void) {
 struct smb5_chip c={.tcpm_psy=(void *)1,.pps_enabled=true,.pps_fault=true};
 struct power_supply p={&c};union power_supply_propval v={0};
 if(smb5_set_property(&p,POWER_SUPPLY_PROP_CHARGING_ENABLED,&v)||
    !c.user_inhibit||c.pps_enabled||!c.pps_fault||stops!=1||scheduled!=1)return 1;
 v.intval=1;
 if(smb5_set_property(&p,POWER_SUPPLY_PROP_CHARGING_ENABLED,&v)||
    c.user_inhibit||c.pps_enabled||!c.pps_fault||stops!=1||scheduled!=2)return 2;
 /* Reconcile permission=1 during a valid PPS session must preserve it. */
 c.pps_enabled=true;c.pps_fault=false;
 if(smb5_set_property(&p,POWER_SUPPLY_PROP_CHARGING_ENABLED,&v)||!c.pps_enabled)return 3;
 stop_error=-EIO;v.intval=0;
 if(smb5_set_property(&p,POWER_SUPPLY_PROP_CHARGING_ENABLED,&v)!=-EIO||
    !c.user_inhibit||c.pps_enabled)return 4;
 v.intval=2;
 if(smb5_set_property(&p,POWER_SUPPLY_PROP_CHARGING_ENABLED,&v)!=-EINVAL)return 5;
 return 0;
}
''')

    def test_rescue_audit_rejects_modular_vbus_provider(self):
        audit = ROOT / 'tools/config-audit.py'
        tree = ast.parse(audit.read_text(encoding='utf-8'))
        lists = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                 if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                 and node.targets[0].id in {'MUST', 'MUST_NOT'}}
        values = {name: value for name, value, _ in lists['MUST']}
        values.update({name: 'n' for name, _ in lists['MUST_NOT']})
        self.assertEqual(values['REGULATOR_QCOM_USB_VBUS'], 'y')
        with tempfile.TemporaryDirectory(prefix='umi-pps-config-') as tmp:
            path = Path(tmp) / 'config'
            fragment = Path(tmp) / 'fragment'
            fragment.write_text('CONFIG_REGULATOR_QCOM_USB_VBUS=y\n')
            for provider, expected in [('y', 0), ('m', 1), ('n', 1)]:
                with self.subTest(provider=provider):
                    values['REGULATOR_QCOM_USB_VBUS'] = provider
                    path.write_text(''.join(f'CONFIG_{k}={v}\n' for k, v in values.items()))
                    result = subprocess.run([sys.executable, str(audit), str(path),
                                             '--fragment', str(fragment)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def harness(self):
        constants = ['SMB5_PPS_MIN_UV', 'SMB5_PPS_MAX_UV', 'SMB5_PPS_STEP_UV',
                     'SMB5_PPS_STEP_UA', 'SMB5_PPS_POLL_MS', 'SDP_CURRENT_UA',
                     'CURRENT_SCALE_FACTOR', 'USB_DEFAULT_CURRENT_UA', 'BC12_CURRENT_UA',
                     'USBIN_OPTIONS_1_CFG', 'BC1P2_SRC_DETECT_BIT', 'HVDCP_EN_BIT',
                     'HVDCP_AUTH_ALG_EN_CFG_BIT', 'HVDCP_AUTONOMOUS_MODE_EN_CFG_BIT',
                     'HVDCP_NO_AUTH_QC3_CFG_BIT', 'CMD_APSD', 'APSD_RERUN_BIT',
                     'APSD_STATUS', 'APSD_RESULT_STATUS', 'APSD_DTC_STATUS_DONE_BIT',
                     'APSD_RESULT_STATUS_MASK', 'DCP_CHARGER_BIT', 'CDP_CHARGER_BIT',
                     'SDP_CHARGER_BIT', 'FLOAT_CHARGER_BIT', 'OCP_CHARGER_BIT',
                     'USBIN_ADAPTER_ALLOW_OVERRIDE',
                     'USBIN_ADAPTER_ALLOW_MASK', 'USBIN_ADAPTER_ALLOW_CONTINUOUS',
                     'FLOAT_VOLTAGE_CFG', 'FLOAT_VOLTAGE_SETTING_MASK',
                     'FAST_CHARGE_CURRENT_CFG', 'FAST_CHARGE_CURRENT_SETTING_MASK']
        defines = '\n'.join(re.search(r'^#define\s+' + name + r'\s+[^\n]+',
                                      SOURCE, re.M).group(0) for name in constants)
        poll_properties = re.search(r'^static const enum power_supply_property '
                                    r'smb5_poll_properties\[\] = \{.*?^};',
                                    SOURCE, re.M | re.S).group(0)
        return r'''
#include <stdbool.h>
#include <stdio.h>
#include <errno.h>
#include <string.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define min(a,b) ((a)<(b)?(a):(b))
#define round_down(a,b) ((a)&~((b)-1))
#define rounddown(a,b) ((a)/(b)*(b))
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) (((~0U)<<(l))&(~0U>>(31-(h))))
#define READ_ONCE(x) (x)
#define mutex_lock(p) ((void)0)
#define mutex_unlock(p) ((void)0)
#define dev_err_ratelimited(d,fmt,...) ((void)(d),(void)printf(fmt,__VA_ARGS__))
#define msecs_to_jiffies(x) (x)
''' + defines + r'''
enum power_supply_property {POWER_SUPPLY_PROP_ONLINE,POWER_SUPPLY_PROP_USB_TYPE,
 POWER_SUPPLY_PROP_VOLTAGE_NOW,POWER_SUPPLY_PROP_CURRENT_NOW,POWER_SUPPLY_PROP_VOLTAGE_MIN,
 POWER_SUPPLY_PROP_VOLTAGE_MAX,POWER_SUPPLY_PROP_CURRENT_MAX,
 POWER_SUPPLY_PROP_STATUS,POWER_SUPPLY_PROP_HEALTH,POWER_SUPPLY_PROP_CHARGING_ENABLED};
union power_supply_propval {int intval;};
''' + poll_properties + r'''
enum {POWER_SUPPLY_HEALTH_GOOD=1,POWER_SUPPLY_USB_TYPE_C=6,
 POWER_SUPPLY_USB_TYPE_PD=7,POWER_SUPPLY_USB_TYPE_PD_PPS=8};
struct battery_info {int voltage_max_design_uv,constant_charge_current_max_ua;};
struct smb5_chip {bool apsd_enabled,pps_enabled,pps_active,pps_fault,user_inhibit,pd_stopping;
 int pps_error,pps_voltage_uv,pps_current_ua,input_max_ua,pd_lock,base,status_change_work;
 bool poll_snapshot_valid;int poll_values[ARRAY_SIZE(smb5_poll_properties)];
 void *dev,*regmap,*chg_psy;struct battery_info *batt_info;};
static int calls,fail_at,online,voltage,current,source_max,health,usb_type;
static int input_limit,charging,enabled_calls,refuse,disable_calls,reg_calls,fv_reg,fcc_reg;
static int apsd_status,apsd_result,apsd_options,reruns,notified,unsafe_transition;
static int measured_current,poll_override,poll_override_value,poll_failure,poll_reads;
static int scheduled;
static int step(void) {return ++calls==fail_at ? -EIO : 0;}
static int smb5_source_get(struct smb5_chip *c,enum power_supply_property p) {
 int ret=step(); if(ret)return ret;
 switch(p) {case POWER_SUPPLY_PROP_ONLINE:return online;
 case POWER_SUPPLY_PROP_USB_TYPE:return usb_type;
 case POWER_SUPPLY_PROP_VOLTAGE_NOW:return voltage;
 case POWER_SUPPLY_PROP_CURRENT_NOW:return current;
 case POWER_SUPPLY_PROP_VOLTAGE_MIN:return 3300000;
 case POWER_SUPPLY_PROP_VOLTAGE_MAX:return 11000000;
 case POWER_SUPPLY_PROP_CURRENT_MAX:return source_max;
 default:return -EINVAL;}}
static int smb5_source_set(struct smb5_chip *c,enum power_supply_property p,int v) {
 int ret=step();if(ret)return ret;
 if(p==POWER_SUPPLY_PROP_VOLTAGE_NOW && voltage!=v && (charging||input_limit>100000))
  unsafe_transition++;
 if(p==POWER_SUPPLY_PROP_ONLINE) {if(!refuse)online=v;if(v==1){voltage=5000000;current=1500000;}}
 if(p==POWER_SUPPLY_PROP_CURRENT_NOW)current=v;
 if(p==POWER_SUPPLY_PROP_VOLTAGE_NOW)voltage=v;
 return 0;}
static int smb5_set_prop_charging_enabled(struct smb5_chip *c,unsigned v) {
 if(!v) {disable_calls++;}
 int ret=step();if(ret)return ret;
 charging=v;if(v)enabled_calls++;return 0;}
static int smb5_set_current_limit(struct smb5_chip *c,unsigned v) {
 int ret=step();if(ret)return ret;input_limit=v;return 0;}
static int smb5_get_prop_health(struct smb5_chip *c,int *v) {
 int ret=step();if(ret)return ret;*v=health;return 0;}
static int regmap_update_bits(void *m,int reg,int mask,int val) {
 reg_calls++;int ret=step();if(ret)return ret;
 if(reg==FLOAT_VOLTAGE_CFG)fv_reg=val;
 if(reg==FAST_CHARGE_CURRENT_CFG)fcc_reg=val;
 if(reg==USBIN_OPTIONS_1_CFG)apsd_options=(apsd_options&~mask)|(val&mask);
 if(reg==CMD_APSD)reruns++;
 return 0;}
static int regmap_read(void *m,int reg,unsigned *val) {
 int ret=step();if(ret)return ret;
 *val=reg==APSD_STATUS?apsd_status:apsd_result;return 0;}
static void power_supply_changed(void *p) {notified++;}
static void schedule_delayed_work(int *w,int delay) {scheduled++;}
/* Telemetry reads are independent of policy I/O failure injection. */
static int smb5_get_property(void *p,enum power_supply_property prop,
                             union power_supply_propval *val) {
 poll_reads++;
 if((int)prop==poll_failure)return -EIO;
 if((int)prop==poll_override) {val->intval=poll_override_value;return 0;}
 switch(prop) {
 case POWER_SUPPLY_PROP_STATUS:val->intval=charging;break;
 case POWER_SUPPLY_PROP_HEALTH:val->intval=health;break;
 case POWER_SUPPLY_PROP_CURRENT_NOW:val->intval=measured_current;break;
 case POWER_SUPPLY_PROP_VOLTAGE_NOW:val->intval=voltage;break;
 case POWER_SUPPLY_PROP_ONLINE:val->intval=online;break;
 case POWER_SUPPLY_PROP_USB_TYPE:val->intval=usb_type;break;
 case POWER_SUPPLY_PROP_CURRENT_MAX:val->intval=input_limit;break;
 case POWER_SUPPLY_PROP_CHARGING_ENABLED:val->intval=charging;break;
 default:return -EINVAL;
 }
 return 0;}
static struct smb5_chip reset(void) {
 calls=0;fail_at=0;online=1;voltage=5000000;current=1500000;
 source_max=3000000;health=POWER_SUPPLY_HEALTH_GOOD;usb_type=POWER_SUPPLY_USB_TYPE_PD_PPS;
 input_limit=500000;charging=0;enabled_calls=0;refuse=0;disable_calls=0;reg_calls=0;
 apsd_status=APSD_DTC_STATUS_DONE_BIT;apsd_result=DCP_CHARGER_BIT;
 apsd_options=0;reruns=0;notified=0;unsafe_transition=0;
 measured_current=1000000;poll_override=-1;poll_failure=-1;poll_reads=0;scheduled=0;
 return (struct smb5_chip){.pps_enabled=true,.pps_voltage_uv=9000000,
 .pps_current_ua=1500000,.input_max_ua=1500000};}
''' + '\n'.join(reliability.function(SOURCE, name) for name in [
            'smb5_pps_valid_target', 'smb5_set_apsd', 'smb5_bc12_current',
            'smb5_pps_stop', 'smb5_pps_update',
            'smb5_poll_changed', 'smb5_pd_work', 'smb5_battery_config'])

    def test_poll_notifies_each_mutable_property_but_suppresses_identical_samples(self):
        public = re.search(r'smb5_properties\[\] = \{(.*?)\n};', SOURCE, re.S).group(1)
        sampled = re.search(r'smb5_poll_properties\[\] = \{(.*?)\n};', SOURCE, re.S).group(1)
        properties = lambda text: set(re.findall(r'POWER_SUPPLY_PROP_\w+', text))
        self.assertEqual(properties(sampled), properties(public) - {
            'POWER_SUPPLY_PROP_MANUFACTURER', 'POWER_SUPPLY_PROP_MODEL_NAME'})
        self.run_c(self.harness() + r'''
int main(void) {
 struct smb5_chip c=reset();smb5_pd_work(&c);
 if(notified!=1||!c.poll_snapshot_valid)return 1;
 smb5_pd_work(&c);
 if(notified!=1||scheduled!=2)return 2;
 for(unsigned i=0;i<ARRAY_SIZE(smb5_poll_properties);i++) {
  c=reset();smb5_pd_work(&c);
  poll_override=smb5_poll_properties[i];poll_override_value=c.poll_values[i]+1;
  smb5_pd_work(&c);
  if(notified!=2||c.poll_values[i]!=poll_override_value)return 3;
  smb5_pd_work(&c);
  if(notified!=2)return 4;
 }
 c=reset();smb5_pd_work(&c);
 int reads=poll_reads,queued=scheduled;c.pd_stopping=true;
 smb5_pd_work(&c);
 if(poll_reads!=reads||scheduled!=queued||notified!=1)return 5;
 return 0;
}
''')

    def test_poll_read_errors_notify_invalidate_and_recover_without_partial_cache(self):
        self.run_c(self.harness() + r'''
int main(void) {
 for(unsigned i=0;i<ARRAY_SIZE(smb5_poll_properties);i++) {
  struct smb5_chip c=reset();smb5_pd_work(&c);
  int old[ARRAY_SIZE(smb5_poll_properties)];memcpy(old,c.poll_values,sizeof(old));
  measured_current++;poll_failure=smb5_poll_properties[i];
  smb5_pd_work(&c);
  if(notified!=2||c.poll_snapshot_valid||memcmp(old,c.poll_values,sizeof(old)))return 1;
  smb5_pd_work(&c);
  if(notified!=3||c.poll_snapshot_valid||c.pps_fault||!charging)return 2;
  poll_failure=-1;smb5_pd_work(&c);
  if(notified!=4||!c.poll_snapshot_valid)return 3;
  smb5_pd_work(&c);
  if(notified!=4)return 4;
 }
 /* Policy failures must notify even if exported measurements are unchanged. */
 struct smb5_chip c=reset();smb5_pd_work(&c);
 for(unsigned i=0;i<ARRAY_SIZE(smb5_poll_properties);i++) {
  if(smb5_poll_properties[i]==POWER_SUPPLY_PROP_STATUS||
     smb5_poll_properties[i]==POWER_SUPPLY_PROP_CHARGING_ENABLED)c.poll_values[i]=0;
  if(smb5_poll_properties[i]==POWER_SUPPLY_PROP_ONLINE)c.poll_values[i]=1;
  if(smb5_poll_properties[i]==POWER_SUPPLY_PROP_VOLTAGE_NOW)c.poll_values[i]=5000000;
  if(smb5_poll_properties[i]==POWER_SUPPLY_PROP_CURRENT_MAX)c.poll_values[i]=100000;
 }
 fail_at=calls+1;smb5_pd_work(&c);
 if(notified!=2||!c.pps_fault||charging)return 5;
 return 0;
}
''')

    def test_success_and_every_policy_io_failure_latches_off(self):
        self.run_c(self.harness() + r'''
int main(void) {
 struct smb5_chip c=reset();smb5_pd_work(&c);int total=calls;
 if(!c.pps_active||c.pps_fault||!charging||online!=2||voltage!=9000000||
    input_limit!=1500000)return 1;
 /* Every operation before the final enable is an independently fallible I/O. */
 for(int i=1;i<=total;i++) {
  c=reset();fail_at=i;smb5_pd_work(&c);
  if(!c.pps_fault||c.pps_enabled||c.pps_error!=-EIO||charging||enabled_calls||
     !disable_calls||input_limit>500000||online==2) {
   printf("unsafe failure at %d/%d online=%d enabled=%d limit=%d\n",i,total,online,charging,input_limit);
   return 2;}
 }
 printf("PPS operation failure points: %d\n",total);return 0;
}
''')

    def test_contract_readback_refusal_health_limits_and_disconnect(self):
        self.run_c(self.harness() + r'''
int main(void) {
 struct smb5_chip c=reset();refuse=1;smb5_pd_work(&c);
 if(charging||!c.pps_fault||enabled_calls)return 1;
 c=reset();health=2;smb5_pd_work(&c);
 if(charging||!c.pps_fault||enabled_calls)return 2;
 c=reset();c.pps_enabled=false;health=2;smb5_pd_work(&c);
 if(charging||c.pps_fault||c.pps_enabled)return 12;
 health=POWER_SUPPLY_HEALTH_GOOD;smb5_pd_work(&c);
 if(!charging||c.pps_fault||c.pps_enabled||input_limit!=1500000)return 13;
 c=reset();source_max=1000000;smb5_pd_work(&c);
 if(!charging||input_limit!=1000000||current!=1000000)return 3;
 c=reset();online=0;smb5_pd_work(&c);
 if(charging||c.pps_enabled||c.pps_active||c.pps_fault)return 4;
 c=reset();usb_type=1;smb5_pd_work(&c);
 if(charging||!c.pps_fault||enabled_calls)return 5;
 c=reset();c.user_inhibit=true;smb5_pd_work(&c);
 if(charging||enabled_calls)return 6;
 c=reset();c.pps_fault=true;smb5_pd_work(&c);
 if(charging||enabled_calls)return 7;
 c=reset();c.pps_enabled=false;current=100000;smb5_pd_work(&c);
 if(!charging||input_limit>current||c.pps_active)return 8;
 c=reset();c.pps_enabled=false;voltage=12000000;smb5_pd_work(&c);
 if(charging||!c.pps_fault)return 9;
 c=reset();current=100000;smb5_pd_work(&c);
 if(charging||!c.pps_fault||enabled_calls)return 10;
 c=reset();voltage=12000000;smb5_pd_work(&c);
 if(charging||!c.pps_fault||enabled_calls)return 11;
 return 0;
}
''')

    def test_heartbeat_sends_new_request_and_stop_attempts_all_operations(self):
        self.run_c(self.harness() + r'''
int main(void) {
 struct smb5_chip c=reset();smb5_pd_work(&c);int first=calls;
 smb5_pd_work(&c);
 if(calls<=first||!charging||c.pps_fault||online!=2)return 1;
 /* APDO CURRENT_MAX below the user target must keep the capped contract. */
 c=reset();source_max=1000000;smb5_pd_work(&c);first=calls;
 smb5_pd_work(&c);
 if(calls<=first||c.pps_fault||!charging||online!=2||
    current!=1000000||input_limit!=1000000)return 2;
 for(int i=1;i<=6;i++) {
  c=reset();online=2;c.pps_active=true;charging=1;fail_at=i;
  int ret=smb5_pps_stop(&c);
  if(!ret||!disable_calls||calls<i)return 3;
  /* A failed load-disable must not skip the protocol fallback attempt. */
  if(i==1 && online!=1)return 4;
 }
 return 0;
}
''')

    def test_non_pd_detection_pending_recovery_and_contract_precedence(self):
        self.run_c(self.harness() + r'''
int main(void) {
 struct smb5_chip c=reset();c.pps_enabled=false;usb_type=POWER_SUPPLY_USB_TYPE_C;
 current=0;voltage=0;smb5_pd_work(&c);
 if(charging||c.pps_fault||input_limit>100000||!notified)return 1;
 voltage=5000000;smb5_pd_work(&c);
 /* A stale DONE/DCP result must not enable charging in the rerun cycle. */
 if(charging||c.pps_fault||reruns!=1||!c.apsd_enabled||apsd_options!=8)return 2;
 apsd_status=0;smb5_pd_work(&c);
 if(charging||c.pps_fault||reruns!=1)return 3;
 apsd_status=1;smb5_pd_work(&c);
 if(!charging||c.pps_fault||input_limit!=1500000||reruns!=1)return 4;
 apsd_result=CDP_CHARGER_BIT;smb5_pd_work(&c);
 if(!charging||input_limit!=1500000)return 5;
 apsd_result=SDP_CHARGER_BIT;smb5_pd_work(&c);
 if(!charging||input_limit!=100000)return 6;
 unsigned unknowns[]={0,FLOAT_CHARGER_BIT,OCP_CHARGER_BIT,
  SDP_CHARGER_BIT|DCP_CHARGER_BIT};
 for(unsigned i=0;i<sizeof(unknowns)/sizeof(*unknowns);i++) {
  apsd_result=unknowns[i];smb5_pd_work(&c);
  if(charging||input_limit||c.pps_fault)return 7;
 }
 /* A PD budget of zero is never replaced by stale BC1.2 detection. */
 usb_type=POWER_SUPPLY_USB_TYPE_PD;apsd_result=DCP_CHARGER_BIT;smb5_pd_work(&c);
 if(charging||input_limit||c.apsd_enabled||apsd_options)return 8;
 current=100000;smb5_pd_work(&c);
 if(!charging||input_limit!=100000||c.pps_fault)return 9;
 /* Rp 1.5A/3A owns the limit; do not start BC1.2 in that case. */
 usb_type=POWER_SUPPLY_USB_TYPE_C;current=3000000;smb5_pd_work(&c);
 if(!charging||input_limit!=1500000||c.apsd_enabled)return 10;
 current=0;smb5_pd_work(&c);smb5_pd_work(&c);
 online=0;smb5_pd_work(&c);
 if(charging||c.apsd_enabled||apsd_options||c.pps_fault)return 11;
 online=1;smb5_pd_work(&c);
 if(charging||reruns!=3||c.pps_fault)return 12;
 c.user_inhibit=true;smb5_pd_work(&c);
 if(charging||c.pps_fault)return 13;
 return 0;
}
''')

    def test_every_non_pd_detection_io_failure_stops_load(self):
        self.run_c(self.harness() + r'''
int main(void) {
 for(int enabled=0;enabled<=1;enabled++) {
  struct smb5_chip c=reset();c.pps_enabled=false;c.apsd_enabled=enabled;
  usb_type=POWER_SUPPLY_USB_TYPE_C;current=0;smb5_pd_work(&c);
  int total=calls;
  for(int i=1;i<=total;i++) {
   c=reset();c.pps_enabled=false;c.apsd_enabled=enabled;charging=1;
   usb_type=POWER_SUPPLY_USB_TYPE_C;current=0;fail_at=i;smb5_pd_work(&c);
   if(charging||!disable_calls||input_limit>100000||!c.pps_fault) {
    printf("BC1.2 failure enabled=%d call=%d/%d\n",enabled,i,total);return 1;
   }
  }
 }
 return 0;
}
''')

    def test_failed_detection_rerun_cannot_leave_bc12_on_during_pd_retry(self):
        self.run_c(self.harness() + r'''
int main(void) {
 struct smb5_chip c=reset();fail_at=2;
 if(smb5_set_apsd(&c,true)!=-EIO||!c.apsd_enabled||apsd_options!=8)return 1;
 fail_at=0;
 if(smb5_set_apsd(&c,false)||c.apsd_enabled||apsd_options)return 2;
 return 0;
}
''')

    def test_pps_voltage_changes_shed_load_and_publish_state(self):
        self.run_c(self.harness() + r'''
int main(void) {
 struct smb5_chip c=reset();charging=1;input_limit=1500000;smb5_pd_work(&c);
 if(c.pps_fault||!charging||unsafe_transition||!notified)return 1;
 int disables=disable_calls;c.pps_voltage_uv=5000000;smb5_pd_work(&c);
 if(c.pps_fault||!charging||unsafe_transition||disable_calls<=disables||notified!=2)
  return 2;
 disables=disable_calls;smb5_pd_work(&c);
 if(c.pps_fault||!charging||disable_calls!=disables||unsafe_transition)return 3;
 return 0;
}
''')

    def test_target_boundaries_and_pm8150b_register_encoding(self):
        self.run_c(self.harness() + r'''
int main(void) {
 struct smb5_chip c=reset();
 if(smb5_pps_valid_target(5000000,500000,1500000)||
    smb5_pps_valid_target(9000000,1500000,1500000))return 1;
 int bad[][2]={{-1,500000},{4999999,500000},{9000001,500000},{5020001,500000},
 {5000000,-1},{5000000,499999},{5000000,1500001},{5000000,550001}};
 for(unsigned i=0;i<sizeof(bad)/sizeof(*bad);i++)
  if(smb5_pps_valid_target(bad[i][0],bad[i][1],1500000)!=-EINVAL)return 2;
 struct battery_info b={4400000,1500000};c.batt_info=&b;
 if(smb5_battery_config(&c)||fv_reg!=80||fcc_reg!=30||c.input_max_ua!=1500000)return 3;
 for(int i=1;i<=2;i++) {c=reset();c.batt_info=&b;fail_at=i;
  if(smb5_battery_config(&c)!=-EIO||calls!=i)return 4;}
 b.voltage_max_design_uv=4790001;c=reset();c.batt_info=&b;
 if(smb5_battery_config(&c)!=-EINVAL||reg_calls)return 5;
 b.voltage_max_design_uv=4400000;b.constant_charge_current_max_ua=-1;
 if(smb5_battery_config(&c)!=-EINVAL||reg_calls)return 6;
 return 0;
}
''')

    def test_hardware_health_is_not_good_on_fault_or_read_failure(self):
        names = ['BATTERY_CHARGER_STATUS_2', 'BATTERY_CHARGER_STATUS_7_REG',
                 'CHARGER_ERROR_STATUS_BAT_OV_BIT', 'CHARGER_ERROR_STATUS_SFT_EXPIRE_BIT',
                 'CHARGER_ERROR_STATUS_BAT_TERM_MISSING_BIT', 'BAT_TEMP_STATUS_TOO_COLD_BIT',
                 'BAT_TEMP_STATUS_TOO_HOT_BIT', 'BAT_TEMP_STATUS_COLD_SOFT_BIT',
                 'BAT_TEMP_STATUS_HOT_SOFT_BIT', 'BAT_TEMP_STATUS_TOO_COLD_AFP_BIT',
                 'BAT_TEMP_STATUS_TOO_HOT_AFP_BIT']
        defines = '\n'.join(re.search(r'^#define\s+' + name + r'\s+[^\n]+',
                                      SOURCE, re.M).group(0) for name in names)
        self.run_c(r'''
#include <errno.h>
#define BIT(n) (1U<<(n))
#define dev_err(...) ((void)0)
enum {POWER_SUPPLY_HEALTH_GOOD=1,POWER_SUPPLY_HEALTH_OVERVOLTAGE,
 POWER_SUPPLY_HEALTH_UNSPEC_FAILURE,POWER_SUPPLY_HEALTH_COLD,POWER_SUPPLY_HEALTH_OVERHEAT,
 POWER_SUPPLY_HEALTH_COOL,POWER_SUPPLY_HEALTH_WARM};
struct smb5_chip {void *dev,*regmap;int base;};
static unsigned fault,temp;static int calls,fail;
static int regmap_read(void *m,int r,unsigned *v) {
 if(++calls==fail) {return -EIO;}
 *v=calls==1?fault:temp;return 0;}
''' + defines + '\n' + reliability.function(SOURCE, 'smb5_get_prop_health') + r'''
int main(void) {struct smb5_chip c={0};int val=77;
 for(fail=1;fail<=2;fail++) {calls=0;
  if(smb5_get_prop_health(&c,&val)!=-EIO||val!=77)return 1;}
 fail=0;
 unsigned faults[]={CHARGER_ERROR_STATUS_BAT_OV_BIT,CHARGER_ERROR_STATUS_SFT_EXPIRE_BIT,
  CHARGER_ERROR_STATUS_BAT_TERM_MISSING_BIT};
 for(unsigned i=0;i<3;i++) {calls=0;fault=faults[i];
  if(smb5_get_prop_health(&c,&val)||val==POWER_SUPPLY_HEALTH_GOOD)return 2;}
 fault=0;
 unsigned temps[]={BAT_TEMP_STATUS_TOO_COLD_BIT,BAT_TEMP_STATUS_TOO_HOT_BIT,
  BAT_TEMP_STATUS_COLD_SOFT_BIT,BAT_TEMP_STATUS_HOT_SOFT_BIT,
  BAT_TEMP_STATUS_TOO_COLD_AFP_BIT,BAT_TEMP_STATUS_TOO_HOT_AFP_BIT};
 for(unsigned i=0;i<sizeof(temps)/sizeof(*temps);i++) {calls=0;temp=temps[i];
  if(smb5_get_prop_health(&c,&val)||val==POWER_SUPPLY_HEALTH_GOOD)return 3;}
 temp=0;calls=0;
 if(smb5_get_prop_health(&c,&val)||val!=POWER_SUPPLY_HEALTH_GOOD)return 4;
 return 0;}
''')

    def test_input_telemetry_scales_buck_current_and_propagates_errors(self):
        self.run_c(r'''
#include <errno.h>
#include <limits.h>
#define dev_err(...) ((void)0)
#define IS_ERR(p) (0)
#define PTR_ERR(p) (-EIO)
struct iio_channel {int unused;};
struct smb5_chip {void *dev;struct iio_channel *usb_in_i_chan;};
static int online=1,online_ret,adc_ret,adc_value,reads;
static int smb5_get_prop_usb_online(struct smb5_chip *c,int *v) {
 *v=online;return online_ret;}
static int iio_read_channel_processed(struct iio_channel *c,int *v) {
 reads++;*v=adc_value;return adc_ret;}
''' + reliability.function(SOURCE, 'smb5_get_iio_chan') + r'''
int main(void) {
 struct iio_channel i,v;struct smb5_chip c={.usb_in_i_chan=&i};int out=77;
 adc_value=200000;
 if(smb5_get_iio_chan(&c,&i,&out)||out!=1000000)return 1;
 adc_value=5000000;
 if(smb5_get_iio_chan(&c,&v,&out)||out!=5000000)return 2;
 online_ret=-EIO;out=77;reads=0;
 if(smb5_get_iio_chan(&c,&i,&out)!=-EIO||out!=77||reads)return 3;
 online_ret=0;adc_ret=-EIO;
 if(smb5_get_iio_chan(&c,&i,&out)!=-EIO)return 4;
 adc_ret=0;adc_value=INT_MAX;
 if(smb5_get_iio_chan(&c,&i,&out)!=-ERANGE)return 5;
 adc_value=-1;
 if(smb5_get_iio_chan(&c,&i,&out)!=-ERANGE)return 6;
 online=0;reads=0;
 if(smb5_get_iio_chan(&c,&i,&out)||out||reads)return 7;
 return 0;
}
''')

    def test_fuel_gauge_teardown_stops_notifier_and_work_before_freeing_data(self):
        fg = (ROOT / 'power/qcom_fg.c').read_text(encoding='utf-8')
        self.run_c(r'''
#include <stdbool.h>
struct qcom_fg_chip {void *chg_psy,*batt_psy,*batt_info,*sram_wq;
 int nb,status_changed_work;};
struct platform_device {struct qcom_fg_chip *data;};
static int sequence;
static struct qcom_fg_chip *platform_get_drvdata(struct platform_device *p) {
 return p->data;}
static void power_supply_unreg_notifier(int *n) {sequence=sequence*10+1;}
static void cancel_delayed_work_sync(int *w) {sequence=sequence*10+2;}
static void power_supply_put_battery_info(void *p,void *b) {sequence=sequence*10+3;}
static void destroy_workqueue(void *w) {sequence=sequence*10+4;}
''' + reliability.function(fg, 'qcom_fg_remove') + r'''
int main(void) {
 struct qcom_fg_chip c={.chg_psy=(void *)1,.sram_wq=(void *)2};
 struct platform_device p={.data=&c};qcom_fg_remove(&p);
 if(sequence!=1234)return 1;
 sequence=0;c.chg_psy=0;c.sram_wq=0;qcom_fg_remove(&p);
 if(sequence!=3)return 2;
 return 0;
}
''')

    def test_pd_init_never_enables_load_or_overwrites_tcpm_roles(self):
        defines = '\n'.join(re.findall(r'^#define[^\n]+', SOURCE, re.M))
        start = SOURCE.index('static const struct smb5_register smb5_init_seq[]')
        array = SOURCE[start:SOURCE.index('\n};', start) + 3]
        self.run_c(r'''
#include <stdio.h>
#include <stdbool.h>
#include <errno.h>
#define BIT(n) (1U<<(n))
#define GENMASK(h,l) ((1U<<((h)+1))-(1U<<(l)))
#define ARRAY_SIZE(x) (sizeof(x)/sizeof(*(x)))
#define dev_dbg(...) ((void)0)
#define dev_err_probe(d,r,...) (r)
typedef unsigned char u8;typedef unsigned short u16;
struct smb5_register {u16 addr;u8 mask,val;};
struct smb5_chip {void *tcpm_psy,*dev,*regmap;int base;};
''' + defines + r'''
static int calls,fail,role_write,enable_write,icl,load,apsd;
static int regmap_update_bits(void *m,int reg,int mask,int value) {
 if(++calls==fail)return -EIO;
 if(reg>=0x500 && reg<0x600)role_write++;
 if(reg==CHARGING_ENABLE_CMD && value)enable_write++;
 if(reg==CMD_ICL_OVERRIDE)icl=value;
 if(reg==USBIN_LOAD_CFG)load=value;
 if(reg==USBIN_OPTIONS_1_CFG)apsd=value;
 return 0;}
''' + array + '\n' + reliability.function(SOURCE, 'smb5_init_hw') + r'''
int main(void) {struct smb5_chip c={.tcpm_psy=(void *)1};
 /* Keep expectations independent from the driver macros under test. */
 if(smb5_init_hw(&c)||role_write||enable_write||icl!=0x1||
    load!=0x10||apsd)return 1;
 int total=calls;
 for(int i=1;i<=total;i++) {calls=0;fail=i;
  if(smb5_init_hw(&c)!=-EIO||calls!=i||role_write||enable_write)return 2;}
 return 0;}
''')


if __name__ == '__main__':
    unittest.main()
