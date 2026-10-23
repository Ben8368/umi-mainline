// SPDX-License-Identifier: GPL-2.0
/*
 * STMicroelectronics FTS touchscreen driver - Xiaomi Mi 10 (umi)
 *
 * The panel of the Mi 10 is a command-mode AMOLED and the touch controller is
 * soldered to the same flex, so the touchscreen is a separate I2C slave on
 * QUPV3 wrap1 SE5 (i2c@a94000 -> "i2c13" in mainline, vendor bus i2c-3) at
 * address 0x49.
 *
 * Protocol (verified against the vendor driver, drivers/input/touchscreen/st):
 *   - every read/write is a plain I2C transfer; a command is the first byte
 *     written, results are read back in a second (repeated start) message
 *   - the event FIFO is drained one event at a time with command 0x85; each
 *     event is exactly 8 bytes and 0x00 in byte 0 means "no more events"
 *   - byte 0 is "<class><object>": the low nibble is the object (3 = touch
 *     point, others are gestures) and the high nibble is the class
 *     (1 = enter/motion, 3 = leave).  Older ST parts use the flat codes
 *     0x03/0x04/0x05, both spellings are accepted here.
 *   - bytes 1..7 for a touch point:
 *       [1] bits 3..0 touch id, bits 7..4 number of remaining contacts
 *       [2] x >> 4          [3] y >> 4
 *       [4] bits 7..4 x & 0xf, bits 3..0 y & 0xf
 *       [5] bits 7..6 touch size, bits 4..0 major
 *       [6] minor
 *
 * The controller keeps its firmware and configuration in its own flash; MIUI
 * already programmed them ("firmware in the chip newer or equal -> no update"),
 * so this driver never writes to the flash and never loads a firmware blob.
 * It also never touches a regulator: both rails are enabled by ABL and are
 * left exactly as found.
 */

#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/input.h>
#include <linux/input/mt.h>
#include <linux/input/touchscreen.h>
#include <linux/interrupt.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/pm.h>
#include <linux/slab.h>
#include <linux/unaligned.h>

#define FTS_CMD_READ_INFO	0x80	/* 8 bytes: [0] chip ver, [2..3] fw ver,
					 * [4] cfg id, [5] cfg ver, [6..7] chip id */
#define FTS_CMD_FIFO_READ_ONE	0x85	/* read one 8 byte event */
#define FTS_CMD_FIFO_FLUSH	0xa1
#define FTS_CMD_SENSE_OFF	0x92
#define FTS_CMD_SENSE_ON	0x93

#define FTS_EVENT_SIZE		8
#define FTS_FIFO_DEPTH		64
#define FTS_MAX_FINGERS		10

/*
 * The first events after probe are logged verbatim.  That is how the class /
 * object encoding above was pinned down, and it stays useful whenever a unit
 * turns up with a different controller revision.
 */
#define FTS_RAW_DUMP_DEFAULT	96

struct fts_data {
	struct i2c_client *client;
	struct input_dev *input;
	struct gpio_desc *reset;
	struct touchscreen_properties prop;
	struct mutex lock;		/* serialises FIFO access */
	int dump_left;
	bool awake;
};

static int fts_i2c_read(struct fts_data *ts, u8 cmd, u8 *buf, int len)
{
	struct i2c_msg msgs[2] = {
		{ .addr = ts->client->addr, .flags = 0, .len = 1, .buf = &cmd },
		{ .addr = ts->client->addr, .flags = I2C_M_RD, .len = len,
		  .buf = buf },
	};
	int ret;

	ret = i2c_transfer(ts->client->adapter, msgs, ARRAY_SIZE(msgs));
	if (ret < 0)
		return ret;

	return ret == ARRAY_SIZE(msgs) ? 0 : -EIO;
}

static int fts_i2c_write(struct fts_data *ts, const u8 *buf, int len)
{
	struct i2c_msg msg = {
		.addr = ts->client->addr,
		.flags = 0,
		.len = len,
		.buf = (u8 *)buf,
	};
	int ret;

	ret = i2c_transfer(ts->client->adapter, &msg, 1);
	if (ret < 0)
		return ret;

	return ret == 1 ? 0 : -EIO;
}

