# Optional checks against a real IVAO MTL installation. Skipped unless IVAO_MTL_DIR points to one:
#   set IVAO_MTL_DIR=D:\...\Packages\Community\IVAO_MTL      (PowerShell: $env:IVAO_MTL_DIR = "...")
#   python -m unittest discover -s tests -p test_real_mtl.py -v
# The installation is never changed: create_vmr.py runs on a copy of the aircraft.cfg files (it repairs
# "VERSION]" in place), the GUI reads the original (it only reads).

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from support import create_vmr, gui_rules, read_rules, run_script, vmr_gui

MTL = os.environ.get("IVAO_MTL_DIR")


@unittest.skipUnless(MTL and (Path(MTL) / "SimObjects" / "Airplanes").is_dir(), "IVAO_MTL_DIR not set")
class RealMtlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        copy = Path(cls._tmp.name) / "IVAO_MTL"
        source = Path(MTL)
        for cfg in (source / "SimObjects" / "Airplanes").glob("*/aircraft.cfg"):
            target = copy / cfg.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cfg, target)
        if (source / "mtl.dat").is_file():
            shutil.copyfile(source / "mtl.dat", copy / "mtl.dat")
        cls.out = Path(cls._tmp.name) / "out"
        cls.script, cls.printed = run_script(copy / "SimObjects" / "Airplanes", cls.out)
        cls.copy_library = vmr_gui.Library(copy).scan()
        cls.library = vmr_gui.Library(source).scan()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_script_and_gui_agree(self):
        self.assertEqual(read_rules(self.out / "ivaomtl.vmr"), gui_rules(self.copy_library, False))
        self.assertEqual(read_rules(self.out / "ivaomtl_standard.vmr"), gui_rules(self.copy_library, True))

    def test_gui_on_the_original_matches_the_copy(self):
        self.assertEqual(gui_rules(self.library, False), gui_rules(self.copy_library, False))

    def test_no_errors(self):
        self.assertEqual(self.library.errors, [], "repair the MTL with the MTL Installer")

    def test_rules_are_usable(self):
        rules = gui_rules(self.library, False)
        self.assertGreater(len(rules), 1000)
        for prefix, type_code, models in rules:
            self.assertRegex(prefix, r"^([A-Z]{3})?$")
            self.assertTrue(type_code and models)
        self.assertEqual(len({(p, t) for p, t, _ in rules}), len(rules))

    def test_types_with_a_house_livery_have_a_fallback(self):
        # Vojta's case: the MTL has no KLM A350-900 and no plain A359, but it has "Airbus Industries (AIB)"
        rules = {(p, t): m for p, t, m in gui_rules(self.library, False)}
        type_only = {t for p, t in rules if p == ""}
        for type_code in ("A359", "A20N", "B738", "B77W", "AT45"):
            self.assertIn(type_code, type_only, type_code)
        self.assertIn("A359AIB", rules[("", "A359")])
        self.assertIn(("AIB", "A359"), rules)
        # every type that has any livery in the rules of an airline, or a left-out livery, has a type-only rule
        # unless nothing but airline liveries exist for it
        for livery in self.library.liveries.values():
            if livery["inVmr"] and livery["airline"] in create_vmr.MANUFACTURER_CODES:
                self.assertIn(livery["type"], type_only, livery["id"])

    def test_business_jets_have_a_civil_type_only_rule(self):
        # Vojta's NetJets Europe Global: every business jet type of the MTL has a type-only rule, and a type whose
        # fallback could be a private or a military livery never gets the military one (GLF3: not the USAF C-20s)
        rules = {(p, t): m for p, t, m in gui_rules(self.library, False)}
        types = {l["type"] for l in self.library.liveries.values()}
        for type_code in ("GLEX", "GLF4", "GLF5", "GLF6", "CL30", "CL35", "CL60", "C25C", "C750", "E55P", "FA7X", "LJ45", "PC12", "PC24"):
            if type_code in types:
                self.assertIn(("", type_code), rules, type_code)
        for (prefix, type_code), models in rules.items():
            if prefix == "" and "@" in models and any("@" not in m and self.library.liveries[m]["fallback"] for m in models.split("//")):
                self.fail("military liveries in the fallback of %s: %s" % (type_code, models))

    def test_every_livery_has_a_catalog_number(self):
        self.assertEqual([l["id"] for l in self.library.liveries.values() if not l["catalogId"]], [])

    def test_mtl_dat_and_installed_liveries_match(self):
        dat = Path(MTL) / "mtl.dat"
        if not dat.is_file():
            self.skipTest("no mtl.dat")
        listed = {line.split(",", 1)[0] for line in dat.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()}
        missing = sorted(listed - set(self.library.liveries))
        self.assertEqual(missing, [], "liveries in mtl.dat that are not installed (damaged aircraft.cfg?)")


if __name__ == "__main__":
    unittest.main()
