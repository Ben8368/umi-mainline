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

## Where the bring-up actually stands

Everything below was measured on umi with a serial console, not inferred.
Three protocol mistakes had been keeping the whole thing down, and once they
were fixed the AFE finally came up.

### 1. Three protocol facts

| what | wrong before | right |
|---|---|---|
| load-data selector | `0xA4 01 <type>` | **`0xA4 06 <type>`** |
| framebuffer address width | 32 bit after `0xA6` | **16 bit after `0xA6`** |
| register address width | 16 bit | **32 bit after `0xFA`** |

The vendor map for the `0xA4` selector byte is `0x00` special, `0x01` FW
interrupt control, `0x02` force cal, `0x03` CX tuning, **`0x06` load data**.
Every early raw-frame request went to the interrupt-control command instead,
which is also what first blacked the panel.

The framebuffer is a *different address space* from the `0xFA` registers.
Handing `0xA6` a 32 bit address still returns something that parses like a
header, so the mistake is silent — the tell is a frame counter that never
moves.

### 2. FULL panel init, not panel init

`A4 00 03`, not `A4 00 02`. The whole vendor function is:

```
reset the chip (GPIO 38 low 10 ms, high)
A4 00 03
A4 06 01          then read the system info back
```

The vendor picks which one from the AFE versions in the system info:

```
cfgAfeVer != cxAfeVer        -> SPECIAL_FULL_PANEL_INIT   0x03
cfgAfeVer != panelCfgAfeVer  -> SPECIAL_PANEL_INIT        0x02
```

This unit reads `cfgAfeVer 0x00 / cxAfeVer 0x05`, so it needs the **full**
one. `A4 00 02` alone changes nothing, which is why it looked like a dead end.

Measured effect (`echo 4 > enable`):

```
before:  sysinfo res 0x0        tx 0  rx 0   raw@0000
after:   sysinfo res 2339x1079  tx 17 rx 37 raw@9148
```

`2339x1079` is the panel minus one; `17x37` are the real TX/RX channel
counts. The three AFE versions also settle from `00/05/05` to `05/05/05`.

### 3. IER is read-only, and writing it causes the interrupt storm

`0x20000029` reads `0x40` on a freshly reset chip and the FW overwrites
whatever is written to it. Writing `0x41` after every interrupt produced
**1370 interrupts per second with an empty FIFO behind them** and made the
console crawl. The vendor's `fts_enableInterrupt()` only enables the Linux
irq; it never touches the register. Removing the write drops the counter to
2 and the line releases.

### 4. Frame addresses and what the data says

Frame addresses live in the system info at these offsets:

```
[136] raw      0x9148
[138] filter   0x4904
[140] strength 0x4f40
[142] baseline 0x5d82
```

Sampled on this unit:

```
raw      @ 9148:  6a cb 6a cb ...    (0xCB6A = -13462)
baseline @ 5d82:  6a cb 6a cb ...    identical
filter   @ 4904:  00 00 00 ...       delta when nothing touches the panel
strength @ 4f40:  00 00 00 ...
```

So the `EVT_TYPE_STATUS_FORCE_CAL` / subtype `0x01` ("mutual negative
detect") that kept firing was **not** a broken baseline — the baseline had
correctly absorbed the `-13462` offset.

### 5. The remaining problem, stated plainly

`raw` stays exactly `6a cb`, sample after sample, while the frame counter
keeps incrementing. Real sampling has noise; a value that never moves one
LSB means the AFE is not receiving a real signal. With the baseline equal to
it, `filter` is a constant zero, no finger can cross the detection
threshold, and no ENTER event is ever generated.

Related observations:

* `A0 00 01` really starts the scan — `0x2000004a` goes `00 -> 50`. But if
  the gesture write `A2 03 00 00 00 03` follows it, the register drops back
  to `00`. Sending `A0 00 01` by hand afterwards brings it to `50` again, so
  the scan command is fine and something after it is not.
* Two error events show up after the full panel init,
  `f374010000000000` and `f384100000000000`. Neither type is in the vendor
  table, so they are firmware extensions, most likely reporting the same
  thing measured above.

The two explanations left are a Cx/panel dataset that does not match this
unit's routing, or excitation the vendor stack sets up somewhere still
unaccounted for. Either one wants a logic analyser capture of the working
MIUI stack on SDA/SCL (GPIO36/GPIO37) to diff against — guessing further has
stopped paying.

### 6. Controls that exist in this driver

```
/sys/devices/platform/4900000003.touchscreen/enable
    0  controller unpowered (display safest)
    1  powered and handshaked, sensing off
    2  sensing on
    3  panel init (A4 00 02) then sensing on
    4  full panel init (A4 00 03) then sensing on   <-- the one that works

/sys/devices/platform/4900000003.touchscreen/frame
    echo 30|31|32|33   request raw|filter|baseline|strength frame and report
                       whether the frame counter moved

/sys/devices/platform/4900000003.touchscreen/dbg
    echo 1             log every event, past the boot budget

/sys/devices/platform/4900000003.touchscreen/cmd
    w <bytes...>       raw write          (0xA4 is filtered, see below)
    r <op> <len>       write one byte, read len
    x <bytes...> <len> write, then read
    h <addr32> <len>   read a 32 bit addressed hardware register

/sys/devices/platform/soc@0/ae00000.display-subsystem/ae94000.dsi/ae94000.dsi.0/repower
    echo 1             re-send the 59 packet panel on-sequence
```

`repower` matters: poking the touch controller can leave the command mode
AMOLED dark while the SoC keeps scanning, and this brings it back without a
reboot.

### 7. Display safety

`0xA4` is filtered in the `cmd` poke box because it can kill the panel:

```
A4 00 01  FIFO flush      harmless, used by the driver
A4 00 02  panel init      did not black the panel in the end
A4 00 03  full panel init did black it once, `repower` recovered it
A4 01 xx  interrupt ctrl  the old "load data" mistake, do not send
A4 06 xx  load data       safe, this is how frames are requested
```

