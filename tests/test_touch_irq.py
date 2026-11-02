#!/usr/bin/env python3
"""Run extracted IRQ code with a blocking IRQ model, not a kernel test."""
from pathlib import Path
import unittest

import test_touch_idle as idle
from test_touch_idle import COMMON, actual, helpers

ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / 'fts521/fts_lib/ftsCore.c').read_text()
SOURCE = (ROOT / 'fts521/fts.c').read_text()
FIXTURES = ROOT / 'tests/fixtures/touch_irq'

IRQ_MODEL = r"""
#include <stdatomic.h>
#include <stdlib.h>
#define READ_ONCE(x) __atomic_load_n(&(x), __ATOMIC_RELAXED)
#define WRITE_ONCE(x,v) __atomic_store_n(&(x), (v), __ATOMIC_RELAXED)
static pthread_mutex_t fts_int=PTHREAD_MUTEX_INITIALIZER;
static int disable_irq_count;
static pthread_mutex_t gate=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv=PTHREAD_COND_INITIALIZER;
static bool irq_active, recovery_entered, finish_irq, sync_entered, disabled_done;
static int nosync_calls, sync_calls, irq_depth, enable_calls;
static bool installed=true;
static int irq_token, external_token;
static struct client { struct device dev; int irq; } client;
static struct client *getClient(void) { return &client; }
#define spin_lock_irqsave(l,f) do { (f)=0; mutex_lock(l); } while (0)
#define spin_unlock_irqrestore(l,f) do { (void)(f); mutex_unlock(l); } while (0)
#define spin_lock_irq(l) mutex_lock(l)
#define spin_unlock_irq(l) mutex_unlock(l)
#define spin_unlock(l) mutex_unlock(l)
#define logError(...) ((void)0)
#define ERROR_OP_NOT_ALLOW (-1)
static void disable_irq_nosync(int irq) {
    assert(installed); nosync_calls++; irq_depth++;
}
static void synchronize_irq(int irq) {
    /* Linux waits for all active IRQ threads, including the caller if misused. */
    assert(current != READ_ONCE(current_info->irq_thread));
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
static void enable_irq(int irq) {
    assert(installed && irq_depth>0); irq_depth--; enable_calls++;
}
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
static int reads, fifo_event_type;
static int fts_writeReadU8UX(int cmd,int n,int a,u8 *data,int size,int dummy) {
    data[0]=reads++ == 0 ? 0xf0 : 0; data[1]=fifo_event_type; return 0;
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
static int poll_result, reset_attempts;
#define pollForEvent(e,n,b,t) ((void)(e), reset_attempts++, poll_result)
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
    assert(sync_calls==1 && disabled_done);
    /* An IRQ recovery release must not consume the external owner's mask. */
    assert(irq_depth==1);
    current=&external_token;
    fts_enableInterrupt(); assert(irq_depth==0);
    /* A redundant enable is not another kernel enable. */
    int enables=enable_calls;
    fts_enableInterrupt(); assert(irq_depth==0 && enable_calls==enables);
    return 0;
}
"""


def irq_code(core=CORE, source=SOURCE, main=MAIN, lifecycle=False):
    common = COMMON.replace('static void *current;',
                            'static _Thread_local void *current;')
    common = common.replace('struct fts_ts_info {',
        'struct fts_ts_info {\n    void *irq_thread, *input_dev;\n'
        '    bool irq_external_disabled, irq_recovery_disabled;\n'
        '    pthread_mutex_t fwupdate_lock; void *irq_fwupdate_owner;\n'
        '    struct client *client; struct irq_board *board;\n'
        '    void *vdd_reg, *avdd_reg;\n'
        '    void (**event_dispatch_table)(struct fts_ts_info *, unsigned char *);')
    common = common.replace('d->data=i;',
        'assert(!pthread_mutex_init(&i->fwupdate_lock, NULL)); d->data=i;')
    transaction = (actual('fts_fwupdate_begin', core) +
                   actual('fts_fwupdate_end', core)) if 'void fts_fwupdate_begin(' in core else ''
    extra = (IRQ_LIFECYCLE + actual('fts_chip_powercycle', source) +
             actual('fts_error_event_handler', source) +
             actual('fts_interrupt_install', source) +
             actual('fts_interrupt_uninstall', source)) if lifecycle else ''
    return (common + helpers(source) + IRQ_MODEL +
            actual('fts_disableInterruptNoSync', core) +
            actual('fts_disableInterrupt', core) + actual('fts_enableInterrupt', core) +
            actual('fts_system_reset', core) +
            actual('fts_event_handler', source.replace('static irqreturn_t ', 'static int ')) +
            transaction + extra + main)


