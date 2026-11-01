# vmr_gui.Library: reading the installed MTL, catalog numbers and the problems it reports.

import hashlib

from support import ALL_TITLES, LEFT_OUT, TempDirTestCase, livery, make_mtl, vmr_gui, write_model


def tree_hash(root):
    """A hash over every file below root, to prove that the GUI changes nothing."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode() + path.read_bytes())
    return digest.hexdigest()


class LibraryTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.mtl = make_mtl(self.tmp / "IVAO_MTL")
        self.library = vmr_gui.Library(self.mtl).scan()

    def test_every_livery(self):
        self.assertEqual(sorted(self.library.liveries), sorted(ALL_TITLES))
        self.assertEqual(self.library.errors, [])
        self.assertTrue(self.library.scanned)

    def test_livery_fields(self):
        l = self.library.liveries["F100DLA"]
        self.assertEqual(l, {"id": "F100DLA", "airline": "DLA", "inVmr": True, "type": "F100", "texture": "DAL",
                             "name": "Air Dolomiti (DLA)", "model": "IVAO_F100", "standard": True, "catalogId": 101})
        self.assertFalse(self.library.liveries["A320AAF2"]["standard"])
        self.assertEqual(self.library.liveries["B737"]["airline"], "")
        for title in LEFT_OUT:
            self.assertFalse(self.library.liveries[title]["inVmr"], title)
            self.assertEqual(self.library.liveries[title]["airline"], "")

    def test_catalog_numbers(self):
        self.assertEqual(self.library.liveries["C172"]["catalogId"], 9999)  # from mtl.dat, no ivao.ini
        self.assertEqual(self.library.liveries["F14@UN"]["catalogId"], 107)

    def test_ivao_ini_wins_over_mtl_dat(self):
        (self.mtl / "mtl.dat").write_text("F100DLA,Air Dolomiti (DLA),0.0,0.0,5\n", encoding="utf-8")
        self.assertEqual(vmr_gui.Library(self.mtl).scan().liveries["F100DLA"]["catalogId"], 101)

    def test_texture_folder_case_does_not_matter(self):
        folder = self.mtl / "SimObjects" / "Airplanes" / "IVAO_F100"
        (folder / "texture.DAL").rename(folder / "texture.dal")
        self.assertEqual(vmr_gui.Library(self.mtl).scan().liveries["F100DLA"]["catalogId"], 101)

    def test_the_mtl_is_not_changed(self):
        before = tree_hash(self.mtl)
        vmr_gui.Library(self.mtl).scan()
        self.assertEqual(tree_hash(self.mtl), before)
        self.assertIn("VERSION]", (self.mtl / "SimObjects/Airplanes/IVAO_F100/aircraft.cfg").read_text())

    def test_progress_counts_the_aircraft_folders(self):
        # the loading screen of the page shows how far the scan is (/api/progress)
        folders = [d for d in (self.mtl / "SimObjects" / "Airplanes").iterdir()]
        self.assertEqual(self.library.progress, {"done": len(folders), "total": len(folders)})
        self.assertTrue(self.library.scanned)
        fresh = vmr_gui.Library(self.mtl)
        self.assertEqual(fresh.progress, {"done": 0, "total": 0})
        self.assertFalse(fresh.scanned)
        self.assertEqual(vmr_gui.Library(None).scan().progress, {"done": 0, "total": 0})

    def test_rescan_starts_over(self):
        write_model(self.mtl / "SimObjects" / "Airplanes", "IVAO_NEW", [livery("A320NEW", "NEW", "A320", "New (NEW)")])
        self.library.scan()
        self.assertIn("A320NEW", self.library.liveries)
        self.assertEqual(len(self.library.liveries), len(ALL_TITLES) + 1)


class LibraryProblemsTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.airplanes = self.tmp / "SimObjects" / "Airplanes"
        self.airplanes.mkdir(parents=True)

    def test_no_mtl(self):
        library = vmr_gui.Library(self.tmp / "nothing").scan()
        self.assertEqual((library.liveries, library.errors, library.mtl_rules(False)), ({}, [], []))

    def test_problems_are_reported(self):
        (self.airplanes / "BAD").mkdir()
        (self.airplanes / "BAD" / "aircraft.cfg").write_text("msfs_mode = 1\n", encoding="utf-8")
        write_model(self.airplanes, "SKIP", [
            livery("NOTYPE", "NTY", "", "No type (NTY)"),
            livery("", "NTI", "A320", "No title (NTI)"),
            livery("A320ONE", "ONE", "A320", "One (ONE)"),
        ])
        write_model(self.airplanes, "TWICE", [livery("A320ONE", "TWO", "A320", "Two (TWO)")])
        library = vmr_gui.Library(self.tmp).scan()
        self.assertEqual(list(library.liveries), ["A320ONE"])
        self.assertEqual(library.liveries["A320ONE"]["airline"], "ONE")
        self.assertEqual(len(library.errors), 4)
        joined = "\n".join(library.errors)
        for text in ("BAD", "empty aircraft type", "no title", "already uses"):
            self.assertIn(text, joined)

    def test_encodings_and_unquoted_title(self):
        write_model(self.airplanes, "CP", [livery("A320CPA", "CPA", "A320", "Cathay Ä (CPA)", quoted=False)], encoding="cp1252", newline="\r\n")
        library = vmr_gui.Library(self.tmp).scan()
        self.assertEqual(library.liveries["A320CPA"]["name"], "Cathay Ä (CPA)")


class CatalogNumberFilesTest(TempDirTestCase):
    def test_read_catalog_id(self):
        folder = self.tmp / "texture.X"
        folder.mkdir()
        self.assertIsNone(vmr_gui.read_catalog_id(folder))
        self.assertIsNone(vmr_gui.read_catalog_id(None))
        (folder / "ivao.ini").write_text("[IVAO]\nfile_version = 3\n", encoding="utf-8")
        self.assertIsNone(vmr_gui.read_catalog_id(folder))
        (folder / "ivao.ini").write_text("﻿[IVAO]\r\n  MTL_VERSION =  42 \r\n", encoding="utf-8")
        self.assertEqual(vmr_gui.read_catalog_id(folder), 42)

    def test_read_mtl_dat(self):
        path = self.tmp / "mtl.dat"
        self.assertEqual(vmr_gui.read_mtl_dat(path), {})
        path.write_text("A320AAF,Aigle Azur (AAF),0.0,0.0,11636\nC172,Cessna, 172, with commas,0.0,0.0,5\n"
                        "bad\nNONUM,x,0,0,abc\n,noid,0,0,7\n", encoding="utf-8")
        self.assertEqual(vmr_gui.read_mtl_dat(path), {"A320AAF": 11636, "C172": 5})


if __name__ == "__main__":
    import unittest
    unittest.main()
