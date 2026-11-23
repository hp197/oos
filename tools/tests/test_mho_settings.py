# SPDX-License-Identifier: GPL-2.0-or-later

"""Offline tests of tools/mho-settings.py: the steps it takes and the part it writes for OOS. No adb, no scope."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("oos_mho_settings", ROOT / "tools/mho-settings.py")
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)


class Steps(unittest.TestCase):
    def test_every_channel_combination_and_one_channel_always_on(self):
        self.assertEqual(len(ms.COMBOS), 15)
        cmds = ms.channels_commands((2, 4))
        self.assertEqual(cmds[:2], [":CHANnel2:DISPlay ON", ":CHANnel4:DISPlay ON"])
        self.assertEqual(cmds[2:], [":CHANnel1:DISPlay OFF", ":CHANnel3:DISPlay OFF"])

    def test_the_plan_reads_the_adcs_where_the_sampling_changes_only(self):
        steps = ms.plan()
        names = [n for n, _, _ in steps]
        tb = len(ms.TIMEBASES)
        self.assertEqual(len(steps), 1 + 4 * (1 + tb + 1 + 13 + 1) + 1 + tb + 1 + 15)
        adc = [n for n, _, r in steps if r]
        # once per channel alone, once for all four, and every combination
        self.assertEqual(len(adc), 4 + 1 + 15)
        self.assertIn("CH3 tdiv=2e-9", adc)
        self.assertNotIn("CH3 tdiv=1e-6", adc)
        # a fixed depth, set again before each channel: the stock system changes it at slow time bases
        self.assertIn(":ACQuire:MDEPth 10k", steps[0][1])
        alone = [c for n, c, _ in steps if n.endswith(" alone") or n == "CH1-4 on"]
        self.assertEqual(len(alone), 5)
        self.assertTrue(all(":ACQuire:MDEPth 10k" in c for c in alone))
        self.assertNotIn("CH3 scale=0.1", adc)
        self.assertIn("CH3 scale=0.1", names)
        self.assertLess(len(ms.plan(quick=True)), len(steps))

    def test_a_setting_of_the_part_for_oos(self):
        state = ms.state_line(["1", "0", "0", "0", "1.0E0", "1.0E0", "1.0E0", "1.0E0", "2.0E-4", "5.0E6", "AUTO"])
        self.assertEqual(state, "state on1=1 on2=0 on3=0 on4=0 scale1=1.0E0 scale2=1.0E0 scale3=1.0E0 scale4=1.0E0 "
                                "tdiv=2.0E-4 srate=5.0E6 mdepth=AUTO")
        lines = ms.setting_lines("CH1 tdiv=1e-6", [":TIMebase:MAIN:SCALe 1e-6"], state, {0x10d8: 5},
                                 [(0, {0x54: 0x1803})], [("CH1", 0x07, 0xc440)], [("a149", 0)])
        self.assertEqual(lines, ["setting CH1_tdiv=1e-6", "scpi :TIMebase:MAIN:SCALe 1e-6", state,
                                 "fpga 0x10d8 0x00000005", "adc 0 0x54 0x1803", "afe 1 0x07 0xc440", "select a149 0",
                                 "endsetting"])

    def test_the_extended_plan_steps_each_channels_vertical_settings_and_the_combinations(self):
        ext = ms.extended_plan()
        names = [n for n, _, _ in ext]
        self.assertEqual(len(names), len(set(names)), "every setting has a name of its own")
        self.assertFalse(set(names) & {n for n, _, _ in ms.plan()})
        per_channel = 1 + len(ms.OFFSET_SCALES) * (1 + len(ms.OFFSET_DIVS)) + 1 + 3 + len(ms.BW_LIMITS) + 1 + 2
        self.assertEqual(len(ext), 4 * per_channel + 10 * (1 + len(ms.TIMEBASES_QUICK)))
        # no name is a time base or a scale of a channel alone, which OOS reads from the names
        self.assertFalse([n for n in names if n.startswith(("CH1 tdiv=", "CH1 scale=", "CH2 tdiv=", "CH2 scale="))])
        offsets = dict((n, c) for n, c, _ in ext)
        self.assertEqual(offsets["CH3 offset=-0.4 at=0.1"], [":CHANnel3:OFFSet -0.4"])
        self.assertEqual(offsets["CH3 offset=0.04 at=0.01"], [":CHANnel3:OFFSet 0.04"])
        # the offset goes to 0 V before the scale changes, so that the stock system does not clamp it
        self.assertEqual(offsets["CH2 offset=0 at=1"], [":CHANnel2:OFFSet 0", ":CHANnel2:SCALe 1"])
        adc = [n for n, _, r in ext if r]
        self.assertEqual(adc, [f"combo={','.join(map(str, c))} tdiv=2e-9" for c in ms.COMBOS if len(c) in (2, 3)])
        self.assertTrue(all(":ACQuire:MDEPth 10k" in c for n, c, _ in ext if n.endswith((" vertical", " on"))))

    def test_the_extended_state_holds_each_channels_vertical_settings(self):
        self.assertEqual(len(ms.EXTENDED_QUERIES), len(ms.EXTENDED_KEYS))
        answers = ["1"] * len(ms.STATE_QUERIES) + ["0.3", "0", "0", "0"] + ["AC"] * 4 + ["OFF"] * 4 + ["OMEG"] * 4
        line = ms.state_line(answers, ms.EXTENDED_KEYS)
        self.assertIn(" offset1=0.3 offset2=0 ", line)
        self.assertTrue(line.endswith("imp3=OMEG imp4=OMEG"))


if __name__ == "__main__":
    unittest.main()
