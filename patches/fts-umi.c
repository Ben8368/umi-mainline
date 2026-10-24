// SPDX-License-Identifier: GPL-2.0
/*
 * STMicroelectronics FTS5 touchscreen driver - Xiaomi Mi 10 (umi)
 *
 * The panel of the Mi 10 is a command-mode AMOLED and the touch controller is
 * soldered to the same flex, so the touchscreen is a separate slave at address
 * 0x49 on the two wires that QUPV3 wrap1 SE5 (0xa94000) also claims.
 *
 * ★ The bus is bit-banged here
 *
 *   On a running MIUI the two bus pins report "function gpio", owned by
 *   a94000.i2c - the vendor "i2c-geni" is not driving the QUP there.  The SE
 *   has its FIFO interface disabled (GENI_IF_DISABLE_RO), so mainline geni-i2c
 *   has to use GPI DMA, and on this board GPI never answers EV ALLOCATE:
 *
 *       gpi a00000.dma-controller: cmd: EV ALLOCATE completion timeout:2
 *       geni_i2c a94000.i2c: error -ENODEV: Failed to setup GPI DMA mode
 *
 *   The generic i2c-gpio driver registered a bus but every transfer came back
 *   -ENXIO: its open-drain path wants native open-drain support that
 *   pinctrl-msm does not have.  A plain bit-banged bus with explicit direction
 *   switching - the same thing the vendor "gpio mode" does - works and is
 *   trivially debuggable.  A bus scan settled the pad order: gpio36 is SDA,
 *   gpio37 is SCL.
 *
 * ★ Protocol: FTI (FTM5), NOT the old FTS "hardware register" protocol
 *
 *   The Mi 10 ships the FTS 5.2.1 generation of the ST driver
 *   (drivers/input/touchscreen/fts_521 in the vendor tree, compatible
 *   "st,fts"), whose chip speaks the FTI memory-mapped protocol:
 *
 *   - every register access is one op code plus a *32 bit big endian* address
 *     that is sent on the wire, i.e. the whole command is
 *         { 0xFA, a31..a24, a23..a16, a15..a8, a7..a0 }
 *     followed by a repeated start and the payload.  A write appends the data
 *     bytes to that same message.
 *     (fts_521: FTS_CMD_HW_REG_R/W = 0xFA, ADDR_SIZE_HW_REG = BITS_32)
 *   - the register map lives at 0x20000000, not at 0x0000:
 *         0x20000000 chip id (2 bytes)        0x20000029 interrupt enable
 *         0x20000004 firmware version (2)     0x20000024 system reset
 *         0x20000025 boot option              0x20000078 flash CRC status
 *   - the event FIFO is drained with a single byte op code 0x86 and an 8 byte
 *     read per event; there is no 0x85
 *   - scanning is enabled with 0xA0 {mode 0x00, mask 0x01}
 *   - no dummy byte is inserted on I2C (DUMMY_* are all 0 for I2C_INTERFACE)
 *
 *   The previous revision of this driver used the older FTM3 op codes
 *   (0xB6 + 16 bit addresses, IER at 0x002C, reset at 0x0023).  Those are
 *   simply not decoded by this part: every write was ACKed by the I2C slave
 *   state machine and every read came back as zeros, which is exactly what the
 *   measurements showed.  Address 0x49 answering with ACK/NACK correctly and
 *   every single read returning 0x00 is the signature of "valid I2C, wrong
 *   protocol", not of a dead chip.
 *
 * Firmware and configuration live in the controller's own flash and were
 * programmed by MIUI, so nothing is ever written to the flash.  The two
 * supplies are fixed-value rails that are only enabled; no voltage, current or
 * OPP is programmed anywhere.
 */

#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/input.h>
#include <linux/input/mt.h>
#include <linux/input/touchscreen.h>
#include <linux/interrupt.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/pm.h>
#include <linux/regulator/consumer.h>
#include <linux/slab.h>

/* FTI op codes (fts_521/fts_lib/ftsHardware.h) */
#define FTS_CMD_HW_REG		0xfa	/* read and write share the op code */
#define FTS_CMD_READALL		0x86	/* + read FIFO_EVENT_SIZE bytes */
#define FTS_CMD_SCAN_MODE	0xa0	/* + mode + scan mask */
#define FTS_CMD_FEATURE		0xa2	/* + feature id + settings */

#define FTS_FEAT_GESTURE	0x03

#define FTS_CMD_SYSTEM		0xa4
#define FTS_SYS_CMD_SPECIAL	0x00
#define FTS_SYS_CMD_LOAD_DATA	0x01
#define FTS_SYS_CMD_FORCE_CAL	0x02
#define FTS_SPECIAL_FIFO_FLUSH	0x01

/* FTI register addresses, all inside the 0x2000_0000 window */
#define ADDR_DCHIP_ID		0x20000000u
#define ADDR_DCHIP_FW_VER	0x20000004u
#define ADDR_SYSTEM_RESET	0x20000024u
#define ADDR_BOOT_OPTION	0x20000025u
#define ADDR_IER		0x20000029u
#define ADDR_CRC		0x20000078u

