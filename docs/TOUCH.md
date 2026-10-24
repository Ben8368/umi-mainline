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


## p66 - ioff trim, gesture feature, frame statistics

Three new tools, all driven from `enable` and one new attribute, so a whole
experiment fits into a single boot:

```
echo 4 > .../enable   full panel init + scan          (unchanged)
echo 5 > .../enable   full init + ioff trim + scan
echo 6 > .../enable   full init + ioff trim + gesture + scan
echo 1 > .../raw      stop scan, read raw/flt/base, restart scan
```

`raw` prints one line per frame: node count, min, max, average and the first
eight samples. `min == max` over all 629 nodes is the whole story of this
bring-up: a live capacitance matrix never looks like that.

### What the build measured

```
sysinfo frames raw@9148 flt@4904 str@4f40 base@5d82
raw  @9148 n 629 min -13462 max -13462 avg -13462 head -13462 -13462 ...
base @5d82 n 629 min -13462 max -13462 avg -13462 head -13462 -13462 ...
flt  @4904 n 629 min -32742 max  32751 avg    470 head 19997 4045 20475 ...
```

Both SYS_CMD_SPECIAL_TUNING / SPECIAL_TUNING_IOFF (`A4 08 02 00`) and the
gesture feature the vendor writes right after sense on (`A2 03 00 00 00 03`)
are accepted by the controller (both return 0) and change nothing: raw and
baseline stay at one repeated -13462, which is also what the FW complains
about as FORCE_CAL / 0x01 "mutual negative detect". The filter frame is
uninitialised memory - it does not change between reads either, so it is not
a live matrix.

So the analog front end is not the lever. What is left is the FW's own panel
(CX) data, i.e. whether it ever ran a real mutual scan for this panel.

### New display safety fact

Running the full panel init **twice in one boot** wedges the DSI:

```
[drm:dpu_encoder_frame_done_timeout] [dpu error]enc32 frame done timeout
dsi_cmds2buf_tx: cmd dma tx failed, type=0x15, data0=0xfc, len=4, ret=-110
panel-xiaomi-umi: on-sequence: packet 37 dtype 0x15 failed (-110)
```

and this time `repower` did **not** recover it - the re-sent on-sequence dies
with -110 because the command DMA is already stuck. Only a reboot brought the
panel back. Rule for the next builds: at most one panel init per boot, and
`repower` is not a general escape hatch any more.

### Vendor reference, from a booted MIUI

MIUI is locked down (`ro.build.type=user`, `ro.debuggable=0`, no `su`, dmesg
and sysfs touch nodes denied to the `shell` user), so the vendor's raw frame
dump is out of reach. What could be read without root:

```
getevent -p  ->  /dev/input/event5 name "fts"
                 ABS 0x35 X 0..1079      ABS 0x36 Y 0..2339
                 ABS 0x30/0x31 area, ABS 0x39 tracking id
```

i.e. the vendor reports the panel resolution, not the 37x17 sensor matrix,
and touch events do reach the framework. The controller, the panel and the
flex are fine; the difference is on our side.

## The vendor's own boot log (root on MIUI)

MIUI is `user`/non-debuggable, but Magisk's `su` is present, so a direct
`adb shell su -c dmesg` works - the earlier "no root" conclusion was wrong
(PowerShell 5.1 mangles nested quotes in `su -c "..."`, which is what made it
look like `su` was missing; a single-token command needs no quoting at all).

What a real probe looks like:

```
[ FTS ] fts_probe: Probe start
[ FTS ] parse_dt:fw_name: st_fts_j2_1.ftb / j2_2.ftb / j2_3.ftb
[ FTS ] FW VER = 0132
[ FTS ] CONFIG VER = 004C
[ FTS ] CX VER = FFFF
[ FTS ] AFE VER: CFG = 05 - CX = 05 - PANEL = 05
[ FTS ] Lockdown:0x53,0x42,0x32,0x01,0x74,0x02,0x32,0x01
[ FTS ] parseBinFile: FILE Fw Version = 0132
[ FTS ] parseBinFile: FILE Config Version = 0000004C
[ FTS ] parseBinFile: CX Version = FFFF
[ FTS ] fts_mode_handler: Sense ON
```

Three things fall out of it:

1. **`CX VER = FFFF` is normal.** MIUI reads the same value, so the CX data
   is not missing on this unit. Our log printed `d[22..23]` as `cfg`; the real
   CONFIG VER is `d[20..21]` = `004C` and `d[22..23]` is the config project id.
2. **Our system info read matches MIUI byte for byte** - FW 0132, CFG 004C,
   AFE 05/05/05, same lockdown code. The protocol side of this driver is done.
3. **The probe does no panel init at all.** The whole sequence is
   `fts_init` = soft reset (`FA 20000024 80`) + `readSysInfo(0)` (plain
   framebuffer read, no `A4 06 01`) followed by
   `fts_mode_handler` = `setScanMode(ACTIVE, 0x01)` + gesture feature.
   There is no `A4 00 02`, no `A4 00 03`, no ioff trim.

## The reference frame

`cat /sys/bus/i2c/devices/3-0049/ms_raw` with root returns the vendor's own
`MsTouchRaw,17,37` matrix. It is node specific and small, roughly -300..+340,
with the first two columns larger (865..2201). That is what a healthy raw
frame on this panel looks like - against the single repeated `-13462` this
driver reads on every node.

## Why this points at the panel init

The full panel init is the one thing this driver does that the vendor does not,
and the "mutual negative detect" storm plus the frozen raw frame both started
right after the first one. p67 therefore adds

```
echo 7 > .../enable    soft reset + read sysinfo + scan, no panel init
```

