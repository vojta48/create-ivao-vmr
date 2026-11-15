# create_vmr.py as a script: reading aircraft.cfg files, repairing "VERSION]", the files it writes, the
# command line options and the AIG mode.

import contextlib
import io
import os
import stat
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

import support
from support import LEFT_OUT, TempDirTestCase, create_vmr, livery, make_mtl, read_rules, run_script, write_model


class FixVersionSectionTest(TempDirTestCase):
    def fix(self, data):
        path = self.tmp / "aircraft.cfg"
        path.write_bytes(data)
        script = __import__("importlib").reload(create_vmr)
        with contextlib.redirect_stdout(io.StringIO()):
            changed = script.fix_version_section(str(path))
        return changed, path.read_bytes(), script

    def test_repairs_only_that_line(self):
        changed, data, script = self.fix(b"\xef\xbb\xbf[fltsim.0]\r\ntitle=\"A\"\r\n  VERSION]\r\nmajor=1\r\n")
        self.assertTrue(changed)
        self.assertEqual(data, b"\xef\xbb\xbf[fltsim.0]\r\ntitle=\"A\"\r\n  [VERSION]\r\nmajor=1\r\n")
        self.assertEqual(len(script.fixed_files), 1)

    def test_last_line_without_newline(self):
        self.assertEqual(self.fix(b"a=1\nVERSION]")[1], b"a=1\n[VERSION]")

    def test_leaves_good_and_other_lines_alone(self):
        for data in (b"[VERSION]\n", b"VERSION] extra\n", b"MYVERSION]\n", b"title=VERSION]\n"):
            changed, result, _ = self.fix(data)
            self.assertFalse(changed, data)
            self.assertEqual(result, data)

    def test_missing_file(self):
        self.assertFalse(create_vmr.fix_version_section(str(self.tmp / "missing.cfg")))

    def test_read_only_file(self):
        path = self.tmp / "aircraft.cfg"
        path.write_bytes(b"VERSION]\n")
        os.chmod(path, stat.S_IREAD)
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertFalse(create_vmr.fix_version_section(str(path)))
            self.assertIn("Could not write fix", out.getvalue())
            self.assertEqual(path.read_bytes(), b"VERSION]\n")
        finally:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


class ReadModelsTest(TempDirTestCase):
    """create_model_list on aircraft.cfg files with the problems found in real MTL installations."""

    def setUp(self):
        super().setUp()
        self.airplanes = self.tmp / "SimObjects" / "Airplanes"
        self.airplanes.mkdir(parents=True)

    def run_on(self):
        return run_script(self.airplanes, self.tmp / "out")

    def test_encodings(self):
        write_model(self.airplanes, "BOM", [livery("A320BOM", "BOM", "A320", "Bom (BOM)")], encoding="utf-8-sig")
        write_model(self.airplanes, "CP", [livery("A320CPA", "CPA", "A320", "Cathay Ä (CPA)")], encoding="cp1252", newline="\r\n")
        write_model(self.airplanes, "UTF", [livery("A320ÜTF", "UTF", "A320", "Ünïcode (UTF)")])
        script, _ = self.run_on()
        self.assertEqual(script.livery_info["A320CPA"][3], "Cathay Ä (CPA)")
        self.assertIn(("UTF", "A320", ("A320ÜTF",)), read_rules(self.tmp / "out" / "ivaomtl.vmr"))
        self.assertEqual(script.errored_files, [])

    def test_duplicate_sections_and_options(self):
        write_model(self.airplanes, "DUP", [livery("A320DUP", "DUP", "A320", "Dup (DUP)")], extra="\n[VERSION]\nmajor=1\n[VERSION]\nmajor=2\n")
        script, _ = self.run_on()
        self.assertIn("A320DUP", script.livery_info)

    def test_version_bug_is_repaired_and_read(self):
        cfg = write_model(self.airplanes, "VER", [livery("A320VER", "VER", "A320", "Ver (VER)")], version_bug=True)
        script, out = self.run_on()
        self.assertIn("A320VER", script.livery_info)
        self.assertIn(b"[VERSION]", cfg.read_bytes())
        self.assertIn("broken \"VERSION]\" section header", out)

    def test_unreadable_file_is_reported(self):
        (self.airplanes / "BAD").mkdir()
        (self.airplanes / "BAD" / "aircraft.cfg").write_text("no section header\n", encoding="utf-8")
        write_model(self.airplanes, "OK", [livery("A320OK", "OKA", "A320", "Ok (OKA)")])
        script, out = self.run_on()
        self.assertEqual(len(script.errored_files), 1)
        self.assertIn("Some files had errors", out)
        self.assertIn("A320OK", script.livery_info)

    def test_skipped_liveries(self):
        write_model(self.airplanes, "SKIP", [
            livery("NOTYPE", "NTY", "", "No type (NTY)"),
            livery("A320ONE", "ONE", "A320", "One (ONE)"),
        ])
        write_model(self.airplanes, "TWICE", [livery("A320ONE", "TWO", "A320", "Two (TWO)")])
        script, _ = self.run_on()
        self.assertNotIn("NOTYPE", script.livery_info)
        self.assertEqual(script.livery_info["A320ONE"][0], "ONE")  # the first one found wins
        self.assertEqual(len(script.errored_files), 2)

    def test_unquoted_title_and_uppercase_section(self):
        cfg = write_model(self.airplanes, "UQ", [livery("A320UQ", "UQA", "A320", "Uq (UQA)", quoted=False)])
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("[fltsim.0]", "[FLTSIM.0]"), encoding="utf-8")
        script, _ = self.run_on()
        self.assertIn("A320UQ", script.livery_info)
        self.assertEqual(script.errored_files, [])

    def test_folder_without_aircraft_cfg(self):
        (self.airplanes / "AI_Sounds").mkdir()
        script, _ = self.run_on()
        self.assertEqual(script.errored_files, [])
        self.assertEqual(read_rules(self.tmp / "out" / "ivaomtl.vmr"), [])


