# Reading and writing VMR files in the GUI (parse_vmr, build_vmr), reading text files and the presets.

import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from support import ROOT, TempDirTestCase, vmr_gui

HEADER = '<?xml version="1.0" encoding="utf-8"?>\n<ModelMatchRuleSet>\n'


class ParseVmrTest(unittest.TestCase):
    def test_all_attributes(self):
        rules = vmr_gui.parse_vmr(HEADER +
            '<ModelMatchRule Callsign="okabc" TypeCode="c172" ModelName="C172" />\n'
            '<ModelMatchRule CallsignPrefix=" dlh " FlightNumberRange=" 100-200 " TypeCode="A320" ModelName=" A320DLH // A320DLH2 //" />\n'
            '<ModelMatchRule CallsignPrefix="XYZ" TypeCode="B738" ModelName="B738A&amp;B" />\n'
            '</ModelMatchRuleSet>\n')
        self.assertEqual(rules, [
            {"callsign": "", "type": "C172", "models": ["C172"], "exactCallsign": "OKABC"},
            {"callsign": "DLH", "type": "A320", "models": ["A320DLH", "A320DLH2"], "flightNumbers": "100-200"},
            {"callsign": "XYZ", "type": "B738", "models": ["B738A&B"]},
        ])

    def test_model_names_keep_their_case(self):
        self.assertEqual(vmr_gui.parse_vmr(HEADER + '<ModelMatchRule TypeCode="A320" ModelName="AIG Airbus a320" /></ModelMatchRuleSet>')[0]["models"], ["AIG Airbus a320"])

    def test_missing_attributes(self):
        self.assertEqual(vmr_gui.parse_vmr("<ModelMatchRuleSet><ModelMatchRule /></ModelMatchRuleSet>"), [{"callsign": "", "type": "", "models": []}])

    def test_broken_xml_falls_back_to_regex(self):
        text = ('<ModelMatchRuleSet>\n<ModelMatchRule CallsignPrefix="CSA" TypeCode="B738" ModelName="B738TVSWL" /> \n'
                '<ModelMatchRule Callsign="OKABC" TypeCode="C172" ModelName="A&amp;B &quot;x&quot;">\n<!-- open')
        self.assertEqual(vmr_gui.parse_vmr(text), [
            {"callsign": "CSA", "type": "B738", "models": ["B738TVSWL"]},
            {"callsign": "", "type": "C172", "models": ['A&B "x"'], "exactCallsign": "OKABC"},
        ])

    def test_comment_after_root(self):
        text = HEADER + '<ModelMatchRule TypeCode="A320" ModelName="X" />\n</ModelMatchRuleSet>\n<!-- c -->\n<!-- d -->'
        self.assertEqual(len(vmr_gui.parse_vmr(text)), 1)

    def test_empty(self):
        self.assertEqual(vmr_gui.parse_vmr(""), [])
        self.assertEqual(vmr_gui.parse_vmr("not a vmr"), [])


class BuildVmrTest(unittest.TestCase):
    def test_format(self):
        text = vmr_gui.build_vmr([
            {"callsign": "DLH", "exactCallsign": "DLH1", "flightNumbers": "1-9", "type": "A320", "models": ["A", "B&C"]},
            {"callsign": "", "type": "C172", "models": ["C172"]},
        ], comment="Presets: a -- b")
        self.assertEqual(text.split("\r\n"), [
            '<?xml version="1.0" encoding="utf-8"?>',
            "<ModelMatchRuleSet>",
            '<ModelMatchRule CallsignPrefix="DLH" Callsign="DLH1" FlightNumberRange="1-9" TypeCode="A320" ModelName="A//B&amp;C" />',
            '<ModelMatchRule TypeCode="C172" ModelName="C172" />',
            "</ModelMatchRuleSet>",
            "<!-- Presets: a - - b -->",
            "<!-- VMR created by create-ivao-vmr GUI https://github.com/vojta48/create-ivao-vmr -->",
            "",
        ])
        ET.fromstring(text.split("\r\n<!--")[0].split("?>", 1)[1])

    def test_incomplete_rules_are_left_out(self):
        text = vmr_gui.build_vmr([{"callsign": "A", "type": "", "models": ["X"]}, {"callsign": "A", "type": "A320", "models": []}])
        self.assertNotIn("<ModelMatchRule ", text)

    def test_round_trip(self):
        rules = [{"callsign": "DLH", "type": "A320", "models": ["A320DLH", 'Q"uote'], "exactCallsign": "DLH1"},
                 {"callsign": "", "type": "ZZZZ", "models": ["ZZZZ"], "flightNumbers": "10-20"}]
        self.assertEqual(vmr_gui.parse_vmr(vmr_gui.build_vmr(rules, "comment")), rules)


class ReadTextTest(TempDirTestCase):
    def test_encodings(self):
        for data, expected in ((b"\xef\xbb\xbfA\xc3\xa4", "Aä"), (b"A\xe4", "Aä"), (b"plain", "plain")):
            path = self.tmp / "f.txt"
            path.write_bytes(data)
            self.assertEqual(vmr_gui._read_text(path), expected)


class PresetsTest(TempDirTestCase):
    def test_bundled_presets(self):
        presets = {p["id"]: p for p in vmr_gui.list_presets()}
        self.assertIn("smartwings_group", presets)
        self.assertIn("extra_rules", presets)
        self.assertEqual(presets["smartwings_group"]["name"], "smartwings group")
        self.assertIn("Place before the IVAO MTL rules", presets["extra_rules"]["description"])

    def test_preset_next_to_the_program_replaces_bundled_one(self):
        own = self.tmp / "presets"
        own.mkdir()
        (own / "extra_rules.vmr").write_text('<ModelMatchRuleSet><ModelMatchRule CallsignPrefix="AAA" TypeCode="A320" ModelName="X" /></ModelMatchRuleSet><!-- mine -->', encoding="utf-8")
        (own / "zzz_new.vmr").write_text("<ModelMatchRuleSet></ModelMatchRuleSet>", encoding="utf-8")
        (own / "not_a_preset.txt").write_text("x", encoding="utf-8")
        with mock.patch.object(vmr_gui, "PRESETS_DIRS", [ROOT / "presets", own]):
            presets = vmr_gui.list_presets()
        by_id = {p["id"]: p for p in presets}
        self.assertEqual(by_id["extra_rules"]["description"], "mine")
        self.assertEqual(by_id["extra_rules"]["rules"], [{"callsign": "AAA", "type": "A320", "models": ["X"]}])
        self.assertEqual([p["id"] for p in presets], sorted(by_id, key=str.lower))
        self.assertNotIn("not_a_preset", by_id)

    def test_missing_folders(self):
        with mock.patch.object(vmr_gui, "PRESETS_DIRS", [self.tmp / "nope"]):
            self.assertEqual(vmr_gui.list_presets(), [])


if __name__ == "__main__":
    unittest.main()
