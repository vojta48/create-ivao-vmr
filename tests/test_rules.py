# The rules that turn one MTL livery into (part of) a VMR rule: airline code, type, standard or special,
# and grouping. They live in create_vmr.py and are shared with the GUI.

import unittest

from support import create_vmr


class LiveryNamePartsTest(unittest.TestCase):
    def test_name_qualifiers_and_code(self):
        self.assertEqual(create_vmr.livery_name_parts('"Air Canada (old colors) (ACA)"'), ("Air Canada", ["old colors"], "ACA"))

    def test_without_code(self):
        self.assertEqual(create_vmr.livery_name_parts("Royal Navy"), ("Royal Navy", [], ""))
        self.assertEqual(create_vmr.livery_name_parts("Ukrainian Falcons (104)"), ("Ukrainian Falcons", [], "104"))

    def test_last_group_must_be_a_code(self):
        self.assertEqual(create_vmr.livery_name_parts("Wizz Air (Sharklets)"), ("Wizz Air", ["Sharklets"], ""))
        self.assertEqual(create_vmr.livery_name_parts("Name (abc)"), ("Name", ["abc"], ""))

    def test_empty(self):
        self.assertEqual(create_vmr.livery_name_parts(""), ("", [], ""))


class StandardLiveryTest(unittest.TestCase):
    def test_plain_name_is_standard(self):
        self.assertTrue(create_vmr.is_standard_livery("ACA", "Air Canada (ACA)"))
        self.assertTrue(create_vmr.is_standard_livery("XYZ", "Some Airline"))

    def test_qualifier_makes_it_special(self):
        for name in ("Air Canada (old colors) (ACA)", "Lufthansa (Star Alliance) (DLH)", "Qatar Airways (Cargo) (QTR)", "Xyz (retro)"):
            self.assertFalse(create_vmr.is_standard_livery("X", name), name)

    def test_neutral_qualifiers_stay_standard(self):
        for q in ("CFM", "IAE", "PW", "P&W", "Pratt & Whitney", "RR", "Rolls-Royce", "GE", "Trent", "LEAP", "neo", "ceo",
                  "CFM engines", "NC", "New Colors", "New Colours", "new livery", "new scheme", "current colors",
                  "WL", "Winglets", "Blended Winglets", "Split Winglets", "Scimitar Winglets", "Sharklets"):
            self.assertTrue(create_vmr.is_standard_livery("X", "Airline (%s) (ABC)" % q), q)

    def test_neutral_and_special_together_is_special(self):
        self.assertFalse(create_vmr.is_standard_livery("X", "Wizz Air (Old Colors) (Sharklets) (WZZ)"))

    def test_without_name_the_texture_decides(self):
        self.assertTrue(create_vmr.is_standard_livery('"EWG"', ""))
        self.assertFalse(create_vmr.is_standard_livery("EWG2", '""'))