which is the vendor's probe sequence, and keeps `enable 4/5/6` for comparison
and for a controller that was already poked into a bad state.

## p67 / p68 - vendor parity does not fix the frame

p67 added

```
echo 7 > .../enable    soft reset (FA 20000024 80) + readSysInfo + scan
```

which is the vendor's whole probe sequence - no panel init. The system info
comes back identical to MIUI's (FW 0132, TX 17, RX 37, same frame addresses),
and the raw frame is still one repeated -13462 on all 629 nodes.

p68 added two ways to read a frame:

```
echo 1 > .../raw    keep scanning, wait 200 ms, read   (vendor shape)
echo 2 > .../raw    sense off, 50 ms, flush, read, resume
```

and a scan mask sweep (0x01, 0x03, 0x05, 0x09, 0xFF). Raw stays -13462 in
every single combination, while the filter frame tracks it exactly
(raw == baseline, filter == 0), which is what the controller believes.

This is the same read procedure the vendor's own `ms_raw` attribute uses
(`setScanMode(ACTIVE,01)`, 200 ms, `setScanMode(ACTIVE,00)`, 50 ms, flushFIFO,
getMSFrame3(MS_RAW)), and on MIUI the same attribute returns a node specific
matrix around -300..+340. So the procedure is not the difference; the AFE
state at read time is.

Poking the same framebuffer address with the other memory opcodes shows the
two views are different engines: `FA 00009148` returns code-like repeats
(`28 68 40 1c`), `A8 9148` returns zeros, `A6 9148` returns `6a cb`. The 0xA6
window is the FW framebuffer and it is only meaningful for data the FW has
actually produced.

Open question, next measurement: MIUI can also be asked for its own CX data
(`cat /sys/bus/i2c/devices/3-0049/ms_cx_total`). If that is populated on MIUI
and the compensation it describes is what the AFE needs, the remaining step is
to get the same CX data into the controller at boot - the one thing this
driver has never done and never checked.

## p69 - p71 - and what the event log actually says

Three more things were matched to the vendor and changed nothing:

- p69: the vendor power sequence exactly (vdd first, 15 ms, `regulator_set_load`
  100 mA vote on avdd, then avdd).  The load vote is accepted and the rail
  stays at 3300 mV; raw is unchanged.
- p70: a runtime DSI poke (`echo "<7 byte header> <payload> ..." > dsi` on the
  panel device).  The MIUI `mi,mdss-dsi-vi-setting-low/high` commands
  (`page 1` + `B9 1A...` / `B9 1F...`) go through and change nothing either.
- p71: Sense ON with the full active mask `0xFF`, which is what the working
  upstream mainline port uses, instead of `0x01`.  Accepted, scan register
  reads 0x50, raw is still one repeated -13462.

The chip's stored panel data is *identical* to MIUI's, byte for byte:

```
echo "w a4 06 50" > .../cmd      # LOAD_PANEL_CX_TOT_MS_TOUCH
echo "x a6 00 00 40" > .../cmd   # -> a5 50 02 00 | 08 00 18 00 1c 00 1c 00 ...
```

A5 signature, load type 0x50, then 8, 24, 28, 28, ... which is exactly the
`ms_cx_total` matrix MIUI prints (`MsTouchTotalCx,20,37`, `R00, 8, 24, 28, ...`
and its last node -16).  So the controller's CX/panel compensation is intact.

### The event log

With the whole FIFO drained the boot looks like this:

```
ev 4301a40001000005   echo of A4 00 01 (FIFO flush)
ev 4301a00000000004   echo of A0 00 00 (sense off)
ev 4301a000ff000003   echo of A0 00 FF (sense on)
ev 4303f82a00000003   STATUS / FRAME_DROP, and then hundreds more
ev 4303f82a00000002
ev 4303f82a00000001
...
ev 4303b1430000000f
```

`0x43` is STATUS, `0x03` is EVT_TYPE_STATUS_FRAME_DROP, and byte 7 counts down
because the FIFO is full and we are draining it.  The controller produces a
frame drop for *every single frame* from the moment sensing comes on, and it
also reports FORCE_CAL / 0x01 "mutual negative detect" once.

That is the missing half of the picture: the analog front end is not silent, it
samples and its result is rejected as negative on every frame.  Raw, baseline
and filter are consistent with that (raw == baseline == -13462, filter == 0).

### What is left

Every digital difference that could be found has been removed: reset, sysinfo,
CX data, scan mode and mask, gesture feature, ioff trim, frame read procedure,
interrupt model, power sequencing, load votes, VI setting.  The remaining
suspect is the analog side of the panel/controller interface, i.e. something
that neither the DT nor the command set above can express.

### Upstream status (found by searching, not by guessing)

A mainline driver for exactly this chip family exists and is being upstreamed:

- `[PATCH v4 00/11] Input: support for STM FTS5`
  https://lkml.iu.edu/hypermail/linux/kernel/2604.1/01858.html
- a working port already in a mainline tree:
  https://github.com/sm7150-mainline/linux/commit/36f473a81f63ecfbe58d5d13f6ed998ce7885c50

Reading that driver against this one turned up the two differences that were
then tested (the 0xFF scan mask, and the CRC driven init selection), and it is
also the cheapest way to stop guessing: it is the reference implementation, it
uses plain `i2c_transfer()`, and it carries the full init flow including the
`pollForErrorType()` CRC checks that decide between no init, panel init and
full panel init.  The plan that follows from this is to wrap the bit-banged bus
in a real `i2c_algorithm`/`i2c_adapter` (the bus works; only the QUP DMA path is
broken) and let that driver probe 0x49 unchanged.
