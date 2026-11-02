/* SPDX-License-Identifier: GPL-2.0-only
 * Historical counterexamples only; not built into the driver.
 * Source: f295b949bf7d5b9aa77c24a93ff0748b522ead9b:fts521/fts.c
 * fwupdate_store / parse_dt are verbatim; probe acquisition/unwind are
 * verbatim fragments between the named boundaries, in an extraction wrapper.
 * Copyright (C) 2016-2023, STMicroelectronics - All Rights Reserved
 * Author(s): ACD(Analog Custom Devices) Software Team for STMicroelectronics.
 * License terms: GPL V2.0. Compiled only by the offline harness.
 */
static ssize_t fwupdate_store(struct device *dev,
			      struct device_attribute *attr,
			      const char *buf, size_t count)
{
	struct fts_ts_info *info = dev_get_drvdata(dev);
	const char *name = info->board->default_fw_name;
	int mode = 0, ret = 0;
	u16 fw_vers = 0, config_id = 0;

	if (kstrtoint(buf, 0, &mode))
		return -EINVAL;
	fts_idle_hold(info);
	if (!name)
		name = "st_fts_j2_2.ftb";

	/*
	 * The controller interrupt must be off while we poke the IC: with the
	 * chip sitting in its bootloader the handler would keep re-reading the
	 * event FIFO from under the flash procedure (that is what wedged the
	 * kernel on the first attempt).
	 */
	if (info->client->irq)
		disable_irq(info->client->irq);

	if (mode & 128) {
		/*
		 * Long reset pulse: the vendor pulses RESET for 10 ms, which may
		 * not be enough for the ROM to re-sample a blank/corrupt flash.
		 * RESET is active low on this board (the vendor's own sequence
		 * drives 0 for 10 ms and then 1).
		 */
		u8 id[2] = { 0, 0 };

		if (info->board->reset_gpio != GPIO_NOT_DEFINED) {
			gpio_set_value(info->board->reset_gpio, 0);
			msleep(200);
			gpio_set_value(info->board->reset_gpio, 1);
			msleep(100);
			logError(1, "%s fwupdate: long reset pulse done\n", tag);
		} else {
			logError(1, "%s fwupdate: no reset gpio\n", tag);
		}

		ret = fts_writeReadU8UX(FTS_CMD_HW_REG_R, ADDR_SIZE_HW_REG,
					ADDR_DCHIP_ID, id, 2, DUMMY_FIFO);
		logError(1, "%s fwupdate: chip id after reset ret %d -> %02X %02X\n",
			 tag, ret, id[0], id[1]);
	}

	if (mode & 16) {
		/* raw HW-register dump: the whole flash/download path is driven
		 * through 0x200000xx (0xFA write / 0xFB read), so reading these
		 * tells us whether the IC still answers at that level. */
		static const u64 addrs[] = { 0x20000024ULL, 0x20000025ULL,
					     0x2000006AULL, 0x2000006BULL };
		int i;

		for (i = 0; i < ARRAY_SIZE(addrs); i++) {
			u8 b[2] = { 0xEE, 0xEE };

			ret = fts_writeReadU8UX(FTS_CMD_HW_REG_R,
						ADDR_SIZE_HW_REG, addrs[i],
						b, 2, 0);
			logError(1,
				 "%s fwupdate: hw[%08llX] ret %d -> %02X %02X\n",
				 tag, (unsigned long long)addrs[i], ret, b[0],
				 b[1]);
		}
	}

	if (mode & 32) {
		u8 v = 0x01;

		ret = fts_writeU8UX(FTS_CMD_HW_REG_W, ADDR_SIZE_HW_REG,
				    0x20000024ULL, &v, 1);
		logError(1, "%s fwupdate: hold_m3(0x24=1) ret %d\n", tag, ret);
	}

	if (mode & 64) {
		ret = flash_unlock();
		logError(1, "%s fwupdate: flash_unlock ret %d\n", tag, ret);
	}

	if (mode & 8) {
		ret = fts_chip_powercycle(info);
		logError(1, "%s fwupdate: chip powercycle -> %d\n", tag, ret);
		msleep(400);
	}

	if (mode & 1) {
		ret = getFirmwareVersion(&fw_vers, &config_id);
		logError(1, "%s fwupdate: on-chip fw=0x%04X cfg=0x%04X (ret %d)\n",
			 tag, fw_vers, config_id, ret);

		ret = flashProcedure(name, 1, 0);
		logError(1, "%s fwupdate: flashProcedure(%s) -> %d\n",
			 tag, name, ret);
	}

	if (mode & 256) {
		/*
		 * Blind recovery reflash.  The IC has no runnable application
		 * FW (the previous burn erased it and then aborted because the
		 * flash status register could no longer be polled), so the whole
		 * reflash is driven with fixed waits around the write-only
		 * erase/DMA commands.  See fts_flash_blind in fts_lib/ftsFlash.c.
		 */
		fts_flash_blind = 1;
		ret = flashProcedure(name, 1, 0);
		fts_flash_blind = 0;
		logError(1, "%s fwupdate: BLIND flashProcedure(%s) -> %d\n",
			 tag, name, ret);

		/* If the burn worked the FW runs again and answers a reset. */
		ret = fts_system_reset();
		logError(1, "%s fwupdate: reset after blind burn -> %d\n",
			 tag, ret);
		ret = getFirmwareVersion(&fw_vers, &config_id);
		logError(1,
			 "%s fwupdate: after blind burn fw=0x%04X cfg=0x%04X ret %d\n",
			 tag, fw_vers, config_id, ret);
		{
			u8 id[2] = { 0xEE, 0xEE };

			ret = fts_writeReadU8UX(FTS_CMD_HW_REG_R,
						ADDR_SIZE_HW_REG,
						ADDR_DCHIP_ID, id, 2, 0);
			logError(1,
				 "%s fwupdate: chip id after blind burn ret %d -> %02X %02X\n",
				 tag, ret, id[0], id[1]);
		}
	}

	if (mode & 1024) {
		/*
		 * FIFO histogram: with the interrupt disabled nothing consumes the
		 * event FIFO, so this shows what the controller actually produces.
		 * Touch reports are EVT_ID_ENTER/MOTION/LEAVE_POINT (0x13/0x23/
		 * 0x33), so if only 0x43 (STATUS) shows up the AFE is not seeing
		 * the panel at all regardless of what the driver does.
		 */
		u8 ev[FIFO_EVENT_SIZE];
		u16 hist[NUM_EVT_ID];
		int k;

		memset(hist, 0, sizeof(hist));
		/* drain whatever was queued before we took the FIFO over */
		for (k = 0; k < 128; k++) {
			if (fts_writeReadU8UX(FIFO_CMD_READONE, 0, 0, ev,
					      FIFO_EVENT_SIZE, DUMMY_FIFO) < OK)
				break;
			if (ev[0] == EVT_ID_NOEVENT)
				break;
		}

		mdelay(1000);
		for (k = 0; k < 128; k++) {
			if (fts_writeReadU8UX(FIFO_CMD_READONE, 0, 0, ev,
					      FIFO_EVENT_SIZE, DUMMY_FIFO) < OK)
				break;
			if (ev[0] == EVT_ID_NOEVENT)
				break;
			hist[ev[0] >> 4]++;
			if (k < 12)
				logError(1,
					 "%s fwupdate: fifo %02X %02X %02X %02X %02X %02X %02X %02X\n",
					 tag, ev[0], ev[1], ev[2], ev[3], ev[4],
					 ev[5], ev[6], ev[7]);
		}
		for (k = 0; k < NUM_EVT_ID; k++)
			if (hist[k])
				logError(1,
					 "%s fwupdate: event id 0x%X0 count %u\n",
					 tag, k, hist[k]);
		logError(1, "%s fwupdate: mode_active = %08X resume_bit %d\n",
			 tag, info->mode, info->resume_bit);
	}

	if (mode & 4) {
		ret = fts_system_reset();
		logError(1, "%s fwupdate: system_reset -> %d\n", tag, ret);
	}

	if (mode & 512) {
		/* Report what the IC currently holds; also re-read the system
		 * info so the CX/AFE versions are fresh. */
		ret = readSysInfo(0);
		logError(1,
			 "%s fwupdate: sysinfo ret %d chip0 0x%04X fw 0x%04X svn 0x%04X cfg 0x%04X cx 0x%04X\n",
			 tag, ret, systemInfo.u16_chip0Id,
			 systemInfo.u16_fwVer, systemInfo.u16_svnRev,
			 systemInfo.u16_cfgVer, systemInfo.u16_cxVer);
		logError(1,
			 "%s fwupdate: afe cfg 0x%02X cx 0x%02X panel 0x%02X res %ux%u\n",
			 tag, systemInfo.u8_cfgAfeVer, systemInfo.u8_cxAfeVer,
			 systemInfo.u8_panelCfgAfeVer, systemInfo.u16_scrResX,
			 systemInfo.u16_scrResY);
		logError(1,
			 "%s fwupdate: mpFlag 0x%02X ssDet 0x%02X fwCrc 0x%08X cfgCrc 0x%08X txrx %ux%u\n",
			 tag, systemInfo.u8_mpFlag, systemInfo.u8_ssDetScanSet,
			 systemInfo.u32_fwCrc, systemInfo.u32_cfgCrc,
			 systemInfo.u8_scrTxLen, systemInfo.u8_scrRxLen);
		logError(1,
			 "%s fwupdate: die %02X%02X%02X%02X%02X%02X%02X%02X rel %02X%02X%02X%02X%02X%02X%02X%02X\n",
			 tag, systemInfo.u8_dieInfo[0], systemInfo.u8_dieInfo[1],
			 systemInfo.u8_dieInfo[2], systemInfo.u8_dieInfo[3],
			 systemInfo.u8_dieInfo[4], systemInfo.u8_dieInfo[5],
			 systemInfo.u8_dieInfo[6], systemInfo.u8_dieInfo[7],
			 systemInfo.u8_releaseInfo[0], systemInfo.u8_releaseInfo[1],
			 systemInfo.u8_releaseInfo[2], systemInfo.u8_releaseInfo[3],
			 systemInfo.u8_releaseInfo[4], systemInfo.u8_releaseInfo[5],
			 systemInfo.u8_releaseInfo[6], systemInfo.u8_releaseInfo[7]);
		logError(1,
			 "%s fwupdate: frames ms raw 0x%04X filt 0x%04X stren 0x%04X dbg 0x%04X\n",
			 tag, systemInfo.u16_msTchRawAddr,
			 systemInfo.u16_msTchFilterAddr,
			 systemInfo.u16_msTchStrenAddr, systemInfo.u16_dbgInfoAddr);
	}

	if (mode & 2) {
		/*
		 * A blank CX area makes the IC queue a CX CRC error event ahead
		 * of every command echo, so checkEcho() would refuse the full
		 * panel init that is supposed to rebuild it.  Tolerate that for
		 * the duration of the recovery.
		 */
		fts_lenient_echo = 1;
		ret = production_test_initialization(SPECIAL_FULL_PANEL_INIT);
		logError(1, "%s fwupdate: production_test_initialization -> %d\n",
			 tag, ret);
		fts_lenient_echo = 0;
		logError(1,
			 "%s fwupdate: after PI cx 0x%04X afe cfg 0x%02X cx 0x%02X panel 0x%02X\n",
			 tag, systemInfo.u16_cxVer, systemInfo.u8_cfgAfeVer,
			 systemInfo.u8_cxAfeVer, systemInfo.u8_panelCfgAfeVer);
		if (ret >= OK) {
			/*
			 * The panel init and CX data are only computed in the IC's
			 * RAM.  Without this command they never reach the flash, so
			 * the next reset finds an empty CX area again and the whole
			 * init has to be redone - that is the difference between a
			 * touch that reports something and one that only emits
			 * STATUS/FRAME_DROP for ever.
			 */
			u8 save = SAVE_CX | SAVE_PANEL_CONF;
			int sret = writeSysCmd(SYS_CMD_SAVE_FLASH, &save, 1);

			logError(1,
				 "%s fwupdate: save to flash (cx|panel) -> %d\n",
				 tag, sret);
			if (sret < OK)
				ret = sret;
		}
		if (ret >= OK) {
			ret = cleanUp(0x01);
			logError(1, "%s fwupdate: cleanUp -> %d\n", tag, ret);
		}
	}

	/*
	 * Factory production test.
	 *
	 * The production line does not need the factory FW file to leave the IC
	 * in a usable state: it runs the panel's own MP test, which re-tunes the
	 * analogue front end and rewrites the CX area in flash.  The limits file
	 * ships in the stock vendor image (stm_fts_production_limits_2.csv is
	 * the 17x37 one, i.e. this module), so the whole flow can be replayed
	 * here.
	 *
	 *   mode 2048  ITO test only (electrode open/short + self capacitance)
	 *   mode 4096  full MP test: ITO + panel init + data test, then save
	 *   mode 8192  with 4096: use SPECIAL_PANEL_INIT instead of FULL
	 *   mode 16384 special tuning: Ioff calibration + CX tuning, then save
	 */
	if (mode & (2048 | 4096 | 16384)) {
		extern TestToDo tests;
		const char *lim = FTS_LIMITS_FILE;

		/* a brand new CX area queues a CRC error ahead of every echo */
		fts_lenient_echo = 1;

		if (mode & 2048) {
			initTestToDo();
			ret = production_test_ito(lim, &tests);
			logError(1,
				 "%s fwupdate: production_test_ito(%s) -> %d\n",
				 tag, lim, ret);
		}

		if (mode & 4096) {
			const int init_type = (mode & 8192) ?
				SPECIAL_PANEL_INIT : SPECIAL_FULL_PANEL_INIT;

			initTestToDo();
			ret = production_test_main(lim, 1, init_type, &tests);
			logError(1,
				 "%s fwupdate: production_test_main(%s, init %d) -> %d\n",
				 tag, lim, init_type, ret);

			if (ret >= OK) {
				u8 save = SAVE_CX | SAVE_PANEL_CONF;
				int sret = writeSysCmd(SYS_CMD_SAVE_FLASH, &save, 1);

				logError(1, "%s fwupdate: save after MP test -> %d\n",
					 tag, sret);
				if (sret < OK)
					ret = sret;
			}
		}

		if (mode & 16384) {
			u8 ioff[2] = { SPECIAL_TUNING_IOFF, 0x00 };
			u8 cx[2] = { 0x00, 0x01 };	/* hover autotune */
			u8 save = SAVE_CX | SAVE_PANEL_CONF;

			ret = writeSysCmd(SYS_CMD_SPECIAL_TUNING, ioff, 2);
			logError(1, "%s fwupdate: SPECIAL_TUNING(ioff) -> %d\n",
				 tag, ret);
			ret = writeSysCmd(SYS_CMD_CX_TUNING, cx, 2);
			logError(1, "%s fwupdate: CX_TUNING -> %d\n", tag, ret);
			ret = writeSysCmd(SYS_CMD_SAVE_FLASH, &save, 1);
			logError(1, "%s fwupdate: save after tuning -> %d\n",
				 tag, ret);
		}

		fts_lenient_echo = 0;
	}

	if (info->client->irq)
		enable_irq(info->client->irq);

	/* Raw diagnostics may leave the IC in ROM or a non-sensing mode. */
	fts_idle_release(info, false);
	return count;
}

