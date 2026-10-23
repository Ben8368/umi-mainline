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
 * ★ Protocol: this is FTS5, not FTS4
 *
 *   Verified against the upstream "Input: support for STM FTS5" series
 *   (David Heidelberg, v7) and the vendor driver:
 *
 *   - events are read in one shot with 0x86; the controller returns
 *     STACK_DEPTH * 8 bytes and the list ends at the first 0x00 event
 *   - the event class is the *high* nibble of event[0]:
 *       0x03 controller ready (whole byte), 0x10 enter, 0x20 motion,
 *       0x30 leave, 0x40 status, 0x50 user report, 0xe0 debug, 0xf0 error
 *     (the vendor log prints "Event 0x13 - Press" / "0x33 - release", i.e.
 *     0x10|0x3 and 0x30|0x3 - the low nibble carries major axis bits)
 *   - touch point layout:
 *       [0] id high nibble | major bits 5:4 in bits 3:2
 *       [1] touch id high nibble | touch type low nibble (1 = finger)
 *       [2] x bits 7:0
 *       [3] y bits 3:0 high nibble | x bits 11:8 low nibble
 *       [4] y bits 11:4
 *       [5] pressure
 *       [6] major bits 3:0 high nibble | minor bits 3:0 low nibble
 *       [7] minor bits 5:4 in bits 7:6
 *   - scanning is enabled with 0xa0 {mode 0x00, mask 0x01}; there is no 0x93
 *   - the interrupt source is armed by writing {0xb6 0x00 0x2c 0x01}
 *     (hardware register write), not by an I2C command
 *   - 0x80 (read info) does not exist on this part, it answers with zeros
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

#define FTS_CMD_READ_ALL_EVENT	0x86	/* FTS5 bulk read (returns empty here) */
#define FTS_CMD_FIFO_READ_ONE	0x85	/* vendor: one 8 byte event at a time */
#define FTS_CMD_SET_SCAN_MODE	0xa0	/* + mode byte + scan mask byte */
#define FTS_CMD_CLEAR_EVENT	0xa1
#define FTS_CMD_FORCE_CAL	0xa2
#define FTS_CMD_MS_CX_TUNING	0xa3
#define FTS_CMD_SS_CX_TUNING	0xa4
#define FTS_CMD_MS_MT_SENSE_OFF	0x92
#define FTS_CMD_MS_MT_SENSE_ON	0x93
#define FTS_CMD_SLEEP_IN	0x90
#define FTS_CMD_SLEEP_OUT	0x91

#define FTS_SCAN_MODE_ACTIVE	0x00
#define FTS_SCAN_MULTI_TOUCH	0x01

/* FTS5 event classes (high nibble of event[0]) */
#define FTS_EV5_CONTROLLER_READY	0x03
#define FTS_EV5_MT_ENTER		0x10
#define FTS_EV5_MT_MOTION		0x20
#define FTS_EV5_MT_LEAVE		0x30
#define FTS_EV5_STATUS_UPDATE		0x40
#define FTS_EV5_USER_REPORT		0x50
#define FTS_EV5_DEBUG			0xe0
#define FTS_EV5_ERROR			0xf0

#define FTS_EVENT_SIZE		8
#define FTS_STACK_DEPTH		32
#define FTS_DATA_SIZE		(FTS_EVENT_SIZE * FTS_STACK_DEPTH)

#define FTS_MAX_FINGERS		10
#define FTS_I2C_DELAY_US	2	/* ~250 kHz */
#define FTS_POLL_MS		30

#define FTS_RAW_DUMP_DEFAULT	64

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

