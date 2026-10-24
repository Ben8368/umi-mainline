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
#include <linux/math64.h>
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
#define FTS_CMD_FRAMEBUFFER	0xa6	/* + 16 bit address, then a read */

#define FTS_FEAT_GESTURE	0x03

#define FTS_CMD_SYSTEM		0xa4
#define FTS_SYS_CMD_SPECIAL	0x00
/*
 * 0x01 is SYS_CMD_INT (FW interrupt control), not load data.  The vendor
 * driver never sends it and neither should this one: every request built
 * around "0xA4 01 30" was addressed to the interrupt-control command, which
 * is why the frame counter never moved.
 */
#define FTS_SYS_CMD_INT		0x01
#define FTS_SYS_CMD_FORCE_CAL	0x02
#define FTS_SYS_CMD_CX_TUNING	0x03
#define FTS_SYS_CMD_LOAD_DATA	0x06	/* + one byte of load type */
#define FTS_SYS_CMD_SPECIAL_TUNING	0x08	/* + two byte option */
#define FTS_SPECIAL_FIFO_FLUSH	0x01
#define FTS_SPECIAL_PANEL_INIT	0x02
#define FTS_SPECIAL_FULL_INIT	0x03

/*
 * Options for FTS_SYS_CMD_SPECIAL_TUNING.  0x02 is SPECIAL_TUNING_IOFF, the
 * per channel input offset trim of the analog front end.
 *
 * The vendor runs it in front of every raw frame dump (production_test_ito(),
 * fts_mutual_raw_ito_show(), hover autotune) but never on the normal boot path,
 * because a controller whose compensation is intact does not need it.  This
 * unit reads -13462 on every single mutual node and the FW itself flags that as
 * FORCE_CAL / 0x01 "mutual negative detect", which is what a missing or
 * mismatched offset trim looks like.
 *
 * This is an internal DAC calibration, not a supply setting: no rail, current
 * limit or OPP is touched.  The result lives in RAM only - nothing is saved to
 * the controller flash - so a power cycle throws it away again.
 */
#define FTS_TUNING_IOFF		0x02

/*
 * Load types for FTS_SYS_CMD_LOAD_DATA (ftsSoftware.h load_opt).  This is a
 * separate namespace from FTS_SYS_CMD_*: 0x30 is a raw frame, but 0x01 is
 * LOAD_SYS_INFO and only means anything after the 0x06 selector.
 */
#define FTS_LOAD_SYS_INFO	0x01
#define FTS_LOAD_SYNC_FRAME_RAW	0x30
#define FTS_LOAD_SYNC_FRAME_FLT	0x31
#define FTS_LOAD_SYNC_FRAME_BASE 0x32
#define FTS_LOAD_SYNC_FRAME_STR	0x33

/*
 * The framebuffer lives at address 0 of the *16 bit* address space and is
 * read with 0xA6.  That is a different address width from the 0xFA register
 * window above - handing a 32 bit address to 0xA6 shifts every byte and
 * quietly returns something that still looks like a valid header.
 *
 * Every payload starts with 4 bytes { 0xA5, <load type>, count lo, count hi }.
 */
#define FTS_FB_ADDR		0x0000
#define FTS_FB_SIGNATURE	0xa5
#define FTS_FB_HEADER_SIZE	4
#define FTS_SYS_INFO_SIZE	208	/* vendor SYS_INFO_SIZE */
#define FTS_TIMEOUT_REQU_DATA	200	/* ms, vendor TIMEOUT_REQU_DATA */

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
#define FTS_I2C_DELAY_US	4	/* ~100 kHz on the bit-banged bus */
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
	bool dbg;		/* log every event, not just the boot budget */
	unsigned int err_count;
	u8 buf[FTS_DATA_SIZE];
	struct delayed_work poll_work;
	bool powered;
	bool scanning;
	bool irq_on;
	bool awake;
	/* panel geometry and frame addresses, filled in from the FW sys info */
	u16 tx;
	u16 rx;
	u16 raw_addr;
	u16 filt_addr;
	u16 str_addr;
	u16 base_addr;
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