static int fts_command(struct fts_data *ts, u8 cmd)
{
	return fts_i2c_write(ts, &cmd, 1);
}

static int fts_read_info(struct fts_data *ts)
{
	struct device *dev = &ts->client->dev;
	u8 info[FTS_EVENT_SIZE];
	int ret;

	ret = fts_i2c_read(ts, FTS_CMD_READ_INFO, info, sizeof(info));
	if (ret) {
		dev_warn(dev, "info read failed: %d\n", ret);
		return ret;
	}

	dev_info(dev,
		 "chip id %04x, chip ver %02x, fw ver %04x, cfg %02x/%02x\n",
		 get_unaligned_be16(&info[6]), info[0],
		 get_unaligned_be16(&info[2]), info[4], info[5]);

	return 0;
}

static void fts_report_point(struct fts_data *ts, const u8 *ev, bool down)
{
	struct input_dev *input = ts->input;
	unsigned int id = ev[1] & 0x0f;
	unsigned int count = ev[1] >> 4;
	unsigned int x = (ev[2] << 4) | ((ev[4] & 0xf0) >> 4);
	unsigned int y = (ev[3] << 4) | (ev[4] & 0x0f);

	input_mt_slot(input, id);

	if (!down) {
		input_mt_report_slot_state(input, MT_TOOL_FINGER, false);
		if (!count)
			input_report_key(input, BTN_TOUCH, 0);
		return;
	}

	input_mt_report_slot_state(input, MT_TOOL_FINGER, true);
	touchscreen_report_pos(input, &ts->prop, x, y, true);
	input_report_abs(input, ABS_MT_TOUCH_MAJOR, ev[5] & 0x1f);
	input_report_abs(input, ABS_MT_TOUCH_MINOR, ev[6]);
	input_report_abs(input, ABS_MT_PRESSURE, ev[5] & 0x1f);
	input_report_key(input, BTN_TOUCH, 1);
	input_report_key(input, BTN_TOOL_FINGER, 1);
}

static void fts_handle_event(struct fts_data *ts, const u8 *ev)
{
	u8 class = ev[0] >> 4;
	u8 object = ev[0] & 0x0f;

	/* Flat codes used by the older ST parts. */
	if (ev[0] == 0x03 || ev[0] == 0x05)
		return fts_report_point(ts, ev, true);
	if (ev[0] == 0x04)
		return fts_report_point(ts, ev, false);

	if (object != 0x03)		/* not a touch point (gesture etc.) */
		return;

	if (class == 0x01)
		fts_report_point(ts, ev, true);
	else if (class == 0x03)
		fts_report_point(ts, ev, false);
}

static irqreturn_t fts_irq_thread(int irq, void *data)
{
	struct fts_data *ts = data;
	u8 ev[FTS_EVENT_SIZE];
	int i, ret;

	mutex_lock(&ts->lock);

	for (i = 0; i < FTS_FIFO_DEPTH; i++) {
		ret = fts_i2c_read(ts, FTS_CMD_FIFO_READ_ONE, ev, sizeof(ev));
		if (ret) {
			dev_err_ratelimited(&ts->client->dev,
					    "event read failed: %d\n", ret);
			break;
		}
		if (ev[0] == 0x00)
			break;

		if (ts->dump_left > 0) {
			ts->dump_left--;
			dev_info(&ts->client->dev, "ev %8phN\n", ev);
		}

		fts_handle_event(ts, ev);
	}

	input_sync(ts->input);
	mutex_unlock(&ts->lock);

	return IRQ_HANDLED;
}

static int fts_power_on(struct fts_data *ts)
{
	struct device *dev = &ts->client->dev;

	if (ts->reset) {
		gpiod_set_value_cansleep(ts->reset, 0);
		msleep(20);
		gpiod_set_value_cansleep(ts->reset, 1);
		/*
		 * The datasheet only promises "reset time < 10 ms"; the vendor
		 * driver is even more generous and sleeps 300 ms in its power
		 * cycle path.  120 ms is comfortably inside that range.
		 */
		msleep(120);
	}

	fts_command(ts, FTS_CMD_FIFO_FLUSH);
	fts_command(ts, FTS_CMD_SENSE_ON);

	dev_info(dev, "powered on (reset %s)\n",
		 ts->reset ? "toggled" : "not wired, relying on ABL state");
	return 0;
}

