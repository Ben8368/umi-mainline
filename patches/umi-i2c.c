// SPDX-License-Identifier: GPL-2.0
/*
 * umi-i2c - bit-banged I2C adapter for the Xiaomi Mi 10 (umi) touch bus
 *
 * The touch controller hangs on the two wires QUPV3 wrap1 SE5 (0xa94000) also
 * claims, but that SE has its FIFO interface disabled (GENI_IF_DISABLE_RO), so
 * mainline geni-i2c needs GPI DMA and GPI never answers EV ALLOCATE on this
 * board.  i2c-gpio also fails: its open drain path wants native open drain
 * support that pinctrl-msm does not provide, and every transfer came back
 * -ENXIO.  A plain bit-banged master with explicit direction switching works
 * (a bus scan settled the pad order: gpio36 is SDA, gpio37 is SCL).
 *
 * Why an i2c_adapter and not a private bus: the reference driver for this
 * controller family (drivers/input/touchscreen/fts521) is a normal i2c_driver
 * and only talks to the chip through i2c_transfer().  Exposing the bus as a
 * real adapter means that driver, and anything else that ends up on these two
 * wires, can just probe.
 *
 * Device tree:
 *
 *     i2c_touch: i2c-touch {
 *             compatible = "umi,i2c-bitbang";
 *             sda-gpios = <&tlmm 36 GPIO_ACTIVE_HIGH>;
 *             scl-gpios = <&tlmm 37 GPIO_ACTIVE_HIGH>;
 *             clock-frequency = <400000>;
 *             #address-cells = <1>;
 *             #size-cells = <0>;
 *             touchscreen@49 { compatible = "st,fts"; reg = <0x49>; ... };
 *     };
 */

#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/slab.h>

/*
 * 4 us per half period is a bit under 100 kHz after the GPIO calls.  Slower
 * than the controller can do, but the touch firmware has no minimum and a
 * timing budget that is easy to reason about matters more than throughput.
 */
#define UMI_I2C_DELAY_US	4

struct umi_i2c {
	struct device *dev;
	struct gpio_desc *sda;
	struct gpio_desc *scl;
	struct i2c_adapter adap;
	struct mutex lock;	/* one master, one transfer at a time */
};

static inline void umi_sda_low(struct umi_i2c *u)
{
	gpiod_direction_output(u->sda, 0);
}

static inline void umi_sda_release(struct umi_i2c *u)
{
	gpiod_direction_input(u->sda);
}

static inline void umi_scl_low(struct umi_i2c *u)
{
	gpiod_direction_output(u->scl, 0);
}

static inline void umi_scl_release(struct umi_i2c *u)
{
	gpiod_direction_input(u->scl);
}

/* SCL high while SDA goes high -> low: a start condition */
static void umi_start(struct umi_i2c *u)
{
	umi_sda_release(u);
	umi_scl_release(u);
	udelay(UMI_I2C_DELAY_US);
	umi_sda_low(u);
	udelay(UMI_I2C_DELAY_US);
	umi_scl_low(u);
	udelay(UMI_I2C_DELAY_US);
}

static void umi_stop(struct umi_i2c *u)
{
	umi_sda_low(u);
	udelay(UMI_I2C_DELAY_US);
	umi_scl_release(u);
	udelay(UMI_I2C_DELAY_US);
	umi_sda_release(u);
	udelay(UMI_I2C_DELAY_US);
}

/* returns 0 on ACK, -ENXIO on NACK */
static int umi_write_byte(struct umi_i2c *u, u8 byte)
{
	int i, ret = 0;

	for (i = 7; i >= 0; i--) {
		if (byte & (1 << i))
			umi_sda_release(u);
		else
			umi_sda_low(u);
		udelay(UMI_I2C_DELAY_US);
		umi_scl_release(u);
		udelay(UMI_I2C_DELAY_US);
		umi_scl_low(u);
		udelay(UMI_I2C_DELAY_US);
	}

	/* release SDA and clock the ninth bit in */
	umi_sda_release(u);
	udelay(UMI_I2C_DELAY_US);
	umi_scl_release(u);
	udelay(UMI_I2C_DELAY_US);
	if (gpiod_get_value(u->sda))
		ret = -ENXIO;	/* NACK */
	umi_scl_low(u);
	udelay(UMI_I2C_DELAY_US);

	return ret;
}

static u8 umi_read_byte(struct umi_i2c *u, bool ack)
{
	u8 byte = 0;
	int i;

	umi_sda_release(u);
	for (i = 7; i >= 0; i--) {
		udelay(UMI_I2C_DELAY_US);
		umi_scl_release(u);
		udelay(UMI_I2C_DELAY_US);
		if (gpiod_get_value(u->sda))
			byte |= (1 << i);
		umi_scl_low(u);
	}

	/* drive ACK for all but the last byte of a read */
	if (ack)
		umi_sda_low(u);
	else
		umi_sda_release(u);
	udelay(UMI_I2C_DELAY_US);
	umi_scl_release(u);
	udelay(UMI_I2C_DELAY_US);
	umi_scl_low(u);
	udelay(UMI_I2C_DELAY_US);
	umi_sda_release(u);

	return byte;
}