#define SYSTEM_RESET_VALUE	0x80
#define IER_ENABLE		0x41
#define IER_DISABLE		0x00

/* Scan modes and the multi touch scan mask */
#define FTS_SCAN_MODE_ACTIVE	0x00
#define FTS_SCAN_MODE_LOW_POWER	0x01
#define FTS_SCAN_MT		0x01

/* Event ids: FW always sets the low nibble of the id to 0x3 */
#define FTS_EV_NOEVENT		0x00
#define FTS_EV_CONTROLLER_READY	0x03	/* whole byte, after a reset */
#define FTS_EV_ENTER		0x13
#define FTS_EV_MOTION		0x23
#define FTS_EV_LEAVE		0x33
#define FTS_EV_STATUS		0x43
#define FTS_EV_USER_REPORT	0x53
#define FTS_EV_DEBUG		0xe3
#define FTS_EV_ERROR		0xf3

#define FTS_EVENT_SIZE		8
#define FTS_STACK_DEPTH		32
#define FTS_DATA_SIZE		(FTS_EVENT_SIZE * FTS_STACK_DEPTH)

#define FTS_MAX_FINGERS		10
#define FTS_I2C_DELAY_US	10	/* ~30 kHz on the bit-banged bus */
#define FTS_POLL_MS		20
#define FTS_EVENTS_PER_POLL	6

#define FTS_RAW_DUMP_DEFAULT	48

struct fts_data {
	struct device *dev;
	struct input_dev *input;
	struct gpio_desc *sda;
	struct gpio_desc *scl;
	struct gpio_desc *reset;
	struct regulator_bulk_data supplies[2];
	struct touchscreen_properties prop;
	struct mutex lock;		/* serialises bus access */
	int irq;
	u8 addr;
	int dump_left;
	int dbg_polls;
	unsigned int err_count;
	u8 buf[FTS_DATA_SIZE];
	struct delayed_work poll_work;
	bool powered;
	bool scanning;
	bool irq_on;
	bool awake;
};

/* ---------------- bit-banged I2C ---------------- */

static inline void fts_sda_low(struct fts_data *ts)
{
	gpiod_direction_output(ts->sda, 0);
}

static inline void fts_sda_release(struct fts_data *ts)
{
	gpiod_direction_input(ts->sda);
}

static inline void fts_scl_low(struct fts_data *ts)
{
	gpiod_direction_output(ts->scl, 0);
}

static inline void fts_scl_release(struct fts_data *ts)
{
	gpiod_direction_input(ts->scl);
}

static void fts_start(struct fts_data *ts)
{
	fts_sda_release(ts);
	fts_scl_release(ts);
	udelay(FTS_I2C_DELAY_US);
	fts_sda_low(ts);		/* SDA falls while SCL is high */
	udelay(FTS_I2C_DELAY_US);
	fts_scl_low(ts);
	udelay(FTS_I2C_DELAY_US);
}

static void fts_stop(struct fts_data *ts)
{
	fts_sda_low(ts);
	udelay(FTS_I2C_DELAY_US);
	fts_scl_release(ts);
	udelay(FTS_I2C_DELAY_US);
	fts_sda_release(ts);		/* SDA rises while SCL is high */
	udelay(FTS_I2C_DELAY_US);
}

static int fts_write_byte(struct fts_data *ts, u8 byte)
{
	int i, nack;

	for (i = 7; i >= 0; i--) {
		if (byte & BIT(i))
			fts_sda_release(ts);
		else
			fts_sda_low(ts);
		udelay(FTS_I2C_DELAY_US);
		fts_scl_release(ts);
		udelay(FTS_I2C_DELAY_US);
		fts_scl_low(ts);
		udelay(FTS_I2C_DELAY_US);
	}

	/* ninth clock: release SDA and sample it */
	fts_sda_release(ts);
	udelay(FTS_I2C_DELAY_US);
	fts_scl_release(ts);
	udelay(FTS_I2C_DELAY_US);
	nack = gpiod_get_value(ts->sda);
	fts_scl_low(ts);
	udelay(FTS_I2C_DELAY_US);

	return nack ? -ENXIO : 0;
}

static u8 fts_read_byte(struct fts_data *ts, bool ack)
{
	u8 byte = 0;
	int i;

	fts_sda_release(ts);
	for (i = 7; i >= 0; i--) {
		udelay(FTS_I2C_DELAY_US);
		fts_scl_release(ts);
		udelay(FTS_I2C_DELAY_US);
		if (gpiod_get_value(ts->sda))
			byte |= BIT(i);
		fts_scl_low(ts);
	}
	udelay(FTS_I2C_DELAY_US);

	if (ack)
		fts_sda_low(ts);
	else
		fts_sda_release(ts);
	udelay(FTS_I2C_DELAY_US);
	fts_scl_release(ts);
	udelay(FTS_I2C_DELAY_US);
	fts_scl_low(ts);
	fts_sda_release(ts);
	udelay(FTS_I2C_DELAY_US);

	return byte;
}

