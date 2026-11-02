/* SPDX-License-Identifier: GPL-2.0-only
 * Historical regression input, extracted without behavior changes from
 * fts521/fts_lib/ftsCore.c at 8761242997e24bb7f262e70544400a52089092f1.
 * Copyright (C) 2016-2023, STMicroelectronics - All Rights Reserved
 * Author(s): ACD(Analog Custom Devices) Software Team for STMicroelectronics.
 * License terms: GPL V2.0. Compiled only by the offline harness.
 */
static int fts_disableInterruptNoSync(void)
{
	if (getClient() != NULL) {
		spin_lock_irq(&fts_int);
		logError(0, "%s Number of disable = %d\n", tag,
			 disable_irq_count);
		if (disable_irq_count == 0) {
			logError(0, "%s Executing Disable...\n", tag);
			disable_irq_nosync(getClient()->irq);
			disable_irq_count++;
		}
		/* disable_irq is re-entrant so it is required to keep track
		  * of the number of calls of this when reenabling */

		spin_unlock(&fts_int);
		logError(0, "%s Interrupt No Sync Disabled!\n", tag);
		return OK;
	} else {
		logError(1, "%s %s: Impossible get client irq... ERROR %08X\n",
			 tag, __func__, ERROR_OP_NOT_ALLOW);
		return ERROR_OP_NOT_ALLOW;
	}
}
static int fts_disableInterrupt(void)
{
	unsigned long flag;

	if (getClient() != NULL) {
		spin_lock_irqsave(&fts_int, flag);
		logError(0, "%s Number of disable = %d\n", tag,
			 disable_irq_count);
		if (disable_irq_count == 0) {
			logError(0, "%s Executing Disable...\n", tag);
			disable_irq(getClient()->irq);
			disable_irq_count++;
		}
		/* disable_irq is re-entrant so it is required to keep track
		  * of the number of calls of this when reenabling */
		spin_unlock_irqrestore(&fts_int, flag);
		logError(0, "%s Interrupt Disabled!\n", tag);
		return OK;
	} else {
		logError(1, "%s %s: Impossible get client irq... ERROR %08X\n",
			 tag, __func__, ERROR_OP_NOT_ALLOW);
		return ERROR_OP_NOT_ALLOW;
	}
}
static int fts_enableInterrupt(void)
{
	unsigned long flag;

	if (getClient() != NULL) {
		spin_lock_irqsave(&fts_int, flag);
		logError(0, "%s Number of re-enable = %d\n", tag,
			 disable_irq_count);
		while (disable_irq_count > 0) {
			/* loop N times according on the pending number of
			 * disable_irq to truly re-enable the int */
			logError(0, "%s Executing Enable...\n", tag);
			enable_irq(getClient()->irq);
			disable_irq_count--;
		}

		spin_unlock_irqrestore(&fts_int, flag);
		logError(0, "%s Interrupt Enabled!\n", tag);
		return OK;
	} else {
		logError(1, "%s %s: Impossible get client irq... ERROR %08X\n",
			 tag, __func__, ERROR_OP_NOT_ALLOW);
		return ERROR_OP_NOT_ALLOW;
	}
}
static int fts_system_reset(void)
{
	struct fts_ts_info *info = dev_get_drvdata(&getClient()->dev);
	u8 readData[FIFO_EVENT_SIZE];
	int event_to_search;
	int res = -1;
	int i;
	u8 data[1] = { SYSTEM_RESET_VALUE };

	fts_idle_hold(info);
	event_to_search = (int)EVT_ID_CONTROLLER_READY;

	logError(0, "%s System resetting...\n", tag);
	for (i = 0; i < RETRY_SYSTEM_RESET && res < 0; i++) {
		resetErrorList();
		fts_disableInterrupt(); /* disable interrupt before resetting to
					 * be able to get boot events */

		if (reset_gpio == GPIO_NOT_DEFINED)
			res = fts_writeU8UX(FTS_CMD_HW_REG_W, ADDR_SIZE_HW_REG,
					    ADDR_SYSTEM_RESET, data,
					    ARRAY_SIZE(data));
		else {
			gpio_set_value(reset_gpio, 0);
			msleep(10);
			gpio_set_value(reset_gpio, 1);
			res = OK;
		}
		if (res < OK)
			logError(1, "%s fts_system_reset: ERROR %08X\n", tag,
				 ERROR_BUS_W);
		else {
			res = pollForEvent(&event_to_search, 1, readData,
					   GENERAL_TIMEOUT);
			if (res < OK)
				logError(1, "%s fts_system_reset: ERROR %08X\n",
					 tag, res);
		}
	}
	fts_idle_release(info, false);
	if (res < OK) {
		logError(
			1,
			"%s fts_system_reset...failed after 3 attempts: ERROR %08X\n",
			tag, (res | ERROR_SYSTEM_RESET_FAIL));
		return res | ERROR_SYSTEM_RESET_FAIL;
	} else {
		logError(0, "%s System reset DONE!\n", tag);
		system_reseted_down = 1;
		system_reseted_up = 1;
		return OK;
	}
}