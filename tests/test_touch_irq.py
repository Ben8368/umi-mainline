#!/usr/bin/env python3
"""Run extracted IRQ code with a blocking IRQ model, not a kernel test."""
from pathlib import Path
import unittest

import test_touch_idle as idle
from test_touch_idle import COMMON, actual, helpers

ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / 'fts521/fts_lib/ftsCore.c').read_text()
SOURCE = (ROOT / 'fts521/fts.c').read_text()

IRQ_MODEL = r"""
#include <stdatomic.h>
#include <stdlib.h>
#define READ_ONCE(x) (x)
#define WRITE_ONCE(x,v) ((x)=(v))
static pthread_mutex_t fts_int=PTHREAD_MUTEX_INITIALIZER;
static int disable_irq_count;
static pthread_mutex_t gate=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv=PTHREAD_COND_INITIALIZER;
static bool irq_active, recovery_entered, finish_irq, sync_entered, disabled_done;
static int nosync_calls, sync_calls;
static struct client { struct device dev; int irq; } client;
static struct client *getClient(void) { return &client; }
#define spin_lock_irqsave(l,f) do { (f)=0; mutex_lock(l); } while (0)
#define spin_unlock_irqrestore(l,f) do { (void)(f); mutex_unlock(l); } while (0)
#define spin_lock_irq(l) mutex_lock(l)
#define spin_unlock_irq(l) mutex_unlock(l)
#define spin_unlock(l) mutex_unlock(l)
#define logError(...) ((void)0)
#define ERROR_OP_NOT_ALLOW (-1)
static void disable_irq_nosync(int irq) { nosync_calls++; }
static void synchronize_irq(int irq) {
    /* Linux waits for all active IRQ threads, including the caller if misused. */
    assert(current != current_info->irq_thread);
    assert(!pthread_mutex_trylock(&fts_int));
    mutex_unlock(&fts_int);
    mutex_lock(&gate);
    sync_calls++; sync_entered=true; pthread_cond_broadcast(&cv);
    while (irq_active) pthread_cond_wait(&cv,&gate);
    mutex_unlock(&gate);
}
static void disable_irq(int irq) {
    disable_irq_nosync(irq); synchronize_irq(irq);
}
#define enable_irq(irq) ((void)0)
typedef int irqreturn_t;
typedef void (*event_dispatch_handler_t)(struct fts_ts_info *, unsigned char *);
#define IRQ_HANDLED 1
#define HZ 100
#define jiffies_to_msecs(n) (n)
#define pm_wakeup_event(d,t) ((void)0)
#define FIFO_EVENT_SIZE 8
#define FIFO_DEPTH 2
#define FIFO_CMD_READONE 0x85
#define DUMMY_FIFO 0
#define EVT_ID_NOEVENT 0
#define NUM_EVT_ID 16
static int fts_dbg_events;
#define input_sync(d) ((void)0)
static int reads;
static int fts_writeReadU8UX(int cmd,int n,int a,u8 *data,int size,int dummy) {
    data[0]=reads++ == 0 ? 0xf0 : 0; return 0;
}
#define SYSTEM_RESET_VALUE 1
#define EVT_ID_CONTROLLER_READY 1
#define RETRY_SYSTEM_RESET 3
#define GPIO_NOT_DEFINED (-1)
#define FTS_CMD_HW_REG_W 0
#define ADDR_SIZE_HW_REG 0
#define ADDR_SYSTEM_RESET 0
#define GENERAL_TIMEOUT 1
#define ERROR_BUS_W (-2)
#define ERROR_SYSTEM_RESET_FAIL (-4)
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define resetErrorList() ((void)0)
#define gpio_set_value(g,v) ((void)0)
#define msleep(t) ((void)0)
#define fts_writeU8UX(...) 0
#define pollForEvent(e,n,b,t) ((void)(e), 0)
static int reset_gpio=1, system_reseted_down, system_reseted_up;
"""

MAIN = r"""
static void recovery(struct fts_ts_info *i, unsigned char *ev) {
    assert(fts_system_reset()==0);
    mutex_lock(&gate);
    recovery_entered=true; pthread_cond_broadcast(&cv);
    while (!finish_irq) pthread_cond_wait(&cv,&gate);
    mutex_unlock(&gate);
    /* External synchronize_irq must not retain fts_int while we re-enable. */
    fts_enableInterrupt();
}
static int irq_token, external_token;
static void *irq_runner(void *p) {
    current=&irq_token;
    assert(fts_event_handler(7,p)==IRQ_HANDLED);
    mutex_lock(&gate); irq_active=false; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    return NULL;
}
static void *disabler(void *p) {
    current=&external_token;
    assert(fts_disableInterrupt()==0);
    mutex_lock(&gate); disabled_done=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    return NULL;
}
int main(void) {
    struct fts_ts_info i; pthread_t irq,off;
    event_dispatch_handler_t dispatch[NUM_EVT_ID] = {0};
    dispatch[15]=recovery;
    setup(&i,&client.dev); i.event_dispatch_table=dispatch;
    irq_active=true;
    assert(!pthread_create(&irq,NULL,irq_runner,&i));
    mutex_lock(&gate);
    while (!recovery_entered) pthread_cond_wait(&cv,&gate);
    mutex_unlock(&gate);
    assert(!pthread_create(&off,NULL,disabler,&i));
    mutex_lock(&gate);
    while (!sync_entered && !disabled_done) pthread_cond_wait(&cv,&gate);
    assert(sync_entered && !disabled_done);
    finish_irq=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    pthread_join(irq,NULL); pthread_join(off,NULL);
    assert(i.irq_thread==NULL && i.idle_holds==0);
    assert(sync_calls==1 && nosync_calls==1 && disabled_done);
    return 0;
}
"""