/*
 * Write outlen bytes, then a repeated start and inlen bytes in - the same two
 * messages-in-one-transfer shape the vendor fts_writeRead() hands to
 * i2c_transfer().  The controller expects the read to follow without an
 * intervening stop.
 */
static int fts_xfer_n(struct fts_data *ts, const u8 *out, int outlen,
		      u8 *in, int inlen)
{
	int i, ret;

	fts_start(ts);
	ret = fts_write_byte(ts, ts->addr << 1);
	for (i = 0; i < outlen && !ret; i++)
		ret = fts_write_byte(ts, out[i]);
	if (ret)
		goto out;

	if (!inlen) {
		fts_stop(ts);
		return 0;
	}

	fts_start(ts);
	ret = fts_write_byte(ts, (ts->addr << 1) | 1);
	if (ret)
		goto out;

	for (i = 0; i < inlen; i++)
		in[i] = fts_read_byte(ts, i < inlen - 1);

	fts_stop(ts);
	return 0;

out:
	fts_stop(ts);
	return ret;
}

static int fts_send(struct fts_data *ts, const u8 *buf, int len)
{
	return fts_xfer_n(ts, buf, len, NULL, 0);
}

/* { 0xFA, a31..a0 } then a repeated start and len bytes in */
static int fts_hw_read(struct fts_data *ts, u32 addr, u8 *buf, int len)
{
	u8 out[5] = { FTS_CMD_HW_REG, (addr >> 24) & 0xff, (addr >> 16) & 0xff,
		      (addr >> 8) & 0xff, addr & 0xff };

	return fts_xfer_n(ts, out, sizeof(out), buf, len);
}

/* { 0xFA, a31..a0, data... } in one message, no read phase */
static int fts_hw_write(struct fts_data *ts, u32 addr, const u8 *data, int len)
{
	u8 out[8];

	if (len < 1 || len > (int)sizeof(out) - 5)
		return -EINVAL;

	out[0] = FTS_CMD_HW_REG;
	out[1] = (addr >> 24) & 0xff;
	out[2] = (addr >> 16) & 0xff;
	out[3] = (addr >> 8) & 0xff;
	out[4] = addr & 0xff;
	memcpy(&out[5], data, len);

	return fts_send(ts, out, 5 + len);
}

/* one 8 byte event out of the FIFO: { 0x86 } then a read */
static int fts_read_one_event(struct fts_data *ts, u8 *ev)
{
	u8 cmd = FTS_CMD_READALL;

	return fts_xfer_n(ts, &cmd, 1, ev, FTS_EVENT_SIZE);
}

/*
 * Drain the FIFO the way the vendor's fts_event_handler() does.
 *
 * This is the whole trick of the protocol: byte 7 of the *first* event carries
 * the number of events still queued in its low 5 bits.  Reading a single event
 * and walking away leaves the rest in the FIFO, and the controller keeps the
 * interrupt line asserted until the FIFO has been emptied - which shows up as
 * an interrupt storm and as touch events that never surface.
 */
static int fts_read_events(struct fts_data *ts, int *count)
{
	u8 cmd = FTS_CMD_READALL;
	int ret, rest;

	ret = fts_xfer_n(ts, &cmd, 1, ts->buf, FTS_EVENT_SIZE);
	if (ret) {
		*count = 0;
		return ret;
	}

	rest = ts->buf[FTS_EVENT_SIZE - 1] & 0x1f;
	if (rest > FTS_STACK_DEPTH - 1)
		rest = FTS_STACK_DEPTH - 1;

	if (rest)
		ret = fts_xfer_n(ts, &cmd, 1, &ts->buf[FTS_EVENT_SIZE],
				 FTS_EVENT_SIZE * rest);

	*count = rest + 1;
	return ret;
}

static int fts_set_scan_mode(struct fts_data *ts, u8 mode, u8 mask)
{
	u8 cmd[3] = { FTS_CMD_SCAN_MODE, mode, mask };

	return fts_send(ts, cmd, sizeof(cmd));
}

static int fts_flush_fifo(struct fts_data *ts)
{
	u8 cmd[3] = { FTS_CMD_SYSTEM, FTS_SYS_CMD_SPECIAL,
		      FTS_SPECIAL_FIFO_FLUSH };

	return fts_send(ts, cmd, sizeof(cmd));
}

/* ---------------- input ---------------- */

