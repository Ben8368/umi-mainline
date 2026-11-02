/* SPDX-License-Identifier: GPL-2.0-only
 * Historical regression input, extracted without behavior changes from
 * fts521/fts.c at 06f47f656db64bcbe833f63ed8e060c3d8185568.
 * Copyright (C) 2016-2023, STMicroelectronics - All Rights Reserved
 * Author(s): ACD(Analog Custom Devices) Software Team for STMicroelectronics.
 * License terms: GPL V2.0. Compiled only by the offline harness.
 */
static int fts_gpio_setup(int gpio, bool config, int dir, int state)
{
	int retval = 0;
	unsigned char buf[16];

	if (config) {
#if LINUX_VERSION_CODE < KERNEL_VERSION(7, 0, 0)
		snprintf(buf, 16, "fts_gpio_%u\n", gpio);

		retval = gpio_request(gpio, buf);
		if (retval) {
			logError(1, "%s %s: Failed to get gpio %d (code: %d)",
				 tag, __func__, gpio, retval);
			return retval;
		}
#else
		/* 7.x：引脚已经由 devm_gpiod_get() 掌住，这里只补方向。 */
		(void)buf;
#endif

		if (dir == 0)
			retval = gpio_direction_input(gpio);
		else
			retval = gpio_direction_output(gpio, state);
		if (retval) {
			logError(1, "%s %s: Failed to set gpio %d direction",
				 tag, __func__, gpio);
			return retval;
		}
	}
#if LINUX_VERSION_CODE < KERNEL_VERSION(7, 0, 0)
	else
		gpio_free(gpio);
#endif

	return retval;
}
static int fts_set_gpio(struct fts_ts_info *info)
{
	int retval;
	struct fts_hw_platform_data *bdata = info->board;

	retval = fts_gpio_setup(bdata->irq_gpio, true, 0, 0);
	if (retval < 0) {
		logError(1, "%s %s: Failed to configure irq GPIO\n", tag,
			 __func__);
		goto err_gpio_irq;
	}

	if (bdata->reset_gpio >= 0) {
		retval = fts_gpio_setup(bdata->reset_gpio, true, 1, 0);
		if (retval < 0) {
			logError(1, "%s %s: Failed to configure reset GPIO\n",
				 tag, __func__);
			goto err_gpio_reset;
		}
	}
	if (bdata->reset_gpio >= 0) {
		gpio_set_value(bdata->reset_gpio, 0);
		msleep(10);
		gpio_set_value(bdata->reset_gpio, 1);
	}

	return OK;

err_gpio_reset:
	fts_gpio_setup(bdata->irq_gpio, false, 0, 0);
	bdata->reset_gpio = GPIO_NOT_DEFINED;
err_gpio_irq:
	return retval;
}