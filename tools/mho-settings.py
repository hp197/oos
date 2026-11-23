#!/usr/bin/env python3
# Copyright (C) 2026 dekajoule
# SPDX-License-Identifier: GPL-2.0-or-later
"""Record what the stock MHO900 system sets for each setting, for OOS to set the same
(docs/protocols/mho-acquisition.md, section 7).

  mho-settings.py <scope-ip> [--adb-port 55555] [--scpi-port 5555] [--yes] [--quick] [--extended | --trigger-only]

Needs tools/mho-check.py next to it (its adb, SCPI, trace and register helpers) and the same set-up: network adb as
root, SCPI on port 5555, the stock system running. Nothing may be connected to the inputs.

It steps the stock system through the settings over SCPI, as a user would at the front panel, and records for each:
the settings as the scope reports them, the FPGA's configuration registers (pcie2dev, one address each, the list of
mho-check.py --snapshot), the words sent to the front ends while the setting changed (the trace event of --afe), the
select lines, and for the settings that change the sampling, the 128 registers of each ADC (read transfers through the
FPGA's ADC bridge, as --snapshot). The steps:

- at a fixed depth of 10 k points, for each channel alone: the time bases from 2 ns/div to 100 ms/div (the ADCs read
  at the first) and every scale at 200 us/div (the front ends' words and the lanes' gain and offset);
- the time bases with all four channels on;
- every combination of channels on, at 1 us/div, with the ADCs (their input selection follows the channels).

--extended adds, after those, what a channel's vertical settings and several channels at once need: for each channel
alone at 200 us/div the offset at 10 mV, 100 mV and 1 V/div (from -4 to +4 divisions), the coupling (AC, GND), the
bandwidth limits and 50 ohm; then every combination of two and three channels at the time bases of --quick (the ADCs
read at the first). Every setting's state then also holds each channel's offset, coupling, bandwidth limit and
impedance. Last, for each channel alone with the trigger on it, the edge trigger's level at +2 divisions at every
scale, once with an offset and once on the falling slope: the TPU's level words then show the gain the stock system
converts the level with. About 20 minutes more. --trigger-only takes only those trigger steps (about 6 minutes).

Then it sets everything back, the depth included. About 12 minutes (--quick: fewer time bases, about 6). It writes
mho-settings-<model>-<date>.txt; its last part, after `---- oos settings ----`, is what OOS reads.
"""
import argparse
import datetime
import importlib.util
import itertools
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_MARK = "---- oos settings ----"
TIMEBASES = ("2e-9", "5e-9", "1e-8", "2e-8", "5e-8", "1e-7", "2e-7", "5e-7", "1e-6", "2e-6", "5e-6", "1e-5", "2e-5",
             "5e-5", "1e-4", "2e-4", "5e-4", "1e-3", "2e-3", "5e-3", "1e-2", "2e-2", "5e-2", "1e-1")
TIMEBASES_QUICK = ("2e-9", "1e-8", "1e-7", "1e-6", "1e-5", "1e-4", "2e-4", "1e-3", "1e-2", "1e-1")
COMBOS = [c for k in (1, 2, 3, 4) for c in itertools.combinations((1, 2, 3, 4), k)]
# --extended: the scales at which the offset is stepped, the offsets in divisions, the bandwidth limits tried (a limit
# the model does not have is answered with an SCPI error, which the report keeps)
OFFSET_SCALES = ("0.01", "0.1", "1")
OFFSET_DIVS = (-4, -2, -1, 1, 2, 4)
BW_LIMITS = ("20M", "250M")
# --extended, --trigger-only: the trigger level in divisions at every scale
TRIGGER_DIVS = 2


def load_check():
    path = os.path.join(HERE, "mho-check.py")
    if not os.path.exists(path):
        sys.exit("mho-settings.py needs mho-check.py next to it (from the same release); nothing done")
    spec = importlib.util.spec_from_file_location("mho_check", path)
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)
    return mc