static void fts_report_point(struct fts_data *ts, const u8 *ev, bool down,
			     bool have_area)
{
	struct input_dev *input = ts->input;
	unsigned int id = ev[1] >> 4;
	unsigned int x = ((ev[3] & 0x0f) << 8) | ev[2];
	unsigned int y = (ev[4] << 4) | ((ev[3] & 0xf0) >> 4);
	unsigned int area = have_area ? ((ev[5] << 8) | ev[6]) : 1;

	if (id >= FTS_MAX_FINGERS) {
		dev_warn_ratelimited(ts->dev, "slot %u out of range\n", id);
		return;
	}

	input_mt_slot(input, id);

	if (!down) {
		input_mt_report_slot_state(input, MT_TOOL_FINGER, false);
		return;
	}

	input_mt_report_slot_state(input, MT_TOOL_FINGER, true);
	touchscreen_report_pos(input, &ts->prop, x, y, true);
	input_report_abs(input, ABS_MT_TOUCH_MAJOR, area);
	input_report_abs(input, ABS_MT_PRESSURE, area ? area : 1);
}

static void fts_parse_event(struct fts_data *ts, const u8 *ev)
{
	switch (ev[0]) {
	case FTS_EV_NOEVENT:
	case FTS_EV_CONTROLLER_READY:
		return;
	case FTS_EV_ENTER:
		fts_report_point(ts, ev, true, false);
		break;
	case FTS_EV_MOTION:
		fts_report_point(ts, ev, true, true);
		break;
	case FTS_EV_LEAVE:
		fts_report_point(ts, ev, false, false);
		break;
	case FTS_EV_ERROR:
		dev_warn_ratelimited(ts->dev, "controller error %8phN\n", ev);
		return;
	default:
		/*
		 * Status / echo / user report / debug.  These were silenced
		 * while hunting log noise, but the controller reports at a few
		 * hundred events a second and none of them is a touch, so the
		 * content is exactly what has to be seen now.
		 */
		if (ts->dump_left > 0) {
			ts->dump_left--;
			dev_info(ts->dev, "ev %8phN\n", ev);
		}
		return;
	}

	if (ts->dump_left > 0) {
		ts->dump_left--;
		dev_info(ts->dev, "ev %8phN id %u %u,%u area %u\n", ev,
			 ev[1] >> 4,
			 ((ev[3] & 0x0f) << 8) | ev[2],
			 (ev[4] << 4) | ((ev[3] & 0xf0) >> 4),
			 (ev[5] << 8) | ev[6]);
	}
}

/*
 * Polling instead of interrupts.
 *
 * The level-low interrupt source stops delivering after the very first
 * interrupt on this unit even though the enable register is rewritten after
 * every frame, and /proc/interrupts stays pinned at 1 while the panel is
 * being touched.  Reading the FIFO on a timer is what the vendor driver
 * effectively ends up doing for events it missed, needs no IRQ programming at
 * all, and is cheap.
 */
static void fts_poll_work(struct work_struct *work)
{
	struct fts_data *ts = container_of(work, struct fts_data, poll_work.work);
	bool any = false;
	int i, ret, count = 0;

	mutex_lock(&ts->lock);

	ret = fts_read_events(ts, &count);
	if (ret) {
		if (++ts->err_count <= 5)
			dev_err(ts->dev, "event read failed: %d (%u)\n",
				ret, ts->err_count);
		count = 0;
	} else {
		ts->err_count = 0;
	}

	for (i = 0; i < count; i++) {
		u8 *ev = &ts->buf[i * FTS_EVENT_SIZE];

		if (ts->dbg_polls < 4) {
			dev_info(ts->dev, "poll%u: %8phN\n", ts->dbg_polls, ev);
			ts->dbg_polls++;
		}

		if (ev[0] == FTS_EV_NOEVENT)
			continue;

		fts_parse_event(ts, ev);
		any = true;
	}

	if (any) {
		input_mt_sync_frame(ts->input);
		input_sync(ts->input);
	}

	mutex_unlock(&ts->lock);

	if (ts->scanning)
		schedule_delayed_work(&ts->poll_work,
				      msecs_to_jiffies(FTS_POLL_MS));
}

static irqreturn_t fts_irq_thread(int irq, void *data)
{
	struct fts_data *ts = data;
	bool any = false;
	int i, ret, count = 0;

	mutex_lock(&ts->lock);

	/* drain the whole FIFO, exactly like the vendor handler */
	ret = fts_read_events(ts, &count);
	if (ret) {
		/*
		 * A dead bus with a level-low interrupt means the handler
		 * would be re-entered forever.  Complain a few times, then
		 * shut the interrupt off so the log survives.
		 */
		ts->err_count++;
		count = 0;
		if (ts->err_count <= 5)
			dev_err(ts->dev, "event read failed: %d (%u)\n",
				ret, ts->err_count);
		else if (ts->err_count == 6) {
			dev_err(ts->dev,
				"bus is not answering, disabling irq %d\n",
				ts->irq);
			disable_irq_nosync(ts->irq);
		}
	} else {
		ts->err_count = 0;
	}

	for (i = 0; i < count; i++) {
		u8 *ev = &ts->buf[i * FTS_EVENT_SIZE];

		if (ev[0] == FTS_EV_NOEVENT)
			continue;

		fts_parse_event(ts, ev);
		any = true;
	}

	if (any) {
		input_mt_sync_frame(ts->input);
		input_sync(ts->input);
	}

	/*
	 * The FW clears IER itself once it has an event to hand over and then
	 * waits for the host; without this re-arm it stops producing events
	 * after the very first one.  Reading IER back after an enable always
	 * returned 0x00, which is what made the missing re-arm visible.
	 */
	if (ts->powered) {
		u8 en = IER_ENABLE;

		fts_hw_write(ts, ADDR_IER, &en, 1);
	}

	mutex_unlock(&ts->lock);
	return IRQ_HANDLED;
}

