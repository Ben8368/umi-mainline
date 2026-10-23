# Touchscreen

**Part:** STMicroelectronics FTS, I2C address `0x49`
**Bus:** `i2c@a94000` (QUPV3 wrap1 SE5) → mainline label `&i2c13`
**Driver:** `patches/fts-umi.c`

## How the part was identified

The vendor device tree has **two** touch nodes on the same I2C controller,
both `status = "ok"`:

```
i2c@a94000 {
        qcom,i2c-touch-active = "st,fts";
        fts@49   { compatible = "st,fts";     ... };   /* ST  */
        goodix@5d{ compatible = "goodix,gt9889"; ... };/* Goodix */
};
```

Only one of them is populated on any given unit, so the DT cannot answer the
question. The live device can:

```
$ adb shell getevent -pl | grep -A2 'name:'
  add device 6: /dev/input/event5
    name:     "fts"
...
$ adb shell su -c 'cat /sys/bus/i2c/devices/*/name'
/sys/bus/i2c/devices/3-0049: fts
/sys/bus/i2c/devices/3-005d: gt9889      <- instantiated, never bound
```

and the vendor driver says so in `dmesg`:

```
[    1.538773] [ FTS ] fts_get_config: Choose config 1: st_fts_j2_2.ftb
[    1.538830] [ FTS ] flash_burn: Firmware in the chip newer or equal to the
                      one to burn! NO UPDATE ERROR 8000000C
```

Two conclusions:

1. This unit is **ST FTS**, not Goodix.
2. **Firmware and configuration already live in the controller's own flash.**
   Nothing has to be uploaded, and the driver must never write to the flash.

## Wiring (from the vendor device tree)

| Signal | Value | Vendor property |
|---|---|---|
| SDA / SCL | GPIO37 / GPIO36, function `qup13` | `qupv3_se13_i2c_active` |
| reset | GPIO38, active high (high = out of reset) | `fts,reset-gpio = <&tlmm 0x26 0x00>` |
| interrupt | GPIO39, level low | `fts,irq-gpio = <&tlmm 0x27 0x2008>` |
| AVDD 3.3 V | enable GPIO69 (`touch_vddio_vreg`) | `avdd-supply` |
| VDD 1.8 V | pm8150a LDO1 | `vdd-supply` |

Neither rail is touched by the kernel. Both are enabled by ABL before the
kernel starts, the vendor driver only ever *enables* them, and this driver
reproduces that state exactly. If a rail were off, the first I2C transfer
would fail with `-ENXIO`/`-ETIMEDOUT` and the log would say so.

## Protocol

Every transfer is a plain I2C write of a command byte, optionally followed by
a read of the answer:

```
S addr+W  <cmd>            S addr+R  <data...>
```

| Command | Meaning |
|---|---|
| `0x80` | read information, 8 bytes: chip version, firmware version, config id/version, chip id |
| `0x85` | read one event from the FIFO (8 bytes) |
| `0xA1` | flush the FIFO |
| `0x92` / `0x93` | sense off / on |

Events are drained one at a time; byte 0 == `0x00` means "FIFO empty".

### Event layout (8 bytes)

```
byte 0   <class><object>
           object = bits 3..0 : 3 = touch point, other values = gestures
           class  = bits 7..4 : 1 = enter/motion, 3 = leave
byte 1   bits 3..0 touch id, bits 7..4 number of remaining contacts
byte 2   x >> 4
byte 3   y >> 4
byte 4   bits 7..4 = x & 0xf, bits 3..0 = y & 0xf
byte 5   bits 7..6 touch size, bits 4..0 major
byte 6   minor
byte 7   unused
```

Coordinates are therefore 12-bit:

```
x = (ev[2] << 4) | ((ev[4] & 0xf0) >> 4)
y = (ev[3] << 4) | (ev[4] & 0x0f)
```

Older ST parts use flat event codes `0x03` (enter) / `0x04` (leave) /
`0x05` (motion) instead of the class/object byte. The driver accepts both
spellings, because the vendor log on this unit shows `Event 0x13 - Press`
/ `Event 0x33 - release`, which is the class/object form, while the vendor
header still defines the flat codes.

### Why the first 96 events are dumped verbatim

```
[   35.611777] fts-umi 3-0049: ev 13 00 21 4c 7a 11 03 00
```

If a different controller revision ever turns up, having the raw bytes in the
log is worth more than any amount of guessing about the protocol.

## Reset sequence

```
reset = 0
20 ms
reset = 1
120 ms
flush FIFO (0xA1), sense on (0x93)
```

The vendor power cycle path waits 300 ms after releasing reset; 120 ms is
comfortably within what the datasheet allows and keeps the probe fast.

## Known limitations

* No gestures, no swipe-to-wake, no in-display-fingerprint area reporting —
  plain multi-touch only.
* The interrupt is a threaded handler that drains the whole FIFO per
  interrupt; no ESD recovery yet.
* Only the `st,fts` variant is driven. A Goodix GT9889 unit needs a different
  driver (mainline `goodix_berlin*` is a reasonable starting point, but the
  firmware/config handling will have to be adapted).