def irq_code(core=CORE, source=SOURCE):
    common = COMMON.replace('static void *current;',
                            'static _Thread_local void *current;')
    common = common.replace('struct fts_ts_info {',
        'struct fts_ts_info {\n    void *irq_thread, *input_dev;\n'
        '    void (**event_dispatch_table)(struct fts_ts_info *, unsigned char *);')
    return (common + helpers(source) + IRQ_MODEL +
            actual('fts_disableInterruptNoSync', core) +
            actual('fts_disableInterrupt', core) + actual('fts_enableInterrupt', core) +
            actual('fts_system_reset', core) +
            actual('fts_event_handler', source.replace('static irqreturn_t ', 'static int ')) + MAIN)


def probe_code(source=SOURCE):
    # Keep the actual early acquisition decisions and common unwind labels.
    # The unrelated input/DT/core init middle is deliberately not simulated.
    start = source.index('\n\tif (dp) {', source.index('static int fts_probe('))
    end = source.index('\n#ifdef CONFIG_PINCTRL', start)
    cleanup = source[source.index('ProbeErrorExit_4:\n'):]
    cleanup = cleanup[:cleanup.index('\n}')] + '\n}'
    common = COMMON.replace('struct fts_ts_info {',
        'struct fts_hw_platform_data { int irq_gpio, reset_gpio; };\n'
        'struct fts_ts_info {\n    struct fts_hw_platform_data *board;')
    stubs = r"""
#define GFP_KERNEL 0
#define ENOMEM 12
#define GPIO_NOT_DEFINED (-1)
#define logError(...) ((void)0)
#define dev_set_drvdata(d,p) ((d)->data=(p))
static struct fts_hw_platform_data board={1,2};
static struct fts_ts_info *fts_info;
static int stage, fail_stage, reg_puts, poweroffs, frees, freed;
static void *devm_kzalloc(struct device *d, size_t n, int flags) {
    return ++stage==fail_stage ? NULL : &board;
}
#define parse_dt(d,b) ((void)0)
static int fts_get_reg(struct fts_ts_info *i, bool get) {
    if (!get) { reg_puts++; return 0; }
    return ++stage==fail_stage ? -517 : 0;
}
static int fts_enable_reg(struct fts_ts_info *i, bool enable) {
    if (!enable) { poweroffs++; return 0; }
    return ++stage==fail_stage ? -5 : 0;
}
static int fts_set_gpio(struct fts_ts_info *i) { return ++stage==fail_stage ? -16 : 0; }
#define fts_gpio_setup(g,c,d,v) (frees++)
#define kfree(p) (freed++)
static struct { struct device dev; } client_store;
static int probe_fragment(struct fts_ts_info *info) {
    __typeof__(client_store) *client=&client_store;
    int dp=1, retval, error=0;
    bool gpio_ready=false;
    if (false) goto ProbeErrorExit_0;
"""
    main = r"""
int main(void) {
    const int expected[]={0,-12,-517,-5,-16,-5};
    for (int failure=1;failure<=5;failure++) {
        struct fts_ts_info i;
        setup(&i,&client_store.dev); fts_info=&i;
        stage=reg_puts=poweroffs=frees=freed=0; fail_stage=failure;
        assert(probe_fragment(&i)==expected[failure]);
        assert(freed==1 && client_store.dev.data==NULL && fts_info==NULL);
        assert(reg_puts==(failure>=2));
        assert(poweroffs==(failure>=4));
        assert(frees==(failure==5 ? 2 : 0));
        assert(!i.idle_work.pending);
        pthread_mutex_destroy(&i.idle_lock);
    }
    return 0;
}
"""
    return (common + helpers(source) + stubs + source[start:end] +
            '\n(void)gpio_ready; error=-5; goto ProbeErrorExit_4;\n' + cleanup + main)