class AirlineCodeTest(unittest.TestCase):
    code = staticmethod(create_vmr.mtl_airline_code)

    def test_catalog_code_wins_over_texture(self):
        self.assertEqual(self.code("DAL", "Air Dolomiti (DLA)"), "DLA")
        self.assertEqual(self.code('"EZE"', '"EasyJet (EZY)"'), "EZY")

    def test_texture_when_no_code_in_name(self):
        self.assertEqual(self.code("abcwl", "Some Airline"), "ABC")
        self.assertEqual(self.code("MIG", "Ukrainian Falcons (104)"), "MIG")

    def test_plain_model_is_type_only(self):
        self.assertEqual(self.code("default", "Boeing House (BOE)"), "")
        self.assertEqual(self.code("Default", ""), "")
        self.assertEqual(self.code("", "Cessna 172"), "")
        self.assertEqual(self.code('""', ""), "")

    def test_white_and_blank_textures_are_the_plain_model(self):
        # found in the MTL: the plain model is not always called "default". Without this, "white" and "blank"
        # would become the callsigns WHI and BLA (BLA is Blue Air).
        self.assertEqual(self.code("white", "Cessna Caravan", "C208"), "")
        self.assertEqual(self.code("White", "Falcon 50 (White)", "FA50"), "")
        self.assertEqual(self.code("BLANK", "General Aviation (Blank)", "B722"), "")
        self.assertEqual(self.code("blank", "General Aviation (Blank)", "BE36"), "")
        # real airlines whose code starts the same way keep their rule
        self.assertEqual(self.code("BLA", "Blue Air (BLA)", "B733"), "BLA")
        self.assertEqual(self.code("WHT", "White Airways (WHT)", "A310"), "WHT")
        self.assertEqual(self.code("BLAWL", "Blue Air (Winglets) (BLA)", "B738"), "BLA")

    def test_plain_model_with_a_generic_name_is_type_only(self):
        # found in the MTL: plain models with the texture ZZZ and a generic catalog name (Vojta's SR22 case)
        self.assertEqual(self.code("ZZZ", "Default", "SR22"), "")
        self.assertEqual(self.code("ZZZ", "White", "F70"), "")
        self.assertEqual(self.code("ZZZ2", "White (Blank)", "F100"), "")
        self.assertEqual(self.code("ZZZ", "General Aviation", "AT43"), "")
        self.assertEqual(self.code("BBA", "White (Blank)", "LJ25"), "")
        # a ZZZ livery of a particular aircraft or owner is still left out
        self.assertIsNone(self.code("ZZZ", "Las Vegas Sands (VP-CMS)", "A345"))
        self.assertIsNone(self.code("ZZZWL", "General Aviation (HZ-HAA) (winglets) (ZZZ)", "B735"))
        self.assertIsNone(self.code("ZZZ2", "White Blue Livery", "C207"))
        self.assertIsNone(self.code("ZZZ", "Private (ZZZ)", "A320"))
        # and a generic name with an airline code is that airline's livery
        self.assertEqual(self.code("ZZZ", "Default (ABC)", "A320"), "ABC")
        self.assertTrue(create_vmr.is_plain_model_name("General Aviation (Blank)"))
        self.assertFalse(create_vmr.is_plain_model_name("General Aviation (HZ-HAA)"))

    def test_plain_model_named_like_its_type_is_type_only(self):
        self.assertEqual(self.code("HAR", "AV-8 Harrier", "HAR"), "")
        self.assertEqual(self.code("F5", "F5 (Grey)", "F5"), "")
        self.assertEqual(self.code("V22", "V22 Osprey", "V22"), "")
        # a catalog code still wins: texture="E190" for "AirX Charter (AXY)"
        self.assertEqual(self.code("E190", "AirX Charter (AXY)", "E190"), "AXY")
        self.assertIsNone(self.code("F5", "F5 (Grey)", "F16"))

    def test_airline_code_in_an_earlier_bracket(self):
        # found in the MTL: the livery tag comes last, the airline code before it
        self.assertEqual(self.code("UAE2", "Emirates (UAE) (NBA)"), "UAE")
        # the usual case with two codes: engines or a parent code first, the airline last
        self.assertEqual(self.code("KAY", "K5-Aviation (ACJ) (KAY)"), "KAY")
        self.assertEqual(self.code("PEO2", "Petro Air (SOC) (PEO)"), "PEO")
        self.assertEqual(self.code("ZZZ", "Xyz (ZZZ) (ABC)"), "ABC")

    def test_invisible_model_is_left_out(self):
        self.assertIsNone(self.code("dummy", "No Model (Invisible)", "ZZZZ"))
        self.assertIsNone(self.code('"Dummy"', ""))

    def test_type_zzzz_is_type_only(self):
        self.assertEqual(self.code("SHP", "Blimp", "ZZZZ"), "")
        self.assertEqual(self.code("SHP", "Blimp", "A320"), "SHP")

    def test_no_usable_code(self):
        for texture, name in (("ZZZ2", "Privately Owned"), ("@UN", "Navy"), ("RN", "Royal Navy"),
                              ("ZZZ", "Private (ZZZ)"), ("12A", "Numbers"), ("A1B", "Digit inside")):
            self.assertIsNone(self.code(texture, name), texture)

    def test_military_and_private_with_code(self):
        self.assertEqual(self.code("@UN", "United States Navy 'SD' (USN)"), "USN")
        self.assertEqual(self.code("ZZZWL7", "Las Vegas Sands (winglets) (BBJ)"), "BBJ")

    def test_type_code(self):
        self.assertEqual(create_vmr.mtl_type_code('"A320"'), "A320")
        self.assertEqual(create_vmr.mtl_type_code('"F14"'), "F14")
        self.assertEqual(create_vmr.mtl_type_code("b38m"), "B38M")
        self.assertEqual(create_vmr.mtl_type_code('"A4  "'), "A4")
        self.assertEqual(create_vmr.mtl_type_code('"B748F"'), "B748")
        self.assertEqual(create_vmr.mtl_type_code(""), "")


class XmlTest(unittest.TestCase):
    def test_xml_attr(self):
        self.assertEqual(create_vmr.xml_attr('A&B "x" <y>'), "A&amp;B &quot;x&quot; &lt;y&gt;")

    def test_build_rule(self):
        self.assertEqual(create_vmr.build_rule("DLH", "A320", "A320DLH//A&B"),
                         '<ModelMatchRule CallsignPrefix="DLH" TypeCode="A320" ModelName="A320DLH//A&amp;B" /> \n')

    def test_build_rule_without_prefix(self):
        for callsign, type_code in (("", "C172"), ("def", "C172"), ("SHP", "ZZZZ")):
            self.assertNotIn("CallsignPrefix", create_vmr.build_rule(callsign, type_code, "X"))


class GroupRulesTest(unittest.TestCase):
    model_list = {"AAA": {"A320": ["A", "A2", "AWL"], "B738": ["B2"]}, "": {"C172": ["C"]}}
    special = {"A2", "B2"}

    def test_all_liveries(self):
        self.assertEqual(create_vmr.group_rules(self.model_list, self.special, False),
                         [("AAA", "A320", ["A", "A2", "AWL"], False), ("AAA", "B738", ["B2"], False), ("", "C172", ["C"], False)])

    def test_standard_only(self):
        self.assertEqual(create_vmr.group_rules(self.model_list, self.special, True),
                         [("AAA", "A320", ["A", "AWL"], False), ("AAA", "B738", ["B2"], True), ("", "C172", ["C"], False)])

    def test_input_unchanged(self):
        create_vmr.group_rules(self.model_list, self.special, True)
        self.assertEqual(self.model_list["AAA"]["A320"], ["A", "A2", "AWL"])

    def test_empty(self):
        self.assertEqual(create_vmr.group_rules({}, set(), True), [])


if __name__ == "__main__":
    unittest.main()