# Kernel APIs are modeled, but lifecycle/recovery decisions below are real C.
IRQ_LIFECYCLE = r"""
#define i2c_client client
#define setSystemResetedUp(v) (system_reseted_up=(v))
#define setSystemResetedDown(v) (system_reseted_down=(v))
#define IRQF_ONESHOT 1
#define IRQF_NO_AUTOEN 2
#define GFP_KERNEL 0
#define FTS_TS_DRV_NAME "fts-test"
#define EVT_TYPE_ERROR_ESD 1
#define EVT_TYPE_ERROR_HARD_FAULT 2
#define EVT_TYPE_ERROR_WATCHDOG 3
struct irq_board { int irq_flags, irq_gpio, reset_gpio; };
static int free_calls, request_result, event_type=EVT_TYPE_ERROR_WATCHDOG;
static bool pause_recovery, input_released;
static void fts_nop_event_handler(struct fts_ts_info *i, unsigned char *ev) {}
#define install_handler(...) ((void)0)
#define kzalloc(n,f) calloc(1,n)
#define kfree(p) free(p)
static int request_threaded_irq(int irq, void *top,
        irqreturn_t (*thread)(int,void *), int flags, const char *name, void *data) {
    assert(!installed && irq_depth==0);
    if (request_result) return request_result;
    assert(flags & IRQF_NO_AUTOEN);
    installed=true; irq_depth=1; return 0;
}
static void free_irq(int irq, void *data) {
    assert(installed && irq_depth>0);
    synchronize_irq(irq);
    installed=false; irq_depth=0; free_calls++;
}
static void release_all_touches(struct fts_ts_info *i) {}
static int regulator_disable(void *r) { return 0; }
static int regulator_enable(void *r) { return 0; }
#define dumpErrorInfo(...) ((void)0)
static int fts_mode_handler(struct fts_ts_info *i,int force) {
    if (pause_recovery) {
        mutex_lock(&gate);
        recovery_entered=true; pthread_cond_broadcast(&cv);
        while (!finish_irq) pthread_cond_wait(&cv,&gate);
        mutex_unlock(&gate);
    }
    return 0;
}
#define sysfs_remove_group(...) ((void)0)
#define fb_unregister_client(...) ((void)0)
#define cancel_work_sync(...) ((void)0)
#define destroy_workqueue(...) ((void)0)
#define fts_gpio_setup(...) ((void)0)
#define input_unregister_device(...) do { \
    assert(!installed && !irq_active && current_info->idle_stopping); \
    input_released=true; \
} while (0)
static int fts_enable_reg(struct fts_ts_info *i,bool enable) {
    assert(!enable && !installed); return 0;
}
static int fts_get_reg(struct fts_ts_info *i,bool get) {
    assert(!get && !installed); return 0;
}
"""

IRQ_LIFECYCLE_MAIN = r"""
static struct irq_board board={.irq_gpio=-1,.reset_gpio=-1};
static void init_irq(struct fts_ts_info *i) {
    setup(i,&client.dev); current=&external_token;
    i->irq_registered=false; i->client=&client; i->board=&board;
    installed=false; irq_depth=0;
    assert(fts_system_reset()==0); /* Before request: no IRQ API calls. */
    assert(irq_depth==0);
    assert(fts_interrupt_install(i)==0);
    assert(irq_depth==1 && i->irq_registered);
    i->event_dispatch_table[15]=fts_error_event_handler;
    fts_enableInterrupt(); assert(irq_depth==0);
}
static void *irq_recover(void *p) {
    struct fts_ts_info *i=p; current=&irq_token;
    reads=0; fifo_event_type=event_type;
    assert(fts_event_handler(7,i)==IRQ_HANDLED);
    mutex_lock(&gate); irq_active=false; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    return NULL;
}
static void *external_stop(void *p) {
    current=&external_token;
    if (REMOVE_CASE) {
        fts_remove(&client);
    } else {
        assert(fts_disableInterrupt()==0);
        assert(irq_depth==1); /* IRQ recovery has returned, our mask remains. */
    }
    mutex_lock(&gate); disabled_done=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    return NULL;
}
int main(void) {
    for (event_type=1;event_type<=3;event_type++) {
        struct fts_ts_info *i=calloc(1,sizeof(*i)); pthread_t irq,off;
        init_irq(i);
        for (int n=0;n<20;n++) {
            assert(fts_system_reset()==0 && irq_depth==1);
            assert(fts_system_reset()==0 && irq_depth==1); /* reset retry */
            fts_enableInterrupt(); assert(irq_depth==0);
            irq_active=true;
            irq_recover(i); assert(irq_depth==0 && i->idle_holds==0);
        }
        pause_recovery=true;
        irq_active=true; recovery_entered=finish_irq=sync_entered=disabled_done=false;
        assert(!pthread_create(&irq,NULL,irq_recover,i));
        mutex_lock(&gate);
        while (!recovery_entered) pthread_cond_wait(&cv,&gate);
        mutex_unlock(&gate);
        assert(!pthread_create(&off,NULL,external_stop,i));
        mutex_lock(&gate);
        while (!sync_entered && !disabled_done) pthread_cond_wait(&cv,&gate);
        assert(sync_entered && !disabled_done);
        finish_irq=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
        pthread_join(irq,NULL); pthread_join(off,NULL);
        current=&external_token; pause_recovery=false;
        if (REMOVE_CASE) {
            assert(!installed && irq_depth==0 && input_released);
        } else {
            fts_enableInterrupt(); assert(irq_depth==0);
            fts_idle_stop(i); fts_interrupt_uninstall(i);
            assert(!installed && !i->irq_registered && i->event_dispatch_table==NULL);
            pthread_mutex_destroy(&i->idle_lock); free(i);
        }
    }
    /* Failed IRQ request and probe unwind must not free an unowned IRQ. */
    struct fts_ts_info i;
    setup(&i,&client.dev); i.client=&client; i.board=&board; i.irq_registered=false;
    installed=false; request_result=-16;
    int frees=free_calls;
    assert(fts_interrupt_install(&i)<0 && !i.irq_registered && !installed);
    fts_interrupt_uninstall(&i); assert(free_calls==frees && irq_depth==0);
    return 0;
}
"""


