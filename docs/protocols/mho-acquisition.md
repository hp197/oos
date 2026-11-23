# MHO900 acquisition: start-up, registers, read-out, measurements

Status: **not yet verified on hardware.** Nothing here has run on an MHO900. It describes how the stock MHO900 system
(00.01.00.00.26) starts the acquisition board and uses its FPGA, compared with the DHO800/DHO900 pages in this folder.
"Assumed" marks an interpretation. OOS does not drive this board yet (ADR 0028, [mho.md](../mho.md)); the facts below
are kept in `hal/src/mho/acq.rs` as data, so the bring-up at the bench starts from them.

In one sentence: the main board, the register window, the read-out path and the sample format are the DHO's; the
start-up of the board, the ADCs and their clock, the front ends and the mask block are new.

## 1. Start-up of the acquisition board (stock order)

The stock start script reads the board's **hardware code** first (a GPIO strap driver, `hdcode`), and several steps
depend on it. Code 1 is an early board; codes 2 and up are later ones.

| # | step | how |
|---|---|---|
| 1 | hardware code | `/sys/class/hdcode/hdcode_dev/hdcode_value` (0 when the driver gives none) |
| 2 | fan | code 1: an on/off line; codes 3 and up: PWM1, `pwm-fan` (as in OOS's device tree) |
| 3 | ADC supply | GPIO0_A1 (gpio 1) = 1 (not on code 1) |
| 4 | front-end supply | GPIO0_A2 (gpio 2) = 1 (not on code 1) |
| 5 | Ethernet PHY | Motorcomm driver, link down and up again |
| 6 | sample clock | a **LMK04821** on a GPIO 3-wire bus (`/dev/spi_3wires`), one register table per hardware code (codes 1, 2, 3 and up) |
| 7 | FPGA supply | GPIO1_A0 (gpio 32) = 1 |
| 8 | FPGA image | a Kintex-7 in slave serial mode: PROGRAM_B, INIT_B and DONE on GPIOs (`/dev/spi2k7_ctl`: GPIO1_B5, GPIO2_C7, GPIO2_C4 from the platform probe), the bitstream streamed over SPI (`/dev/spidev1.0` or `/dev/spidev5.0`: on code 3 the stock device tree enables only spi5 with its spidev, and `/dev/spidev1.0` is not there (platform probes of an MHO954 and an MHO98); `/dev/spidev5.0` on code 1); then 5 s |
| 9 | PCIe | `pcie-rockchip`, then `xdma`; when no `/dev/xdma0_*` appears, both are unloaded and loaded again, up to 10 times |
| 10 | front-end bus, generator | the AFE bus on GPIOs (`/dev/spi_simulate`, one chip select per channel, 24-bit frames: section 8); the generator board on `ttyS4` (codes 2 and up) |
| 11 | others | DAC range driver, LA probe detect GPIO3_D0 (gpio 120, input), front-end overload inputs (`afe_rms`) |
| 12 | application | per channel the front-end init, the SCU init, then the JESD204 link (section 4) |

The clock tables are TI register words: 136 lines `R<n> 0x<aaaadd>`, 24 bits = register address (bits 23:8) and data
(bits 7:0), the fields apart by a tab; the first line, a reset of R0, carries a label: `R0 (INIT)` then `0x000090`
(verified on a unit: the bring-up's error on an MHO98, GitHub issue #4). They are the unit's own files `/rigol/resource/conf/init_all_clock_V00_01.txt`
(code 1), `_V00_02.txt` (code 2) and `_V00_03.txt` (codes 3 and up) (platform probe). OOS ships none of them; the
bring-up of docs/mho.md reads the unit's own at run time, as it reads the FPGA image. The bus: chip select gpio 50
(active low, idle high), clock gpio 49 (idle low), one data line gpio 51, and `sysref_reset` gpio 54, left at 0 by the
stock system (platform probe). The stock clock driver takes these four lines and no others. gpio 52 (GPIO1_C4), listed
as `reset` beside them in the platform probe, is the DSI panel's reset, as on the DHO: under OOS the panel driver holds
it, and the bring-up's request for it failed with "Resource busy" on an MHO98 (verified on the unit, GitHub issue #4).
The frame is assumed to be the LMK04821 data sheet's.

The FPGA image is chosen by the hardware code; the file is the unit's own under `/rigol/FPGA` (OOS may read it at run
time, it cannot ship it, ADR 0013):

| hardware code | image |
|---|---|
| 1 | `sparrow3_K160T.bit` |
| 2 to 7 | `sparrow3_RT688.bit` |
| 8 to 11 | `sparrow3_K160T_LR.bit` |

## 2. Register window and read-out stream

The same devices as on the DHO800/DHO900 (acquisition-start.md, section "read rules"):

- registers: `/dev/xdma0_bypass`, mapped whole, **16 MiB** (the blocks reach 0x30000; the DHO's window is 32 KiB);
  32-bit words at byte offsets, one lock around each access;
- read-out: `/dev/xdma0_c2h_0`, a plain blocking `read()` of the requested bytes. Analog and LA traces come over the
  same stream, one after the other.

The stock system also uses a memory copy engine of its kernel to move a single-channel record from the read buffer
into the waveform buffer. That is a copy on the processor's side, not part of the FPGA protocol; OOS does not need it.

## 3. Register blocks

| offsets | block | compared with the DHO800/DHO900 |
|---|---|---|
| 0x0004 | FPGA version | |
| 0x1000 to 0x1574 | SPU: ADC lanes, sample rate, memory, filters, interpolation, read-out window, LA, probes | same offsets, some values wider (below) |
| 0x2000 to 0x2274 | TPU: trigger, serial triggers, auto trigger | same layout; the auto trigger has words at 0x226c to 0x2274 |
| 0x2438 | WAU: mask control | new |
| 0x3000, 0x3004 | ADC SPI bridge (section 4) | the DHO has the generator here |
| 0x4000 to 0x40d0, 0x4100, 0x4104 | SCU: run, record and play, status, time stamps, stop reason | same offsets and bits, plus new words |
| 0x5000 to 0x5040 | Bode analysis | new |
| 0x6058 to 0x6064 | WAU: Bode source | new |
| 0x610c to 0x6158 | WAU: mask and pass/fail | the DHO has this block at 0x1184 to 0x11cc |
| 0x10100, 0x10108 | a PWM output (assumed: an offset or level DAC) | new |
| 0x20004 to 0x20818 | JESD204 receiver of the two ADCs | new |
| 0x30000 | multi-channel sync (assumed: the generator board) | new |

### What is the same

Of the 235 register offsets OOS uses on the DHO800/DHO900, 169 are used by the stock MHO900 system at the same
offset for the same function. Those that matter for a first acquisition:

| register | meaning (acquisition-start.md, record-play.md) |
|---|---|
| 0x4004 | bit 0 FSM start, bit 2 play-last pulse, bit 31 stop |
| 0x4008 | bits 3:0 FSM channel mask, bit 17 roll, bit 22 scan, bits 23/24 analog/LA stream, zoom |
| 0x400c | record and play mode (record sequence bits 25, 28, 29) |
| 0x4010, 0x4014, 0x4018 | frame window: first, current, last |
| 0x4030, 0x4034 | status (0x4034 written to clear) |
| 0x404c | pre-sample compensation |
| 0x4050, 0x4054 | pre- and post-trigger samples |
| 0x10d0 to 0x10d8 | sample rate |
| 0x10e0 | segment size |
| 0x10e4 | record depth (memsel) |
| 0x1100 to 0x1114 | wave range of the read-out |
| 0x11e8, 0x11f0 | TX state and TX length |

The record and play words 0x4068 and 0x406c, the frame time stamps 0x40b0 to 0x40c4, the auto-trigger word 0x4064,
the compression 0x1170 and the TX words 0x11fc and 0x12c0 are written as OOS writes them on the DHO.

### What is new

Registers the stock MHO900 system uses that OOS does not use on the DHO800/DHO900 (apart from the blocks of the
table above that are new as a whole):

| register | what the stock system does |
|---|---|
| 0x101c, 0x102c | ADC bit slip: set and read back |
| 0x1098 to 0x10a0 | a second output filter: control, coefficients, bypass |
| 0x10dc | anti-alias setting of the acquisition |
| 0x1104, 0x110c | wave range: start and end as two words each (assumed: 64-bit values for depths over 4 G) |
| 0x111c | the sinc filter's input length, second word |
| 0x1120 to 0x112c | coarse and fine read-out delay |
| 0x1168 | the interpolation factor |
| 0x11ec, 0x11f4, 0x12c4 | more TX information of the read-out (analog and LA) |
| 0x1208, 0x120c | recorded range, normal and roll |
| 0x12e4 | start offset of a channel in the read-out, and the LA fine offset |
| 0x1328 | acquisition delay |
| 0x1408 to 0x1414, 0x142c, 0x1440 to 0x1454 | probe offset DACs, probe power, the probes' 1-wire bus |
| 0x1518 | maximum output |
| 0x155c to 0x1574 | per-channel gain and two offsets after the ADC, with a bypass and mode word |
| 0x2028 to 0x2080 | trigger A, B and R events, logic operations, delay and holdoff event counts |
| 0x210c to 0x21cc | serial triggers: I2S, LIN, CAN, FlexRay, MIL-STD-1553B |
| 0x2264 | external trigger input and its hysteresis |
| 0x226c to 0x2274 | a second auto trigger (enable, status, two words) |
| 0x2438 | mask control of the WAU |
| 0x401c | hardware version |
| 0x4044, 0x4048 | FPGA DNA |
| 0x4100 | stop reason (read, written to clear); 0x4104 an AUX output control |

## 4. ADCs and their link

Two ADCs, interleaved (data sheet: 4 GSa/s), each behind a JESD204 link into the FPGA. The processor reaches their
registers through an SPI bridge in the FPGA:

```
0x3000 = strobe | select | addr << 16 | data     ; strobe = bit 26, select = bit 24 (ADC 0) or bit 25 (ADC 1)
wait 100 us
0x3000 = select | addr << 16 | data              ; the same word without the strobe
(read: bit 23 set in addr and data 0; after a further 100 us the 16 data bits are in 0x3004)
```

A read's 16 bits are valid when bit 16 of 0x3004 is set. **Verified on the unit** (an MHO98 and an MHO934, GitHub
issues #4 and #248, the bring-up's `adc` step of docs/mho.md under OOS, after the clock table and the FPGA image): all
32 reads of registers 0x00 to 0x0f of both ADCs came back valid, so both ADCs answer behind the bridge. Before any ADC
register is written the raw words differ from ADC to ADC and from unit to unit; 0x09 (0x0700, once 0x0d00), 0x0a
(0x8080), 0x0b (0) and 0x0e (0x0080) read the same on all four ADCs.

The ADC clock count 0x1210 read **49999** on both units under OOS (the DHO800/DHO900 reads 62500 at its 1.25 GHz, and
the same count goes as the clock: docs/models.md). Whether the stock system reads the same on the MHO900 is not yet
known; `tools/mho-check.py` reads it from version 7.

The stock system XORs the data with a fixed mask per register before it writes it, as it does for the DHO's ADC
(adc-spu-init.md); the masks are not known yet.

At a cold start the application pulses 0x2003c (1, 5 ms, 0; assumed: the link reset), sets up the receiver
(0x20004 to 0x2002c, 0x20400 to 0x2040c, 0x2080c to 0x20818) and enables the DAC sync for 50 ms. Assumed: the JESD204
link takes the place of the DHO's lane alignment (adc-spu-init.md); the ADC bit slip words 0x101c and 0x102c point to a
remaining alignment step.

## 5. Read-out and sample format

A read-out is requested and read as on the DHO800/DHO900 (record-play.md): set the window, request, then one `read()`
of the length the TX registers say. The words are what OOS already decodes:

- 16 bits, little endian;
- **7500 codes per division around 32768**: volts = (code - 32768) / 7500 x V/div - offset. The stock system's vertical
  increment (V/div / 7500) and ground (32768 + offset in codes) are the DHO's;
- channels share the words as on the DHO (horizontal-config.md 2.2): one channel alone, two on even and odd words,
  three or four in groups of four, word 4i + k = CH k+1.

So `seq::decode_volts` of the DHO800/DHO900 is the decode the MHO900 needs; `hal::mho::acq::volts` holds the same
formula and a test keeps the two equal.

## 6. Measurements

The stock system computes its measurements on the processor, from the decoded read-out, not in the FPGA. It reads two
kinds of data for them:

- the **screen trace**: the compressed read-out the display uses (as on the DHO800/DHO900);
- the **record**: for one measurement mode it sets the wave range and TX information for up to one million points,
  requests a read-out of the memory and splits it by channel as in section 5 (assumed: the "full record" range of
  the measurements).

OOS's measurements already work this way on every board: `oos-dsp` computes them from frames in volts, the screen
gate from the displayed record and the full-record gate from the retained memory (docs/measurement-modules.md). Once
the MHO900 board delivers frames (`Board`, ui/src/board/mho), the whole measurement pipeline carries over unchanged.
What the board must deliver for it: the frames in volts with their sample interval, and the retained deep record for
the full-record gate.

## 7. Checking it on a unit

`tools/mho-check.py <scope-ip>` checks on an MHO900 under its stock system what can be seen without writing to the
hardware, and writes `mho-check-<model>-<date>.txt` to attach to the GitHub issue. It needs Python 3 and adb on the
PC, network adb and SCPI (port 5555) on the scope; like `tools/platform-probe.sh` it restarts adbd as root.

| check | what it looks at | expected |
|---|---|---|
| S1 to S3 | hardware code, `version.txt`, `/rigol/FPGA` | the image table of section 1, this unit's image present |
| S4 | GPIO0_A1, GPIO0_A2, GPIO1_A0, GPIO3_D0 | outputs at 1 (not the supplies on code 1), the probe detect an input |
| S5, S6 | modules and device nodes | the drivers and devices of section 1 and 2; the `/dev/spidev*` there recorded |
| S7, S8 | PCIe | `10ee:7024`, a BAR of 16 MiB |
| S9 | clock tables | 136 TI register words each (only counted, not copied) |
| S10, S11 | open devices, kernel log | recorded; the FPGA configured: its PCIe endpoint enumerates after the load (the DONE the driver logs when it requests the line comes before the load and is 0) |
| R1 to R4 | registers read once | the blocks answer; 0x3000 holds a finished bridge word (strobe 0, one ADC) |
| R5 to R9 | 0x4008 with CH1, CH1+2, CH1 to 4, CH1 to 3 | channel mask 0x1, 0x3, 0xf; roll and scan off at 1 us/div |
| R10 | 0x10e4 at 1k and 1M points | the record depth changes |
| R11 | 0x40b0/0x40b4 while running | the time stamp moves |
| R12 | 0x4008 at 200 ms/div | roll or scan bit set |
| R13 | 0x4004, 0x4034, 0x4100 in STOP | recorded |
| R14 | 0x2438 and 0x6110 with the mask test off, on and running | the mask block follows; unchanged is recorded (the test may need a mask, and the check makes none) |
| R15 | waveform preamble in WORD at 0.1 and 1 V/div | 7500 codes per division, centre 32768 |
| R16 | the settings again | each written back on its own (the memory depth as `10k`, `1M` ...: the number its query answers is refused), then read and compared with before |

Registers are read with the stock tool `/rigol/tools/pcie2dev`, always with exactly one address (it writes when it is
given two), and only at addresses the stock system uses itself: a read of an address the FPGA does not decode could
stop the processor. The settings it changes over SCPI are read first and set back at the end; `--no-scpi` leaves
them alone and skips R5 to R15. Not covered: the read-out stream itself, the interleave of the words and the ADC
bridge's writes in full (they would need the application stopped or writes to the hardware).

`tools/mho-check.py <scope-ip> --map` runs none of the checks but maps what section 8 leaves open about the front ends
and the sample path. It steps through about 55 settings with nothing connected to the inputs: the scale of CH1 from
1 mV/div to 10 V/div, its offset, coupling and bandwidth limit, each other channel on at two scales, the time base
from 2 ns/div to 1 ms/div with one, two and four channels, the bandwidth limit of each channel with all four on (one
channel per ADC lane), and the trigger level (`--fifty` adds each channel at 50 ohm at three scales). After each step
it records what changed against the step before:

- the FPGA's configuration registers that the stock system writes itself (analog gain and offset per ADC lane, the
  gain and offsets after the ADC, the AFE and probe offset DACs, sample rate, interpolation, delays, trigger levels,
  the PWM outputs), read back with `pcie2dev`;
- the GPIO lines of `/sys/kernel/debug/gpio`, among them the front ends' select lines;
- the words seen in the ADC bridge (0x3000) while the setting changed, about 120 reads: some of the ADC register
  writes the change makes, as written (with the stock system's mask applied);
- new lines of the kernel log.

The settings it changes are read first and set back one by one at the end, and compared again. The report,
`mho-map-<model>-<date>.txt`, ends with every register per step as a table. Each channel is switched on before its
own settings are written back: on an MHO98 the stock system did not take the scale of a channel that was off, and
CH2 to CH4 stayed at 10 mV/div.

`tools/mho-check.py <scope-ip> --afe` records what `--map` cannot see: the words the stock system sends to the front
ends (driver `spi2afe_gpio`: chip selects gpio 76, 66, 69, 68 for cs0 to cs3, clock 75, data out 74, data in 73) and
to the clock chip (3-wire bus: chip select 50, clock 49, data 51), and the select lines `a`, `b`, `c`. It switches on
the kernel's trace event `gpio_value`, filtered to these lines, records it around each setting, and switches it off
again with the trace settings as they were; tracefs lives in memory, nothing else is written. The words are decoded on
the PC: one frame per chip-select low, and what the driver reads. A front-end frame of 24 clocks is shown as channel,
register and data (the format of section 8); other frames show the data line at the rising and at the falling clock
edge. The steps are those of `--map`, an idle step first (what the stock system writes by itself), then the offset and
AC coupling of CH1 at 10 mV/div and 1 V/div, and every scale, the offset, coupling and bandwidth limit of CH2 to CH4
(`--fifty`: each channel at 50 ohm). CH1 stays on while CH2 to CH4 are stepped: it changes none of their words.
Each step lists the front-end registers that changed. It needs the event in the
kernel (4.4 has it when tracing is built in; the stock kernel mounts tracefs) and adb root. The report is
`mho-afe-<model>-<date>.txt`; it ends with the front-end registers per step as a table and the raw events.

`tools/mho-check.py <scope-ip> --snapshot` takes one setting of the stock system whole, for the first acquisition
under OOS. It switches each channel that is off on and off again: switching a channel on sends its set of
front-end words (25 frames, section 8), which it records with the trace event of `--afe`. The first channel that got
its set is the snapshot's channel: the owner connects the probe compensation output
to it, and the tool steps it through every scale (28 frames each), then sets it to 1 V/div (0.1 V/div when the signal
is under 1 V peak to peak, behind a 10:1 probe), 1 MOhm, DC, 200 us/div, edge trigger at the signal's mean, and lets
the stock system acquire. Then it reads the select lines, the FPGA's configuration registers (the offsets of section
3 the stock system uses in the SPU, TPU and SCU blocks, the JESD204 receiver, the PWM words and 0x30000; not the DNA),
the 128 registers of each ADC through the bridge of section 4, twice (a register counts when both reads are valid and
equal), and the stock system's measurements and trace of the signal as a reference. Everything is set back. The
report `mho-snapshot-<model>-<date>.txt` ends with a part for OOS, after the line `---- oos snapshot ----`:
`key value` lines (`format 1`, `model`, `hwcode`, `channel`, `scale`, `timebase`, `trigger-level`), `afe STEP REG
DATA` in the order the stock system sent them (`on` the whole set, `base`, `scale=V` per scale), `select LINE LEVEL`,
`fpga OFFSET VALUE` and `adc N REG DATA`, all hex, then `end`. The values in it are the unit's own (section 8); OOS
reads them from the file on the unit and ships none (ADR 0013).

`tools/mho-check.py <scope-ip> --capture-all` records the stock system's cold start of the acquisition board, then
takes the snapshot. It stops the stock scope program, unloads xdma and the PCIe host, loads the FPGA again with the
stock tool of the start script (`spi2fpga`, section 1) and the PCIe drivers with the stock script (`load_pcie.sh`), and
starts the program again, as at power-on. Meanwhile the trace event of `--afe` records the board's GPIO lines, and
`mho-poll` (a static program of OOS, pushed over adb) watches the ADC bridge word 0x3000, the link reset 0x2003c and
0x10120 from a read-only mapping. Each ADC transfer leaves its word in 0x3000 for at least 100 us (section 4); the
watcher reads it about once a microsecond, and its file says how fast it read (`loop_us`). It opens the device only
after `load_pcie.sh`, so it never holds it while the drivers are unloaded. At its start it writes a mark into the
kernel's trace buffer, which puts both records on one time line. The report `mho-capture-<model>-<date>.txt` ends,
after the line `---- oos capture ----`, with `format 1`, the steps in the order the stock program made them in the
recipe form of section 10 (`adc`, `adcread`, `afe`, `select`, `wr`, and `wait` for pauses over 2 ms), then `end`.
The ADC words are the ones the stock program wrote, its masks applied.

`tools/mho-settings.py <scope-ip>` (with `mho-check.py` next to it) records what the stock system sets per setting,
for OOS to set the same: at a fixed depth of 10 k points it steps over SCPI, for each channel alone, through the time
bases from 2 ns/div to 100 ms/div and through every scale at 200 us/div, then through the time bases with all four
channels on and every combination of channels at 1 us/div, and sets everything back. The first version (mho-dev-17)
left the depth to the scope: after 50 ms/div the stock system kept 1 M points, so its later settings were taken at
another depth than the first (an MHO934, issue #248). For each setting it records the scope's own report of it (channels, scales,
time base, sample rate, depth), the FPGA's configuration registers of the snapshot's list, the front-end words sent
while it changed and the select lines, and where the sampling changes (the time bases and the channel combinations)
the 128 registers of each ADC. The report `mho-settings-<model>-<date>.txt` ends, after `---- oos settings ----`,
with `format 1`, `model`, `hwcode`, then per setting `setting NAME`, its `scpi` lines, a `state` line, `fpga`, `adc`,
`afe` and `select` lines and `endsetting`, then `end`.

With `--extended` it records, after those settings, what a channel's vertical settings and several channels at once
need: for each channel alone at 200 us/div and 10 k points the offset from -4 to +4 divisions at 10 mV, 100 mV and
1 V/div (set to 0 V before each scale), the coupling (AC, GND, DC), the bandwidth limits 20M and 250M (a limit the
model lacks is answered with an SCPI error, which the report keeps) and 50 ohm; then every combination of two and
three channels at the time bases of `--quick`, the ADCs read at the first. Their names (`CHn_offset=V_at=S`,
`CHn_coupling=`, `CHn_bwlimit=`, `CHn_impedance=`, `combo=`) are none of the names OOS reads a time base or a scale
from, so the file reads as without `--extended`. Every `state` line then also holds `offset1..4`, `coupling1..4`,
`bwlimit1..4` and `imp1..4`.
Last, for each channel alone at 200 us/div with the edge trigger on it, it sets the trigger level to +2 divisions at
every scale (`CHn_trig=L_at=S`), at 100 mV/div once more with an offset of -2 divisions and once on the falling slope:
the TPU's level words of those settings give the gain the stock system converts a level with. On an MHO98 that gain
was not the read-out's 7500 codes per division but 6720 at 100 mV/div, 7253 at 1 V/div and 7477 at 10 mV/div, with
a hysteresis of 0.3 division at the same gain, and the level words the same for both slopes (only 0x201c changes);
**verified on the unit** (GitHub issue #4). `--trigger-only` takes only those steps.

`tools/mho-check.py <scope-ip> --afe-init` records the front ends' set-up at the start of the stock scope program:
it switches on the trace event of `--afe` (a 16 MiB buffer in memory), restarts the program (`am force-stop`;
Android's launcher starts it again, else `monkey` does), records for about half a minute, and sets the trace back.
The report `mho-afe-init-<model>-<date>.txt` lists the frames of every channel and the select lines' changes in
order and ends, after the line `---- oos afe init ----`, with a part for OOS: `format 1`, `afe CH REG DATA` and
`select NAME LEVEL` in the order they happened, then `end`.

## 8. Seen on units (stock system 00.01.00, hardware code 3)

From `mho-check.py` on an MHO954 (twice) and an MHO98 and `--map` on an MHO98 and the MHO954 (issue #4),
`mho-check.py`, `--map` (twice) and `--afe` with `--fifty` on an MHO934 (issue #248), `--afe` on the MHO954 and on
two MHO98 of different owners (issue #4), and `--map` and `--afe` with 50 ohm on a third MHO98 (issue #491);
**verified on the unit** means read on these units under the stock system,
nothing of it driven by OOS:

- The MHO934 is the same board: its platform probe is the MHO954's but for the licence files, all 25 checks as
  assumed (with `/dev/spidev2.0` and `/dev/spidev5.0`, and the mask block as on the MHO954), and its `--map` changes
  the same registers at the same steps as the MHO98's. Only calibrated values differ (lane gain and offset, 0x1058,
  the trigger level words) and bits that also change at steps that do not touch them (0x4008, bit 4 of 0x1004). The
  platform probe of the second MHO98 shows the same board again.
- All 25 checks of the MHO954 as assumed, with the spidevs `/dev/spidev2.0` and `/dev/spidev5.0`, also as root. The
  MHO98's three differences were the check's own (S6, S11) or are explained by the mask block below (R14).
- Mask block: 0x6110 is 0x00100000 while the mask test runs, 0 when it is off or on and stopped; 0x2438 stays 0
  (verified on the unit, MHO954, twice).
- The analog gain and offset words 0x14c8 to 0x14f4 belong to the four ADC **lanes**, not to the channels: with CH1
  alone all four hold CH1's values, with two channels lanes 1 and 3 hold CH1's and lanes 2 and 4 the other's, with four
  channels each its own (verified on the unit). With GND coupling the lane's gain is 0 and its offset 0x8000.
- AC coupling changes nothing `--map` reads; the offset changes no register but the trigger level words, and moves
  the data line of the front ends' bus (verified on the unit). Both are set over that bus: one word each, in
  registers 0x07 and 0x28 of the channel's front end (verified on the unit, `--afe`, below).
- Bandwidth limit 20 MHz: one bit per ADC lane in 0x1004 and in 0x1014, bit 20 + lane. With all four channels on,
  CH1's limit sets bit 20, CH2's bit 21, CH3's bit 22, CH4's bit 23 (0x1004 0x04004a50 to 0x04104a50 ... 0x04804a50);
  with CH1 alone, which is on all four lanes, bits 23:20 go to 0xf (verified on the unit, MHO934; CH1 alone also
  MHO98). The limit also changes that lane's analog offset word by a few codes.
- The scope has no 500 uV/div step: it takes `:CHANnel<n>:SCALe 0.0005` as 1 mV/div, sends the same front-end words
  and sets the same lane gain on every channel of four units, and the MHO934's menu ends at 1 mV/div (verified on the
  unit). `mho-check.py` steps from 1 mV/div since version 5.
- Select lines: each channel has a group of three, `a`, `b` and `c` (names of the stock driver): CH1 149, 152, 153;
  CH2 129, 130, 131; CH3 125, 126, 127; CH4 122, 123, 124. At 1 MOhm `c` is high at 0.1 and 0.2 V/div and `a` at 5
  and 10 V/div, both low between; at 50 ohm `c` stays low and `a` is high at 1 V/div. `b` changed in no step. The
  same on every channel of four units (verified on the unit).
- Sample rate: one channel 4 GSa/s from 2 to 100 ns/div, with interpolation at 2 and 10 ns/div (0x1154, 0x115c,
  0x1168), 1 GSa/s at 1 us/div; 0x10d0 is 0x8001, 0x8002, 0x8004 or 0x8008 at the higher rates and 0 below them,
  where 0x10d8 divides 250 MSa/s (5, 25, 250 give 50, 10, 1 MSa/s). The segment size 0x10e0 is 0x200, 0x400 and
  0x800 with one, two and three or four channels (verified on the unit).
- The front ends' bus (`--afe`: MHO934, MHO954, two MHO98):
  - A write frame is 24 bits, MSB first: the driver sets the data line, then the clock low and high, so a bit is
    valid at the rising edge. Register address in bits 23:16, data in bits 15:0. The clock rests low (SPI mode 0): it
    is low when the chip select falls and goes low once more after each byte, and each half period is about 7 us (raw
    events of a scale change, an MHO98, `--afe`). That is the bus of the DHO800/DHO900 (`dho::afe::GpioAfe`). OOS
    drove it with the clock resting high and without pauses up to mho-dev-14, and no front end took a word: every
    register and the status read 0x0000ff (two MHO98, mho-dev-13, issues #4 and #491).
  - A read frame is 32 clocks: the driver sends 0x80 (assumed: bit 7 read, register 0) and 24 bits come back on the
    data-in line. The stock system reads twice, 2 ms apart, every few hundred ms while a channel is at 50 ohm, and once
    more when it goes back to 1 MOhm; nowhere else. It read 0x0c40ff at 50 ohm and 0x0440ff after (MHO934, every
    channel; the same on every channel of the third MHO98). Assumed: bit 19 is a state of the 50 ohm path, and the
    reads watch it for an overload.
  - Chip select per channel: CH1 cs3 (gpio 68), CH2 cs2 (gpio 69), CH3 cs1 (gpio 66), CH4 cs0 (gpio 76).
  - A scale change sends 28 frames in a fixed order (some registers two or three times), the offset one frame
    (0x28), AC or DC coupling one (0x07), the bandwidth limit the scale's 28 frames with 0x2e and 0x28 changed. A
    channel switched on gets 25 frames: 0x2f, 0x2c, 0x2d, 0x23, 0x29, 0x2a, 0x07, 0x2e, 0x2b, 0x35, 0x27, 0x06, 0x24,
    0x25, 0x28, some of them twice or three times (MHO934, `--snapshot`, every channel switched on after a power-on,
    three runs; the 53 frames `--afe` saw at its step "on, 1 V/div" were these and the scale's 28). 0x20 and 0x21 come
    with the scale; 0x22, 0x26 and 0x36 with neither. GND coupling, the time base, the trigger level and switching a
    channel off send nothing, and nothing is sent while the scope runs untouched.
    No frame went over the clock chip's bus in any step.
  - 50 ohm (MHO934 and the third MHO98, every channel): about 70 frames, among them a run of writes to 0x2c and 0x2d
    with the values stepping (assumed: a trim of the 50 ohm path), then 0x07 with bit 13 set (0xe440 at 10 mV/div,
    0xa440 at 1 V/div), 0x29 range 3, 0x2a bits 15:14 set, bit 12 of 0x23 cleared and an own offset zero in 0x28. Back
    at 1 MOhm the scale's words return, but 0x2c and 0x2d keep a changed value, the unit's own per channel (0xcd5d and
    0xc100 on CH1 of the MHO934, 0xcd5d and 0xc200 on the MHO98's; 0xcc0c and 0xc000 before on every unit), and the
    full-bandwidth word of 0x2e comes back as 0x1fcc instead of 0x1fcb (every channel of both units).

  **Which values are the unit's own.** The MHO934 sent the same words in two runs two days apart, with two exceptions:
  the offset zero in 0x28 moved by up to 12 codes, and 0x2e (below). The five units send the same registers at the same
  steps, but most values differ from unit to unit, also between the three MHO98. So they are not the model's but the
  unit's: its calibration (assumed). The same on every unit: 0x07, 0x2a (but at 5 V/div), 0x22, 0x2b, 0x2c and 0x2d (at
  1 MOhm, before 50 ohm), the range field of 0x29 and which bits switch at which scale. The unit's own: 0x06, 0x21, the
  low byte of 0x23, 0x24 to 0x27, the zero of 0x28, bits 15:10 of 0x29, 0x2f and 0x35, and at some scales bits of 0x20,
  bits 7:6 of 0x29 and bits 15:14 of 0x2e. Candidates for where the stock system takes them from are the unit's files
  `cal_afe_zero.hex`, `cal_afe_bandwidth.hex` and `cal_vertical.hex` under `/rigol/data`; `cal_afe_bandwidth.hex` and a
  `cal_tmp_hex.log` are written again at every start (their time is the start's on a second MHO98). OOS cannot ship such
  values (ADR 0013); a port reads them from the unit or measures them.

  The registers and what changed them (CH1's values of the MHO934; the other channels and units change the same
  registers at the same steps):

  | register | changes with | seen |
  |---|---|---|
  | 0x07 | coupling, scale, 50 ohm | bit 15 DC (cleared for AC); bit 14 set from 1 mV/div to 50 mV/div: 0xc440 there, 0x8440 from 0.1 V/div; bit 13 50 ohm. The same on every unit |
  | 0x28 | offset, scale, bandwidth limit, 50 ohm | the offset DAC, about 0x8000 at 0 V with the unit's own zero per scale and channel; +0.3 V at 0.1 V/div is +471 codes on all four channels, +2 V at 1 V/div +2062, +0.05 V at 10 mV/div -981 |
  | 0x29 | scale, 50 ohm | bits 9:8 the range: 0 from 1 to 5 mV/div, 1 from 10 to 50 mV/div, 2 from 0.1 V/div, 3 at 50 ohm; bits 7:6 are 10 or 01 by scale (mostly the same on every unit); bits 15:10 the unit's own per channel |
  | 0x2a | scale, 50 ohm | bits 15:12: 0 at 1 to 2 mV/div and 10 to 20 mV/div, 1 at 5 and 50 mV/div, 3 from 0.1 to 1 V/div and at 10 V/div, 0xb at 2 V/div; bits 15:14 set at 50 ohm. The same on every unit, but at 5 V/div: 2 or 3 per channel and unit (3 on CH2 and CH4 of the MHO934 and MHO954, on CH3 and CH4 of the third MHO98, 2 elsewhere) |
  | 0x2e | scale, bandwidth limit, 50 ohm | full bandwidth: bits 13:0 0x1fcb (MHO954, the three MHO98, the MHO934 since a change of its licences), 0x1dc9 on the MHO934 before; bit 11 cleared at 5 V/div; bits 15:14 01 or 10 at some scales, per unit; 0x1fcc after a channel was at 50 ohm (MHO934, third MHO98). 20 MHz limit 0x1905 on every channel of every unit |
  | 0x20, 0x21 | scale, with the select lines | 0xa038/0x03f3 at 0.1 and 0.2 V/div (`c` high), 0xa04c/0x0073 from 0.5 to 2 V/div, 0xa07e/0x06f3 at 5 and 10 V/div (`a` high; 0xa06e or 0xa05e on the other channels); 0x21 and some bits of 0x20 the unit's own |
  | 0x23 | scale, 50 ohm | bits 15:8 0x2c up to 50 mV/div, 0x14 from 0.1 V/div (bit 10 differs per unit), bit 12 cleared at 50 ohm; the low byte the unit's own |
  | 0x06, 0x27 | scale | one value per range and channel, the unit's own (0x06 of CH1: 0x1e, 0x2e, 0x0c) |
  | 0x2c, 0x2d, 0x36 | 50 ohm | 0x2c 0xcc0c and 0x2d 0xc000 on every unit until a channel was at 50 ohm; 0x36 written only then |
  | 0x22, 0x24 to 0x26, 0x2b, 0x2f, 0x35 | nothing in these steps | 0x22 0, 0x2b 0x4c5f on every unit; the others the unit's own |

  So the front end has three ranges at 1 MOhm, switched at 10 mV/div and 0.1 V/div, and a fourth at 50 ohm; the
  select lines switch at 0.1 and 0.5 V/div (`c`) and at 5 V/div (`a`).

  Assumed from the MHO934: the full-bandwidth bits 9 and 1 of 0x2e follow the licensed bandwidth. Between the two runs
  its owner installed every licence of the model, the bandwidth upgrade among them (reported in issue #248), and since
  then the MHO934 sends the MHO954's and MHO98's value. Which of the upgraded bandwidths 0x1fcb stands for (500 MHz or
  more) is open: the MHO954's licences are not known.
- 0x4008 changes between two values while nothing is changed (0x08805181 and 0xc880b1a1 at 1 us/div): it holds state
  bits besides the channel mask, so `--map` lists it at steps that do not touch it.

## 9. Open at the bench

- the LMK04821 settings and the ADC register set and masks (sections 1 and 4);
- the JESD204 link values and how to see that it is up;
- the front ends: what the registers of section 8 mean bit by bit; how the unit's own values follow from its
  calibration files (or, failing that, a table of them per unit taken under the stock system with `--afe`); what the
  50 ohm trim of 0x2c and 0x2d does and what the read of register 0 reports; which bandwidth 0x2e's full-bandwidth value stands for;
- whether the run and read-out sequences of acquisition-start.md work unchanged with the new words of section 3 left
  at their power-on values.

## 10. The first acquisition from a snapshot

**Not yet verified on hardware** (ADR 0077). `oos-fpgad mho-start` starts the board from the unit's own snapshot of
the stock system (section 7) and arms one acquisition. The order is assumed from the stock cold start (sections 1
and 4); a step that does not read back as written does not stop the run, it is reported.

1. The bring-up of docs/mho.md: supplies, clock table, FPGA image, PCIe.
2. The ADCs: every register of the snapshot that read valid and the same twice, ADC 0 then ADC 1, in address order,
   written through the bridge (section 4) with the data as read. The stock system's masks are already in that data:
   it is what the ADC holds.
3. The link: 0x2003c = 1, 5 ms, 0; the JESD204 receiver's words of the snapshot (0x20004 to 0x20818); 0x10120 with
   bit 0 set for 50 ms (assumed: the sync enable of the stock cold start), then with it cleared.
4. The FPGA's configuration: the snapshot's words in address order, the SCU's mode word 0x4008 last. Left out: the
   status and read-back words (0x11e8, 0x1208, 0x120c, 0x1210, 0x1438, 0x401c, 0x4030, 0x4034, 0x40b0, 0x40b4,
   0x40c0, 0x40c4, 0x4100) and the words the arm writes itself (0x1000, 0x4004, 0x400c, 0x4010 to 0x4018, 0x4080).
   The control words 0x4004, 0x400c, 0x1000 and 0x4080 read back with state bits: an MHO934 and an MHO98 read
   different values in the same setting, and 0x4080 with its done bit set (verified on the unit, `--snapshot`,
   issues #248 and #491). So the arm starts them from the DHO800/DHO900's stock values (assumed: the same bits), and
   of 0x4008 takes only the channel mask (bits 3:0) and bit 27, which every MHO900 read had set. The configuration
   reads back as set: the record depth 0x10e4 10000 points and the TX length 0x11f0 the same at 200 us/div, 0x10d8 50
   (250 MSa/s / 50 = 5 MSa/s, 10000 points in 2 ms), 0x4050 and 0x4054 5000 each, and 0x1004, 0x1010 and 0x4020 the
   same on both units.
5. The front ends' set-up of the stock program's start, when the unit's file of `mho-check.py --afe-init` is there
   (`/oos/mho-afe-init.txt`): every channel's frames and the select lines' changes in the order the stock program
   made them when it started. Then the front end of the snapshot's channel: the set of its switch-on, then the words
   of its scale, in the order the stock
   system sent them (section 8); then the twelve select lines at the levels the snapshot read.
6. A read-back of steps 2 and 4: how many words and registers read as in the snapshot, and the first that do not.
   A write-only register or a status bit may read otherwise and be right.
7. One acquisition with the sequences of the DHO800/DHO900 (acquisition-start.md, record-play.md): the status
   cleared, the arm, up to 2 s for 0x4080 bit 30, the play side's pass-through, the play-last read-out of 4000
   points around the record's middle, then one read of the stream. The FSM's channel mask is the snapshot's (bits
   3:0 of 0x4008). Up to three tries.

8. Diagnostics, each variant with one acquisition read and reported: the front ends' status read on all four
   channels (32 clocks, 0x80 out, 24 bits in; the stock system reads 0x0440ff at 1 MOhm, section 8), and the snapshot
   channel's registers read the same way with 0x80 | register (assumed: the stock system reads register 0 only); the FSM channel
   masks 0x1, 0x2, 0x4, 0x8 and 0xf (all four split into the words 4i+k); 0x1004 written again; and the ADC registers
   that did not read back written once more and read at once. A variant that holds the square wave ends the run with
   `RESULT: IT MEASURES in a diagnostic variant`.

**Seen on the unit** (hp197's MHO98, mho-dev-11, issue #4): every step ran, the first acquisition completed (forced
by the auto trigger after 100 ms) and its 4000 words were read: a flat line at -9 mV whose words step by 18 codes,
real samples of an input without the signal. 237 of 261 FPGA words and 93 and 109 of the ADCs' registers read back
as in the snapshot; in each eight-register block of the ADCs' lanes bit 6 of the seventh register did not (0x0044
read 0x0004), nor bit 15 of 0x0a; 0x1004 read 0x04004084 for 0x04004a84 written.

**Seen on two units** (hp197's and skluehspies' MHO98, mho-dev-12, issues #4 and #491): every channel mask and all
four lanes held flat lines of real samples, and the front ends' status read 0x0000ff on all four channels, where the
stock system reads 0x0440ff: the bus answers, but bits 18 and 10 are not set, also on the channel that got its 53
frames. Assumed: the front ends are not in their working state, because they miss the set-up the stock program gives
them when it starts (registers 0x22, 0x26 and 0x36 were in none of the recorded steps). `mho-check.py --afe-init`
records that set-up (section 7).

**Recipes.** With the capture (`/oos/mho-capture.txt`) or a recipe (`/oos/mho-recipe.txt`) on the unit,
`mho-start` runs a recipe after the bring-up instead of the steps above: one line per item, the steps in the form
`wr OFFSET VALUE`, `wait MS`, `adc N REG DATA`, `adcread N REG`, `afe CH REG DATA`, `select NAME LEVEL`, and
`plan PHASE` (a phase of the snapshot's start), `capture` (the capture's steps), `adc-sync` (every ADC register
that reads otherwise than in the snapshot written with the snapshot's value), `acquire [MASK]` (one acquisition,
reported), `status` (the front ends' status reads), `afe-power-cycle` and `label TEXT`
(hal/src/mho/recipe.rs lists them). Without a recipe but with a capture it runs the capture, then the snapshot's
link, configuration and channel, `adc-sync`, and one acquisition.

**Verified on the unit** (hp197's MHO98, mho-dev-15, issue #4, 2026-11-22): with the front ends on the bus of
section 8, the capture of the stock cold start, the snapshot's link, configuration and CH2 front end, and then the
ADC registers brought to the snapshot's values, the acquisition held the probe compensation signal: 0.000 V and
0.312 V, mean 0.156 V, as the stock system measured it (0 to 0.32 V, mean 0.156 V). All four front ends' status read
0x0440 as under the stock system, and the input relays clicked. Without the ADC step the frame was flat: the cold
start leaves the ADCs' input selection 0x54/0x55 (0x9460/0x0004 against the snapshot's 0x1803/0x0005) and the lanes'
trims (0x04, 0x05, 0x14, 0x15 ... of each eight-register block) as the program's start had them. The read-back and the diagnostics follow either way. A recipe
changes what is tried without a new build.

The verdict: the words decoded at the snapshot's scale (section 5) hold a square wave when two levels at least half a
division apart each hold a tenth of the points or more, within the screen. `oos-mho-live` then shows the frames on the
screen with oos-ui's live source (`--fpga-live --snapshot FILE`), one acquisition after the other.

## 11. The board set from the unit's recorded settings

**Not yet verified on hardware.** With the unit's recording of `tools/mho-settings.py` on the scope
(`/oos/mho-settings.txt`), the MHO900's acquisition thread of oos-ui (`oos-ui --hw`, started by `oos-mho-live`) sets
the board from the screen's keys, one channel at a time: the first channel on, its scale at the BNC and the time base
go to the nearest recorded step of each (by ratio), and the state is made from two recorded settings
(`hal/src/mho/settings.rs`):

- the channel's setting at that time base (`CHn tdiv=T`, at 1 V/div): its FPGA words, but for the words of section
  10 left out, the SCU's mode word (the arm writes it) and the words that hold live values (0x1024, 0x1028, 0x1030,
  0x1044, 0x1048, 0x1438, 0x40b8, 0x40d0, which read differently from one setting to the next with nothing changed);
- the scale: the bits its setting (`CHn scale=V`, at 200 us/div) changes against the channel at 1 V/div
  (`CHn scale=1`), laid over each word by exclusive or;
- the ADCs' registers of the channel's first time base, written where they read otherwise (their input selection,
  0x54/0x55, follows the channel; they do not change with the time base: an MHO934's recording, issue #248);
- the front end: the channel's switch-on set, then the scale's words, and the scale's select lines.

The sample interval is the reciprocal of the sample rate the stock system reported, the trigger at the pre-trigger
count 0x4050, the points read the record's depth (at most 100 000, around the trigger). The first two acquisitions
after a change are dropped while the board settles. Frames are volts at the probe tip (the screen's probe ratio).

**Seen on the unit** (hp197's MHO98, mho-dev-21, issue #4): the keys set the board on CH1 (the snapshot was CH2):
every scale from 1 mV/div to 5 V/div showed the probe compensation signal at the same 0 to 0.3 V, and the time bases
from 2 us/div to 10 ms/div at the recorded sample rates. From 1 us/div on (1 GSa/s and above) the read-out was a flat
line. The read-out's pass-through of the DHO800/DHO900 cleared the upper bits of 0x1154 that the stock system sets
(0x4c3); from mho-dev-22 on the MHO900's pass-through keeps them (`snapshot::passthrough_keeping`). That did not help:
on skluehspies' MHO98 (mho-dev-22, issue #491) the read-out from 1 GSa/s on was still a flat line at exactly 0 V
(0 V peak to peak). Besides the rate code 0x10d0 (0x8004 against 0x8008) the stock system's settings of 1 us/div and
2 us/div differ in 0x1128 (0xc0010006 against 0xc0010007) and in the SPU's filter word 0x1098 (0 against 1): from
1 GSa/s on the stock system runs the digital filter (adc-mode.md section 4.2), with coefficients its start loads
through 0x109c and OOS does not. From mho-dev-23 on the plan keeps the filter bypassed at every rate
(`settings::FILTER`, bits 1:0 = 1). **Assumed** that the unloaded filter is why the read-out was flat.

**Seen on the unit** (skluehspies' MHO98, mho-dev-22, issue #491): the keys set scale and time base up to 500 MSa/s;
at 2 us/div the falling edge of the probe compensation signal is there, but at a different place in each frame. The
recorded level words are the stock level, 0 V, the low level of that signal, so the trigger fires on noise. 0x4034 bit
6 was set at the end of every acquisition (0x4c0031e0), so it does not tell the trigger from the auto trigger's
timeout. From mho-dev-23 on the acquisition thread sets the edge trigger on the channel measured at the screen's level
and slope with the DHO800/DHO900's sequence (`tpu::edge`; **assumed** the same TPU: the stock 0x201c is the DHO's
0x00aa4100, an edge on CH1, and the level words have its layout), and the screen's log lists the status words of every
50 acquisitions. `mho-start` counts a square with one level at the end of the range as the square wave, clipped.

**Seen on the unit** (skluehspies' MHO98, mho-dev-23, issue #491): from 1 GSa/s on the read-out holds the signal (1,
2 and 4 GSa/s, 0 to 0.3 V), so the filter was it. The board's trigger fires: with the level above the signal the
acquisitions ended with status 0x4c0031a0, with the level on the signal 0x4c0031e0, so 0x4034 bit 6 is "triggered" as
on the DHO800/DHO900. At 200 us/div and 20 ms/div the edge of the set slope, rising or falling, is at the trigger
point; at 200 us/div the record sometimes lacks its first part (the trigger came before the samples before it were
recorded). From 500 MSa/s on the edge is mostly not at the trigger point and the frames show the signal's high or low
level; where an edge was in a frame, it was not always the set slope's. Not yet known: where the trigger lies in the
record at those rates. The stock system's read-out window ends 0x2d1 points past its length (0x1100 = 10 721 for
10 000 points; the DHO800/DHO900's 0x248). From mho-dev-24 on the screen's log reports, every 50 frames, how far the
edge of the set slope and level nearest the trigger point lies from it, and the screen puts its trigger point on
that edge (a software trigger on the board's frames until the offset is known).

**Seen on the unit** (skluehspies' MHO98, mho-dev-24, issue #491): at 4 GSa/s (100 and 200 ns/div) the edge was
within 2 samples of the trigger point in every frame, for minutes. At every rate below (2 GSa/s down to 5 MSa/s, with
0x10d0 = 0x8002 to 0x8008 or the second divider) it lay anywhere in the record, and from 500 MSa/s to 2 GSa/s mostly
outside it. So the board's trigger and the record meet at the ADCs' own rate only; what the stock system sets besides
for the slower rates is not known. From mho-dev-25 on a setting below 4 GSa/s by a whole ratio k of at most 100
(20 us/div and faster) is recorded at 4 GSa/s with the channel's 4 GSa/s setting, k times as deep (0x10e4, the points
before and after the trigger 0x4050/0x4054, the segment 0x10e0), and every k-th point makes the frame
(`settings::plan_fast`). The segment size is a quarter of the DHO800/DHO900's (`hz::mem_size`): that gives the stock
system's 0x200 at 10 000 points and 0x8000 at 1 000 000 (assumed between them). Slower settings keep their own rate and
the screen's software trigger.

**Seen on the unit** (skluehspies' MHO98, mho-dev-24 again, issue #491): started at 200 us/div and taken step by step
to 100 ns/div, the edge lay at the trigger point (median 1 to 2 samples) at every rate, 5 MSa/s to 4 GSa/s, with a
few frames off. In the first run, started at 100 ns/div (4 GSa/s) and taken slower, it lay anywhere below 4 GSa/s.
So the slower rates meet the trigger until the board has run at 4 GSa/s. The DHO800/DHO900's horizontal set-up
pulses the pre-processing reset (0x1000 bit 5, horizontal-config.md section 4.1, steps 13 and 14), which the plans
leave out with the rest of 0x1000. From mho-dev-26 on the acquisition thread pulses it before and after the words of
every plan (**assumed** to be what resyncs them); with a file `/oos/mho-native` every time base records at its own
rate instead of at 4 GSa/s, to compare the two.

**Seen on the unit** (skluehspies' MHO98, mho-dev-26, issue #491), both runs started at 100 ns/div (4 GSa/s) and taken
slower to 200 us/div: with every time base at its own rate the edge lay at the trigger point (median 1 to 2 samples)
at every rate, so the pre-processing reset resyncs them after 4 GSa/s. Recorded at 4 GSa/s and thinned, only about
half the frames held an edge, and 200 us/div afterwards lay anywhere again. Every acquisition ended triggered (0x4034
bit 6). At its own rate the share of frames with the set slope's edge was 90 to 100 % at 100 ns/div, 500 ns/div and
200 us/div, 60 to 80 % from 1 us/div to 20 us/div. From mho-dev-27 on each time base records at its own rate (the 4
GSa/s recording with a file `/oos/mho-fast`), and the screen's log counts the frames without the set slope's edge that
have the other slope's at the trigger point (an earlier picture at 1 us/div showed a falling edge there with the slope
set to rising).

**Seen on the unit** (skluehspies' MHO98, mho-dev-27, issue #491), started at 100 ns/div and taken slower: 100 and
200 ns/div held the edge at the trigger point in every frame, but from 500 ns/div on it lay anywhere again, as in the
first mho-dev-24 run, although the code path was mho-dev-26's that held it. So the pre-processing reset does not
resync them every time. No frame had the other slope's edge at the trigger point. The SPU control word 0x1000 reads
0x88 after the FPGA is loaded, and in all 202 recorded settings of that unit with bit 7 set (0x0578xa80 to 0x0586xa80
while it acquires, 0x80 in roll mode); the DHO800/DHO900's shadow of it is 0, so the arm's stop sequence cleared bit 7
on every acquisition. From mho-dev-28 on the MHO900's shadow keeps it (`snapshot::S1000`, **assumed** to be a setting);
with a file `/oos/mho-s1000-zero` the acquisition thread clears it as before, to compare.

**Seen on the unit** (skluehspies' MHO98, mho-dev-28, issue #491), two starts of the board one after the other: in
the first, with bit 7 kept, the slower rates lay anywhere; in the second, with it cleared, the edge lay at the
trigger point in 40 to 50 of 50 frames from 500 ns/div to 20 us/div. Over mho-dev-24 to -28 whether the slower rates
met the trigger changed from one start of the board to the next, whatever the build changed, while 4 GSa/s met it in
every start: a phase that settles at random at the start would do that. The DHO800/DHO900's cold boot fixes the ADCs'
phase with the ADC sync (0x1000 bit 1, cold-boot.md `spu_adc_sync`), which the MHO900's start never pulsed. From
mho-dev-29 on the acquisition thread pulses it after every setting (**assumed** to fix that phase; a file
`/oos/mho-no-adc-sync` leaves it out), and 0x1000 bit 7 is cleared again as on the DHO800/DHO900 (kept with a file
`/oos/mho-s1000-stock`).

**Verified on the unit** (skluehspies' MHO98, mho-dev-29, issue #491): in three starts of the board one after the
other, the edge lay at the trigger point at every time base tried (100 ns, 500 ns, 1, 2, 5, 10, 20 and 200 us/div):
the median of every block of 50 frames within 3 samples of it, nearly every frame with the edge. So the ADC sync after
a setting fixes the phase. Single frames still lie off (in about half the blocks at least one); the record's first
part missing at the slower rates (the trigger before the points before it) is the likely cause, not yet checked.

**Seen on the unit** (skluehspies' MHO98, mho-dev-29, issue #491): with CH2, CH3 or CH4 the only channel on and the
probe on it, the screen stayed flat, and the trigger did not fire (0x4034 0x4c0031a0); CH1 measured. The stock system
records CH2, CH3 or CH4 alone together with CH1: in that unit's recording 0x4008 bits 3:0 are 3, 5 and 9 (1 for CH1),
the segment 0x10e0 is twice CH1's at the same depth (0x400 against 0x200 at 10 k points), 0x1120/0x1128 carry 2 where
CH1's carry 1, the fastest rate is 2 GSa/s instead of 4, and ADC 0 keeps CH1's input mode (0x54 = 0x9460) while ADC 1
takes the channel's (0x1803, 0x3149, 0x00c5). OOS set the FSM's mask to the channel's own bit. From mho-dev-30 on the
plan takes the recorded mask, the read-out takes the points of every channel in it (twice the words for two) and keeps
the channel's: lower channel on the even words, higher on the odd ones, as on the DHO800/DHO900 (**assumed** the same
on the MHO900). After each setting the screen's log shows the levels of both channels once, so a picture of the probe
on one of them tells which words hold it. A 10:1 probe set to 10x read 2.2 V for the 3 V signal at 500 mV/div: at the
BNC that is 50 mV/div, whose range (about 4.3 divisions either side) ends at 0.22 V, so the signal was clipped; the
screen's vertical offset, which the stock system uses to bring it into range, is not yet sent to the board. The trigger: the stock system's level words hold a window around the level (0x2004
0x7760/0x8000, 0x2008 0x8000/0x8890 at 0 V and 1 V/div: about 2200 codes either side) and its auto trigger waits
0x4060 = 5 000 000 ticks at every time base; the screen showed TRIG'D at 100 us/div and slower only, where a record
holds an edge of the 1 kHz signal anyway, so whether the FPGA's trigger fires is open.