/* ---------------- power up ---------------- */

static int fts_power_on(struct fts_data *ts)
{
	u8 ev[FTS_EVENT_SIZE];
	u8 id[2] = { 0 }, ver[2] = { 0 };
	int ret, i, ready = 0;

	/*
	 * Vendor fts_enable_reg() enables the bus supply (3.3 V) before the
	 * power supply (1.8 V); keep that order.  Both are fixed rails: only
	 * the enable is touched, no voltage is programmed.
	 */
	ret = regulator_bulk_enable(ARRAY_SIZE(ts->supplies), ts->supplies);
	if (ret) {
		dev_err(ts->dev, "failed to enable supplies: %d\n", ret);
		return ret;
	}
	msleep(20);

	/*
	 * fts_system_reset(): drive reset low for 10 ms and release it.  The
	 * FW then announces itself with a CONTROL_READY event on the FIFO, and
	 * that event is the only proof the controller actually started - the
	 * vendor driver blocks on it too (pollForEvent with GENERAL_TIMEOUT).
	 */
	if (ts->reset) {
		gpiod_set_value_cansleep(ts->reset, 0);
		msleep(10);
		gpiod_set_value_cansleep(ts->reset, 1);
	}

	for (i = 0; i < 30; i++) {
		if (!fts_read_one_event(ts, ev) &&
		    ev[0] == FTS_EV_CONTROLLER_READY) {
			ready = 1;
			break;
		}
		msleep(10);
	}
	dev_info(ts->dev, "controller %s after %d ms\n",
		 ready ? "ready" : "NOT ready", i * 10);

	/* 0x20000000 / 0x20000004, both little endian on the wire */
	if (!fts_hw_read(ts, ADDR_DCHIP_ID, id, sizeof(id)))
		dev_info(ts->dev, "chip id %02x%02x\n", id[1], id[0]);
	else
		dev_info(ts->dev, "chip id read failed\n");

	if (!fts_hw_read(ts, ADDR_DCHIP_FW_VER, ver, sizeof(ver)))
		dev_info(ts->dev, "fw ver %02x%02x\n", ver[1], ver[0]);
	else
		dev_info(ts->dev, "fw ver read failed\n");

	/* vendor fts_enableInterrupt(): IER = 0x41 */
	{
		u8 en = IER_ENABLE;

		ret = fts_hw_write(ts, ADDR_IER, &en, 1);
		dev_info(ts->dev, "interrupt enable: %d\n", ret);
	}

	/* drop whatever the controller queued while it was booting */
	fts_flush_fifo(ts);

	ts->powered = true;
	dev_info(ts->dev, "powered on\n");
	return 0;
}

/*
 * Powering the controller and enabling its sensing are two separate steps, and
 * the second one is the one the panel objects to: the controller and the
 * command mode AMOLED sit on the same flex and share the 3.3 V touch/vddio rail
 * (vendor name disp_vddio_vreg).  Every build that let the controller actually
 * run left the panel black, and deferring it until after the panel was up did
 * not help, so the armed/dead distinction is exposed here instead of being
 * guessed at with one reflash per attempt:
 *
 *   echo 0 > .../enable    controller unpowered (the p43 state, panel safe)
 *   echo 1 > .../enable    controller powered and handshaked, sensing off
 *   echo 2 > .../enable    sensing on, events and input reporting active
 */
static int fts_enable_interrupt(struct fts_data *ts)
{
	u8 en = IER_ENABLE;

	return fts_hw_write(ts, ADDR_IER, &en, 1);
}

/*
 * Bring sensing up the way the vendor's fts_init_sensing() does it:
 *
 *     mode_handler()            -> scan on, then the gesture feature
 *     setScanMode(ACTIVE, 00)   -> sense off
 *     WAIT_AFTER_SENSEOFF
 *     setScanMode(ACTIVE, 01)   -> sense on
 *     fts_enableInterrupt()     -> IER last
 *
 * A single 0xA0 00 01 does flip a controller register (0x2000004a goes 00 to
 * 50), but the FW never produces touch events that way - it wants the explicit
 * off/on cycle, and the interrupt armed only after that.
 */