/* { 0xA6, ah, al } then a read: the framebuffer address is 16 bit wide */
static int fts_fb_read(struct fts_data *ts, u16 addr, u8 *buf, int len)
{
	u8 out[3] = { FTS_CMD_FRAMEBUFFER, (addr >> 8) & 0xff, addr & 0xff };

	return fts_xfer_n(ts, out, sizeof(out), buf, len);
}

/*
 * requestSyncFrame() from the vendor library.
 *
 * The FW does not answer a frame request with an event, it fills a buffer in
 * its own memory and bumps a counter.  The handshake is therefore: read the
 * counter, ask for the frame, then poll until the counter changes.  A frame
 * counter that never moves is the only direct evidence available from the
 * host side that the analog front end is not sampling.
 *
 * Returns the new counter on success or a negative errno; *changed tells
 * whether the counter actually moved.
 */
static int fts_request_frame(struct fts_data *ts, u8 type, bool *changed)
{
	u8 hdr[FTS_FB_HEADER_SIZE] = { 0 };
	u8 req[3] = { FTS_CMD_SYSTEM, FTS_SYS_CMD_LOAD_DATA, type };
	int ret, i, base, now;
	bool moved = false;

	*changed = false;

	ret = fts_fb_read(ts, FTS_FB_ADDR, hdr, sizeof(hdr));
	if (ret)
		return ret;
	if (hdr[0] != FTS_FB_SIGNATURE)
		return -EIO;

	base = hdr[2] | (hdr[3] << 8);

	ret = fts_send(ts, req, sizeof(req));
	if (ret)
		return ret;

	now = base;
	for (i = 0; i < FTS_TIMEOUT_REQU_DATA / 2; i++) {
		msleep(2);
		ret = fts_fb_read(ts, FTS_FB_ADDR, hdr, sizeof(hdr));
		if (ret)
			return ret;
		if (hdr[0] != FTS_FB_SIGNATURE)
			continue;
		now = hdr[2] | (hdr[3] << 8);
		if (now != base) {
			moved = true;
			break;
		}
	}

	*changed = moved;
	dev_info(ts->dev, "frame %02x: count %d -> %d (%s) hdr %*ph\n",
		 type, base, now, moved ? "moved" : "stuck",
		 (int)sizeof(hdr), hdr);

	return 0;
}

/*
 * readSysInfo(0): after a reset the FW leaves its system info in the
 * framebuffer, so this doubles as a check that the 16 bit address path is
 * the right one.  The layout is the vendor's, parsed out of readSysInfo():
 *
 *     [ 4.. ] api, chip ids, fw/svn/cfg/cx versions, AFE versions
 *     [ 80 ] screen resolution, then TX/RX lengths
 *     [136 ] address of the raw frame inside the framebuffer
 *
 * The TX/RX lengths matter: they are the panel geometry the FW uses to turn
 * sampled nodes into touch points.  If they read back as 0 the controller
 * samples happily and can hand out frames all day, but it can never find a
 * finger on them - which is precisely what this unit was doing.
 */