def irq_lifecycle_code(remove=False):
    # Select the I2C remove definition before extracting its shared body.
    source = SOURCE.replace('#else\nstatic void fts_remove(struct spi_device *client)\n{\n#endif', '')
    main = actual('fts_remove', source) + IRQ_LIFECYCLE_MAIN.replace('REMOVE_CASE', str(int(remove)))
    return irq_code(main=main, lifecycle=True)


def gpio_code(source=SOURCE, first_mode=0):
    stubs = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
/* Vendor buffer signedness is unrelated to ownership, as in kernel builds. */
#pragma GCC diagnostic ignored "-Wpointer-sign"
#define LINUX_VERSION_CODE 0
#define KERNEL_VERSION(a,b,c) 1
#define GPIO_NOT_DEFINED (-1)
#define OK 0
#define logError(...) ((void)0)
#define msleep(n) ((void)0)
#define gpio_set_value(g,v) ((void)0)
struct fts_hw_platform_data { int irq_gpio,reset_gpio; };
struct fts_ts_info { struct fts_hw_platform_data *board; };
static int owned[3],requests[3],frees[3],fail_request,fail_direction;
static int gpio_request(unsigned g,const char *s) {
    /* Target gpiolib-legacy.c: no descriptor returns -EPROBE_DEFER. */
    if (g>2) return -517;
    if (g==fail_request) return -517;
    assert(!owned[g]); owned[g]=1; requests[g]++; return 0;
}
static void gpio_free(int g) {
    assert(owned[g]); owned[g]=0; frees[g]++;
}
static int gpio_direction_input(int g) { return g==fail_direction?-5:0; }
static int gpio_direction_output(int g,int v) { return g==fail_direction?-5:0; }
"""
    main = r"""