static int fts_start_scan(struct fts_data *ts)
{
	static const u8 gesture[] = { FTS_CMD_FEATURE, FTS_FEAT_GESTURE,
				      0x00, 0x00, 0x00, 0x03 };
	int ret;

	fts_flush_fifo(ts);

	/*
	 * ★ Keep this to ONE scan-mode write.
	 *
	 * Following the vendor's fts_init_sensing() literally - sense on,
	 * gesture, then sense off, 50 ms, sense on again - left the display
	 * black on p53, and so did poking SYS_CMD_SPECIAL with PANEL_INIT
	 * (0xA4 00 02) by hand.  Every build up to p52, which only ever wrote
	 * the scan mode once, kept the panel alive.  The touch controller is
	 * on the panel flex, so cycling its sensing also disturbs the command
	 * mode AMOLED.  Do not put the off/on cycle back without a way to
	 * bring the panel back.
	 */
	ret = fts_set_scan_mode(ts, FTS_SCAN_MODE_LOW_POWER, 0);
	if (ret)
		return ret;
	msleep(20);

	ret = fts_set_scan_mode(ts, FTS_SCAN_MODE_ACTIVE, FTS_SCAN_MT);
	if (ret)
		return ret;

	fts_send(ts, gesture, sizeof(gesture));

	ret = fts_enable_interrupt(ts);
	dev_info(ts->dev, "scan on: %d\n", ret);

	return ret;
}

static void fts_power_off(struct fts_data *ts)
{
	if (ts->scanning) {
		fts_set_scan_mode(ts, FTS_SCAN_MODE_LOW_POWER, 0);
		ts->scanning = false;
	}

	if (ts->powered) {
		regulator_bulk_disable(ARRAY_SIZE(ts->supplies), ts->supplies);
		ts->powered = false;
	}

	ts->awake = false;
}

/*
 * Runtime I2C poke box.
 *
 *   echo w 86                  > .../cmd   write one byte
 *   echo w a0 00 01            > .../cmd   write three bytes
 *   echo r 86 8                > .../cmd   write 0x86, read 8 bytes
 *   echo h 20000004 2          > .../cmd   read 2 bytes at FTI address
 *   echo H 20000029 41         > .../cmd   write 1 byte at FTI address
 *
 * Lets the command sequence be worked out on the live device instead of
 * recompiling the kernel for every guess.
 */
static ssize_t fts_cmd_store(struct device *dev, struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct fts_data *ts = dev_get_drvdata(dev);
	unsigned int vals[10] = { 0 };
	u8 out[10], in[64];
	const char *p = buf;
	int nvals = 0, ret, i;
	char op;

	while (*p == ' ')
		p++;
	op = *p++;
	if (op != 'w' && op != 'W' && op != 'r' && op != 'R' &&
	    op != 'h' && op != 'H' && op != 'x' && op != 'X')
		return -EINVAL;
	while (*p == ' ')
		p++;

	while (nvals < ARRAY_SIZE(vals) && sscanf(p, "%x", &vals[nvals]) == 1) {
		nvals++;
		while (*p && *p != ' ' && *p != '\n')
			p++;
		while (*p == ' ')
			p++;
	}
	if (!nvals)
		return -EINVAL;

	/*
	 * ★ 0xA4 (FTS_CMD_SYSTEM) can kill the display.
	 *
	 * Measured on umi:
	 *   0xA4 00 01  SYS_CMD_SPECIAL/FIFO_FLUSH  harmless, used by flush
	 *   0xA4 00 02  SYS_CMD_SPECIAL/PANEL_INIT  panel goes black
	 *   0xA4 02     SYS_CMD_FORCE_CAL           panel goes black
	 * 0xA4 00 02 and 0xA4 02 both survived the write, came back with the
	 * echo event, and left the command mode AMOLED dark until reboot.
	 * The controller drives the panel flex, so nothing here may touch the
	 * panel init or the calibration path.  SYS_CMD_LOAD_DATA (0xA4 01 xx)
	 * only asks the FW to fill a memory buffer and is allowed, it is how a
	 * touch frame gets requested.
	 */
	if ((op == 'w' || op == 'W') && vals[0] == FTS_CMD_SYSTEM &&
	    !(nvals >= 2 && vals[1] == FTS_SYS_CMD_LOAD_DATA) &&
	    !(nvals >= 2 && vals[1] == FTS_SYS_CMD_FORCE_CAL) &&
	    !(nvals >= 3 && vals[1] == FTS_SYS_CMD_SPECIAL &&
	      vals[2] == FTS_SPECIAL_FIFO_FLUSH)) {
		dev_warn(dev, "refusing 0xA4 system command, it blacks out the panel\n");
		return -EPERM;
	}

	mutex_lock(&ts->lock);
	if (op == 'w' || op == 'W') {
		for (i = 0; i < nvals; i++)
			out[i] = vals[i];
		ret = fts_send(ts, out, nvals);
		dev_info(dev, "cmd w %d bytes -> %d\n", nvals, ret);
	} else if (op == 'h' || op == 'H') {
		int rdlen = nvals > 1 ? vals[1] : 2;

		if (rdlen > (int)sizeof(in))
			rdlen = sizeof(in);
		ret = fts_hw_read(ts, vals[0], in, rdlen);
		if (ret)
			dev_info(dev, "hw r %08x -> %d\n", vals[0], ret);
		else
			dev_info(dev, "hw r %08x len %d -> %*ph\n", vals[0],
				 rdlen, rdlen, in);
	} else if (op == 'x' || op == 'X') {
		/* x <byte> [<byte>...] <readlen>: write, then read */
		int wlen = nvals - 1, rdlen = vals[nvals - 1];

		if (wlen < 1)
			return -EINVAL;
		if (rdlen < 1 || rdlen > (int)sizeof(in))
			rdlen = sizeof(in);
		if (wlen > (int)sizeof(out))
			wlen = sizeof(out);
		for (i = 0; i < wlen; i++)
			out[i] = vals[i];

		ret = fts_xfer_n(ts, out, wlen, in, rdlen);
		if (ret)
			dev_info(dev, "cmd x %d/%d -> %d\n", wlen, rdlen, ret);
		else
			dev_info(dev, "cmd x %d/%d -> %*ph\n", wlen, rdlen,
				 rdlen, in);
	} else {
		int rdlen = nvals > 1 ? vals[1] : 8;

		if (rdlen > (int)sizeof(in))
			rdlen = sizeof(in);
		out[0] = vals[0];
		ret = fts_xfer_n(ts, out, 1, in, rdlen);
		if (ret)
			dev_info(dev, "cmd r %02x len %d -> %d\n", vals[0],
				 rdlen, ret);
		else
			dev_info(dev, "cmd r %02x len %d -> %*ph\n", vals[0],
				 rdlen, rdlen, in);
	}
	mutex_unlock(&ts->lock);

	return count;
}
static DEVICE_ATTR(cmd, 0200, NULL, fts_cmd_store);

