# Helpers shared by the tests: a fake IVAO MTL on disk, running create_vmr.py on it, reading VMR files and
# running the GUI server. Standard library only.

import atexit
import contextlib
import importlib
import io
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The GUI keeps its files in the user's AppData. The tests (and the programs they start) use a temporary folder
# instead, so that they never read or change the real settings and rules of whoever runs them.
DATA_DIR = tempfile.mkdtemp(prefix="ivao-vmr-tests-")
os.environ["IVAO_VMR_GUI_DATA_DIR"] = DATA_DIR
atexit.register(shutil.rmtree, DATA_DIR, True)

import create_vmr  # noqa: E402
import vmr_gui  # noqa: E402


def livery(title, texture, ui_type, name, catalog=None, quoted=True):
    """One [fltsim.N] section of a fake aircraft.cfg (catalog: the number written into texture.<X>/ivao.ini)."""
    return {"title": title, "texture": texture, "ui_type": ui_type, "ui_variation": name, "catalog": catalog, "quoted": quoted}


def write_model(airplanes, folder, liveries, version_bug=False, encoding="utf-8", newline="\n", extra=""):
    """Writes SimObjects/Airplanes/<folder>/aircraft.cfg (and the ivao.ini of each texture folder) and returns
    the path of the aircraft.cfg. version_bug adds the broken "VERSION]" header the MTL sometimes has."""
    model_dir = Path(airplanes) / folder
    model_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, entry in enumerate(liveries):
        q = '"' if entry["quoted"] else ""
        lines += ["[fltsim.%d]" % i, "title=%s%s%s" % (q, entry["title"], q), 'texture="%s"' % entry["texture"],
                  'ui_type="%s"' % entry["ui_type"], 'ui_variation="%s"' % entry["ui_variation"], ""]
        if entry["texture"] and entry["catalog"]:
            tex = model_dir / ("texture." + entry["texture"])
            tex.mkdir(exist_ok=True)
            (tex / "ivao.ini").write_text("[IVAO]\nmtl_version = %d\nfile_version = 1\n" % entry["catalog"], encoding="utf-8")
    if version_bug:
        lines += ["VERSION]", "major=1", ""]
    cfg = model_dir / "aircraft.cfg"
    cfg.write_bytes((newline.join(lines) + extra).encode(encoding))
    return cfg


# The fake MTL most tests use. Every line is a case the rules have to handle.
LIVERIES = {
    "IVAO_A320": [
        livery("A320AAF", "AAF", "A320", "Aigle Azur (AAF)", 110),
        livery("A320AAF2", "AAF2", "A320", "Aigle Azur (old) (AAF)", 111),          # special
        livery("A320AAFWL", "AAFWL", "A320", "Aigle Azur (Sharklets) (AAF)", 116),  # neutral qualifier: standard
        livery("A320XYZ2", "XYZ2", "A320", "Xyz Air (retro) (XYZ)", 112),           # only special: kept
    ],
    "IVAO_B737": [
        livery("B737EZY", "EZE", "B737", "EasyJet (EZY)", 103),                     # texture typo
        livery("B737ZZZWL7", "ZZZWL7", "B737", "Las Vegas Sands (winglets) (BBJ)", 104),
        livery("B737ZZZ", "ZZZ", "B737", "Privately Owned", 105),                   # left out
        livery("B737", "default", "B737", "Boeing House (BOE)", 106),               # type-only
    ],
    "IVAO_C172": [livery("C172", "", "C172", "Cessna 172", None)],                  # no texture: type-only, no ivao.ini
    "IVAO_F100": [
        livery("F100DLA", "DAL", "F100", "Air Dolomiti (DLA)", 101),                # catalog code wins
        livery("F100KLM", "KLM", "F100", "KLM Cityhopper (KLM)", 102),
    ],
    "IVAO_F14": [
        livery("F14@UN", "@UN", "F14", "United States Navy 'SD' (USN)", 107),
        livery("F14@IR", "@IR", "F14", "Iran Air Force", 108),                      # left out
    ],
    "IVAO_HAR": [
        livery("HARRN", "RN", "HAR", "Royal Navy", 113),                            # 2-letter texture: left out
        livery("HAR", "HAR", "HAR", "AV-8 Harrier", 117),                           # plain model, texture = type: type-only
    ],
    "IVAO_A388": [
        livery("A388UAE", "UAE", "A388", "Emirates (UAE)", 118),
        livery("A388UAE2", "UAE2", "A388", "Emirates (UAE) (NBA)", 119),            # airline code in an earlier bracket
    ],
    "IVAO_ZZZZ": [
        livery("ZZZZSHP", "SHP", "ZZZZ", "Blimp IVAO 25th Anniversary", 114),       # type ZZZZ: type-only
        livery("ZZZZHAB", "HAB", "ZZZZ", "IVAO Hot Air Balloon", 115),
        livery("ZZZZ", "dummy", "ZZZZ", "No Model (Invisible)", 120),               # invisible model: left out
    ],
}
ALL_TITLES = [entry["title"] for entries in LIVERIES.values() for entry in entries]
LEFT_OUT = {"B737ZZZ", "F14@IR", "HARRN", "ZZZZ"}


def make_mtl(root, version_bug=True):
    """The fake MTL in <root>: SimObjects/Airplanes with the LIVERIES, an AI_Sounds folder without
    aircraft.cfg (like the real MTL) and an mtl.dat."""
    root = Path(root)
    airplanes = root / "SimObjects" / "Airplanes"
    for folder, entries in LIVERIES.items():
        write_model(airplanes, folder, entries, version_bug=version_bug)
    (airplanes / "AI_Sounds").mkdir()
    (root / "mtl.dat").write_text("C172,Cessna 172, with a comma,0.0,0.0,9999\r\nbroken line\r\n,no id,0,0,5\r\n", encoding="utf-8")
    return root


def run_script(models_directory, output_directory, **settings):
    """Runs the generation part of create_vmr.py (main()) with fresh globals. Returns (module, printed text)."""
    script = importlib.reload(create_vmr)
    script.models_directory = str(models_directory)
    script.output_directory = Path(output_directory)
    for name, value in settings.items():
        setattr(script, name, value)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        script.main()
    return script, out.getvalue()


def read_rules(path):
    """The rules of a VMR file as (callsign, type, (models...)) tuples, in file order."""
    return [(r["callsign"], r["type"], tuple(r["models"])) for r in vmr_gui.parse_vmr(Path(path).read_text(encoding="utf-8"))]


def gui_rules(library, standard_only):
    return [(r["callsign"], r["type"], tuple(r["models"])) for r in library.mtl_rules(standard_only)]


class TempDirTestCase(unittest.TestCase):
    """A test case with a fresh temporary folder in self.tmp."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class ServerTestCase(unittest.TestCase):
    """Runs the GUI server on a free port for the whole class, with the fake MTL as models folder."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._tmp.name)
        cls.mtl = make_mtl(cls.tmp / "IVAO_MTL")
        cls.out = cls.tmp / "out"
        cls.app = vmr_gui.App(cls.mtl, cls.out)
        vmr_gui.Handler.app = cls.app
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), vmr_gui.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._tmp.cleanup()

    def request(self, method, path, body=None, headers=None):
        """Returns (status, headers, body bytes)."""
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def post_json(self, path, data):
        import json
        return self.request("POST", path, json.dumps(data), {"Content-Type": "application/json"})