static void fts_read_sysinfo(struct fts_data *ts)
{
	u8 d[FTS_SYS_INFO_SIZE];
	int ret;

	ret = fts_fb_read(ts, FTS_FB_ADDR, d, sizeof(d));
	if (ret) {
		dev_info(ts->dev, "sysinfo read failed: %d\n", ret);
		return;
	}

	if (d[0] != FTS_FB_SIGNATURE) {
		dev_info(ts->dev, "sysinfo bad signature %02x\n", d[0]);
		return;
	}

	dev_info(ts->dev,
		 "sysinfo count %u fw %04x cfg %04x cx %04x afe %02x/%02x/%02x\n",
		 d[2] | (d[3] << 8), d[16] | (d[17] << 8),
		 d[22] | (d[23] << 8), d[24] | (d[25] << 8),
		 d[28], d[29], d[30]);

	ts->tx = d[84];
	ts->rx = d[85];
	ts->raw_addr = d[136] | (d[137] << 8);
	ts->filt_addr = d[138] | (d[139] << 8);
	ts->str_addr = d[140] | (d[141] << 8);
	ts->base_addr = d[142] | (d[143] << 8);

	dev_info(ts->dev,
		 "sysinfo res %ux%u tx %u rx %u key %u force %u protocol %02x\n",
		 d[80] | (d[81] << 8), d[82] | (d[83] << 8),
		 d[84], d[85], d[86], d[87], d[31]);

	dev_info(ts->dev,
		 "sysinfo frames raw@%04x flt@%04x str@%04x base@%04x\n",
		 ts->raw_addr, ts->filt_addr, ts->str_addr, ts->base_addr);
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

/*
 * production_test_initialization(SPECIAL_PANEL_INIT) from the vendor library.
 * The whole function is three calls:
 *
 *     fts_system_reset();
 *     writeSysCmd(SYS_CMD_SPECIAL, { 0x02 }, 1);   // A4 00 02
 *     readSysInfo(1);                             // A4 06 01, then read back
 *
 * The two steps around the command are the point, and they are exactly what
 * the earlier hand pokes left out.  Without the reset in front the FW is not
 * in a state where it takes a panel init, and without readSysInfo(1) there is
 * no receipt: the AFE versions in the system info are what tells us whether
 * the panel area was actually reloaded.
 *
 * Why it is needed at all: the system info of this unit reads
 *
 *     cfgAfeVer = 0x00    cxAfeVer = 0x05    panelCfgAfeVer = 0x05
 *
 * and the vendor driver turns exactly that mismatch into init_type =
 * SPECIAL_PANEL_INIT.  A controller whose panel area is not the one its
 * configuration expects never brings the analog front end up, which is why no
 * amount of scan-mode juggling ever produced a touch event.
 */
static int fts_panel_init(struct fts_data *ts, u8 type)
{
	u8 cmd[3] = { FTS_CMD_SYSTEM, FTS_SYS_CMD_SPECIAL, type };
	u8 req[3] = { FTS_CMD_SYSTEM, FTS_SYS_CMD_LOAD_DATA, FTS_LOAD_SYS_INFO };
	u8 ev[FTS_EVENT_SIZE];
	int ret, i, ready = 0;

	/* 1. fts_system_reset(): toggle reset, then wait for the 0x03 event */
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
	dev_info(ts->dev, "panel init: controller %s after %d ms\n",
		 ready ? "ready" : "NOT ready", i * 10);

	/* 2. A4 00 <type> */
	ret = fts_send(ts, cmd, sizeof(cmd));
	dev_info(ts->dev, "panel init %02x: A4 00 %02x -> %d\n", type, type, ret);
	if (ret)
		return ret;

	/* the FW needs a moment to finish the reload before it answers */
	msleep(100);

	/* 3. readSysInfo(1) */
	ret = fts_send(ts, req, sizeof(req));
	dev_info(ts->dev, "panel init: A4 06 01 -> %d\n", ret);
	if (ret)
		return ret;

	msleep(100);
	fts_read_sysinfo(ts);

	/* IER is left alone here too, same as everywhere else in this driver */
	return 0;
}

/*
 * SPECIAL_TUNING_IOFF - trim the analog front end input offset.
 *
 * The vendor's own frame dump helpers all start with this, and then read a raw
 * frame whose nodes differ from each other.  Ours come back as one repeated
 * value, which is the difference this call is meant to make.
 */
static int fts_ioff_trim(struct fts_data *ts)
{
	u8 cmd[4] = { FTS_CMD_SYSTEM, FTS_SYS_CMD_SPECIAL_TUNING,
		      FTS_TUNING_IOFF, 0x00 };
	int ret;

	ret = fts_send(ts, cmd, sizeof(cmd));
	dev_info(ts->dev, "ioff trim: A4 08 02 00 -> %d\n", ret);
	if (!ret)
		msleep(100);

	return ret;
}

/*
 * The gesture feature the vendor writes right after sense on:
 *
 *     u8 gesture_cmd[6] = { 0xA2, 0x03, 0x00, 0x00, 0x00, 0x03 };
 *     setScanMode(SCAN_MODE_ACTIVE, 0x01);
 *     fts_write_dma_safe(gesture_cmd, 6);
 *
 * i.e. FTS_CMD_FEATURE, FEAT_SEL_GESTURE, four bytes of gesture mask.  Earlier
 * builds sent it too, but always together with the interrupt-enable writes
 * that were flooding the FW, so the combination has not been measured on its
 * own yet.
 */
static int fts_gesture_on(struct fts_data *ts)
{
	u8 cmd[6] = { FTS_CMD_FEATURE, FTS_FEAT_GESTURE, 0x00, 0x00, 0x00, 0x03 };
	int ret;

	ret = fts_send(ts, cmd, sizeof(cmd));
	dev_info(ts->dev, "gesture feature: A2 03 00 00 00 03 -> %d\n", ret);

	return ret;
}

/* the framebuffer read is a repeated start per chunk, like READ_CHUNK does */
static int fts_fb_read_chunks(struct fts_data *ts, u16 addr, u8 *buf, int len)
{
	int done = 0, ret;

	while (done < len) {
		int chunk = min(len - done, 256);

		ret = fts_fb_read(ts, addr + done, buf + done, chunk);
		if (ret)
			return ret;
		done += chunk;
	}

	return 0;
}

/*
 * Print one mutual frame as min / max / average plus its first samples.
 *
 * A live capacitance matrix never has min == max: every node sits at its own
 * offset.  One repeated value over all 629 nodes is the signature of a frame
 * that nothing sampled, and that is the whole question this attribute answers.
 */
static void fts_frame_stats(struct fts_data *ts, const char *name, u16 addr,
			    int nodes)
{
	char head[80];
	int i, ret, off = 0;
	s16 v, lo = 32767, hi = -32768;
	s64 sum = 0;
	u8 *buf;

	if (!nodes || !addr)
		return;

	buf = kzalloc(nodes * 2, GFP_KERNEL);
	if (!buf)
		return;

	ret = fts_fb_read_chunks(ts, addr, buf, nodes * 2);
	if (ret) {
		dev_info(ts->dev, "%s @%04x read failed %d\n", name, addr, ret);
		kfree(buf);
		return;
	}

	for (i = 0; i < nodes; i++) {
		v = (s16)(buf[i * 2] | (buf[i * 2 + 1] << 8));
		if (v < lo)
			lo = v;
		if (v > hi)
			hi = v;
		sum += v;
		if (i < 8)
			off += scnprintf(head + off, sizeof(head) - off, " %d",
					 v);
	}

	dev_info(ts->dev, "%s @%04x n %d min %d max %d avg %lld head%s\n",
		 name, addr, nodes, lo, hi, div_s64(sum, nodes), head);
	kfree(buf);
}

/*
 * Read the raw, filter and baseline frames the way the vendor does it: sense
 * off, wait WAIT_AFTER_SENSEOFF, flush the FIFO, then read the memory.
 *
 * This is the one thing the earlier builds got wrong: they asked for a sync
 * frame while the scan was running.  The FW then does answer with a counter
 * bump, but the frame buffer it hands out is not the fresh matrix.
 */
static ssize_t fts_raw_store(struct device *dev, struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct fts_data *ts = dev_get_drvdata(dev);
	int nodes = ts->tx * ts->rx;
	bool resume;

	mutex_lock(&ts->lock);

	resume = ts->scanning;
	if (resume) {
		fts_set_scan_mode(ts, FTS_SCAN_MODE_ACTIVE, 0x00);
		msleep(50);	/* WAIT_AFTER_SENSEOFF */
		fts_flush_fifo(ts);
	}

	fts_frame_stats(ts, "raw", ts->raw_addr, nodes);
	fts_frame_stats(ts, "flt", ts->filt_addr, nodes);
	fts_frame_stats(ts, "base", ts->base_addr, nodes);

	if (resume)
		fts_set_scan_mode(ts, FTS_SCAN_MODE_ACTIVE, FTS_SCAN_MT);

	mutex_unlock(&ts->lock);

	return count;
}
static DEVICE_ATTR(raw, 0200, NULL, fts_raw_store);

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
		if (ts->dbg || ts->dump_left > 0) {
			if (ts->dump_left > 0)
				ts->dump_left--;
			dev_info(ts->dev, "ev %8phN\n", ev);
		}
		return;
	}

	if (ts->dbg || ts->dump_left > 0) {
		if (ts->dump_left > 0)
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

		if (ts->dbg || ts->dbg_polls < 4) {
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
	 * No IER write here either.  Reading the FIFO is the acknowledgement;
	 * the FW maintains IER itself.
	 */

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

	/*
	 * The vendor driver does not stop at enabling the rails, it also calls
	 * regulator_set_load() on both of them (62000 uA on avdd, 20000 uA on
	 * vdd).  On Qualcomm that is a vote that moves the regulator out of its
	 * low power mode, so regulator_set_mode(FAST) is the closest mainline
	 * equivalent - but it does not work here and is kept only as a record:
	 *
	 *     vdd  (pm8150c L1)  -> -EPERM   mode changes not permitted
	 *     avdd (fixed 3.3 V) -> -EINVAL  no mode support at all
	 *
	 * Neither error is fatal, the rails stay enabled.  Frame count still
	 * never moves, so this was not what kept the AFE from sampling.
	 * No voltage is programmed here.
	 */
	regulator_set_mode(ts->supplies[1].consumer, REGULATOR_MODE_FAST);
	regulator_set_mode(ts->supplies[0].consumer, REGULATOR_MODE_FAST);

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

	/*
	 * Deliberately NOT reading the system info here.
	 *
	 * The 64 byte framebuffer read was the only difference between the
	 * "echo 1" that blacked the panel on p60 and the p49..p52 builds that
	 * stayed alive, so it is kept out of the plain power-on path.  It is
	 * still available where it is actually needed: at the end of the panel
	 * init, as the receipt for whether the panel area was reloaded.
	 */

	/*
	 * IER is deliberately NOT written here.
	 *
	 * The vendor driver never writes it either - fts_enableInterrupt() only
	 * enables the Linux irq.  0x41 looked like an "enable value" purely
	 * because this driver wrote it first: a freshly reset chip reads back
	 * 0x40, every write of 0x41 is immediately overwritten by the FW, and
	 * the write keeps the interrupt line asserted.  With the AFE running
	 * that turned into a self sustaining storm - 1370 interrupts a second
	 * with an empty FIFO behind them.
	 */

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
 * (vendor name disp_vddio_vreg).  The armed/dead distinction is therefore
 * exposed through "enable" instead of being guessed at with one reflash per
 * attempt:
 *
 *   echo 0 > .../enable    controller unpowered (the p43 state, panel safe)
 *   echo 1 > .../enable    controller powered and handshaked, sensing off
 *   echo 2 > .../enable    sensing on, events and input reporting active
 *   echo 3 > .../enable    panel init        (A4 00 02), then sensing on
 *   echo 4 > .../enable    full panel init   (A4 00 03), then sensing on
 */

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
	/*
	 * Vendor senseOff()/senseOn(): both are SCAN_MODE_ACTIVE, only the mask
	 * changes.  Using SCAN_MODE_LOW_POWER for the "off" half switches the
	 * controller onto the self capacitance path, which runs on a different
	 * set of Cx data (LOAD_CX_SS_TOUCH_IDLE); coming back with a bare
	 * 0xA0 00 01 does not swap that data back.  The AFE then samples the
	 * mutual channels against the wrong baseline and reports
	 * EVT_TYPE_STATUS_FORCE_CAL / subtype 0x01 "mutual negative detect"
	 * over and over - exactly what this unit started doing right after the
	 * first panel init.
	 */
	ret = fts_set_scan_mode(ts, FTS_SCAN_MODE_ACTIVE, 0x00);
	if (ret)
		return ret;
	msleep(50);	/* WAIT_AFTER_SENSEOFF */

	ret = fts_set_scan_mode(ts, FTS_SCAN_MODE_ACTIVE, FTS_SCAN_MT);
	if (ret)
		return ret;

	/*
	 * ★ No gesture write here.
	 *
	 * The vendor sends A2 03 00 00 00 03 right after turning sensing on,
	 * but on this unit that write knocks the scan back down: measured on
	 * the register at 0x2000004a,
	 *
	 *     A0 00 00 -> A0 00 01 alone        0x2000004a = 0x50  (scanning)
	 *     A0 00 00 -> A0 00 01 -> A2 03 ... 0x2000004a = 0x00  (stopped)
	 *     then A0 00 01 again by hand       0x2000004a = 0x50  (scanning)
	 *
	 * so the scan command is fine and the gesture feature write is what
	 * turns it back off.  Gestures are not supported by this driver yet,
	 * so dropping the write costs nothing and keeps the controller in the
	 * only state that can produce touch events.
	 */
	dev_info(ts->dev, "scan on\n");

	return 0;
}

static void fts_power_off(struct fts_data *ts)
{
	if (ts->scanning) {
		fts_set_scan_mode(ts, FTS_SCAN_MODE_ACTIVE, 0x00);
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
	 * 0xA4 00 02 survived the write, came back with the echo event, and
	 * left the command mode AMOLED dark until reboot.  The controller
	 * drives the panel flex, so nothing here may touch the panel init or
	 * the calibration path.
	 *
	 * Note what the selector byte actually means: it is NOT load-data for
	 * 0x01.  The vendor map is 0x00 special, 0x01 FW interrupt control,
	 * 0x02 force cal, 0x03 CX tuning, 0x06 load data.  Every early build
	 * that asked for a raw frame with "0xA4 01 30" was therefore sending
	 * an interrupt-control command with payload 0x30 - that is the build
	 * (p53) that first left the panel black, not the scan-mode cycling it
	 * was blamed on at the time.
	 *
	 * A real frame request is 0xA4 06 <load type>; it only asks the FW to
	 * fill a memory buffer and is allowed here.
	 */
	if ((op == 'w' || op == 'W' || op == 'x' || op == 'X') &&
	    vals[0] == FTS_CMD_SYSTEM &&
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

	if (sscanf(buf, "%d", &val) != 1 || val < 0 || val > 6)
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
	case 3:
		if (!ts->powered)
			ret = fts_power_on(ts);
		if (!ret)
			ret = fts_panel_init(ts, FTS_SPECIAL_PANEL_INIT);
		if (!ret)
			ret = fts_start_scan(ts);
		if (!ret) {
			ts->scanning = true;
			ts->awake = true;
			kick = true;
		}
		dev_info(dev, "enable 3: panel init + scanning %s\n",
			 ret ? "FAILED" : "ok");
		break;
	case 4:
		if (!ts->powered)
			ret = fts_power_on(ts);
		if (!ret)
			ret = fts_panel_init(ts, FTS_SPECIAL_FULL_INIT);
		if (!ret)
			ret = fts_start_scan(ts);
		if (!ret) {
			ts->scanning = true;
			ts->awake = true;
			kick = true;
		}
		dev_info(dev, "enable 4: full panel init + scanning %s\n",
			 ret ? "FAILED" : "ok");
		break;
	case 5:
		if (!ts->powered)
			ret = fts_power_on(ts);
		if (!ret)
			ret = fts_panel_init(ts, FTS_SPECIAL_FULL_INIT);
		if (!ret)
			ret = fts_ioff_trim(ts);
		if (!ret)
			ret = fts_start_scan(ts);
		if (!ret) {
			ts->scanning = true;
			ts->awake = true;
			kick = true;
		}
		dev_info(dev, "enable 5: full init + ioff trim + scanning %s\n",
			 ret ? "FAILED" : "ok");
		break;
	case 6:
		if (!ts->powered)
			ret = fts_power_on(ts);
		if (!ret)
			ret = fts_panel_init(ts, FTS_SPECIAL_FULL_INIT);
		if (!ret)
			ret = fts_ioff_trim(ts);
		if (!ret)
			ret = fts_start_scan(ts);
		if (!ret)
			ret = fts_gesture_on(ts);
		if (!ret) {
			ts->scanning = true;
			ts->awake = true;
			kick = true;
		}
		dev_info(dev, "enable 6: full init + ioff + gesture + scan %s\n",
			 ret ? "FAILED" : "ok");
		break;
	}

	mutex_unlock(&ts->lock);

	/*
	 * Interrupt only - do NOT schedule the poll work as well.
	 *
	 * The two readers steal from each other.  A batch read takes the number
	 * of queued events from byte 7 of the first event and then collects
	 * that many more, so a second reader stepping in between the two
	 * transfers splits the batch and both handlers act on half an event
	 * stream.  While the AFE was down this never mattered because there was
	 * nothing to read; now that it samples, it is the difference between
	 * working touch and a console that crawls.
	 */
	if (kick) {
		enable_irq(ts->irq);
		ts->irq_on = true;
	}

	return ret ? ret : count;
}
static DEVICE_ATTR(enable, 0200, NULL, fts_enable_store);

/*
 * Runtime frame probe - the only host-side measurement of whether the analog
 * front end is sampling at all.
 *
 * A touch event only reaches the FIFO when the FW decides that a finger
 * arrived, so "no ENTER event" says nothing about the AFE.  A frame request
 * does: if the frame counter moves, the AFE produced a frame; if it stays
 * put, nothing sampled the panel.
 *
 *   echo 30 > .../frame    raw frame      (LOAD_SYNC_FRAME_RAW)
 *   echo 31 > .../frame    filter frame   (LOAD_SYNC_FRAME_FILTER)
 *   echo 32 > .../frame    baseline frame (LOAD_SYNC_FRAME_BASELINE)
 *   echo 33 > .../frame    strength frame (LOAD_SYNC_FRAME_STRENGTH)
 *
 * The vendor waits WAIT_AFTER_SENSEOFF (50 ms) after stopping sensing before
 * a frame may be read out of the controller memory.
 */
static ssize_t fts_frame_store(struct device *dev,
			       struct device_attribute *attr,
			       const char *buf, size_t count)
{
	struct fts_data *ts = dev_get_drvdata(dev);
	unsigned int type;
	bool moved;
	int ret;

	if (sscanf(buf, "%x", &type) != 1)
		return -EINVAL;

	mutex_lock(&ts->lock);
	ret = fts_request_frame(ts, type, &moved);
	mutex_unlock(&ts->lock);

	if (ret)
		return ret;

	return count;
}
static DEVICE_ATTR(frame, 0200, NULL, fts_frame_store);

/*
 * Event logging switch.
 *
 * The boot-time budget (48 events, 4 poll samples) exists so a controller that
 * misbehaves cannot flood the console, but it is spent long before the
 * interesting part happens: the AFE only comes up after the panel init, and by
 * then nothing is printed any more.
 *
 *   echo 1 > dbg    print every event the FW hands over
 *   echo 0 > dbg    back to quiet
 */
static ssize_t fts_dbg_store(struct device *dev, struct device_attribute *attr,
			     const char *buf, size_t count)
{
	struct fts_data *ts = dev_get_drvdata(dev);
	int v;

	if (sscanf(buf, "%d", &v) != 1)
		return -EINVAL;

	ts->dbg = v != 0;
	if (ts->dbg) {
		ts->dump_left = 1 << 20;
		ts->dbg_polls = 0;
	}
	dev_info(dev, "dbg %d\n", ts->dbg ? 1 : 0);

	return count;
}
static DEVICE_ATTR(dbg, 0200, NULL, fts_dbg_store);

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
	device_create_file(dev, &dev_attr_frame);
	device_create_file(dev, &dev_attr_dbg);
	device_create_file(dev, &dev_attr_raw);

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
		fts_set_scan_mode(ts, FTS_SCAN_MODE_ACTIVE, 0x00);
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