static ssize_t fts_enable_store(struct device *dev,
				struct device_attribute *attr,
				const char *buf, size_t count)
{
	struct fts_data *ts = dev_get_drvdata(dev);
	int val, ret = 0;
	bool kick = false;

	if (sscanf(buf, "%d", &val) != 1 || val < 0 || val > 2)
		return -EINVAL;

	/*
	 * The poll work and the irq thread both take this mutex, so they have
	 * to be stopped before the lock is taken.
	 */
	if (val == 0) {
		cancel_delayed_work_sync(&ts->poll_work);
		ts->scanning = false;
		if (ts->irq_on) {
			disable_irq(ts->irq);
			ts->irq_on = false;
		}
	}

	mutex_lock(&ts->lock);

	switch (val) {
	case 0:
		fts_power_off(ts);
		dev_info(dev, "enable 0: controller unpowered\n");
		break;
	case 1:
		if (!ts->powered) {
			ret = fts_power_on(ts);
			ts->awake = !ret;
		}
		dev_info(dev, "enable 1: powered %s\n", ret ? "FAILED" : "ok");
		break;
	case 2:
		if (!ts->powered)
			ret = fts_power_on(ts);
		if (!ret)
			ret = fts_start_scan(ts);
		if (!ret) {
			ts->scanning = true;
			ts->awake = true;
			kick = true;
		}
		dev_info(dev, "enable 2: scanning %s\n", ret ? "FAILED" : "ok");
		break;
	}

	mutex_unlock(&ts->lock);

	if (kick) {
		enable_irq(ts->irq);
		ts->irq_on = true;
		schedule_delayed_work(&ts->poll_work, 0);
	}

	return ret ? ret : count;
}
static DEVICE_ATTR(enable, 0200, NULL, fts_enable_store);