static int parse_dt(struct device *dev, struct fts_hw_platform_data *bdata)
{
	int retval;
	const char *name;
	struct device_node *np = dev->of_node;
	u32 temp_val;

#if LINUX_VERSION_CODE >= KERNEL_VERSION(7, 0, 0)
	/*
	 * 7.x：中端号已经由标准 "interrupts" 属性给出（client->irq），
	 * 这里没有需要解析的东西。保持 GPIO_NOT_DEFINED 让后面的
	 * gpio_to_irq() 回退路径被跳过。
	 */
	bdata->irq_gpio = GPIO_NOT_DEFINED;
#else
	bdata->irq_gpio = of_get_named_gpio(np, "fts,irq-gpio", 0);
#endif

	logError(0, "%s irq_gpio = %d\n", tag, bdata->irq_gpio);

	retval = of_property_read_string(np, "fts,regulator_dvdd", &name);
	if (retval == -EINVAL)
		bdata->vdd_reg_name = NULL;
	else if (retval < 0)
		return retval;
	else {
		bdata->vdd_reg_name = name;
		logError(0, "%s pwr_reg_name = %s\n", tag, name);
	}

	/*
	 * FW blob used by the (newly ported) flash path, resolved through
	 * request_firmware() -> /lib/firmware/.  MIUI names it per panel
	 * variant (st_fts_j2_1/2/3.ftb, selected by tp-vendor/tp-module).
	 */
	retval = of_property_read_string(np, "fts,default-fw-name", &name);
	if (retval < 0)
		bdata->default_fw_name = "st_fts_j2_2.ftb";
	else
		bdata->default_fw_name = (char *)name;
	logError(0, "%s default_fw_name = %s\n", tag, bdata->default_fw_name);

	retval = of_property_read_string(np, "fts,regulator_avdd", &name);
	if (retval == -EINVAL)
		bdata->avdd_reg_name = NULL;
	else if (retval < 0)
		return retval;
	else {
		bdata->avdd_reg_name = name;
		logError(0, "%s bus_reg_name = %s\n", tag, name);
	}

#if LINUX_VERSION_CODE >= KERNEL_VERSION(7, 0, 0)
	/*
	 * 7.x：复位脚走描述符 API（DT 里的标准 "reset-gpios"），再翻译回
	 * fts_lib 用的整数编号。描述符会一直掌着这个引脚，所以
	 * fts_gpio_setup() 不能再 gpio_request() 一次。
	 */
	{
		struct gpio_desc *gd = devm_gpiod_get_optional(dev, "reset",
							      GPIOD_ASIS);

		if (IS_ERR(gd))
			gd = NULL;
		bdata->reset_gpio = gd ? desc_to_gpio(gd) : GPIO_NOT_DEFINED;
		logError(0, "%s reset_gpio =%d\n", tag, bdata->reset_gpio);
	}
#else
	if (of_property_read_bool(np, "fts,reset-gpio")) {
		bdata->reset_gpio = of_get_named_gpio(np, "fts,reset-gpio", 0);
		logError(0, "%s reset_gpio =%d\n", tag, bdata->reset_gpio);
	} else
		bdata->reset_gpio = GPIO_NOT_DEFINED;
#endif

	retval = of_property_read_u32(np, "fts,irq-flags", &temp_val);
	if (retval < 0)
		return retval;
	else
		bdata->irq_flags = temp_val;

	retval = of_property_read_u32(np, "fts,x-max", &temp_val);
	if (retval < 0)
		bdata->x_max = X_AXIS_MAX;
	else
		bdata->x_max = temp_val;

	retval = of_property_read_u32(np, "fts,y-max", &temp_val);
	if (retval < 0)
		bdata->y_max = Y_AXIS_MAX;
	else
		bdata->y_max = temp_val;

	return OK;
}