int main(void) {
    for (int mode=0;mode<5;mode++) {
        struct fts_hw_platform_data b={1,2}; struct fts_ts_info i={&b};
        fail_direction=mode<=2?mode:0;
        fail_request=mode>=3?mode-2:0;
        int ret=fts_set_gpio(&i);
        if (ret==0) {
            fts_gpio_setup(b.irq_gpio,false,0,0);
            fts_gpio_setup(b.reset_gpio,false,0,0);
        } else {
            assert(ret==(fail_request?-517:-5));
            /* Probe gpio_ready stays false: no additional free is allowed. */
        }
        assert(!owned[1] && !owned[2]);
        assert(requests[1]==frees[1] && requests[2]==frees[2]);
    }
    struct fts_hw_platform_data b={-517,2}; struct fts_ts_info i={&b};
    fail_request=fail_direction=0;
    assert(fts_set_gpio(&i)==-517);
    assert(!owned[1] && !owned[2]);
    return 0;
}
"""
    return (stubs + actual('fts_gpio_setup', source) + actual('fts_set_gpio', source) +
            main.replace('int mode=0', 'int mode=' + str(first_mode)))


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
static int parse_dt(struct device *d, struct fts_hw_platform_data *b) { return 0; }
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
    return (common + helpers() + stubs + source[start:end] +
            '\n(void)gpio_ready; error=-5; goto ProbeErrorExit_4;\n' + cleanup + main)



# Execute the full sysfs dispatcher and real flash/reset/powercycle decisions.
# Hardware/register/FW data and manufacturing algorithms remain modeled.
FW_STUBS = r"""
#include <string.h>
typedef uint16_t u16;
typedef uint64_t u64;
struct device_attribute { int unused; };
#define mdelay(t) ((void)0)
#define FTS_CMD_HW_REG_R 0
#define ADDR_DCHIP_ID 0
#define FTS_LIMITS_FILE "offline"
#define SPECIAL_PANEL_INIT 1
#define SPECIAL_FULL_PANEL_INIT 2
#define SAVE_CX 1
#define SAVE_PANEL_CONF 2
#define SYS_CMD_SAVE_FLASH 1
#define SYS_CMD_SPECIAL_TUNING 2
#define SYS_CMD_CX_TUNING 3
#define SPECIAL_TUNING_IOFF 1
#define ERROR_FW_NO_UPDATE (-16)
#define ERROR_FLASH_BURN_FAILED (-32)
#define ERROR_FLASH_PROCEDURE (-64)
#define ERROR_TIMEOUT (-8)
#define CRC_CX 2
#define SKIP_PANEL_INIT 1
#define SKIP_PANEL_CX_INIT 2
#define EXTERNAL_RELEASE_INFO_SIZE 8
#define MI_TOUCH_LOGI(...) ((void)0)
#define MI_TOUCH_LOGE(...) ((void)0)
typedef int TestToDo;
TestToDo tests;
static int fts_flash_blind, fts_lenient_echo, io_step, io_failure, sensing;
static bool pause_fw, fw_entered, finish_fw, fw_active;
static struct { u16 u16_fwVer; u8 u8_releaseInfo[8]; } systemInfo;
typedef struct {
    u8 *data, externalRelease[8];
    int fw_ver, sec0_size, sec1_size, sec2_size, code_start_addr, config_start_addr;
} Firmware;
static void masked(void) {
    assert(irq_depth>0 || !installed);
    if (current_info->irq_fwupdate_owner==current)
        assert(irq_depth == (int)current_info->irq_external_disabled+1 || !installed);
}
static int io(void) { masked(); return ++io_step==io_failure ? -5 : 0; }
static int kstrtoint(const char *b,int base,int *v) {
    char *end; long n=strtol(b,&end,base);
    if (end==b || *end) return -EINVAL;
    *v=n; return 0;
}
static int getFirmwareVersion(u16 *fw,u16 *cfg) { *fw=*cfg=1; return io(); }
static int readSysInfo(int request) {
    if (pause_fw) {
        mutex_lock(&gate); fw_entered=true; pthread_cond_broadcast(&cv);
        while (!finish_fw) pthread_cond_wait(&cv,&gate);
        mutex_unlock(&gate);
    }
    return io();
}
static int readFwFile(const char *path,Firmware *fw,int keep) {
    *fw=(Firmware){.data=calloc(1,3),.sec0_size=1,.sec1_size=1,.sec2_size=1};
    return io();
}
static int flash_enable_uvlo_autopowerdown(void) { return io(); }
static int hold_m3(void) { return io(); }
static int flash_unlock(void) { return io(); }
static int flash_erase_unlock(void) { return io(); }
static int flash_erase_page_by_page(int keep,Firmware *fw) { return io(); }
static int fillFlash(int addr,u8 *data,int size) { return io(); }
static int senseOn(void) { sensing++; return io(); }
static int writeSysCmd(int cmd,u8 *data,int size) { return io(); }
static int production_test_initialization(int type) { return fts_system_reset(); }
static void initTestToDo(void) {}
static int cleanUp(int enableTouch);
static int production_test_ito(const char *lim,TestToDo *t) { return fts_system_reset(); }
static int production_test_main(const char *lim,int stop,int init,TestToDo *t) {
    return cleanUp(1);
}
"""

FW_MAIN = r"""
static struct irq_board fw_board={.irq_gpio=-1,.reset_gpio=-1,
                                 .default_fw_name="offline.ftb"};