static int umi_xfer_msg(struct umi_i2c *u, struct i2c_msg *msg)
{
	int i, ret = 0;

	/*
	 * ★ No start and no stop here.
	 *
	 * The controller is spoken to with the "address write, then payload
	 * read" shape, and on the vendor stack that is one i2c_transfer() with
	 * two messages, i.e. a repeated start between them and a single stop at
	 * the end.  Putting a stop in between makes the chip forget the
	 * command it just received: the first attempt at this read back
	 * FF FF FF FF for the chip id.
	 */
	if (msg->flags & I2C_M_RD) {
		ret = umi_write_byte(u, (msg->addr << 1) | 1);
		if (ret)
			return ret;

		for (i = 0; i < msg->len; i++)
			msg->buf[i] = umi_read_byte(u, i < msg->len - 1);
	} else {
		ret = umi_write_byte(u, msg->addr << 1);
		if (ret)
			return ret;

		for (i = 0; i < msg->len && !ret; i++)
			ret = umi_write_byte(u, msg->buf[i]);
	}

	return ret;
}

static int umi_i2c_xfer(struct i2c_adapter *adap, struct i2c_msg *msgs, int num)
{
	struct umi_i2c *u = i2c_get_adapdata(adap);
	int i, ret = 0;

	if (num < 1)
		return -EINVAL;

	mutex_lock(&u->lock);

	umi_start(u);
	for (i = 0; i < num && !ret; i++) {
		/* a start between messages is the repeated start the chip wants */
		if (i)
			umi_start(u);
		ret = umi_xfer_msg(u, &msgs[i]);
	}
	umi_stop(u);

	mutex_unlock(&u->lock);

	return ret ? ret : num;
}

static u32 umi_i2c_func(struct i2c_adapter *adap)
{
	return I2C_FUNC_I2C | I2C_FUNC_SMBUS_EMUL;
}

static const struct i2c_algorithm umi_i2c_algo = {
	.master_xfer	= umi_i2c_xfer,
	.functionality	= umi_i2c_func,
};

static void umi_i2c_set_idle(struct umi_i2c *u)
{
	umi_sda_release(u);
	umi_scl_release(u);
}

static int umi_i2c_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct umi_i2c *u;
	u32 freq = 0;
	int ret;

	u = devm_kzalloc(dev, sizeof(*u), GFP_KERNEL);
	if (!u)
		return -ENOMEM;

	u->dev = dev;

	u->sda = devm_gpiod_get(dev, "sda", GPIOD_OUT_HIGH);
	if (IS_ERR(u->sda))
		return dev_err_probe(dev, PTR_ERR(u->sda), "no sda gpio\n");

	u->scl = devm_gpiod_get(dev, "scl", GPIOD_OUT_HIGH);
	if (IS_ERR(u->scl))
		return dev_err_probe(dev, PTR_ERR(u->scl), "no scl gpio\n");

	umi_i2c_set_idle(u);

	mutex_init(&u->lock);

	of_property_read_u32(dev->of_node, "clock-frequency", &freq);

	u->adap.owner = THIS_MODULE;
	u->adap.algo = &umi_i2c_algo;
	u->adap.dev.parent = dev;
	u->adap.dev.of_node = dev->of_node;
	u->adap.nr = -1;
	snprintf(u->adap.name, sizeof(u->adap.name), "umi-dsi-touch-i2c");
	i2c_set_adapdata(&u->adap, u);

	platform_set_drvdata(pdev, u);

	ret = i2c_add_adapter(&u->adap);
	if (ret)
		return dev_err_probe(dev, ret, "cannot register adapter\n");

	dev_info(dev, "bit-banged i2c bus ready (%u Hz), gpio sda %d scl %d\n",
		 freq ? freq : 100000,
		 desc_to_gpio(u->sda), desc_to_gpio(u->scl));

	return 0;
}

static void umi_i2c_remove(struct platform_device *pdev)
{
	struct umi_i2c *u = platform_get_drvdata(pdev);

	i2c_del_adapter(&u->adap);
}

static const struct of_device_id umi_i2c_of_match[] = {
	{ .compatible = "umi,i2c-bitbang" },
	{ }
};
MODULE_DEVICE_TABLE(of, umi_i2c_of_match);

static struct platform_driver umi_i2c_driver = {
	.probe = umi_i2c_probe,
	.remove = umi_i2c_remove,
	.driver = {
		.name = "umi-i2c-bitbang",
		.of_match_table = umi_i2c_of_match,
	},
};
module_platform_driver(umi_i2c_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Bit-banged I2C adapter for the Xiaomi Mi 10 touch bus");