class TouchIrqTests(unittest.TestCase):
    run_c = idle.TouchIdleTests.run_c

    def test_cancel_drains_running_callback_before_it_gets_idle_lock(self):
        # Unlike the original pending-only stub, model an already-running callback
        # which has not acquired idle_lock yet. cancel_sync must drain that work.
        common = COMMON.replace('static void *current;',
                                'static _Thread_local void *current;')
        start = common.index('static void cancel_delayed_work_sync(')
        end = common.index('static void mod_delayed_work(', start)
        common = common[:start] + r'''
static pthread_mutex_t gate=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv=PTHREAD_COND_INITIALIZER;
static bool running, allow_callback, cancel_waiting, transition_done;
static int operation;
static void cancel_delayed_work_sync(struct delayed_work *w) {
    assert(!pthread_mutex_trylock(&current_info->idle_lock));
    mutex_unlock(&current_info->idle_lock);
    mutex_lock(&gate);
    w->pending=false;
    if (running) {
        cancel_waiting=true; pthread_cond_broadcast(&cv);
        while (running) pthread_cond_wait(&cv,&gate);
    }
    mutex_unlock(&gate);
}
''' + common[end:]
        main = r'''
static int worker_token, transition_token;
static void *callback(void *p) {
    struct fts_ts_info *i=p;
    current=&worker_token;
    mutex_lock(&gate);
    running=true; pthread_cond_broadcast(&cv);
    while (!allow_callback) pthread_cond_wait(&cv,&gate);
    mutex_unlock(&gate);
    fts_idle_time_work(&i->idle_work.work);
    mutex_lock(&gate); running=false; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    return NULL;
}
static void *transition(void *p) {
    struct fts_ts_info *i=p;
    current=&transition_token;
    if (operation==0) {
        fts_idle_hold(i); fts_idle_release(i,true);
    } else if (operation==1) {
        fts_idle_pm_prepare(i->dev); fts_idle_pm_complete(i->dev);
    } else {
        fts_idle_stop(i);
    }
    mutex_lock(&gate);
    transition_done=true; pthread_cond_broadcast(&cv);
    mutex_unlock(&gate);
    return NULL;
}
int main(void) {
    for (operation=0;operation<3;operation++) {
        struct fts_ts_info i; struct device d; pthread_t work,t;
        running=allow_callback=cancel_waiting=transition_done=false;
        setup(&i,&d); fts_idle_hold(&i); fts_idle_release(&i,true);
        /* Work is running, no longer pending: cancelling only a timer is wrong. */
        i.idle_work.pending=false;
        assert(!pthread_create(&work,NULL,callback,&i));
        mutex_lock(&gate);
        while (!running) pthread_cond_wait(&cv,&gate);
        mutex_unlock(&gate);
        assert(!pthread_create(&t,NULL,transition,&i));
        mutex_lock(&gate);
        while (!cancel_waiting && !transition_done) pthread_cond_wait(&cv,&gate);
        assert(cancel_waiting && !transition_done);
        assert(!i.idle_ready && (i.idle_holds || i.idle_stopping));
        allow_callback=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
        pthread_join(work,NULL); pthread_join(t,NULL);
        assert(writes==0 && i.idle_holds==0);
        assert(i.idle_work.pending==(operation!=2));
        pthread_mutex_destroy(&i.idle_lock);
    }
    return 0;
}
'''
        self.run_c(common + helpers() + main)
        mutant = SOURCE.replace('cancel_delayed_work_sync(&info->idle_work);', '')
        self.run_c(common + helpers(mutant) + main, success=False)

    def test_probe_early_failures(self):
        self.run_c(probe_code())

    def test_probe_failure_counterexamples(self):
        for old, new in (
            ('error = -ENOMEM;\n\t\t\tgoto ProbeErrorExit_1;',
             'goto ProbeErrorExit_1;'),
            ('error = retval;\n\t\tgoto ProbeErrorExit_2;',
             'goto ProbeErrorExit_2;'),
            ('dev_set_drvdata(&client->dev, NULL);', ''),
            ('if (gpio_ready) {', 'if (false) {'),
        ):
            mutant = SOURCE.replace(old, new)
            self.assertNotEqual(mutant, SOURCE)
            self.run_c(probe_code(mutant), success=False)

    def test_irq_recovery_and_external_drain(self):
        self.run_c(irq_code())

    def test_irq_counterexamples(self):
        # Must fail for self-wait, waiting under fts_int, and omitting the drain.
        for replacement in ('(void)info; synchronize_irq(getClient()->irq);',
                            '(void)info; mutex_lock(&fts_int); synchronize_irq(getClient()->irq);',
                            '(void)info;'):
            mutant = CORE.replace(
                'if (info->irq_registered && READ_ONCE(info->irq_thread) != current)\n'
                '\t\tsynchronize_irq(getClient()->irq);', replacement)
            self.assertNotEqual(mutant, CORE)
            self.run_c(irq_code(mutant), success=False)


if __name__ == '__main__':
    unittest.main()