static void init_fw(struct fts_ts_info *i,bool external,bool registered) {
    setup(i,&client.dev); i->client=&client; i->board=&fw_board;
    current=&external_token; client.irq=7;
    installed=i->irq_registered=registered;
    irq_depth=external && registered;
    i->irq_external_disabled=external;
    poll_result=reset_attempts=io_step=io_failure=0;
    nosync_calls=enable_calls=sync_calls=sensing=0;
    sync_entered=false;
}
int main(void) {
    const int modes[]={0,4,8,256,268,1,269,2,6,128,16,32,64,512,1024,
                       2048,4096,12288,16384,32767};
    for (int registered=0;registered<2;registered++)
    for (int external=0;external<2;external++)
    for (unsigned n=0;n<ARRAY_SIZE(modes);n++) {
        struct fts_ts_info i; char mode[16];
        init_fw(&i,external,registered);
        snprintf(mode,sizeof(mode),"%d",modes[n]);
        assert(fwupdate_store(&client.dev,NULL,mode,1)==1);
        assert(irq_depth==(external && registered));
        assert(i.irq_external_disabled==external && !i.irq_recovery_disabled);
        assert(!i.irq_fwupdate_owner && !i.idle_ready && !i.idle_work.pending);
        assert(!i.idle_holds && writes==0);
        assert(nosync_calls==registered && enable_calls==registered);
        assert(!fts_flash_blind && !fts_lenient_echo);
        if (modes[n]==4) assert(reset_attempts==1 && sensing==0);
        if (modes[n]==8) assert(reset_attempts==0 && sensing==0);
        if (modes[n]==256) assert(reset_attempts==3 && sensing==0);
        if (modes[n]==268) assert(reset_attempts==4 && sensing==0);
        if (modes[n]==0) assert(reset_attempts==0 && sensing==0);
        pthread_mutex_destroy(&i.idle_lock); pthread_mutex_destroy(&i.fwupdate_lock);
    }
    /* Each real flash early-return edge, then retries in failed reset. */
    for (int fail=1;fail<=22;fail++) for (int external=0;external<2;external++) {
        struct fts_ts_info i; init_fw(&i,external,true);
        io_failure=fail;
        assert(fwupdate_store(&client.dev,NULL,"269",3)==3);
        assert(io_step>=fail); /* the requested fault was reached */
        assert(irq_depth==external && i.irq_external_disabled==external);
        assert(enable_calls==1 && nosync_calls==1 && sensing==0);
        assert(!i.irq_fwupdate_owner && !i.idle_ready && !fts_flash_blind);
        pthread_mutex_destroy(&i.idle_lock); pthread_mutex_destroy(&i.fwupdate_lock);
    }
    for (int external=0;external<2;external++) {
        struct fts_ts_info i; init_fw(&i,external,true); poll_result=-5;
        assert(fwupdate_store(&client.dev,NULL,"4",1)==1);
        assert(reset_attempts==3 && irq_depth==external);
        assert(nosync_calls==1 && enable_calls==1 && sensing==0);
        assert(!i.idle_ready && !i.idle_work.pending);
        int masks=nosync_calls, enables=enable_calls;
        assert(fwupdate_store(&client.dev,NULL,"invalid",7)==-EINVAL);
        assert(nosync_calls==masks && enable_calls==enables && irq_depth==external);
        pthread_mutex_destroy(&i.idle_lock); pthread_mutex_destroy(&i.fwupdate_lock);
    }
    return 0;
}
"""

FW_CONCURRENT = r"""
static int fw_token, stop_token;
static struct irq_board fw_board={.irq_gpio=-1,.reset_gpio=-1};
static void *fw_writer(void *p) {
    current=&fw_token;
    assert(fwupdate_store(&client.dev,NULL,"516",3)==3);
    mutex_lock(&gate); fw_active=false; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    return NULL;
}
static void drain_sysfs(void) {
    mutex_lock(&gate);
    sync_entered=true; pthread_cond_broadcast(&cv);
    while (fw_active) pthread_cond_wait(&cv,&gate);
    mutex_unlock(&gate);
}
static void *stopper(void *p) {
    current=&stop_token;
    if (STOP_CASE==1) fts_remove(&client);
    else fts_shutdown(&client);
    return NULL;
}
int main(void) {
    struct fts_ts_info *i=calloc(1,sizeof(*i)); pthread_t irq,fw,stop;
    init_irq(i); i->board=&fw_board; client.irq=7;
    if (STOP_CASE) {
        pause_fw=fw_active=true;
        assert(!pthread_create(&fw,NULL,fw_writer,i));
        mutex_lock(&gate);
        while (!fw_entered) pthread_cond_wait(&cv,&gate);
        assert(irq_depth==1);
        sync_entered=false;
        mutex_unlock(&gate);
        assert(!pthread_create(&stop,NULL,stopper,i));
        if (STOP_CASE==2) pthread_join(stop,NULL);
        mutex_lock(&gate);
        if (STOP_CASE==1) while (!sync_entered) pthread_cond_wait(&cv,&gate);
        assert(installed && irq_depth==1);
        finish_fw=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
        pthread_join(fw,NULL);
        if (STOP_CASE==1) pthread_join(stop,NULL);
        else {
            assert(i->idle_stopping && !i->idle_ready && !i->irq_fwupdate_owner);
            fts_remove(&client);
        }
        assert(!installed && input_released);
    } else {
        pause_recovery=true; irq_active=true;
        assert(!pthread_create(&irq,NULL,irq_recover,i));
        mutex_lock(&gate);
        while (!recovery_entered) pthread_cond_wait(&cv,&gate);
        if (EXTERNAL_MASK) assert(fts_disableInterruptNoSync()==0);
        sync_entered=false; mutex_unlock(&gate);
        assert(!pthread_create(&fw,NULL,fw_writer,i));
        mutex_lock(&gate);
        while (!sync_entered) pthread_cond_wait(&cv,&gate);
        /* Recovery and fwupdate each retain their own depth while draining. */
        assert(irq_depth==2+EXTERNAL_MASK && i->irq_recovery_disabled && i->irq_fwupdate_owner);
        finish_irq=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
        pthread_join(irq,NULL); pthread_join(fw,NULL);
        assert(irq_depth==EXTERNAL_MASK && i->irq_external_disabled==EXTERNAL_MASK && !i->irq_recovery_disabled);
        assert(!i->irq_fwupdate_owner && !i->idle_ready && !i->idle_work.pending);
        current=&external_token; fts_remove(&client);
    }
    return 0;
}
"""


FW_EXTERNAL_MAIN = r"""
int main(void) {
    struct fts_ts_info *i=calloc(1,sizeof(*i)); pthread_t fw;
    init_irq(i); i->board=&fw_board; client.irq=7;
    pause_fw=fw_active=true;
    assert(!pthread_create(&fw,NULL,fw_writer,i));
    mutex_lock(&gate);
    while (!fw_entered) pthread_cond_wait(&cv,&gate);
    assert(irq_depth==1 && !i->irq_external_disabled);
    mutex_unlock(&gate);
    current=&external_token;
    assert(fts_disableInterrupt()==0 && irq_depth==2);
    assert(fts_enableInterrupt()==0 && irq_depth==1);
    assert(i->irq_fwupdate_owner && !i->irq_external_disabled);
    assert(fts_disableInterrupt()==0 && irq_depth==2);
    mutex_lock(&gate); finish_fw=true; pthread_cond_broadcast(&cv); mutex_unlock(&gate);
    pthread_join(fw,NULL);
    assert(irq_depth==1 && i->irq_external_disabled && !i->irq_fwupdate_owner);
    assert(!i->idle_ready && !i->idle_work.pending);
    fts_remove(&client); assert(!installed && input_released);
    return 0;
}
"""


def fwupdate_code(source=SOURCE, main=FW_MAIN, stop_case=None, core=CORE, external=False):
    flash = (ROOT / 'fts521/fts_lib/ftsFlash.c').read_text()
    tool = (ROOT / 'fts521/fts_lib/ftsTool.c').read_text()
    code = irq_code(core=core, main='', lifecycle=True)
    code = code.replace('int irq_flags, irq_gpio, reset_gpio;',
                        'int irq_flags, irq_gpio, reset_gpio; const char *default_fw_name;')
    extra = (FW_STUBS + actual('cleanUp', tool) + actual('flash_burn', flash) +
             actual('flashProcedure', flash) + actual('fwupdate_store', source))
    if stop_case is not None:
        # Reuse actual IRQ lifecycle/remove with a draining sysfs model.
        pre = IRQ_LIFECYCLE_MAIN[:IRQ_LIFECYCLE_MAIN.index('int main(void)')]
        pre = pre.replace('REMOVE_CASE', '1')
        code = code.replace('#define sysfs_remove_group(...) ((void)0)',
                            'static void drain_sysfs(void);\n'
                            '#define sysfs_remove_group(...) drain_sysfs()')
        code += (actual('fts_remove', SOURCE.replace(
                     '#else\nstatic void fts_remove(struct spi_device *client)\n{\n#endif', '')) +
                 actual('fts_shutdown', SOURCE.replace(
                     '#else\nstatic void fts_shutdown(struct spi_device *client)\n#endif', '')))
        extra += pre
        if main != FW_MAIN:
            main = FW_CONCURRENT[:FW_CONCURRENT.index('int main(void)')] + main
        else:
            main = FW_CONCURRENT
        main = main.replace('STOP_CASE', str(stop_case)).replace(
            'EXTERNAL_MASK', str(int(external)))
    return code + extra + main



DT_STUBS = r"""
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#pragma GCC diagnostic ignored "-Wpointer-sign"
#define KERNEL_VERSION(a,b,c) (((a)<<16)+((b)<<8)+(c))
#define LINUX_VERSION_CODE KERNEL_VERSION(6,18,59)
#define GPIO_NOT_DEFINED (-1)
#define EPROBE_DEFER 517
#define GFP_KERNEL 0
#define X_AXIS_MAX 1080
#define Y_AXIS_MAX 2340
#define logError(...) ((void)0)
#define msleep(n) ((void)0)
typedef uint32_t u32;
struct device_node { int unused; };
static bool reset_present;
static int reset_value=2, irq_value=1;
static int reset_queries, irq_queries, reg_gets, reg_puts, powers, poweroffs, freed;
static int owned[3], requests[3], frees[3];
static struct fts_ts_info *fts_info;
static struct fts_hw_platform_data board;
static void *devm_kzalloc(struct device *d,size_t n,int flags) {
    memset(&board,0,sizeof(board)); return &board;
}
static int of_get_named_gpio(struct device_node *np,const char *name,int index) {
    if (!strcmp(name,"fts,irq-gpio")) { irq_queries++; return irq_value; }
    assert(!strcmp(name,"fts,reset-gpio")); reset_queries++; return reset_value;
}
static bool of_property_read_bool(struct device_node *np,const char *name) {
    assert(!strcmp(name,"fts,reset-gpio")); return reset_present;
}
static int of_property_read_string(struct device_node *np,const char *key,const char **s) {
    return -EINVAL;
}
static int of_property_read_u32(struct device_node *np,const char *key,u32 *v) {
    if (!strcmp(key,"fts,irq-flags")) { *v=1; return 0; }
    return -EINVAL;
}
#define GPIOD_ASIS 0
struct gpio_desc { int unused; };
static struct gpio_desc desc;
static struct gpio_desc *devm_gpiod_get_optional(struct device *d,const char *name,int flags) {
    reset_queries++;
    if (!reset_present) return NULL;
    return reset_value<0 ? (struct gpio_desc *)(intptr_t)reset_value : &desc;
}
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define PTR_ERR(p) ((intptr_t)(p))
static int desc_to_gpio(struct gpio_desc *p) { return reset_value; }
static int gpio_request(unsigned g,const char *s) {
    assert(g==1 || g==2); assert(!owned[g]); owned[g]=1; requests[g]++; return 0;
}
static void gpio_free(int g) { assert(g==1 || g==2); assert(owned[g]); owned[g]=0; frees[g]++; }
static int gpio_direction_input(int g) { assert(owned[g]); return 0; }
static int gpio_direction_output(int g,int value) { assert(owned[g]); return 0; }
static void gpio_set_value(int g,int v) { assert(owned[g]); }
static int fts_get_reg(struct fts_ts_info *i,bool get) {
    if (get) reg_gets++; else { assert(reg_gets); reg_puts++; }
    return 0;
}
static int fts_enable_reg(struct fts_ts_info *i,bool enable) {
    if (enable) powers++; else { assert(powers); poweroffs++; }
    return 0;
}
#define dev_set_drvdata(d,p) ((d)->data=(p))
#define kfree(p) (freed++)
static struct client { struct device dev; } client_store;
static int probe_fragment(struct fts_ts_info *info) {
    struct client *client=&client_store;
    struct device_node *dp=client->dev.of_node;
    int retval,error=0;
    bool gpio_ready=false;
    if (false) goto ProbeErrorExit_0;
"""

DT_MAIN = r"""
int main(void) {
    struct device_node node;
    for (int test=0;test<7;test++) {
        struct fts_ts_info i;
        setup(&i,&client_store.dev); client_store.dev.of_node=&node; fts_info=&i;
        reset_present=test!=0; reset_value=2; irq_value=1;
        reset_queries=irq_queries=reg_gets=reg_puts=powers=poweroffs=freed=0;
        if (test==2) reset_value=-EPROBE_DEFER;
        if (test==3) reset_value=-EINVAL;
        if (test==4) reset_value=-ENOENT; /* present malformed property != absent */
        if (test==5) irq_value=-EPROBE_DEFER;
        if (test==6) irq_value=-EINVAL;
        int expected=test>=5?irq_value:(test>=2?reset_value:0);
        int ret=probe_fragment(&i);
        assert(ret==expected);
        assert(reset_queries==(test>=5?0:(int)reset_present));
        if (expected) {
            assert(freed==1 && !client_store.dev.data && !fts_info);
            assert(!reg_gets && !reg_puts && !powers && !poweroffs);
            assert(!requests[1] && !requests[2]);
        } else {
            assert(i.board->reset_gpio==(reset_present?2:GPIO_NOT_DEFINED));
            assert(reg_gets==1 && powers==1 && !freed);
            assert(owned[1] && owned[2]==reset_present);
            /* Exact GPIO release decisions from successful remove. */
            REMOVE_GPIO
            fts_enable_reg(&i,false); fts_get_reg(&i,false);
            assert(!owned[1] && !owned[2] && reg_puts==1 && poweroffs==1);
        }
        memset(requests,0,sizeof(requests)); memset(frees,0,sizeof(frees));
        pthread_mutex_destroy(&i.idle_lock);
    }
    return 0;
}
"""


def dt_code(source=SOURCE, parse_source=None, modern=False):
    common = COMMON.replace('struct device { void *data; };',
                            'struct device { void *data; struct device_node *of_node; };')
    common = common.replace('struct fts_ts_info {',
        'struct fts_hw_platform_data { int irq_gpio,reset_gpio,irq_flags,x_max,y_max; '
        'const char *vdd_reg_name,*avdd_reg_name,*default_fw_name; };\n'
        'struct fts_ts_info { struct fts_hw_platform_data *board;')
    parse = actual('parse_dt', parse_source or source)
    stubs = DT_STUBS[:DT_STUBS.index('static int probe_fragment(')]
    if modern:
        stubs = stubs.replace('#define LINUX_VERSION_CODE KERNEL_VERSION(6,18,59)',
                              '#define LINUX_VERSION_CODE KERNEL_VERSION(7,0,0)')
        main = r"""
int main(void) {
    struct device_node node; struct device d={.of_node=&node};
    const int errors[]={2,-EPROBE_DEFER,-EINVAL,-ENOENT};
    reset_present=false; assert(parse_dt(&d,&board)==0 && board.reset_gpio==-1);
    reset_present=true;
    for (unsigned n=0;n<sizeof(errors)/sizeof(errors[0]);n++) {
        reset_value=errors[n]; int ret=parse_dt(&d,&board);
        assert(ret==(reset_value<0?reset_value:0));
        if (!ret) assert(board.reset_gpio==2);
    }
    assert(!reg_gets && !powers && !requests[1] && !requests[2]);
    return 0;
}
"""
        return common + helpers() + stubs + parse + main
    start = source.index('\n\tif (dp) {', source.index('static int fts_probe('))
    end = source.index('\n#ifdef CONFIG_PINCTRL', start)
    cleanup = source[source.index('ProbeErrorExit_4:\n'):]
    cleanup = cleanup[:cleanup.index('\n}')] + '\n}'
    remove = actual('fts_remove', SOURCE.replace(
        '#else\nstatic void fts_remove(struct spi_device *client)\n{\n#endif', ''))
    gpio_remove = remove[remove.index('\tif (info->board) {'):remove.index('\n\t/* free all */')]
    return (common + helpers() + stubs + parse + actual('fts_gpio_setup', SOURCE) +
            actual('fts_set_gpio', SOURCE) + DT_STUBS[DT_STUBS.index('static int probe_fragment('):] +
            source[start:end] + '\nreturn OK;\n' + cleanup +
            DT_MAIN.replace('REMOVE_GPIO', gpio_remove.replace('info->', 'i.')))


class TouchIrqTests(unittest.TestCase):
    run_c = idle.TouchIdleTests.run_c

    def run_target_assertion(self, code, target):
        # Require a built executable, SIGABRT, and the specific contract failure.
        with idle.tempfile.TemporaryDirectory() as tmp:
            src, exe = Path(tmp) / 'counterexample.c', Path(tmp) / 'counterexample'
            src.write_text(code)
            built = idle.subprocess.run(
                ['gcc', '-std=gnu11', '-Wall', '-Werror', '-Wno-unused-function',
                 '-Wno-unused-variable', '-pthread', str(src), '-o', str(exe)],
                capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            result = idle.subprocess.run([str(exe)], capture_output=True,
                                         text=True, timeout=10)
            self.assertEqual(result.returncode, -6, result.stderr)
            self.assertIn('Assertion', result.stderr)
            self.assertIn(target, result.stderr)



    def test_fwupdate_real_modes_flash_failures_and_existing_masks(self):
        self.run_c(fwupdate_code())

    def test_fwupdate_waits_for_irq_recovery_without_consuming_owners(self):
        for external in (False, True):
            self.run_c(fwupdate_code(stop_case=0, external=external))

    def test_fwupdate_keeps_external_masks_acquired_during_transaction(self):
        self.run_c(fwupdate_code(main=FW_EXTERNAL_MAIN, stop_case=0))

    def test_fwupdate_nested_helpers_must_borrow_transaction_depth(self):
        old = 'if (info->irq_fwupdate_owner == current)\n\t\tgoto out;'
        # Removing either borrow guard leaks depth or consumes an external owner.
        for start in ('int fts_disableInterruptNoSync(', 'int fts_enableInterrupt('):
            at = CORE.index(start)
            mutant = CORE[:at] + CORE[at:].replace(old, 'if (false)\n\t\tgoto out;', 1)
            self.assertNotEqual(mutant, CORE)
            self.run_c(fwupdate_code(core=mutant), success=False)

    def test_fwupdate_remove_and_shutdown_lifetimes(self):
        for stop in (1, 2):
            self.run_c(fwupdate_code(stop_case=stop))

    def test_dt_reset_errors_and_probe_unwind_linux_61859(self):
        self.run_c(dt_code())

    def test_dt_optional_descriptor_errors_7x(self):
        self.run_c(dt_code(modern=True))

    def test_new_p2_historical_runtime_counterexamples(self):
        old = (FIXTURES / 'p2_fwupdate_dt.c').read_text()
        main = FW_MAIN[:FW_MAIN.index('int main(void)')] + r'''
int main(void) {
    struct fts_ts_info i; init_fw(&i,false,true);
    assert(fwupdate_store(&client.dev,NULL,"4",1)==1);
    assert(irq_depth==0);
    return 0;
}
'''
        self.run_target_assertion(fwupdate_code(source=old, main=main), 'irq_depth==0')
        self.run_target_assertion(dt_code(parse_source=old), 'ret==expected')
        self.run_target_assertion(dt_code(source=old, parse_source=SOURCE), 'ret==expected')
        self.run_target_assertion(dt_code(parse_source=old, modern=True),
                                  'ret==(reset_value<0?reset_value:0)')

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

    def test_irq_mask_ownership_and_repeated_error_recovery(self):
        self.run_c(irq_lifecycle_code())

    def test_remove_drains_irq_recovery_and_probe_irq_failure(self):
        self.run_c(irq_lifecycle_code(remove=True))

    def test_gpio_real_acquisition_and_rollback(self):
        self.run_c(gpio_code())

    def test_original_p2_versions_fail_target_assertions(self):
        # Exact historical functions, not git history: CI uses shallow checkout.
        old_core = (FIXTURES / 'p2_core.c').read_text()
        old_gpio = (FIXTURES / 'p2_gpio.c').read_text()
        self.run_c(irq_code(old_core), success=False)
        for first_mode in (1, 2):
            self.run_c(gpio_code(old_gpio, first_mode), success=False)

    def test_original_p1_versions_still_fail_target_assertions(self):
        old_core = (FIXTURES / 'p1_core.c').read_text()
        old_probe = (FIXTURES / 'p1_probe.c').read_text()
        self.run_c(irq_code(old_core), success=False)
        self.run_c(probe_code(old_probe), success=False)

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
