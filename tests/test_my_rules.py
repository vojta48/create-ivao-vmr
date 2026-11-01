# My rules (vmr_gui_my_rules.vmr): kept between runs, cleaned up when the IVAO MTL changes, and the server
# self-test that stops by itself.

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import ROOT, ServerTestCase, TempDirTestCase, livery, make_mtl, vmr_gui, write_model

RULE_DLH = {"callsign": "DLH", "type": "A320", "models": ["A320AAF", "A320GONE"]}       # one livery no longer installed
RULE_GONE = {"callsign": "XXX", "type": "B738", "models": ["B738GONE", "B738GONE2"]}    # nothing installed any more
RULE_OK = {"callsign": "", "type": "C172", "models": ["C172"], "exactCallsign": "OKABC"}


class MyRulesFileTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "vmr_gui_my_rules.vmr"
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_file_yet(self):
        rules = vmr_gui.MyRules(self.path).load()
        self.assertIsNone(rules.rules)
        self.assertFalse(self.path.exists())

    def test_round_trip_is_a_normal_vmr(self):
        stored = vmr_gui.MyRules(self.path).save([RULE_OK, {"callsign": "csa", "type": "b738", "models": [" B738TVSWL "], "flightNumbers": "1-99"}])
        self.assertEqual(stored, [RULE_OK, {"callsign": "CSA", "type": "B738", "models": ["B738TVSWL"], "flightNumbers": "1-99"}])
        text = self.path.read_text(encoding="utf-8")
        self.assertIn('<ModelMatchRule Callsign="OKABC" TypeCode="C172" ModelName="C172" />', text)
        self.assertIn("My rules from the IVAO VMR generator", text)
        self.assertEqual(vmr_gui.MyRules(self.path).load().rules, stored)
        self.assertFalse(self.path.with_name(self.path.name + ".part").exists())

    def test_incomplete_rules_are_not_stored(self):
        stored = vmr_gui.MyRules(self.path).save([{"callsign": "AAA", "type": "", "models": ["X"]}, {"callsign": "AAA", "type": "A320", "models": []}, RULE_OK])
        self.assertEqual(stored, [RULE_OK])

    def test_empty_list_is_kept_as_an_empty_file(self):
        vmr_gui.MyRules(self.path).save([])
        self.assertEqual(vmr_gui.MyRules(self.path).load().rules, [])  # [] is not None: no migration again

    def test_a_failing_write_does_not_stop_the_program(self):
        rules = vmr_gui.MyRules(self.tmp / "missing" / "rules.vmr")
        self.assertEqual(rules.save([RULE_OK]), [RULE_OK])


class FakeLibrary:
    def __init__(self, root, installed, errors=()):
        self.airplanes = Path(root)
        self.liveries = {i: {} for i in installed}
        self.errors = list(errors)


class RemoveMissingTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "vmr_gui_my_rules.vmr"
        vmr_gui.MyRules(self.path).save([RULE_DLH, RULE_GONE, RULE_OK])
        self.rules = vmr_gui.MyRules(self.path).load()
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_liveries_and_empty_rules_are_removed(self):
        self.rules.remove_missing(FakeLibrary(self.tmp, ["A320AAF", "C172"]))
        expected = [dict(RULE_DLH, models=["A320AAF"]), RULE_OK]
        self.assertEqual(self.rules.rules, expected)
        self.assertEqual(vmr_gui.MyRules(self.path).load().rules, expected)  # written to the file
        notice = self.rules.take_notice()
        self.assertIn("Your IVAO MTL has changed.", notice)
        self.assertIn("1 of your rules was removed", notice)
        self.assertIn("XXX B738 (B738GONE, B738GONE2)", notice)
        self.assertIn("removed from 1 of your rules: DLH A320 (A320GONE)", notice)
        self.assertIsNone(self.rules.take_notice())

    def test_nothing_changes_when_everything_is_installed(self):
        before = self.path.read_bytes()
        self.rules.remove_missing(FakeLibrary(self.tmp, ["A320AAF", "A320GONE", "B738GONE", "B738GONE2", "C172"]))
        self.assertIsNone(self.rules.notice)
        self.assertEqual(self.path.read_bytes(), before)

    def test_nothing_is_removed_without_the_mtl(self):
        # no such folder, an empty MTL, and no MTL found in any simulator at all
        for library in (FakeLibrary(self.tmp / "no such folder", ["C172"]), FakeLibrary(self.tmp, []), vmr_gui.Library(None).scan()):
            rules = vmr_gui.MyRules(self.path).load()
            rules.remove_missing(library)
            self.assertEqual(len(rules.rules), 3)
            self.assertIsNone(rules.notice)

    def test_nothing_is_removed_when_the_mtl_has_problems(self):
        # a damaged aircraft.cfg: its liveries are only missing for now
        self.rules.remove_missing(FakeLibrary(self.tmp, ["C172"], errors=["IVAO_A320/aircraft.cfg: could not be read"]))
        self.assertEqual(len(self.rules.rules), 3)
        self.assertIsNone(self.rules.notice)

    def test_checked_only_once_per_run(self):
        self.rules.remove_missing(FakeLibrary(self.tmp, ["A320AAF", "A320GONE", "B738GONE", "C172"]))
        self.rules.remove_missing(FakeLibrary(self.tmp, ["C172"]))
        self.assertEqual(len(self.rules.rules), 3)

    def test_plural_message(self):
        self.rules.remove_missing(FakeLibrary(self.tmp, ["C999"]))
        notice = self.rules.take_notice()
        self.assertIn("3 of your rules were removed, because none of their liveries are installed any more", notice)
        self.assertIn("OKABC C172 (C172)", notice)  # a rule for one exact callsign is named by that callsign
        self.assertEqual(self.rules.rules, [])


class MyRulesServerTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rules_path = cls.tmp / "vmr_gui_my_rules.vmr"
        cls.app = vmr_gui.App(cls.mtl, cls.out, None, vmr_gui.MyRules(cls.rules_path).load())
        vmr_gui.Handler.app = cls.app

    def state(self):
        return json.loads(self.request("GET", "/api/state")[2])

    def test_1_no_rules_file_yet(self):
        state = self.state()
        self.assertIsNone(state["myRules"])
        self.assertIsNone(state["myRulesNotice"])

    def test_2_rules_are_saved(self):
        status, _, body = self.post_json("/api/my-rules", {"rules": [RULE_OK, {"callsign": "", "type": "", "models": []}]})
        self.assertEqual((status, json.loads(body)), (200, {"rules": [RULE_OK]}))
        self.assertEqual(vmr_gui.parse_vmr(self.rules_path.read_text(encoding="utf-8")), [RULE_OK])
        self.assertEqual(self.state()["myRules"], [RULE_OK])

    def test_3_bad_requests(self):
        for body in ({}, {"rules": "x"}, {"rules": [1, 2]}):
            self.assertEqual(self.post_json("/api/my-rules", body)[0], 400, body)
        self.assertEqual(self.state()["myRules"], [RULE_OK])

    def test_4_next_start_cleans_up_against_the_mtl(self):
        self.post_json("/api/my-rules", {"rules": [RULE_DLH, RULE_GONE, RULE_OK]})
        restarted = vmr_gui.App(self.mtl, self.out, None, vmr_gui.MyRules(self.rules_path).load())
        vmr_gui.Handler.app = restarted
        try:
            with mock.patch("builtins.print"):
                state = self.state()
            self.assertEqual(state["myRules"], [dict(RULE_DLH, models=["A320AAF"]), RULE_OK])
            self.assertIn("Your IVAO MTL has changed.", state["myRulesNotice"])
            self.assertIsNone(self.state()["myRulesNotice"])  # only once
        finally:
            vmr_gui.Handler.app = self.app