static int fts_probe(struct i2c_client *client)
{
	if (dp) {
		info->board = devm_kzalloc(&client->dev,
					   sizeof(struct fts_hw_platform_data),
					   GFP_KERNEL);
		if (!info->board) {
			logError(1, "%s ERROR:info.board kzalloc failed\n",
				 tag);
			error = -ENOMEM;
			goto ProbeErrorExit_1;
		}
		parse_dt(&client->dev, info->board);
	}

	logError(0, "%s SET Regulators:\n", tag);
	retval = fts_get_reg(info, true);
	if (retval < 0) {
		logError(1, "%s ERROR: %s: Failed to get regulators\n", tag,
			 __func__);
		error = retval;
		goto ProbeErrorExit_2;
	}

	retval = fts_enable_reg(info, true);
	if (retval < 0) {
		logError(1, "%s %s: ERROR Failed to enable regulators\n", tag,
			 __func__);
		error = retval;
		goto ProbeErrorExit_2;
	}

	logError(0, "%s SET GPIOS:\n", tag);
	retval = fts_set_gpio(info);
	if (retval < 0) {
		logError(1, "%s %s: ERROR Failed to set up GPIO's\n", tag,
			 __func__);
		error = retval;
		goto ProbeErrorExit_4;
	}
	gpio_ready = true;

#ifdef CONFIG_PINCTRL
#endif
ProbeErrorExit_4:
	if (gpio_ready) {
		if (info->board->irq_gpio != GPIO_NOT_DEFINED)
			fts_gpio_setup(info->board->irq_gpio, false, 0, 0);
		if (info->board->reset_gpio != GPIO_NOT_DEFINED)
			fts_gpio_setup(info->board->reset_gpio, false, 0, 0);
	}
	fts_enable_reg(info, false);

ProbeErrorExit_2:
	fts_get_reg(info, false);

ProbeErrorExit_1:
	fts_idle_stop(info);
	dev_set_drvdata(&client->dev, NULL);
	fts_info = NULL;
	kfree(info);

ProbeErrorExit_0:
	logError(1, "%s Probe Failed!\n", tag);

	return error;
}