def channels_commands(on):
    """SCPI lines that leave exactly the channels in `on` switched on (each switched on before the others go off, so
    that one channel is always on)."""
    return ([f":CHANnel{n}:DISPlay ON" for n in on]
            + [f":CHANnel{n}:DISPlay OFF" for n in (1, 2, 3, 4) if n not in on])


def plan(quick=False):
    """[(name, [SCPI commands], read the ADCs)] in order, at a fixed depth of 10 k points: for each channel alone,
    every time base (the ADCs read at the first: they do not change with it) and every scale at 200 us/div; then the
    time bases with all four channels on, and every combination of channels at 1 us/div with the ADCs (their input
    selection follows the channels)."""
    tbs = TIMEBASES_QUICK if quick else TIMEBASES
    base = [":CHANnel1:DISPlay ON", ":ACQuire:MDEPth 10k", ":TRIGger:MODE EDGE", ":TRIGger:EDGE:SOURce CHANnel1",
            ":TRIGger:EDGE:LEVel 0", ":RUN"] + [c for n in (1, 2, 3, 4) for c in (
                f":CHANnel{n}:PROBe 1", f":CHANnel{n}:IMPedance OMEG", f":CHANnel{n}:COUPling DC",
                f":CHANnel{n}:BWLimit OFF", f":CHANnel{n}:OFFSet 0", f":CHANnel{n}:SCALe 1")]
    steps = [("base", base, False)]
    for n in (1, 2, 3, 4):
        # the depth again for every channel: after 50 ms/div the stock system set 1 M points and kept them (an MHO934,
        # issue #248)
        steps.append((f"CH{n} alone", channels_commands((n,)) + [":TIMebase:MAIN:SCALe 1e-6", ":ACQuire:MDEPth 10k",
                                                                 f":CHANnel{n}:SCALe 1"], False))
        steps += [(f"CH{n} tdiv={tb}", [f":TIMebase:MAIN:SCALe {tb}"], k == 0) for k, tb in enumerate(tbs)]
        steps.append((f"CH{n} tdiv=2e-4", [":TIMebase:MAIN:SCALe 2e-4"], False))
        steps += [(f"CH{n} scale={v}", [f":CHANnel{n}:SCALe {v}"], False) for v in MC.SCALES]
        steps.append((f"CH{n} scale=1 again", [f":CHANnel{n}:SCALe 1"], False))
    steps.append(("CH1-4 on", channels_commands((1, 2, 3, 4)) + [":TIMebase:MAIN:SCALe 1e-6", ":ACQuire:MDEPth 10k"],
                  False))
    steps += [(f"CH1-4 tdiv={tb}", [f":TIMebase:MAIN:SCALe {tb}"], k == 0) for k, tb in enumerate(tbs)]
    steps.append(("tdiv=1e-6", [":TIMebase:MAIN:SCALe 1e-6"], False))
    for c in COMBOS:
        steps.append((f"chans={','.join(map(str, c))} tdiv=1e-6", channels_commands(c), True))
    return steps


def trigger_plan():
    """[(name, [SCPI commands], read the ADCs)] of the trigger steps: for each channel alone at 200 us/div, the trigger
    on it, rising, the level at +TRIGGER_DIVS divisions at every scale; at 100 mV/div once more with an offset of -2
    divisions and once on the falling slope; then the level back to 0 V. The names start with `CHn_trig=`."""
    steps = []
    for n in (1, 2, 3, 4):
        steps.append((f"CH{n} trigger", channels_commands((n,)) + [
            ":TIMebase:MAIN:SCALe 2e-4", ":ACQuire:MDEPth 10k", f":CHANnel{n}:OFFSet 0", ":TRIGger:MODE EDGE",
            f":TRIGger:EDGE:SOURce CHANnel{n}", ":TRIGger:EDGE:SLOPe POSitive"], False))
        for v in MC.SCALES:
            level = offset_value(TRIGGER_DIVS, v)
            steps.append((f"CH{n} trig={level} at={v}", [f":CHANnel{n}:SCALe {v}", f":TRIGger:EDGE:LEVel {level}"],
                          False))
        level, off = offset_value(TRIGGER_DIVS, "0.1"), offset_value(-TRIGGER_DIVS, "0.1")
        steps += [(f"CH{n} trig={level} at=0.1 offset={off}", [f":CHANnel{n}:SCALe 0.1",
                                                              f":TRIGger:EDGE:LEVel {level}",
                                                              f":CHANnel{n}:OFFSet {off}"], False),
                  (f"CH{n} trig={level} at=0.1 falling", [f":CHANnel{n}:OFFSet 0", ":TRIGger:EDGE:SLOPe NEGative"],
                   False),
                  (f"CH{n} trig=0 at=0.1", [":TRIGger:EDGE:SLOPe POSitive", ":TRIGger:EDGE:LEVel 0"], False)]
    return steps