class SeveralSimulatorsTest(TempDirTestCase):
    """MSFS 2020 and 2024 can have different MTLs: a livery that only one of them has is not missing."""

    def setUp(self):
        super().setUp()
        self.rules = vmr_gui.MyRules(self.tmp / "vmr_gui_my_rules.vmr")
        self.rules.save([RULE_DLH, RULE_OK])
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_livery_in_the_other_mtl_is_kept(self):
        self.rules.remove_missing(FakeLibrary(self.tmp, ["A320AAF", "C172"]), [FakeLibrary(self.tmp, ["A320GONE"])])
        self.assertEqual(self.rules.rules, [RULE_DLH, RULE_OK])
        self.assertIsNone(self.rules.notice)

    def test_missing_everywhere_is_removed(self):
        self.rules.remove_missing(FakeLibrary(self.tmp, ["A320AAF", "C172"]), [FakeLibrary(self.tmp, ["B738X"])])
        self.assertEqual(self.rules.rules, [dict(RULE_DLH, models=["A320AAF"]), RULE_OK])

    def test_nothing_is_removed_when_the_other_mtl_has_problems(self):
        for other in (FakeLibrary(self.tmp, ["X"], errors=["damaged"]), FakeLibrary(self.tmp, []), FakeLibrary(self.tmp / "gone", ["X"])):
            rules = vmr_gui.MyRules(self.tmp / "vmr_gui_my_rules.vmr").load()
            rules.remove_missing(FakeLibrary(self.tmp, ["A320AAF", "C172"]), [other])
            self.assertEqual(rules.rules, [RULE_DLH, RULE_OK])

    def test_app_reads_the_other_simulators(self):
        # the 2020 MTL is in use and lacks F100KLM, which only the 2024 MTL has
        mtl2020 = make_mtl(self.tmp / "2020" / "IVAO_MTL")
        write_model(mtl2020 / "SimObjects" / "Airplanes", "IVAO_F100", [livery("F100DLA", "DAL", "F100", "Air Dolomiti (DLA)", 101)])
        mtl2024 = make_mtl(self.tmp / "2024" / "IVAO_MTL")
        rule = {"callsign": "KLM", "type": "F100", "models": ["F100KLM"]}
        self.rules.save([rule])
        found = [{"sim": "MSFS 2024 (Steam)", "community": str(mtl2024.parent), "mtl": str(mtl2024)},
                 {"sim": "MSFS 2020 (Steam)", "community": str(mtl2020.parent), "mtl": str(mtl2020)}]
        app = vmr_gui.App(mtl2020, self.tmp, None, vmr_gui.MyRules(self.rules.path).load(), found)
        self.assertEqual(app.checked_my_rules(), [rule])
        # with only the 2020 MTL on the computer, the livery really is gone
        app = vmr_gui.App(mtl2020, self.tmp, None, vmr_gui.MyRules(self.rules.path).load(), found[1:])
        self.assertEqual(app.checked_my_rules(), [])


class MtlChangeEndToEndTest(TempDirTestCase):
    """A livery is removed from the MTL between two runs: the rule that used only that livery disappears."""

    def test_livery_removed_from_the_mtl(self):
        mtl = make_mtl(self.tmp / "IVAO_MTL")
        path = self.tmp / "vmr_gui_my_rules.vmr"
        vmr_gui.MyRules(path).save([{"callsign": "DLH", "type": "F100", "models": ["F100KLM"]}, {"callsign": "", "type": "C172", "models": ["C172"]}])
        # the MTL Installer updates the F100: F100KLM is gone
        write_model(mtl / "SimObjects" / "Airplanes", "IVAO_F100", [livery("F100DLA", "DAL", "F100", "Air Dolomiti (DLA)", 101)])
        app = vmr_gui.App(mtl, self.tmp, None, vmr_gui.MyRules(path).load())
        with mock.patch("builtins.print"):
            rules = app.checked_my_rules()
        self.assertEqual(rules, [{"callsign": "", "type": "C172", "models": ["C172"]}])
        self.assertIn("DLH F100 (F100KLM)", app.my_rules.take_notice())


class ServerSelfTestModeTest(unittest.TestCase):
    """vmr_gui.py --no-browser with IVAO_VMR_GUI_SELFTEST=1 stops by itself with exit code 0 (used by CI)."""

    def test_server_stops_by_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, IVAO_VMR_GUI_SELFTEST="1", IVAO_VMR_GUI_SELFTEST_SECONDS="1")
            result = subprocess.run([sys.executable, str(ROOT / "vmr_gui.py"), "--no-browser", "--port", "0", "-d", tmp, "-p", tmp],
                                    env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Self-test: stopping the server.", result.stdout)
        self.assertNotIn("watchdog fired", result.stdout)


if __name__ == "__main__":
    unittest.main()
