#!/usr/bin/env python3
"""Execute actual idle-work C with fake I/O; this is not a kernel/hardware test."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from test_reliability import function

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'fts521/fts.c').read_text()


def actual(name, source=SOURCE):
    # Locate a definition, not a forward declaration, then use the shared extractor.
    match = re.search(r'^(?:static )?(?:void|bool|int|ssize_t)\s+' + re.escape(name)
                      + r'\([^;]*?\n\{', source, re.M)
    body = source[match.start():]
    if not body.startswith('static '):
        body = 'static ' + body
    return function(body, name)


COMMON = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <pthread.h>
#include <errno.h>
#include <time.h>
typedef unsigned char u8;
#define OK 0
#define container_of(p,t,m) ((t *)((char *)(p)-offsetof(t,m)))
struct work_struct { int unused; };
struct delayed_work { struct work_struct work; bool pending; };
#define to_delayed_work(p) container_of(p,struct delayed_work,work)
struct device { void *data; };
struct fts_ts_info {
    struct delayed_work idle_work;
    pthread_mutex_t idle_lock;
    unsigned idle_holds;
    void *idle_owner;
    bool idle_conflict;
    bool idle_ready, idle_stopping, idle_pm_ready, irq_registered;
    bool sensor_sleep, notifier_registered;
    int resume_bit, notifier;
    struct device *dev;
};
#define mutex_lock(p) assert(!pthread_mutex_lock(p))
#define mutex_unlock(p) assert(!pthread_mutex_unlock(p))
#define system_wq NULL
#define msecs_to_jiffies(ms) (ms)
#define dev_get_drvdata(d) ((d)->data)
static void *current;
static int writes, warns, successes, schedules, write_result;
static struct fts_ts_info *current_info;
static void cancel_delayed_work_sync(struct delayed_work *w) {
    /* Waiting with this mutex held would deadlock the real callback. */
    assert(!pthread_mutex_trylock(&current_info->idle_lock));
    mutex_unlock(&current_info->idle_lock);
    w->pending = false;
}
static void mod_delayed_work(void *q, struct delayed_work *w, int delay) {
    assert(delay == 3000);
    schedules++;
    w->pending = true;
}
static int fts_write(u8 *data, size_t len) {
    static const u8 expected[] = {0xc0, 0x00, 0x00, 0xff};
    assert(len == sizeof(expected));
    for (size_t i=0;i<len;i++) assert(data[i] == expected[i]);
    assert(pthread_mutex_trylock(&current_info->idle_lock) == EBUSY);
    assert(!current_info->idle_stopping && !current_info->idle_holds);
    writes++;
    return write_result;
}
#define dev_warn(...) (warns++)
#define dev_info(...) (successes++)
static void setup(struct fts_ts_info *i, struct device *d) {
    *i=(struct fts_ts_info){.irq_registered=true,.resume_bit=1,.dev=d};
    assert(!pthread_mutex_init(&i->idle_lock, NULL));
    d->data=i;
    current_info=i;
}
'''


def helpers(source=SOURCE):
    return '\n'.join(actual(n, source) for n in (
        'fts_idle_hold_locked', 'fts_idle_hold', 'fts_idle_release_locked', 'fts_idle_release',
        'fts_idle_stop', 'fts_idle_time_work', 'fts_idle_pm_prepare',
        'fts_idle_pm_complete'))


LIFECYCLE = r'''
static void fire(struct fts_ts_info *i) {
    assert(i->idle_work.pending);
    i->idle_work.pending=false;
    fts_idle_time_work(&i->idle_work.work);
}
int main(void) {
    struct fts_ts_info i;
    struct device d;
    setup(&i,&d);
    fts_idle_time_work(&i.idle_work.work);
    assert(writes == 0); /* no init, no command */
    fts_idle_hold(&i); fts_idle_hold(&i);
    fts_idle_release(&i,true);
    assert(!i.idle_work.pending); /* inner scan cannot arm during init */
    fts_idle_release(&i,true);
    assert(i.idle_work.pending && schedules == 1);
    fire(&i);
    assert(writes == 1 && successes == 1 && warns == 0);
    fts_idle_hold(&i); fts_idle_release(&i,true);
    assert(i.idle_work.pending);
    fts_idle_hold(&i); /* reset / power-off / raw diagnostic entry */
    assert(!i.idle_work.pending);
    fts_idle_time_work(&i.idle_work.work); /* stale queued callback */
    assert(writes == 1);
    fts_idle_release(&i,false);
    assert(!i.idle_work.pending);
    fts_idle_hold(&i); fts_idle_release(&i,true);
    write_result=-5;
    fire(&i);
    assert(writes == 2 && warns == 1 && successes == 1);
    assert(!i.idle_work.pending); /* I/O failure is not retried */
    write_result=0;
    assert(!fts_idle_pm_prepare(&d));
    assert(!i.idle_work.pending);
    fts_idle_time_work(&i.idle_work.work);
    assert(writes == 2);
    fts_idle_pm_complete(&d); /* also the aborted-suspend path */
    assert(i.idle_work.pending);
    fire(&i);
    assert(writes == 3);
    fts_idle_pm_prepare(&d);
    fts_idle_hold(&i); fts_idle_release(&i,false); /* reset fails in sleep */
    fts_idle_pm_complete(&d);
    assert(!i.idle_work.pending && !i.idle_ready);
    current=&d;
    fts_idle_hold(&i);
    current=&i;
    fts_idle_hold(&i); /* overlapping recovery, unknown final ordering */
    fts_idle_release(&i,false);
    fts_idle_release(&i,true);
    assert(!i.idle_work.pending && !i.idle_ready);
    fts_idle_hold(&i); fts_idle_release(&i,true);
    i.irq_registered=false; fire(&i); assert(writes == 3);
    i.irq_registered=true;
    fts_idle_hold(&i); fts_idle_release(&i,true);
    i.sensor_sleep=true; fire(&i); assert(writes == 3);
    i.sensor_sleep=false;
    fts_idle_hold(&i); fts_idle_release(&i,true);
    fts_idle_stop(&i); /* remove, shutdown, failed probe */
    assert(!i.idle_work.pending);
    fts_idle_hold(&i); fts_idle_release(&i,true);
    fts_idle_time_work(&i.idle_work.work);
    assert(writes == 3 && !i.idle_work.pending && i.idle_holds == 0);
    return 0;
}
'''

INIT_STUBS = r'''
static int stage, fail_stage, registrations, irq_requests;
static int step(void) { return ++stage == fail_stage ? -5 : 0; }
static int fb_register_client(int *n) { registrations++; return step(); }
static int fts_interrupt_install(struct fts_ts_info *i) {
    int ret=step(); irq_requests++; i->irq_registered=ret==0; return ret;
}
static int fts_mode_handler(struct fts_ts_info *i,int force) { return step(); }
static int setScanMode(int mode,int flags) { return step(); }
static int fts_resetDisableIrqCount(void) { return step(); }
static int fts_enableInterrupt(void) { return step(); }
#define SCAN_MODE_ACTIVE 0
#define WAIT_AFTER_SENSEOFF 1
#define mdelay(x) ((void)0)
#define logError(...) ((void)0)
'''
INIT_MAIN = r'''
int main(void) {
    struct fts_ts_info i; struct device d;
    for (int failure=0; failure<=7; failure++) {
        setup(&i,&d); i.irq_registered=false;
        stage=0; fail_stage=failure; schedules=0;
        int ret=fts_init_sensing(&i);
        assert(i.idle_holds == 0);
        assert((ret<0) == (failure>0));
        assert(i.idle_work.pending == (failure==0));
        if (failure==0) {
            int regs=registrations, irqs=irq_requests;
            stage=0;
            assert(fts_init_sensing(&i)==0);
            assert(registrations==regs && irq_requests==irqs);
        }
        pthread_mutex_destroy(&i.idle_lock);
    }
    return 0;
}
'''
FLOW_STUBS = r'''
#define EVT_TYPE_ERROR_CRC_CX_HEAD 1
#define EVT_TYPE_ERROR_CRC_CX 2
#define EVT_TYPE_ERROR_CRC_CX_SUB_HEAD 3
#define EVT_TYPE_ERROR_CRC_CX_SUB 4
#define EVT_TYPE_ERROR_CRC_PANEL_HEAD 5
#define EVT_TYPE_ERROR_CRC_PANEL 6
#define SPECIAL_FULL_PANEL_INIT 2
#define SPECIAL_PANEL_INIT 1
#define logError(...) ((void)0)
static int fts_lenient_echo, reset_result, chip_result, sense_result;
static struct { int u8_cfgAfeVer,u8_panelCfgAfeVer; } systemInfo;
static int fts_system_reset(void) { return reset_result; }
static int pollForErrorType(u8 *e,int n) { return -1; }
static int fts_chip_initialization(struct fts_ts_info *i,u8 t) { return chip_result; }
static int fts_init_sensing(struct fts_ts_info *i) { return sense_result; }
'''
FLOW_MAIN = r'''
int main(void) {
    struct fts_ts_info i; struct device d;
    setup(&i,&d);
    assert(fts_init_flow(&i)==0 && i.idle_work.pending);
    reset_result=-5;
    assert(fts_init_flow(&i)<0 && !i.idle_work.pending);
    reset_result=0; systemInfo.u8_cfgAfeVer=1; chip_result=-5;
    assert(fts_init_flow(&i)<0 && !i.idle_work.pending);
    chip_result=0; sense_result=-5;
    assert(fts_init_flow(&i)<0 && !i.idle_work.pending);
    sense_result=0;
    assert(fts_init_flow(&i)==0 && i.idle_work.pending);
    assert(i.idle_holds==0);
    return 0;
}
'''


class TouchIdleTests(unittest.TestCase):
    def run_c(self, code, success=True):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'idle.c'
            exe = Path(tmp) / 'idle'
            src.write_text(code)
            built = subprocess.run(['gcc', '-std=gnu11', '-Wall', '-Werror',
                                    '-Wno-unused-function', '-Wno-unused-variable',
                                    '-pthread', str(src), '-o', str(exe)],
                                   capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            if success:
                self.assertEqual(result.returncode, 0, result.stderr)
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Assertion', result.stderr)

    def test_actual_idle_lifecycle_and_io_failure(self):
        self.run_c(COMMON + helpers() + LIFECYCLE)

    def test_actual_init_sensing_errors_and_reinitialization(self):
        self.run_c(COMMON + helpers() + INIT_STUBS + actual('fts_init_sensing') + INIT_MAIN)

    def test_actual_init_flow_does_not_mask_reset_or_calibration_failure(self):
        self.run_c(COMMON + helpers() + FLOW_STUBS + actual('fts_init_flow') + FLOW_MAIN)

    def test_counterexamples_are_rejected_by_runtime_assertions(self):
        mutants = [
            SOURCE.replace('cancel_delayed_work_sync(&info->idle_work);', ''),
            SOURCE.replace('info->idle_pm_ready = false;', ''),
            SOURCE.replace('ready && !info->idle_conflict', 'ready'),
            SOURCE.replace('if (--info->idle_holds == 0 && !info->idle_stopping)',
                           'if (--info->idle_holds == 0)'),
        ]
        for mutant in mutants:
            with self.subTest(mutant=mutants.index(mutant)):
                self.run_c(COMMON + helpers(mutant) + LIFECYCLE, success=False)
        mutant = SOURCE.replace('error |= ret;\n\t\tlogError(', 'error = 0;\n\t\tlogError(')
        self.run_c(COMMON + helpers() + FLOW_STUBS + actual('fts_init_flow', mutant) + FLOW_MAIN,
                   success=False)

    def test_running_idle_write_finishes_before_stop_returns(self):
        gate = r'''
static pthread_mutex_t gate=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv=PTHREAD_COND_INITIALIZER;
static bool entered, allow_finish, stop_started, stop_done;
'''
        common = COMMON.replace('static int fts_write(', gate + '\nstatic int fts_write(')
        common = common.replace('    writes++;', r'''
    mutex_lock(&gate);
    entered=true; pthread_cond_broadcast(&cv);
    while (!allow_finish) pthread_cond_wait(&cv,&gate);
    mutex_unlock(&gate);
    writes++;
''')
        main = r'''
static void *worker(void *p) {
    struct fts_ts_info *i=p;
    fts_idle_time_work(&i->idle_work.work);
    return NULL;
}
static void *stopper(void *p) {
    mutex_lock(&gate); stop_started=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    fts_idle_stop(p);
    mutex_lock(&gate); stop_done=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    return NULL;
}
int main(void) {
    struct fts_ts_info i; struct device d; pthread_t writer,stop;
    struct timespec deadline;
    setup(&i,&d); fts_idle_hold(&i); fts_idle_release(&i,true);
    assert(!pthread_create(&writer,NULL,worker,&i));
    mutex_lock(&gate);
    while (!entered) pthread_cond_wait(&cv,&gate);
    mutex_unlock(&gate);
    assert(!pthread_create(&stop,NULL,stopper,&i));
    mutex_lock(&gate);
    while (!stop_started) pthread_cond_wait(&cv,&gate);
    assert(!clock_gettime(CLOCK_REALTIME,&deadline));
    deadline.tv_nsec+=20000000;
    if (deadline.tv_nsec>=1000000000) { deadline.tv_nsec-=1000000000; deadline.tv_sec++; }
    int ret=0;
    while (!stop_done && ret!=ETIMEDOUT) ret=pthread_cond_timedwait(&cv,&gate,&deadline);
    assert(!stop_done); /* teardown must wait for the already-running I/O */
    allow_finish=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    pthread_join(writer,NULL); pthread_join(stop,NULL);
    assert(stop_done && writes==1 && !i.idle_work.pending);
    fts_idle_time_work(&i.idle_work.work); assert(writes==1);
    return 0;
}
'''
        self.run_c(common + helpers() + main)

    def test_actual_powercycle_does_not_mask_rail_failure(self):
        common = COMMON.replace('struct fts_ts_info {',
            'struct board { int reset_gpio; };\nstruct fts_ts_info {\n'
            '    void *vdd_reg, *avdd_reg; struct board *board;')
        stubs = r'''
#define GPIO_NOT_DEFINED -1
#define logError(...) ((void)0)
#define msleep(ms) ((void)0)
#define gpio_set_value(g,v) ((void)0)
#define release_all_touches(i) ((void)0)
#define setSystemResetedUp(v) ((void)0)
#define setSystemResetedDown(v) ((void)0)
static int rail_step, fail_rail;
static int rail(void *r) {
    assert(current_info->idle_holds && !current_info->idle_work.pending);
    return ++rail_step == fail_rail ? -5 : 0;
}
#define regulator_disable(r) rail(r)
#define regulator_enable(r) rail(r)
static void fts_disableInterrupt(void) {}
'''
        main = r'''
int main(void) {
    struct fts_ts_info i; struct device d;
    struct board board={.reset_gpio=GPIO_NOT_DEFINED};
    for (int failure=0;failure<=4;failure++) {
        setup(&i,&d); i.board=&board; i.vdd_reg=&i; i.avdd_reg=&i;
        fts_idle_hold(&i); fts_idle_release(&i,true);
        rail_step=0; fail_rail=failure;
        assert((fts_chip_powercycle(&i)<0) == (failure!=0));
        assert(rail_step==4 && !i.idle_work.pending && i.idle_holds==0);
        pthread_mutex_destroy(&i.idle_lock);
    }
    return 0;
}
'''
        self.run_c(common + helpers() + stubs + actual('fts_chip_powercycle') + main)
        mutant = SOURCE.replace('error |= ret;\n\t\tif (ret < 0)',
                                'error = ret;\n\t\tif (ret < 0)')
        self.run_c(common + helpers() + stubs + actual('fts_chip_powercycle', mutant) + main,
                   success=False)

    def test_actual_core_scan_mode_gates_rearming(self):
        core = (ROOT / 'fts521/fts_lib/ftsCore.c').read_text()
        stubs = r'''
#define FTS_CMD_SCAN_MODE 0xa0
#define SCAN_MODE_ACTIVE 0
#define SCAN_MODE_LOW_POWER 1
#define ACTIVE_MULTI_TOUCH 1
#define ERROR_SET_SCAN_MODE_FAIL (-256)
#define logError(...) ((void)0)
static struct { struct device dev; } client;
#define getClient() (&client)
static int scan_result;
static int scan_write(u8 *cmd,int size) {
    assert(current_info->idle_holds && !current_info->idle_work.pending);
    assert(cmd[0]==0xa0);
    assert(size==(cmd[1]==SCAN_MODE_LOW_POWER ? 2 : 3));
    return scan_result;
}
#define fts_write scan_write
'''
        main = r'''
#undef fts_write
int main(void) {
    struct fts_ts_info i;
    setup(&i,&client.dev);
    assert(setScanMode(SCAN_MODE_ACTIVE,ACTIVE_MULTI_TOUCH)==0);
    assert(i.idle_work.pending);
    assert(setScanMode(SCAN_MODE_ACTIVE,0)==0);
    assert(!i.idle_work.pending && !i.idle_ready);
    assert(setScanMode(SCAN_MODE_LOW_POWER,ACTIVE_MULTI_TOUCH)==0);
    assert(!i.idle_work.pending);
    assert(setScanMode(SCAN_MODE_ACTIVE,0xff)==0); /* diagnostic scan */
    assert(!i.idle_work.pending);
    scan_result=-5;
    assert(setScanMode(SCAN_MODE_ACTIVE,ACTIVE_MULTI_TOUCH)<0);
    assert(!i.idle_work.pending);
    scan_result=0;
    assert(setScanMode(SCAN_MODE_ACTIVE,ACTIVE_MULTI_TOUCH)==0);
    assert(i.idle_work.pending && i.idle_holds==0);
    return 0;
}
'''
        self.run_c(COMMON + helpers() + stubs + actual('setScanMode', core) + main)

    def test_lifecycle_hooks_reach_actual_helpers(self):
        for name in ('fwupdate_store', 'fts_init_flow', 'fts_init_sensing',
                     'fts_mode_handler', 'fts_resume_work', 'fts_suspend_work',
                     'fts_error_event_handler', 'fts_controller_ready_event_handler',
                     'fts_enable_reg', 'fts_chip_powercycle'):
            body = actual(name)
            self.assertIn('fts_idle_hold(info)', body)
            self.assertIn('fts_idle_release(info,', body)
        core = (ROOT / 'fts521/fts_lib/ftsCore.c').read_text()
        for name in ('fts_system_reset', 'setScanMode'):
            body = function(core.replace('int ' + name + '(', 'static int ' + name + '('), name)
            self.assertLess(body.index('fts_idle_hold(info)'), body.index('fts_write')
                            if name == 'setScanMode' else body.index('gpio_set_value'))
            self.assertIn('fts_idle_release(info,', body)
        remove = SOURCE[SOURCE.index('static void fts_remove('):]
        self.assertLess(remove.index('fts_idle_stop(info)'), remove.index('kfree(info)'))
        unwind = SOURCE[SOURCE.index('ProbeErrorExit_6:\n'):]
        self.assertLess(unwind.index('fts_idle_stop(info)'), unwind.index('input_unregister_device'))
        self.assertEqual(SOURCE.count('.shutdown\t\t= fts_shutdown'), 2)
        self.assertEqual(SOURCE.count('.pm = &fts_idle_pm_ops'), 2)


if __name__ == '__main__':
    unittest.main()
