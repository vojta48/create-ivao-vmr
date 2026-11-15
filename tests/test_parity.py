# create_vmr.py and the GUI must generate exactly the same rules (AGENTS.md, invariant 1).

import tempfile
import unittest
from pathlib import Path

from support import FALLBACKS, LEFT_OUT, gui_rules, livery, make_mtl, read_rules, run_script, vmr_gui, write_model


class ParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.mtl = make_mtl(Path(cls._tmp.name) / "IVAO_MTL")
        airplanes = cls.mtl / "SimObjects" / "Airplanes"
        # problems both have to handle the same way
        write_model(airplanes, "IVAO_ODD", [
            livery("NOTYPE", "NTY", "", "No type (NTY)"),
            livery("A320UQ", "UQA", "A320", "Unquoted (UQA)", quoted=False),
            livery("A320AAF", "DUP", "A320", "Duplicate title (DUP)"),
        ])
        cls.out = Path(cls._tmp.name) / "out"
        cls.script, _ = run_script(airplanes, cls.out)
        cls.library = vmr_gui.Library(cls.mtl).scan()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_all_liveries(self):
        self.assertEqual(read_rules(self.out / "ivaomtl.vmr"), gui_rules(self.library, False))

    def test_standard_liveries(self):
        self.assertEqual(read_rules(self.out / "ivaomtl_standard.vmr"), gui_rules(self.library, True))

    def test_same_problems(self):
        self.assertEqual(len(set(self.script.errored_files)), 1)
        self.assertEqual(len(self.library.errors), 2)
        self.assertTrue(all("IVAO_ODD" in e for e in self.library.errors))

    def test_expected_rules(self):
        rules = {(a, t): m for a, t, m in gui_rules(self.library, False)}
        self.assertEqual(rules[("DLA", "F100")], ("F100DLA",))
        self.assertEqual(rules[("KLM", "F100")], ("F100KLM",))
        self.assertEqual(rules[("EZY", "B737")], ("B737EZY",))
        self.assertEqual(rules[("BBJ", "B737")], ("B737ZZZWL7",))
        self.assertEqual(rules[("", "B737")], ("B737",))
        self.assertEqual(rules[("", "C172")], ("C172",))
        self.assertEqual(rules[("USN", "F14")], ("F14@UN",))
        self.assertEqual(rules[("", "ZZZZ")], ("ZZZZSHP", "ZZZZHAB"))
        self.assertEqual(rules[("AAF", "A320")], ("A320AAF", "A320AAF2", "A320AAFWL"))
        self.assertEqual(rules[("UQA", "A320")], ("A320UQ",))
        self.assertEqual(rules[("", "HAR")], ("HAR",))
        self.assertEqual(rules[("UAE", "A388")], ("A388UAE", "A388UAE2"))
        # the fallbacks of the types without a plain model: the house livery keeps its own rule too
        self.assertEqual(rules[("", "F14")], ("F14@IR",))
        self.assertEqual(rules[("", "A359")], ("A359AIB",))
        self.assertEqual(rules[("AIB", "A359")], ("A359AIB",))
        self.assertEqual(rules[("DLH", "A359")], ("A359DLH",))
        self.assertEqual(rules[("", "H25B")], ("H25BZZZ",))
        self.assertEqual(rules[("ABC", "H25B")], ("H25BABC",))
        self.assertNotIn(("NBA", "A388"), rules)
        self.assertNotIn(("DUP", "A320"), rules)
        for prefix, _ in rules:
            self.assertTrue(prefix == "" or (len(prefix) == 3 and prefix.isalpha() and prefix.isupper() and prefix != "ZZZ"), prefix)
        self.assertFalse(LEFT_OUT & {m for models in rules.values() for m in models})

    def test_standard_only(self):
        rules = {(a, t): m for a, t, m in gui_rules(self.library, True)}
        self.assertEqual(rules[("AAF", "A320")], ("A320AAF", "A320AAFWL"))
        self.assertEqual(rules[("XYZ", "A320")], ("A320XYZ2",))
        self.assertEqual(set(rules), {(a, t) for a, t, _ in gui_rules(self.library, False)})

    def test_same_liveries_left_out(self):
        in_fallback = {t for titles in self.script.fallback_rules.values() for t in titles}
        script_left_out = {t for t, info in self.script.livery_info.items() if info[0] is None and t not in in_fallback}
        gui_left_out = {l["id"] for l in self.library.liveries.values() if not l["inVmr"]}
        self.assertEqual(script_left_out, gui_left_out)
        self.assertEqual(gui_left_out, LEFT_OUT)

    def test_same_fallbacks(self):
        self.assertEqual({t: tuple(m) for t, m in self.script.fallback_rules.items()}, FALLBACKS)
        gui_fallback = {l["id"] for l in self.library.liveries.values() if l["fallback"]}
        self.assertEqual(gui_fallback, {t for titles in FALLBACKS.values() for t in titles})

    def test_rules_are_in_a_stable_order(self):
        again = vmr_gui.Library(self.mtl).scan()
        self.assertEqual(gui_rules(again, False), gui_rules(self.library, False))


if __name__ == "__main__":
    unittest.main()