def offset_value(div, scale):
    """The offset of `div` divisions at `scale` V/div, as the SCPI number (no float noise: 4 * 0.1 is 0.4)."""
    return f"{div * float(scale):.6g}"


def extended_plan():
    """[(name, [SCPI commands], read the ADCs)] of --extended, after plan(): for each channel alone at 200 us/div and
    10 k points the offset in divisions at three scales, set back to 0 V before the next scale; the coupling; the
    bandwidth limits; 50 ohm. Then every combination of two and three channels at the time bases of --quick, the ADCs
    read at the first (their input selection follows the channels). The names start with the channel and a word of
    their own (`CHn_offset=`, `CHn_coupling=`, `combo=`), so that none is a setting of plan()."""
    steps = []
    for n in (1, 2, 3, 4):
        steps.append((f"CH{n} vertical", channels_commands((n,)) + [
            ":TIMebase:MAIN:SCALe 2e-4", ":ACQuire:MDEPth 10k", f":CHANnel{n}:IMPedance OMEG",
            f":CHANnel{n}:COUPling DC", f":CHANnel{n}:BWLimit OFF", f":CHANnel{n}:OFFSet 0"], False))
        for v in OFFSET_SCALES:
            steps.append((f"CH{n} offset=0 at={v}", [f":CHANnel{n}:OFFSet 0", f":CHANnel{n}:SCALe {v}"], False))
            steps += [(f"CH{n} offset={offset_value(d, v)} at={v}", [f":CHANnel{n}:OFFSet {offset_value(d, v)}"], False)
                      for d in OFFSET_DIVS]
        steps.append((f"CH{n} vertical at=0.1", [f":CHANnel{n}:OFFSet 0", f":CHANnel{n}:SCALe 0.1"], False))
        steps += [(f"CH{n} coupling={c}", [f":CHANnel{n}:COUPling {c}"], False) for c in ("AC", "GND", "DC")]
        steps += [(f"CH{n} bwlimit={b}", [f":CHANnel{n}:BWLimit {b}"], False) for b in BW_LIMITS + ("OFF",)]
        steps += [(f"CH{n} impedance=FIFTy", [f":CHANnel{n}:IMPedance FIFTy"], False),
                  (f"CH{n} impedance=OMEG", [f":CHANnel{n}:IMPedance OMEG", f":CHANnel{n}:SCALe 1"], False)]
    for c in (c for c in COMBOS if len(c) in (2, 3)):
        name = ",".join(map(str, c))
        steps.append((f"combo={name} on", channels_commands(c) + [":TIMebase:MAIN:SCALe 1e-6",
                                                                  ":ACQuire:MDEPth 10k"], False))
        steps += [(f"combo={name} tdiv={tb}", [f":TIMebase:MAIN:SCALe {tb}"], k == 0)
                  for k, tb in enumerate(TIMEBASES_QUICK)]
    return steps


STATE_QUERIES = ([f":CHANnel{n}:DISPlay?" for n in (1, 2, 3, 4)] + [f":CHANnel{n}:SCALe?" for n in (1, 2, 3, 4)]
                 + [":TIMebase:MAIN:SCALe?", ":ACQuire:SRATe?", ":ACQuire:MDEPth?"])