static int fts_probe(struct i2c_client *client)
{
	struct device *dev = &client->dev;
	struct fts_data *ts;
	int ret;

	ts = devm_kzalloc(dev, sizeof(*ts), GFP_KERNEL);
	if (!ts)
		return -ENOMEM;

	ts->client = client;
	ts->dump_left = FTS_RAW_DUMP_DEFAULT;
	mutex_init(&ts->lock);
	i2c_set_clientdata(client, ts);

	ts->reset = devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_LOW);
	if (IS_ERR(ts->reset))
		return dev_err_probe(dev, PTR_ERR(ts->reset),
				     "failed to get reset gpio\n");

	if (client->irq <= 0)
		return dev_err_probe(dev, -ENXIO, "no interrupt assigned\n");

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
	input_set_capability(ts->input, EV_KEY, BTN_TOOL_FINGER);
	__set_bit(INPUT_PROP_DIRECT, ts->input->propbit);

	ret = input_mt_init_slots(ts->input, FTS_MAX_FINGERS, INPUT_MT_DIRECT);
	if (ret)
		return dev_err_probe(dev, ret, "failed to init MT slots\n");

	ret = input_register_device(ts->input);
	if (ret)
		return dev_err_probe(dev, ret, "failed to register input\n");

	ret = devm_request_threaded_irq(dev, client->irq, NULL, fts_irq_thread,
					IRQF_ONESHOT, "fts-umi", ts);
	if (ret)
		return dev_err_probe(dev, ret, "failed to request irq %d\n",
				     client->irq);

	/* Reading the id is a pure read; a failure is not fatal (older parts
	 * answer with 0xff) but it is the first thing worth knowing about. */
	fts_read_info(ts);

	ts->awake = true;

	dev_info(dev, "%ux%u, %d slots, irq %d\n",
		 ts->prop.max_x + 1, ts->prop.max_y + 1, FTS_MAX_FINGERS,
		 client->irq);

	return 0;
}

static void fts_remove(struct i2c_client *client)
{
	struct fts_data *ts = i2c_get_clientdata(client);

	mutex_lock(&ts->lock);
	fts_command(ts, FTS_CMD_SENSE_OFF);
	mutex_unlock(&ts->lock);
}

static int fts_suspend(struct device *dev)
{
	struct fts_data *ts = dev_get_drvdata(dev);

	mutex_lock(&ts->lock);
	fts_command(ts, FTS_CMD_SENSE_OFF);
	ts->awake = false;
	mutex_unlock(&ts->lock);

	return 0;
}

static int fts_resume(struct device *dev)
{
	struct fts_data *ts = dev_get_drvdata(dev);

	mutex_lock(&ts->lock);
	fts_power_on(ts);
	ts->awake = true;
	mutex_unlock(&ts->lock);

	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(fts_pm_ops, fts_suspend, fts_resume);

static const struct of_device_id fts_of_match[] = {
	{ .compatible = "st,fts-umi" },
	{ .compatible = "st,fts" },
	{ }
};
MODULE_DEVICE_TABLE(of, fts_of_match);

static const struct i2c_device_id fts_i2c_id[] = {
	{ "fts-umi" },
	{ }
};
MODULE_DEVICE_TABLE(i2c, fts_i2c_id);

static struct i2c_driver fts_driver = {
	.driver = {
		.name = "fts-umi",
		.of_match_table = fts_of_match,
		.pm = pm_sleep_ptr(&fts_pm_ops),
	},
	.probe = fts_probe,
	.remove = fts_remove,
	.id_table = fts_i2c_id,
};
module_i2c_driver(fts_driver);

MODULE_DESCRIPTION("STMicroelectronics FTS touchscreen for Xiaomi Mi 10 (umi)");
MODULE_LICENSE("GPL");