static int fts_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct fts_data *ts;
	u32 addr = 0x49;
	int ret;

	ts = devm_kzalloc(dev, sizeof(*ts), GFP_KERNEL);
	if (!ts)
		return -ENOMEM;

	ts->dev = dev;
	ts->dump_left = FTS_RAW_DUMP_DEFAULT;
	mutex_init(&ts->lock);
	platform_set_drvdata(pdev, ts);

	of_property_read_u32(dev->of_node, "reg", &addr);
	ts->addr = addr & 0xff;

	ts->sda = devm_gpiod_get(dev, "sda", GPIOD_IN);
	if (IS_ERR(ts->sda))
		return dev_err_probe(dev, PTR_ERR(ts->sda), "no sda gpio\n");

	ts->scl = devm_gpiod_get(dev, "scl", GPIOD_IN);
	if (IS_ERR(ts->scl))
		return dev_err_probe(dev, PTR_ERR(ts->scl), "no scl gpio\n");

	ts->reset = devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(ts->reset))
		return dev_err_probe(dev, PTR_ERR(ts->reset), "no reset gpio\n");

	ts->irq = platform_get_irq(pdev, 0);
	if (ts->irq <= 0)
		return dev_err_probe(dev, -ENXIO, "no interrupt\n");

	ts->supplies[0].supply = "avdd";	/* 3.3 V, enabled first */
	ts->supplies[1].supply = "vdd";		/* 1.8 V */
	ret = devm_regulator_bulk_get(dev, ARRAY_SIZE(ts->supplies),
				      ts->supplies);
	if (ret)
		return dev_err_probe(dev, ret, "failed to get supplies\n");

	ts->input = devm_input_allocate_device(dev);
	if (!ts->input)
		return -ENOMEM;

	ts->input->name = "fts-umi";
	ts->input->id.bustype = BUS_I2C;
	ts->input->dev.parent = dev;

	input_set_abs_params(ts->input, ABS_MT_POSITION_X, 0, 1080, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_POSITION_Y, 0, 2340, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_TOUCH_MAJOR, 0, 255, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_TOUCH_MINOR, 0, 255, 0, 0);
	input_set_abs_params(ts->input, ABS_MT_PRESSURE, 0, 255 * 255, 0, 0);

	touchscreen_parse_properties(ts->input, true, &ts->prop);

	input_set_capability(ts->input, EV_KEY, BTN_TOUCH);
	__set_bit(INPUT_PROP_DIRECT, ts->input->propbit);

	ret = input_mt_init_slots(ts->input, FTS_MAX_FINGERS, INPUT_MT_DIRECT);
	if (ret)
		return dev_err_probe(dev, ret, "failed to init MT slots\n");

	ret = input_register_device(ts->input);
	if (ret)
		return dev_err_probe(dev, ret, "failed to register input\n");

	/*
	 * The FW is interrupt driven: it raises the level-low line, clears IER
	 * and waits for the host to drain the FIFO and re-arm it.  Polling
	 * alone therefore never gets touch events.  The handler is installed
	 * here but kept disabled until the controller is actually started, so
	 * a floating or held line cannot storm the GIC while nothing is
	 * powered.
	 */
	ret = devm_request_threaded_irq(dev, ts->irq, NULL, fts_irq_thread,
					IRQF_TRIGGER_LOW | IRQF_ONESHOT,
					"fts-umi", ts);
	if (ret)
		return dev_err_probe(dev, ret, "failed to request irq %d\n",
				     ts->irq);
	disable_irq(ts->irq);

	INIT_DELAYED_WORK(&ts->poll_work, fts_poll_work);

	device_create_file(dev, &dev_attr_cmd);
	device_create_file(dev, &dev_attr_enable);

	dev_info(dev, "%ux%u, %d slots, irq %d\n",
		 ts->prop.max_x + 1, ts->prop.max_y + 1, FTS_MAX_FINGERS,
		 ts->irq);

	return 0;
}

static void fts_remove(struct platform_device *pdev)
{
	struct fts_data *ts = platform_get_drvdata(pdev);

	cancel_delayed_work_sync(&ts->poll_work);

	if (ts->irq_on) {
		disable_irq(ts->irq);
		ts->irq_on = false;
	}

	mutex_lock(&ts->lock);
	fts_power_off(ts);
	mutex_unlock(&ts->lock);
}

static int fts_suspend(struct device *dev)
{
	struct fts_data *ts = dev_get_drvdata(dev);

	cancel_delayed_work_sync(&ts->poll_work);

	mutex_lock(&ts->lock);
	if (ts->awake) {
		fts_set_scan_mode(ts, FTS_SCAN_MODE_LOW_POWER, 0);
		fts_hw_write(ts, ADDR_IER, (const u8[]){ IER_DISABLE }, 1);
		ts->awake = false;
	}
	mutex_unlock(&ts->lock);

	return 0;
}

static int fts_resume(struct device *dev)
{
	struct fts_data *ts = dev_get_drvdata(dev);
	int ret = 0;

	mutex_lock(&ts->lock);
	if (ts->powered) {
		ret = fts_power_on(ts);
		if (!ret)
			ts->awake = true;
	}
	mutex_unlock(&ts->lock);

	if (ts->scanning) {
		enable_irq(ts->irq);
		ts->irq_on = true;
		schedule_delayed_work(&ts->poll_work,
				      msecs_to_jiffies(FTS_POLL_MS));
	}

	return ret;
}

static DEFINE_SIMPLE_DEV_PM_OPS(fts_pm_ops, fts_suspend, fts_resume);

static const struct of_device_id fts_of_match[] = {
	{ .compatible = "st,fts-umi" },
	{ }
};
MODULE_DEVICE_TABLE(of, fts_of_match);

static struct platform_driver fts_driver = {
	.driver = {
		.name = "fts-umi",
		.of_match_table = fts_of_match,
		.pm = pm_sleep_ptr(&fts_pm_ops),
	},
	.probe = fts_probe,
	.remove = fts_remove,
};
module_platform_driver(fts_driver);

MODULE_DESCRIPTION("STMicroelectronics FTS5 touchscreen for Xiaomi Mi 10 (umi)");
MODULE_LICENSE("GPL");