STATE_KEYS = [f"on{n}" for n in (1, 2, 3, 4)] + [f"scale{n}" for n in (1, 2, 3, 4)] + ["tdiv", "srate", "mdepth"]
# --extended: each channel's vertical settings too
VERTICAL = (("offset", "OFFSet"), ("coupling", "COUPling"), ("bwlimit", "BWLimit"), ("imp", "IMPedance"))
EXTENDED_QUERIES = STATE_QUERIES + [f":CHANnel{n}:{q}?" for _, q in VERTICAL for n in (1, 2, 3, 4)]
EXTENDED_KEYS = STATE_KEYS + [f"{k}{n}" for k, _ in VERTICAL for n in (1, 2, 3, 4)]


def state_line(answers, keys=STATE_KEYS):
    """`state KEY=VALUE ...` of the queries' answers, the keys short: on1..on4, scale1..scale4, tdiv, srate, mdepth
    (and with --extended offset1..4, coupling1..4, bwlimit1..4, imp1..4)."""
    return "state " + " ".join(f"{k}={(v or '-').replace(' ', '')}" for k, v in zip(keys, answers))


def setting_lines(name, commands, state, regs, adc, frames, selects):
    """One setting of the part for OOS: `setting NAME`, its commands, its state, `fpga`, `adc`, `afe` (the frames sent
    while it changed, in order) and `select` lines, `endsetting`."""
    out = [f"setting {name.replace(' ', '_')}"] + [f"scpi {c}" for c in commands] + [state]
    out += [f"fpga 0x{a:x} 0x{v:08x}" for a, v in sorted(regs.items())]
    out += [f"adc {n} 0x{r:02x} 0x{d:04x}" for n, vals in adc for r, d in sorted(vals.items())]
    out += [f"afe {ch[2:]} 0x{r:02x} 0x{d:04x}" for ch, r, d in frames]
    out += [f"select {name_} {v}" for name_, v in selects]
    return out + ["endsetting"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("host")
    ap.add_argument("--adb-port", type=int, default=55555)
    ap.add_argument("--scpi-port", type=int, default=5555)
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--quick", action="store_true", help="fewer time bases (about 6 minutes)")
    ap.add_argument("--extended", action="store_true",
                    help="also the offset, coupling, bandwidth limit, 50 ohm, the combinations of two and three "
                    "channels at several time bases and the trigger level at every scale (about 20 minutes more)")
    ap.add_argument("--trigger-only", action="store_true",
                    help="only the trigger level at every scale of each channel (about 6 minutes)")
    a = ap.parse_args()
    adb = MC.Adb(f"{a.host}:{a.adb_port}")
    adb.connect()
    if "sparrow3_" not in adb.sh("ls /rigol/FPGA"):
        sys.exit("this is not an MHO900 under its stock system. Under OOS? Power the scope off and on: OOS starts "
                 "once after an install, the next start is the stock system. Nothing done")
    if not adb.is_root():
        sys.exit("mho-settings.py needs adb root; nothing done")
    if "pcie2dev" not in adb.sh(f"ls {MC.PCIE2DEV}"):
        sys.exit(f"{MC.PCIE2DEV} is missing; nothing done")
    tracer = MC.Tracer(adb)
    why = tracer.available()
    if why:
        sys.exit(f"mho-settings.py: {why}; nothing done")
    if a.trigger_only:
        steps, a.extended = plan(a.quick)[:1] + trigger_plan(), True
        minutes = 6
    else:
        steps = plan(a.quick) + (extended_plan() + trigger_plan() if a.extended else [])
        minutes = (6 if a.quick else 15) + (20 if a.extended else 0)
    queries, keys = (EXTENDED_QUERIES, EXTENDED_KEYS) if a.extended else (STATE_QUERIES, STATE_KEYS)
    if not a.yes:
        ans = input(f"mho-settings.py steps the stock system through {len(steps)} settings over SCPI (time bases, "
                    "channels, scales) and records what it sets in the FPGA, the ADCs and the front ends, then sets "
                    f"everything back (about {minutes} minutes). Nothing may be connected to the inputs. "
                    "Go on? [y/N] ")
        if ans.strip().lower() not in ("y", "yes", "j", "ja"):
            sys.exit("declined; nothing done")
    scpi = MC.Scpi(a.host, a.scpi_port)
    idn = MC.idn_without_serial(scpi.query("*IDN?"))
    model = (idn.split(",")[1].strip() if idn.count(",") >= 3 else "MHO900").replace(" ", "")
    code = adb.sh("cat /sys/class/hdcode/hdcode_dev/hdcode_value").strip()
    cmds = MC.snapshot_restore_list() + [":ACQuire:MDEPth", ":TRIGger:EDGE:SLOPe"]
    keep = {c + "?": scpi.query(c + "?") for c in MC.query_list(cmds) + [":TRIGger:STATus"]}
    levels = {}
    for g, line in MC.gpio_lines(adb.sh("cat /sys/kernel/debug/gpio")).items():
        if g in MC.traced_lines():
            levels[g] = 1 if line.split()[-1] == "hi" else 0
    now = f"{datetime.datetime.now():%Y-%m-%d %H:%M}"
    out = [f"mho-settings (OOS tools/mho-settings.py, mho-check {MC.VERSION}), {now}",
           f"instrument: {idn}", f"hardware code: {code}", f"settings before: {len(keep)} kept"]
    part = [SETTINGS_MARK, "format 1", f"model {model}", f"hwcode {code}"]
    rep = MC.Report()
    t_start = time.time()
    try:
        tracer.start(buffer_kb=8192)
        try:
            for i, (name, commands, read_adc) in enumerate(steps):
                print(f"  {i + 1:3}/{len(steps)} {name}")

                def act():
                    for c in commands:
                        scpi.write(c)
                ev = MC.parse_trace(tracer.record(act, seconds=1.0))
                err = scpi.errors()
                frames = [reg for t, cs, n, rise, fall, miso in MC.decode_bus(ev, MC.AFE_BUS, levels)
                          for reg in [MC.afe_register(cs, n, rise)] if reg]
                for _, g, op, v in ev:
                    if op == "set":
                        levels[g] = v
                state = state_line([scpi.query(q) for q in queries], keys)
                regs = {}
                for k in range(0, len(MC.SNAPSHOT_REGS), MC.SHELL_CHUNK * 4):
                    regs.update(adb.regs(MC.SNAPSHOT_REGS[k:k + MC.SHELL_CHUNK * 4]))
                adc = []
                if read_adc:
                    for n in (0, 1):
                        first = MC.adc_pass(adb, n)
                        good = {r: x & 0xFFFF for r, x in enumerate(first) if x & (1 << 16)}
                        adc.append((n, good))
                selects = [(MC.SELECT_LINES[g].replace(" ", ""), levels.get(g, 0)) for g in sorted(MC.SELECT_LINES)]
                out.append(f"{name}: {len(frames)} front-end frames, {len(regs)} FPGA words, "
                           f"{sum(len(v) for _, v in adc)} ADC registers"
                           + (f"; SCPI: {'; '.join(err)}" if err else ""))
                part += setting_lines(name, commands, state, regs, adc, frames, selects)
        finally:
            left = tracer.stop()
            out.append("trace settings: " + ("as before" if not left else "NOT ALL SET BACK: " + "; ".join(left)))
    finally:
        MC.restore(scpi, rep, keep, cmds)
        out += [f"{s} {k} {t}: {d}" for k, t, s, d in rep.results]
    out.append(f"took {time.time() - t_start:.0f} s")
    out += ["", "The part below is for OOS (copy the file to the scope as /oos/mho-settings.txt); please leave it "
            "as it is.", *part, "end"]
    fname = f"mho-settings-{model}-{datetime.datetime.now():%Y%m%d-%H%M%S}.txt"
    with open(fname, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"written: {fname} - please attach it to the GitHub issue")


MC = load_check()

if __name__ == "__main__":
    main()