class OutputTest(TempDirTestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls._class_tmp = tempfile.TemporaryDirectory()
        mtl = make_mtl(Path(cls._class_tmp.name) / "IVAO_MTL")
        cls.out = Path(cls._class_tmp.name) / "out" / "new folder"
        cls.script, cls.printed = run_script(mtl / "SimObjects" / "Airplanes", cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._class_tmp.cleanup()

    def test_two_files(self):
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["ivaomtl.vmr", "ivaomtl_standard.vmr"])

    def test_vmr_is_well_formed_xml(self):
        for name in ("ivaomtl.vmr", "ivaomtl_standard.vmr"):
            root = ET.parse(self.out / name).getroot()
            self.assertEqual(root.tag, "ModelMatchRuleSet")
            for rule in root:
                self.assertTrue(rule.get("TypeCode") and rule.get("ModelName"))

    def test_no_left_out_livery_in_a_vmr(self):
        for name in ("ivaomtl.vmr", "ivaomtl_standard.vmr"):
            models = {m for _, _, ms in read_rules(self.out / name) for m in ms}
            self.assertFalse(models & LEFT_OUT)

    def test_counts_printed(self):
        self.assertIn("Processed: %d textures." % len(support.ALL_TITLES), self.printed)
        self.assertIn("Special liveries left out: 2.", self.printed)  # A320AAF2, A388UAE2
        self.assertIn("Special liveries kept because the airline has no standard livery for that aircraft type: 1.", self.printed)
        self.assertIn("no airline code a callsign can start with (ZZZ, military \"@\" codes) and their type has a plain model, or because they are the invisible model: 3.", self.printed)
        self.assertIn("Type-only fallback rules for aircraft types without a plain model: 2 (1 with the manufacturer's house livery, 1 with liveries that have no airline code).", self.printed)

    def test_every_livery_is_read(self):
        self.assertEqual(sorted(self.script.livery_info), sorted(support.ALL_TITLES))
        self.assertIn("Run the script with -v to see them.", self.printed)


class VerboseTest(TempDirTestCase):
    def test_verbose_lists_the_left_out_liveries(self):
        mtl = make_mtl(self.tmp / "IVAO_MTL")
        _, printed = run_script(mtl / "SimObjects" / "Airplanes", self.tmp / "o", verbose=True)
        for title in LEFT_OUT:
            self.assertIn("No airline code, left out: " + title + " (", printed)
        self.assertNotIn("left out: F14@IR", printed)
        self.assertIn("Fallback for type F14 (no plain model): F14@IR", printed)
        self.assertIn("Fallback for type A359 (no plain model): A359AIB", printed)
        self.assertIn("Special livery: A320AAF2 (Aigle Azur (old) (AAF))", printed)
        self.assertIn("Created rule for airline DLA type F100", printed)


class OutputNamesTest(TempDirTestCase):
    def test_output_name_and_missing_directory(self):
        mtl = make_mtl(self.tmp / "IVAO_MTL")
        run_script(mtl / "SimObjects" / "Airplanes", self.tmp / "o", output_file="my.vmr")
        self.assertEqual(sorted(p.name for p in (self.tmp / "o").iterdir()), ["my.vmr", "my_standard.vmr"])

    def test_models_directory_missing(self):
        _, printed = run_script(self.tmp / "nothing", self.tmp / "o")
        self.assertIn("does not exist", printed)
        self.assertFalse((self.tmp / "o").exists())


class CommandLineTest(TempDirTestCase):
    def parse(self, *args):
        script = __import__("importlib").reload(create_vmr)
        old_cwd, old_out, old_err = os.getcwd(), sys.stdout, sys.stderr
        os.chdir(self.tmp)
        console = io.StringIO()
        try:
            with mock.patch.object(sys, "argv", ["create_vmr.py", *args]), \
                 mock.patch.object(sys, "__stdout__", console), mock.patch.object(sys, "__stderr__", console):
                try:
                    script.parse_command_line()
                finally:
                    tee = sys.stdout
                    sys.stdout, sys.stderr = old_out, old_err
                    for stream in getattr(tee, "streams", [])[1:]:
                        stream.close()
        finally:
            os.chdir(old_cwd)
        return script, console.getvalue()

    def test_defaults(self):
        script, printed = self.parse()
        self.assertEqual((script.lib, script.output_file, script.verbose, script.pause_at_end), ("ivao", "ivaomtl.vmr", False, True))
        self.assertIn("Log file:", (self.tmp / "create_vmr.log").read_text(encoding="utf-8"))
        self.assertIn("Output to:", printed)

    def test_all_options(self):
        script, _ = self.parse("-d", "models", "-o", "x.vmr", "-p", "outdir", "-v", "-n")
        self.assertEqual((script.models_directory, script.output_file, script.output_directory, script.verbose, script.pause_at_end),
                         ("models", "x.vmr", Path("outdir"), True, False))

    def test_long_options_and_aig(self):
        script, _ = self.parse("--library=aig", "--no-pause", "--verbose", "--directory", "m", "--output-directory", "p")
        self.assertEqual((script.lib, script.output_file, script.models_directory), ("aig", "aig.vmr", "m"))

    def test_bad_library_exits(self):
        with self.assertRaises(SystemExit):
            self.parse("-l", "fsltl")

    def test_unknown_option_is_printed(self):
        _, printed = self.parse("--nonsense")
        self.assertIn("not recognized", printed)


class AigTest(TempDirTestCase):
    def test_aig_library(self):
        airplanes = self.tmp / "SimObjects" / "Airplanes"
        model = airplanes / "AIG_A320"
        model.mkdir(parents=True)
        (model / "aircraft.cfg").write_text(
            '[GENERAL]\nicao_type_designator = "A320"\n\n'
            '[FLTSIM.0]\ntitle = "AIG Airbus A320 Lufthansa"\nicao_airline = "DLH"\n\n'
            '[FLTSIM.1]\ntitle = AIG Airbus A320 Generic\n', encoding="utf-8")
        script, _ = run_script(airplanes, self.tmp / "out", lib="aig", output_file="aig.vmr")
        self.assertEqual(sorted(p.name for p in (self.tmp / "out").iterdir()), ["aig.vmr"])
        self.assertEqual(sorted(read_rules(self.tmp / "out" / "aig.vmr")),
                         [("", "A320", ("AIG Airbus A320 Generic",)), ("DLH", "A320", ("AIG Airbus A320 Lufthansa",))])
        self.assertEqual(script.errored_files, [])


if __name__ == "__main__":
    import unittest
    unittest.main()