static void fts_bus_idle(struct fts_data *ts)
{
	fts_sda_release(ts);
	fts_scl_release(ts);
	udelay(FTS_I2C_DELAY_US);
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

/* generic transfer: outlen bytes out, then a repeated start and inlen bytes in */
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

static int fts_xfer(struct fts_data *ts, u8 cmd, u8 *buf, int len)
{
	return fts_xfer_n(ts, &cmd, 1, buf, len);
}

/* The controller exposes a 16 bit memory window: write {0xb6, hi, lo} then
 * read.  This is how the vendor driver reads FW/CONFIG version - the 0x80
 * "read info" command answers with zeros on this part. */
static int fts_hw_read(struct fts_data *ts, u16 addr, u8 *buf, int len)
{
	u8 out[3] = { 0xb6, (addr >> 8) & 0xff, addr & 0xff };

	return fts_xfer_n(ts, out, sizeof(out), buf, len);
}

static int fts_command(struct fts_data *ts, u8 cmd)
{
	return fts_xfer(ts, cmd, NULL, 0);
}

static int fts_send(struct fts_data *ts, const u8 *buf, int len)
{
	int i, ret;

	fts_start(ts);
	ret = fts_write_byte(ts, ts->addr << 1);
	for (i = 0; i < len && !ret; i++)
		ret = fts_write_byte(ts, buf[i]);
	fts_stop(ts);

	return ret;
}

/* ---------------- chip ---------------- */

static int fts_read_events(struct fts_data *ts, u8 *buf)
{
	return fts_xfer(ts, FTS_CMD_READ_ALL_EVENT, buf, FTS_DATA_SIZE);
}

static void fts_report_point(struct fts_data *ts, const u8 *ev, bool down)
{
	struct input_dev *input = ts->input;
	unsigned int id = ev[1] >> 4;
	unsigned int x = ((ev[3] & 0x0f) << 8) | ev[2];
	unsigned int y = (ev[4] << 4) | ((ev[3] & 0xf0) >> 4);
	unsigned int maj = ((ev[0] & 0x0c) << 2) | (ev[6] >> 4);
	unsigned int min = ((ev[7] & 0xc0) >> 2) | (ev[6] & 0x0f);
	unsigned int pressure = ev[5] ? ev[5] : 1;

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
	input_report_abs(input, ABS_MT_TOUCH_MAJOR, maj);
	input_report_abs(input, ABS_MT_TOUCH_MINOR, min);
	input_report_abs(input, ABS_MT_PRESSURE, pressure);
}

static void fts_parse_events(struct fts_data *ts, const u8 *data)
{
	const char *what;
	int i;

	for (i = 0; i < FTS_STACK_DEPTH; i++) {
		const u8 *ev = &data[i * FTS_EVENT_SIZE];
		u8 type = ev[0] & 0xf0;

		if (ev[0] == 0x00)
			break;

		if (ev[0] == FTS_EV5_CONTROLLER_READY)
			continue;

		switch (type) {
		case FTS_EV5_MT_ENTER:
			what = "enter";
			break;
		case FTS_EV5_MT_MOTION:
			what = "motion";
			break;
		case FTS_EV5_MT_LEAVE:
			what = "leave";
			break;
		case FTS_EV5_ERROR:
			dev_warn_ratelimited(ts->dev,
					     "controller error %8phN\n", ev);
			continue;
		case FTS_EV5_STATUS_UPDATE:
		case FTS_EV5_USER_REPORT:
		case FTS_EV5_DEBUG:
			continue;
		default:
			if (ts->dump_left > 0) {
				ts->dump_left--;
				dev_info(ts->dev, "ev %8phN (class %02x)\n",
					 ev, type);
			}
			continue;
		}

		if (ts->dump_left > 0) {
			ts->dump_left--;
			dev_info(ts->dev,
				 "ev %8phN -> %s id %u %u,%u p%u\n", ev, what,
				 ev[1] >> 4,
				 ((ev[3] & 0x0f) << 8) | ev[2],
				 (ev[4] << 4) | ((ev[3] & 0xf0) >> 4), ev[5]);
		}

		fts_report_point(ts, ev, type != FTS_EV5_MT_LEAVE);
	}

	input_mt_sync_frame(ts->input);
	input_sync(ts->input);
}

/*
 * Polling instead of interrupts.
 *
 * The level-low interrupt source stops delivering after the very first
 * interrupt on this unit even though the enable register is rewritten after
 * every frame, and /proc/interrupts stays pinned at 1 while the panel is
 * being touched.  Reading the event stack on a timer is what the vendor
 * driver effectively ends up doing for events it missed, needs no IRQ
 * programming at all, and is cheap: 32 events are 256 bytes over a 250 kHz
 * bit-banged bus.
 */
static void fts_poll_work(struct work_struct *work)
{
	struct fts_data *ts = container_of(work, struct fts_data, poll_work.work);
	u8 ev[FTS_EVENT_SIZE];
	int i, ret;

	mutex_lock(&ts->lock);

	/*
	 * Read the stack one event at a time with 0x85, exactly like the
	 * vendor driver; 0x86 always came back empty on this unit.  Every raw
	 * event is logged for the first FTS_RAW_DUMP_DEFAULT frames so the
	 * real byte layout can be confirmed from the log.
	 */
	for (i = 0; i < FTS_STACK_DEPTH; i++) {
		ret = fts_xfer(ts, FTS_CMD_FIFO_READ_ONE, ev, sizeof(ev));
		if (ret) {
			if (++ts->err_count <= 5)
				dev_err(ts->dev, "event read failed: %d (%u)\n",
					ret, ts->err_count);
			break;
		}
		ts->err_count = 0;

		if (ts->dbg_polls < 6) {
			dev_info(ts->dev, "poll%u: %8phN\n",
				 ts->dbg_polls, ev);
			ts->dbg_polls++;
		}

		if (ev[0] == 0x00)
			break;

		if (ts->dump_left > 0) {
			ts->dump_left--;
			dev_info(ts->dev, "raw %8phN\n", ev);
		}
	}

	mutex_unlock(&ts->lock);

	schedule_delayed_work(&ts->poll_work, msecs_to_jiffies(FTS_POLL_MS));
}

static irqreturn_t fts_irq_thread(int irq, void *data)
{
	static const u8 ier[] = { 0xb6, 0x00, 0x2c, 0x01 };
	struct fts_data *ts = data;
	int ret;

	mutex_lock(&ts->lock);

	ret = fts_read_events(ts, ts->buf);
	if (ret) {
		/*
		 * A dead bus with a level-low interrupt means the handler would
		 * be re-entered forever.  Complain a few times, then shut the
		 * interrupt off so the log survives.
		 */
		ts->err_count++;
		if (ts->err_count <= 5)
			dev_err(ts->dev, "event read failed: %d (%u)\n",
				ret, ts->err_count);
		else if (ts->err_count == 6) {
			dev_err(ts->dev, "bus is not answering, disabling irq %d\n",
				ts->irq);
			disable_irq_nosync(ts->irq);
		}
	} else {
		ts->err_count = 0;
		fts_parse_events(ts, ts->buf);
	}

	/*
	 * The vendor driver calls fts_interrupt_enable() after draining the
	 * event stack; without this re-arm the source stays quiet after the
	 * very first interrupt (observed: /proc/interrupts stuck at 1).
	 */
	fts_send(ts, ier, sizeof(ier));

	mutex_unlock(&ts->lock);
	return IRQ_HANDLED;
}

static int fts_power_on(struct fts_data *ts)
{
	int ret;

	/* Fixed-value rails, enable only: vdd = 1.8 V, avdd = 3.3 V. */
	ret = regulator_bulk_enable(ARRAY_SIZE(ts->supplies), ts->supplies);
	if (ret) {
		dev_err(ts->dev, "failed to enable supplies: %d\n", ret);
		return ret;
	}

	/* assert reset (low), then release it (high) */
	if (ts->reset) {
		gpiod_set_value_cansleep(ts->reset, 0);
		msleep(20);
		gpiod_set_value_cansleep(ts->reset, 1);
	}
	msleep(300);

	/*
	 * Minimal bring-up: the vendor order is sleep-out while the supplies
	 * are already up, then sense-on.  Nothing else - the hardware register
	 * write (0xb6 00 2c 01) and the tuning/calibration opcodes left the
	 * controller silent here, so they stay out until the event path is
	 * proven.
	 */
	ret = fts_command(ts, FTS_CMD_SLEEP_OUT);
	dev_info(ts->dev, "sleep out: %d\n", ret);
	msleep(100);

	/*
	 * Vendor probe path: after supplying power it writes the system reset
	 * register (SYSTEM_RESET_ADDRESS = 0x0023 in ftsHardware.h) through
	 * the hardware-register window.  Without it the controller answers
	 * every command but never produces events.
	 */
	{
		u8 sysrst[] = { 0xb6, 0x00, 0x23, 0x01 };

		ret = fts_send(ts, sysrst, sizeof(sysrst));
		dev_info(ts->dev, "system reset: %d\n", ret);
		msleep(100);
	}

	/*
	 * Vendor order: system reset, then enable the interrupt source, then
	 * sense on.  IER lives at 0x002C in the hardware register window.
	 */
	{
		u8 ier[] = { 0xb6, 0x00, 0x2c, 0x01 };

		ret = fts_send(ts, ier, sizeof(ier));
		dev_info(ts->dev, "interrupt enable: %d\n", ret);
	}

	ret = fts_command(ts, FTS_CMD_MS_MT_SENSE_ON);
	dev_info(ts->dev, "sense on: %d\n", ret);
	msleep(100);

	{
		u8 ver[2];

		if (!fts_hw_read(ts, 0x000a, ver, sizeof(ver)))
			dev_info(ts->dev, "fw ver %02x%02x\n", ver[0], ver[1]);
		else
			dev_info(ts->dev, "fw ver read failed\n");
	}

	dev_info(ts->dev, "powered on\n");
	return 0;
}

/*
 * Runtime I2C poke box.
 *
 *   echo w 93            > .../cmd     write one byte
 *   echo w b6 00 2c 01   > .../cmd     write four bytes
 *   echo r 85 8          > .../cmd     write 0x85, read 8 bytes (result in dmesg)
 *
 * Lets the command sequence be worked out on the live device instead of
 * recompiling the kernel for every guess.
 */
static ssize_t fts_cmd_store(struct device *dev, struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct fts_data *ts = dev_get_drvdata(dev);
	unsigned int vals[8] = { 0 };
	u8 out[8], in[64];
	const char *p = buf;
	int nvals = 0, ret, i;
	char op;

	while (*p == ' ')
		p++;
	op = *p++;
	if (op != 'w' && op != 'W' && op != 'r' && op != 'R' &&
	    op != 'h' && op != 'H')
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
			dev_info(dev, "hw r %04x -> %d\n", vals[0], ret);
		else
			dev_info(dev, "hw r %04x len %d -> %*ph\n", vals[0],
				 rdlen, rdlen, in);
	} else {
		int rdlen = nvals > 1 ? vals[1] : 8;

		if (rdlen > (int)sizeof(in))
			rdlen = sizeof(in);
		ret = fts_xfer(ts, vals[0], in, rdlen);
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

	ts->supplies[0].supply = "vdd";		/* 1.8 V */
	ts->supplies[1].supply = "avdd";	/* 3.3 V */
	ret = devm_regulator_bulk_get(dev, ARRAY_SIZE(ts->supplies),
				      ts->supplies);
	if (ret)
		return dev_err_probe(dev, ret, "failed to get supplies\n");

	ret = fts_power_on(ts);
	if (ret)
		return ret;

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
	input_set_abs_params(ts->input, ABS_MT_PRESSURE, 0, 255, 0, 0);

	touchscreen_parse_properties(ts->input, true, &ts->prop);

	input_set_capability(ts->input, EV_KEY, BTN_TOUCH);
	__set_bit(INPUT_PROP_DIRECT, ts->input->propbit);

	ret = input_mt_init_slots(ts->input, FTS_MAX_FINGERS, INPUT_MT_DIRECT);
	if (ret)
		return dev_err_probe(dev, ret, "failed to init MT slots\n");

	ret = input_register_device(ts->input);
	if (ret)
		return dev_err_probe(dev, ret, "failed to register input\n");

	INIT_DELAYED_WORK(&ts->poll_work, fts_poll_work);
	schedule_delayed_work(&ts->poll_work, msecs_to_jiffies(200));

	device_create_file(dev, &dev_attr_cmd);

	ts->awake = true;

	dev_info(dev, "%ux%u, %d slots, irq %d\n",
		 ts->prop.max_x + 1, ts->prop.max_y + 1, FTS_MAX_FINGERS,
		 ts->irq);

	return 0;
}

static void fts_remove(struct platform_device *pdev)
{
	struct fts_data *ts = platform_get_drvdata(pdev);

	cancel_delayed_work_sync(&ts->poll_work);

	mutex_lock(&ts->lock);
	fts_command(ts, FTS_CMD_SLEEP_IN);
	mutex_unlock(&ts->lock);
}

static int fts_suspend(struct device *dev)
{
	struct fts_data *ts = dev_get_drvdata(dev);

	mutex_lock(&ts->lock);
	fts_command(ts, FTS_CMD_SLEEP_IN);
	ts->awake = false;
	mutex_unlock(&ts->lock);

	return 0;
}

static int fts_resume(struct device *dev)
{
	struct fts_data *ts = dev_get_drvdata(dev);
	int ret;

	mutex_lock(&ts->lock);
	ret = fts_power_on(ts);
	if (!ret)
		ts->awake = true;
	mutex_unlock(&ts->lock);

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
