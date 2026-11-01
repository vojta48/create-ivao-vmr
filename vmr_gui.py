#!/usr/bin/env python3
# Simple GUI for building a custom vPilot VMR file on top of the IVAO MTL.
# Copyright 2024-2026 create-ivao-vmr contributors. Licensed under the Apache License, Version 2.0; see LICENSE and NOTICE.
#
# Run it from anywhere:
#   python vmr_gui.py
# It finds the IVAO MTL in the Community folder of MSFS 2020 and 2024 (Steam and Microsoft Store) by itself.
# It starts a small local web server (standard library only) and shows the GUI in its own window
# (through pywebview, "pip install pywebview"; without it the GUI opens in your browser instead).
# In the GUI you can:
#   - turn on ready-made rule sets from the "presets" folder (for example the Smartwings group),
#   - add your own ModelMatchRule lines (CallsignPrefix / TypeCode / ModelName, "//" for alternatives),
#   - add the rules generated from your MTL (the same rules create_vmr.py makes, all liveries or the
#     standard liveries only) after your own rules, so that one VMR file is enough in vPilot,
#   - save the result as a VMR file.
# Every livery shows its picture from the MTL catalog (https://mtl.ivao.aero/catalog) and links to its page
# there. The pictures are downloaded once into the "previews" folder in the user's AppData.
# The settings of the last run (VMR name, its folder, ticked presets, MTL choice) and the user's own rules
# are kept in the user's AppData as well (see "Where the program keeps its files" below).
# The .exe looks for a new release on GitHub at start and can update itself (see "Updates" below).
#
# Options:
#   -d | --directory [path]   folder that contains SimObjects/Airplanes (default: the folder chosen last in
#                             the GUI, else the folder of the program or the current folder when it is the
#                             MTL, else the MTL found in the Community folder of the simulator)
#   -p | --output-directory   folder where generated VMR files are saved (default: the folder of the last
#                             saved VMR, the first time Documents\vPilot Files)
#   --port [number]           port of the local server (default: 8765)
#   --browser                 show the GUI in the web browser instead of its own window
#   --no-browser              only run the server, do not open a window or a browser

import argparse
import configparser
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# The rules that turn the liveries into a VMR (airline code, aircraft type, standard or special livery,
# grouping) are shared with create_vmr.py, so the GUI and the script produce the same VMRs.
from create_vmr import group_rules, is_standard_livery, mtl_airline_code, mtl_type_code, xml_attr

# When packed into an .exe with PyInstaller (see build_exe.spec), the gui and presets folders are bundled
# inside the executable and unpacked to a temporary folder (sys._MEIPASS).
FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
GUI_DIR = BUNDLE_DIR / "gui"
# Set by the build workflow: open the window, close it again after a few seconds and exit. With --no-browser
# the server runs for SELF_TEST_SERVER_SECONDS and then stops by itself, so that the test never has to kill it.
SELF_TEST = os.environ.get("IVAO_VMR_GUI_SELFTEST") == "1"
SELF_TEST_SERVER_SECONDS = float(os.environ.get("IVAO_VMR_GUI_SELFTEST_SECONDS") or 30)


# --------------------------------------------------------------------------------------------------
# Where the program keeps its files
# --------------------------------------------------------------------------------------------------
#
# The program can be started from any folder (Downloads, the desktop, Program Files), so it writes nothing
# next to itself. Its files are kept per Windows user:
#   %APPDATA%\IVAO VMR Generator        settings.json, my_rules.vmr and a "presets" folder for own presets
#   %LOCALAPPDATA%\IVAO VMR Generator   vmr_gui.log and the "previews" folder (pictures that can be downloaded again)
# The settings and the user's own rules are in Roaming AppData, the files that are only a cache in Local AppData,
# as Windows expects. IVAO_VMR_GUI_DATA_DIR puts all of them into one other folder (used by the tests and the
# smoke tests of the build workflow, so that they never touch the real files of the user).
APP_FOLDER_NAME = "IVAO VMR Generator"


def user_folders(environ=None, platform=None):
    """(data folder, cache folder) of the program, see above."""
    environ = os.environ if environ is None else environ
    platform = platform or sys.platform
    if environ.get("IVAO_VMR_GUI_DATA_DIR"):
        folder = Path(environ["IVAO_VMR_GUI_DATA_DIR"])
        return folder, folder
    home = Path(environ.get("USERPROFILE") or environ.get("HOME") or Path.home())
    if platform == "win32":
        roaming = Path(environ.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        return roaming / APP_FOLDER_NAME, local / APP_FOLDER_NAME
    # Running from source on Linux or macOS (for development).
    config = Path(environ.get("XDG_CONFIG_HOME") or home / ".config")
    cache = Path(environ.get("XDG_CACHE_HOME") or home / ".cache")
    return config / "ivao-vmr-generator", cache / "ivao-vmr-generator"


DATA_DIR, CACHE_DIR = user_folders()
# A preset in the data folder replaces a bundled one of the same name. The .exe also still reads a "presets"
# folder next to itself, where version 1.1 told users to put their own presets.
PRESETS_DIRS = [BUNDLE_DIR / "presets"] + ([APP_DIR / "presets"] if FROZEN else []) + [DATA_DIR / "presets"]
LOG_FILE = CACHE_DIR / "vmr_gui.log"
LOG_MAX_BYTES = 1000000  # a longer log is renamed to vmr_gui.old.log at start, so that it does not grow forever
# Page of a livery in the MTL catalog (https://mtl.ivao.aero/catalog).
CATALOG_SEARCH = "https://mtl.ivao.aero/catalog?textureName={name}"
# Picture of a livery in the MTL catalog. The thumbnails inside the MTL packages are one generic picture
# for every livery, but the MTL Installer writes an "ivao.ini" into every texture folder it installs, and
# its "mtl_version" is the number of the livery in the catalog. With it the catalog picture can be
# downloaded without an API key. The pictures are kept in the "previews" folder in Local AppData, so that
# each one is downloaded only once.
CATALOG_IMAGE = "https://download.ivao.aero/v2/aircraftsTextures/{id}/files/latest/image"
PREVIEWS_DIR = CACHE_DIR / "previews"
TEXTURE_INFO_FILE = "ivao.ini"
# The MTL Installer also keeps a list of every livery in mtl.dat in the MTL folder, one line per livery:
# "A320AAF,Aigle Azur (AAF),0.0,0.0,11636" (MTL id, catalog name, two numbers, catalog number). It is used
# for the catalog number of liveries whose texture folder has no ivao.ini.
MTL_DAT_FILE = "mtl.dat"
BROKEN_VERSION_LINE = re.compile(r"^([ \t]*)VERSION\](?=[ \t]*\r?$)", re.MULTILINE)

# The settings of the last run (VMR name, folder of the last saved VMR, ticked presets and MTL choice).
# See the "Settings" section below for how the file stays compatible between versions.
SETTINGS_FILE = DATA_DIR / "settings.json"
# The user's own rules ("My rules"), kept as a VMR file (see MyRules below).
MY_RULES_FILE = DATA_DIR / "my_rules.vmr"
# Versions before 1.2 kept these two files next to the program, which was usually the IVAO_MTL folder. They
# are copied to the data folder once (see copy_old_files).
OLD_FILE_NAMES = {SETTINGS_FILE: "vmr_gui_settings.json", MY_RULES_FILE: "vmr_gui_my_rules.vmr"}

# The releases of the program on GitHub, for the update check (see "Updates" below).
GITHUB_REPO = "vojta48/create-ivao-vmr"
LATEST_RELEASE_API = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO
RELEASES_PAGE = "https://github.com/%s/releases" % GITHUB_REPO
RELEASE_DOWNLOADS = "https://github.com/%s/releases/download/" % GITHUB_REPO
EXE_NAME = "IVAO_VMR_Generator.exe"
# Release builds are signed through SignPath Foundation (see "Code signing policy" in the README). When the
# running .exe carries a valid signature of this signer, an update is only installed when it carries one too.
RELEASE_SIGNER = "SignPath Foundation"


def read_app_version():
    """The version of this program. The build writes it into version.txt inside the .exe (see build_exe.spec);
    running from source it is "dev"."""
    try:
        return (BUNDLE_DIR / "version.txt").read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


APP_VERSION = read_app_version()


# --------------------------------------------------------------------------------------------------
# VMR reading and writing
# --------------------------------------------------------------------------------------------------

def parse_vmr(text):
    """Returns the ModelMatchRule entries of a VMR file as a list of dicts with callsign (CallsignPrefix),
    type, models (list of ModelName alternatives) and, only when the rule has them, exactCallsign
    (Callsign: the whole callsign must match) and flightNumbers (FlightNumberRange, e.g. "4439-4858")."""
    rules = []
    # Some hand-made VMR files are not well-formed XML (missing closing tag, comment after the root).
    # Try the XML parser first and fall back to a regular expression that only looks at the rules.
    try:
        root = ET.fromstring(text.strip())
        for rule in root.iter("ModelMatchRule"):
            rules.append(_make_rule(rule.attrib))
        return rules
    except ET.ParseError:
        pass
    for match in re.finditer(r"<ModelMatchRule\b([^>]*)/?>", text):
        attrs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', match.group(1)))
        rules.append(_make_rule({k: _xml_unescape(v) for k, v in attrs.items()}))
    return rules


def _make_rule(attrs):
    rule = {
        "callsign": attrs.get("CallsignPrefix", "").strip().upper(),
        "type": attrs.get("TypeCode", "").strip().upper(),
        "models": [m.strip() for m in attrs.get("ModelName", "").split("//") if m.strip()],
    }
    # Without these the rule would be imported as a much broader one (a rule for one callsign would
    # become a rule for every aircraft of that type).
    if attrs.get("Callsign", "").strip():
        rule["exactCallsign"] = attrs["Callsign"].strip().upper()
    if attrs.get("FlightNumberRange", "").strip():
        rule["flightNumbers"] = attrs["FlightNumberRange"].strip()
    return rule


def _xml_unescape(value):
    return value.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&apos;", "'").replace("&amp;", "&")


def build_vmr(rules, comment=None):
    """Builds the text of a VMR file from a list of rules (see parse_vmr for the format).
    gui/app.js has the same function (buildVmr) for the preview and the "Save as" file; keep both alike."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<ModelMatchRuleSet>"]
    for rule in rules:
        if not rule.get("type") or not rule.get("models"):
            continue
        attrs = ""
        if rule.get("callsign"):
            attrs += ' CallsignPrefix="%s"' % xml_attr(rule["callsign"])
        if rule.get("exactCallsign"):
            attrs += ' Callsign="%s"' % xml_attr(rule["exactCallsign"])
        if rule.get("flightNumbers"):
            attrs += ' FlightNumberRange="%s"' % xml_attr(rule["flightNumbers"])
        attrs += ' TypeCode="%s" ModelName="%s"' % (xml_attr(rule["type"]), xml_attr("//".join(rule["models"])))
        lines.append("<ModelMatchRule%s />" % attrs)
    lines.append("</ModelMatchRuleSet>")
    if comment:
        lines.append("<!-- %s -->" % comment.replace("--", "- -"))
    lines.append("<!-- VMR created by create-ivao-vmr GUI https://github.com/vojta48/create-ivao-vmr -->")
    return "\r\n".join(lines) + "\r\n"


def list_presets():
    files = {}
    for folder in PRESETS_DIRS:
        if folder.is_dir():
            for path in folder.glob("*.vmr"):
                files[path.stem] = path
    presets = []
    for path in sorted(files.values(), key=lambda p: p.stem.lower()):
        text = _read_text(path)
        description = ""
        comment = re.search(r"<!--(.*?)-->", text, re.S)
        if comment:
            description = " ".join(comment.group(1).split())
        presets.append({
            "id": path.stem,
            "name": path.stem.replace("_", " "),
            "file": path.name,
            "description": description,
            "rules": parse_vmr(text),
        })
    return presets


def _read_text(path):
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------------------------------
# Liveries installed in the MTL
# --------------------------------------------------------------------------------------------------

class Library:
    """The liveries found in SimObjects/Airplanes of the MTL, keyed by their title (the MTL id, e.g. A320TVS)."""

    def __init__(self, models_root):
        # models_root None: no MTL was found (see choose_models_root); the library is then empty.
        self.models_root = Path(models_root) if models_root else None
        self.airplanes = self.models_root / "SimObjects" / "Airplanes" if self.models_root else None
        self.liveries = {}
        self.errors = []
        self.catalog_ids = {}
        self.scanned = False

    def found(self):
        return self.airplanes is not None and self.airplanes.is_dir()

    def scan(self):
        self.liveries = {}
        self.errors = []
        self.catalog_ids = read_mtl_dat(self.models_root / MTL_DAT_FILE) if self.models_root else {}
        if self.found():
            for model_dir in sorted(self.airplanes.iterdir(), key=lambda p: p.name):  # the order create_vmr.py uses
                cfg = model_dir / "aircraft.cfg"
                if cfg.is_file():
                    self._read_cfg(model_dir, cfg)
        self.scanned = True
        return self

    def _read_cfg(self, model_dir, cfg):
        # texture="TVS" in aircraft.cfg means the folder texture.TVS, but Windows does not care about case
        folders = {}
        try:
            for child in model_dir.iterdir():
                if child.name.lower().startswith("texture.") and child.is_dir():
                    folders[child.name[len("texture."):].lower()] = child
        except OSError:
            pass
        config = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            # The broken "VERSION]" header that create_vmr.py repairs in the file (see fix_version_section
            # there) is repaired here in memory only: the GUI does not change the MTL.
            text = BROKEN_VERSION_LINE.sub(r"\1[VERSION]", _read_text(cfg))
            config.read_string(text, source=str(cfg))
        except (configparser.Error, OSError) as err:
            self.errors.append("%s: %s" % (cfg, err))
        for section in config.sections():
            if "fltsim" not in section.lower():
                continue
            entry = config[section]
            title = _unquote(entry.get("title", ""))
            type_code = mtl_type_code(entry.get("ui_type", ""))
            # The same liveries create_vmr.py skips (see create_model_list there), with the same reasons.
            problem = None
            if not type_code:
                problem = "has an empty aircraft type"
            elif not title:
                problem = "has no title"
            elif title in self.liveries:
                problem = "uses the title %s, which another livery already uses" % title
            if problem:
                self.errors.append("%s [%s] %s, skipped." % (cfg, section, problem))
                continue
            texture = _unquote(entry.get("texture", ""))
            name = _unquote(entry.get("ui_variation", ""))
            airline = mtl_airline_code(texture, name, type_code)
            self.liveries[title] = {
                "id": title,
                "airline": airline or "",
                # False for liveries without an airline code a callsign can start with (ZZZ, "@xx"): the rules
                # generated from the MTL leave them out (see mtl_airline_code in create_vmr.py).
                "inVmr": airline is not None,
                "type": type_code,
                "texture": texture,
                "name": name,
                "model": model_dir.name,
                "standard": is_standard_livery(texture, name),
                "catalogId": read_catalog_id(folders.get(texture.lower())) or self.catalog_ids.get(title),
            }

    def summary(self):
        return list(self.liveries.values())

    def _model_list(self):
        """The liveries in the form create_vmr.py groups them: model_list[airline][type] = [MTL ids]."""
        model_list = {}
        for livery in self.liveries.values():
            if livery["type"] and livery["inVmr"]:
                model_list.setdefault(livery["airline"], {}).setdefault(livery["type"], []).append(livery["id"])
        return model_list

    def _special(self):
        return {l["id"] for l in self.liveries.values() if not l["standard"]}

    def mtl_rules(self, standard_only):
        """The rules create_vmr.py generates from the MTL (see group_rules there): one rule per airline and
        aircraft type with all its liveries as alternatives, with standard_only the standard liveries only."""
        return [{"callsign": airline, "type": type_code, "models": models}
                for airline, type_code, models, kept in group_rules(self._model_list(), self._special(), standard_only)]


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    return value.strip()


# --------------------------------------------------------------------------------------------------
# Finding the IVAO MTL
# --------------------------------------------------------------------------------------------------
#
# The MTL Installer puts the MTL into the Community folder of the simulator. Where that folder is depends on
# the simulator and on where it was bought, but each simulator writes the folder of its packages into its
# UserCfg.opt, for example
#   InstalledPackagesPath "D:\SteamLibrary\steamapps\common\MSFS2024\Packages"
# and the Community folder is inside it. The place of UserCfg.opt itself is fixed for each simulator:
SIMULATORS = [
    # (name shown to the user, environment variable of the base folder, path of UserCfg.opt inside it)
    ("MSFS 2024 (Steam)", "APPDATA", ("Microsoft Flight Simulator 2024", "UserCfg.opt")),
    ("MSFS 2024 (Microsoft Store)", "LOCALAPPDATA", ("Packages", "Microsoft.Limitless_8wekyb3d8bbwe", "LocalCache", "UserCfg.opt")),
    ("MSFS 2020 (Steam)", "APPDATA", ("Microsoft Flight Simulator", "UserCfg.opt")),
    ("MSFS 2020 (Microsoft Store)", "LOCALAPPDATA", ("Packages", "Microsoft.FlightSimulator_8wekyb3d8bbwe", "LocalCache", "UserCfg.opt")),
]
MTL_FOLDER_NAME = "IVAO_MTL"
PACKAGES_PATH_LINE = re.compile(r'^[ \t]*InstalledPackagesPath[ \t]+"?([^"\r\n]*?)"?[ \t]*\r?$', re.MULTILINE)


def is_mtl_folder(folder):
    """True when the folder looks like an MTL: it has SimObjects/Airplanes."""
    try:
        return bool(folder) and (Path(folder) / "SimObjects" / "Airplanes").is_dir()
    except OSError:
        return False


def read_packages_path(user_cfg):
    """The InstalledPackagesPath of a UserCfg.opt, or None. Raises OSError when the file cannot be read."""
    match = PACKAGES_PATH_LINE.search(_read_text(user_cfg))
    return match.group(1).strip() if match and match.group(1).strip() else None


def mtl_in_community(community):
    """The MTL folder inside a Community folder, or None. Normally it is IVAO_MTL; a folder whose name starts
    with IVAO (an MTL renamed or linked by an add-on manager) is accepted as well."""
    community = Path(community)
    if is_mtl_folder(community / MTL_FOLDER_NAME):
        return community / MTL_FOLDER_NAME
    try:
        children = sorted(community.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None
    for child in children:
        if child.name.lower().startswith("ivao") and is_mtl_folder(child):
            return child
    return None


def find_mtl_folders(environ=None):
    """Every simulator installed for this Windows user, with its Community folder and the MTL in it (None
    when the MTL is not there): [{"sim": "MSFS 2024 (Steam)", "community": "...", "mtl": "..." or None}]."""
    environ = os.environ if environ is None else environ
    found = []
    for sim, variable, parts in SIMULATORS:
        if not environ.get(variable):
            continue
        try:
            packages = read_packages_path(Path(environ[variable]).joinpath(*parts))
        except OSError:
            continue  # this simulator is not installed
        if not packages:
            continue
        community = Path(packages) / "Community"
        mtl = mtl_in_community(community)
        found.append({"sim": sim, "community": str(community), "mtl": str(mtl) if mtl else None})
    return found


def community_of(folder):
    """The Community folder for a folder the user picked: the folder itself when the MTL is in it, or its parent
    when the user picked the IVAO_MTL folder itself. None when there is no MTL in either."""
    folder = Path(folder)
    if mtl_in_community(folder):
        return folder
    if is_mtl_folder(folder) and mtl_in_community(folder.parent) == folder:
        return folder.parent
    return None


def choose_models_root(directory, community, found, here):
    """The MTL folder to use and why: (folder or None, reason). Finding it in the simulators is the normal way;
    the user only has to say where it is when that does not work. In this order:
    - the MTL folder given on the command line (-d), even when it is not an MTL (the GUI then says so);
    - the MTL in the Community folder the user chose (the communityFolder setting, or --community), while it is
      still there;
    - here (the folder of the .exe, or the current folder when run from source) when it is an MTL: version 1.1
      had to be started from the IVAO_MTL folder, and users who keep it there still get that MTL;
    - the MTL found in the Community folder of an installed simulator (the first in SIMULATORS)."""
    if directory:
        return directory, "command line"
    mtl = mtl_in_community(community) if community else None
    if mtl:
        return str(mtl), "chosen"
    if here and is_mtl_folder(here):
        return str(here), "program folder"
    for sim in found:
        if sim["mtl"]:
            return sim["mtl"], sim["sim"]
    return None, None


def default_output_dir(models_root=None):
    """Where VMRs are saved before the user chose a folder: the IVAO_MTL folder in use (where create_vmr.py writes
    its VMRs too), else Documents\\vPilot Files (the folder vPilot keeps its own files in), else Documents."""
    if models_root and is_mtl_folder(models_root):
        return Path(models_root)
    documents = documents_folder()
    if (documents / "vPilot Files").is_dir():
        return documents / "vPilot Files"
    return documents if documents.is_dir() else Path.home()


def documents_folder():
    """The user's Documents folder. Windows can move it (into OneDrive, or a folder with a translated name
    such as "Dokumenty"), so it is asked from Windows instead of assuming %USERPROFILE%\\Documents."""
    if sys.platform == "win32":
        try:
            import ctypes
            buffer = ctypes.create_unicode_buffer(260)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0 and buffer.value:  # 5: CSIDL_PERSONAL
                return Path(buffer.value)
        except (AttributeError, OSError):
            pass
    return Path.home() / "Documents"


# --------------------------------------------------------------------------------------------------
# Files of older versions
# --------------------------------------------------------------------------------------------------

def copy_old_files(folders, presets_dir=None):
    """Versions before 1.2 kept the settings, my rules and the user's own presets next to the program, usually in
    the IVAO_MTL folder. They are copied into the data folder:
    - the settings and my rules from the first of the folders that has them, when the data folder does not have
      them yet. A rules file without any rule counts as not there: the page writes an empty one at the first start,
      before the user may have shown the program where the old files are (see App.use_community);
    - every preset of a "presets" folder there that is not one of the bundled presets (those come with the
      program, an old copy of them must not hide a newer one) and that the data folder does not have yet.
    The old files stay where they are (an older copy of the program may still use them), and a file of the user in
    the data folder is never replaced. Returns the message for the GUI, or None when nothing was copied."""
    presets_dir = Path(presets_dir) if presets_dir else DATA_DIR / "presets"
    copied = []
    for target, old_name in OLD_FILE_NAMES.items():
        if target.exists() and not _without_rules(target):
            continue
        for folder in folders:
            old = Path(folder) / old_name
            if old.is_file():
                if not (target.exists() and _without_rules(old)) and _copy(old, target):
                    copied.append(str(old))
                break
    bundled = {p.name.lower() for p in (BUNDLE_DIR / "presets").glob("*.vmr")}
    for folder in folders:
        old_presets = Path(folder) / "presets"
        if not old_presets.is_dir() or _same_folder(old_presets, BUNDLE_DIR / "presets") or _same_folder(old_presets, presets_dir):
            continue
        for old in sorted(old_presets.glob("*.vmr")):
            target = presets_dir / old.name
            if old.name.lower() not in bundled and not target.exists() and _copy(old, target):
                copied.append(str(old))
    if not copied:
        return None
    notice = ("This version keeps your settings, your own rules and your own presets in %s, so the program can be started "
              "from any folder. These files of the older version were copied there: %s. The old files were not changed; "
              "you can delete them." % (DATA_DIR, ", ".join(copied)))
    print("  " + notice)
    return notice


def _without_rules(path):
    """True for a VMR file without any rule (the settings file is never one)."""
    if path.suffix.lower() != ".vmr":
        return False
    try:
        return not parse_vmr(_read_text(path))
    except OSError:
        return False


def _copy(source, target):
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return True
    except OSError as err:
        print("  Could not copy %s to %s: %s" % (source, target, err))
        return False


def _same_folder(a, b):
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))
    except OSError:
        return False


def old_file_folders(here, directory, found, community=None):
    """The folders where an older version may have kept its files: the folder of the program, the current folder,
    the folder given with -d, the MTL in the Community folder the user chose and every MTL found in the simulators.
    Without duplicates."""
    chosen = mtl_in_community(community) if community else None
    folders = [here, Path.cwd(), directory, chosen] + [sim["mtl"] for sim in found]
    unique = {}
    for folder in folders:
        if folder:
            try:
                unique.setdefault(os.path.normcase(str(Path(folder).resolve())), Path(folder))
            except OSError:
                pass
    return list(unique.values())


# --------------------------------------------------------------------------------------------------
# Livery pictures from the MTL catalog
# --------------------------------------------------------------------------------------------------

def read_catalog_id(texture_dir):
    """The number of a livery in the MTL catalog, from the ivao.ini the MTL Installer put into its
    texture folder ("[IVAO] mtl_version = 18552"). None when the folder was not installed by the installer."""
    if texture_dir is None:
        return None
    info = texture_dir / TEXTURE_INFO_FILE
    try:
        text = info.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    match = re.search(r"^\s*mtl_version\s*=\s*(\d+)\s*$", text, re.MULTILINE | re.IGNORECASE)
    return int(match.group(1)) if match else None


def read_mtl_dat(path):
    """MTL id -> catalog number from the mtl.dat of the MTL Installer. Empty when there is no such file."""
    ids = {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ids
    for line in text.splitlines():
        # the catalog name can contain commas, the catalog number is always the last field
        mtl_id, _, rest = line.partition(",")
        number = rest.rpartition(",")[2].strip()
        if mtl_id.strip() and number.isdigit():
            ids[mtl_id.strip()] = int(number)
    return ids


class Previews:
    """Downloads the catalog picture of a livery once and keeps it in the previews folder."""

    EXTENSIONS = {"image/png": ".png", "image/webp": ".webp", "image/jpeg": ".jpg", "image/gif": ".gif"}

    def __init__(self, folder):
        self.folder = Path(folder)
        self.failed = {}  # catalog id -> error text, so that an unreachable picture is not tried over and over
        self.lock = threading.Lock()
        self.locks = {}  # catalog id -> lock, so that two requests for the same picture download it once
        self.downloads = threading.BoundedSemaphore(4)  # at most four downloads at a time

    def cached(self, catalog_id):
        for ext in self.EXTENSIONS.values():
            path = self.folder / ("%d%s" % (catalog_id, ext))
            if path.is_file():
                return path
        return None

    def get(self, catalog_id):
        """The picture file of a livery, or None when it is not available (no network, not in the catalog)."""
        path = self.cached(catalog_id)
        if path:
            return path
        with self.lock:
            if catalog_id in self.failed:
                return None
            lock = self.locks.setdefault(catalog_id, threading.Lock())
        with lock:
            path = self.cached(catalog_id)
            if path:
                return path
            try:
                with self.downloads:
                    path = self._download(catalog_id)
            except (urllib.error.URLError, OSError, ValueError) as err:
                with self.lock:
                    self.failed[catalog_id] = str(err)
                print("Catalog picture %d not available: %s" % (catalog_id, err))
                return None
        return path

    def _download(self, catalog_id):
        request = urllib.request.Request(CATALOG_IMAGE.format(id=catalog_id), headers={"User-Agent": "create-ivao-vmr GUI"})
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in self.EXTENSIONS:
                raise ValueError("not a picture (%s)" % (content_type or "no content type"))
            data = response.read()
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / ("%d%s" % (catalog_id, self.EXTENSIONS[content_type]))
        temp = path.with_name(path.name + ".part")
        temp.write_bytes(data)
        temp.replace(path)
        return path


# --------------------------------------------------------------------------------------------------
# Updates
# --------------------------------------------------------------------------------------------------
#
# At start the page asks the server whether GitHub has a newer release (only when the checkForUpdates setting
# is on, which is the default). The request goes to api.github.com and contains nothing but the usual headers
# of a web request; the README privacy policy says so. A newer release is offered in a prompt with "Update" and
# "Ignore"; a development version (see is_development_version and Updater.status) is never offered one.
# "Update" makes the .exe update itself right away and restart:
#   1. download IVAO_VMR_Generator.exe of the release into IVAO_VMR_Generator.exe.new next to the running .exe,
#   2. check its size and, when GitHub gives one, its SHA-256 checksum,
#   3. check that Windows finds a valid code signature of SignPath Foundation on it (an unsigned .exe from before
#      code signing was set up may be replaced by an unsigned one with a checksum, see _check_signature),
#   4. rename the running .exe to .old (Windows allows renaming a running program, not deleting it) and the
#      new one to the name of the program,
#   5. start the new .exe and end this one. The next start deletes the .old file.
# When anything fails before step 4 the running .exe is untouched; when step 4 fails half way it is renamed
# back. Running from source the program only tells the user about the new release.

class UpdateError(Exception):
    pass


def version_numbers(text):
    """(1, 2, 0) for "1.2.0", "v1.2.0" or "1.2.0-test"; None for "dev" and other versions that are not a release."""
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(n) for n in match.groups()) if match else None


def is_development_version(text):
    """Versions that are never offered an update: running from source ("dev") and the builds of the workflow that
    are not a release (0.0.0). A version newer than the latest release counts as one too (see Updater.status)."""
    return version_numbers(text) in (None, (0, 0, 0))


def parse_release(data):
    """The parts of a GitHub release (the JSON of the releases/latest API) the update needs."""
    if not isinstance(data, dict) or version_numbers(data.get("tag_name")) is None:
        raise UpdateError("GitHub did not return a release of the program")
    asset = None
    for item in data.get("assets") or []:
        url = item.get("browser_download_url") or ""
        # only the exe of a release of this repository, never a file from anywhere else
        if item.get("name") == EXE_NAME and url.startswith(RELEASE_DOWNLOADS) and isinstance(item.get("size"), int):
            digest = item.get("digest") or ""
            asset = {"url": url, "size": item["size"],
                     "sha256": digest[len("sha256:"):].lower() if digest.lower().startswith("sha256:") else None}
    page = data.get("html_url") or ""
    return {
        "version": data["tag_name"].strip().lstrip("v"),
        "numbers": version_numbers(data["tag_name"]),
        "page": page if page.startswith(RELEASES_PAGE) else RELEASES_PAGE,
        "notes": data.get("body") or "",
        "asset": asset,
    }


def signer_of(path):
    """The subject of the certificate that signed the file, when Windows finds the signature valid; else None.
    PowerShell's Get-AuthenticodeSignature checks the signature and the certificate chain like Windows Explorer
    does (Properties, Digital Signatures). The path is passed in an environment variable, never in the command."""
    if sys.platform != "win32":
        return None
    powershell = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    command = ("$s = Get-AuthenticodeSignature -LiteralPath $env:IVAO_VMR_CHECK_FILE; "
               "if ($s.Status -eq 'Valid') { $s.SignerCertificate.Subject }")
    try:
        result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
                                env=dict(os.environ, IVAO_VMR_CHECK_FILE=str(path)), capture_output=True, text=True,
                                timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as err:
        print("  Could not check the signature of %s: %s" % (path, err))
        return None
    return result.stdout.strip() or None


def signed_by_release_signer(subject):
    return bool(subject) and re.search(r"(?:^|,)\s*CN=%s\s*(?:,|$)" % re.escape(RELEASE_SIGNER), subject) is not None


class Updater:
    """Looks for a newer release on GitHub and installs it. exe None: running from source, nothing to replace."""

    def __init__(self, current_version, exe=None):
        self.current = current_version
        self.exe = Path(exe) if exe else None
        self.lock = threading.Lock()
        self.checked = False
        self.latest = None
        self.error = None

    def status(self):
        """available: the page asks the user to update. development: this version is not a release, or newer than
        the latest release (a build of a branch that is not released yet); such a version is never asked."""
        latest, current = self.latest, version_numbers(self.current)
        development = is_development_version(self.current) or bool(latest and current > latest["numbers"])
        available = bool(latest and not development and latest["numbers"] > current)
        return {
            "checked": self.checked,
            "current": self.current,
            "latest": latest["version"] if latest else None,
            "available": available,
            "development": development,
            "page": latest["page"] if latest else RELEASES_PAGE,
            "notes": latest["notes"] if available else "",
            "canInstall": bool(available and self.exe and latest["asset"] and sys.platform == "win32"),
            "error": self.error,
        }

    def check(self):
        """Asks GitHub for the latest release (once per run unless asked again). A version that is not a release
        (running from source: "dev", a workflow build: 0.0.0) never asks."""
        with self.lock:
            if is_development_version(self.current):
                self.checked, self.error = True, None
                return self.status()
            try:
                self.latest, self.error = parse_release(self._get_json(LATEST_RELEASE_API)), None
            except (urllib.error.URLError, OSError, ValueError, UpdateError) as err:
                self.error = "Could not check for a new version: %s" % err
                print("  " + self.error)
            self.checked = True
            return self.status()

    def _get_json(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "create-ivao-vmr GUI " + self.current,
                                                       "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def install(self):
        """Downloads, checks and puts the new .exe in place of the running one (steps 1 to 4 above). Returns the
        path of the program to start. Raises UpdateError with a message for the user."""
        with self.lock:
            status = self.status()
            if not status["canInstall"]:
                raise UpdateError("There is no update to install here. Download the new version from %s." % status["page"])
            asset = self.latest["asset"]
            new = self.exe.with_name(self.exe.name + ".new")
            try:
                self._download(asset, new)
                self._check_signature(new, asset)
                self._swap(new)
            except (urllib.error.URLError, OSError) as err:
                raise UpdateError("The update could not be installed: %s. Download it from %s instead." % (err, status["page"]))
            finally:
                for leftover in (new, new.with_name(new.name + ".part")):
                    try:
                        leftover.unlink()
                    except OSError:
                        pass
            print("  Updated to version %s." % self.latest["version"])
            return self.exe

    def _download(self, asset, target):
        part = target.with_name(target.name + ".part")
        request = urllib.request.Request(asset["url"], headers={"User-Agent": "create-ivao-vmr GUI " + self.current})
        checksum, size = hashlib.sha256(), 0
        with urllib.request.urlopen(request, timeout=60) as response, open(part, "wb") as out:
            while True:
                block = response.read(1 << 16)
                if not block:
                    break
                size += len(block)
                if size > asset["size"]:
                    break
                checksum.update(block)
                out.write(block)
        if size != asset["size"]:
            raise UpdateError("The download was incomplete or too large (%d bytes instead of %d)." % (size, asset["size"]))
        if asset["sha256"] and checksum.hexdigest() != asset["sha256"]:
            raise UpdateError("The downloaded file does not have the checksum GitHub gives for it, so it was not installed.")
        part.replace(target)

    def _check_signature(self, new, asset):
        """An update never lowers the trust in the program: when the running .exe is signed by SignPath Foundation,
        the new one has to be signed by it as well. Releases made before code signing was set up are not signed;
        an unsigned .exe may only be replaced by an unsigned one whose SHA-256 checksum GitHub published, which is
        as safe as downloading it from the release page by hand."""
        subject = signer_of(new)
        if signed_by_release_signer(subject):
            return
        if signed_by_release_signer(signer_of(self.exe)):
            raise UpdateError("The downloaded file is not signed by %s (%s), so it was not installed."
                              % (RELEASE_SIGNER, "signed by " + subject if subject else "no valid signature"))
        if not asset["sha256"]:
            raise UpdateError("The downloaded file is not signed and GitHub gives no checksum for it, so it was not installed.")

    def _swap(self, new):
        old = self.exe.with_name(self.exe.name + ".old")
        try:
            old.unlink()
        except FileNotFoundError:
            pass
        self.exe.replace(old)
        try:
            new.replace(self.exe)
        except OSError:
            old.replace(self.exe)
            raise


def remove_old_exe(exe):
    """Deletes the .old file a previous update left next to the .exe (it could not be deleted while it ran)."""
    try:
        Path(str(exe) + ".old").unlink()
    except OSError:
        pass


def start_program(exe, arguments):
    """Starts the updated .exe on its own. A one-file PyInstaller program passes its unpacked folder to programs
    it starts; PYINSTALLER_RESET_ENVIRONMENT makes the new one unpack its own files instead."""
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe)] + list(arguments), env=env, close_fds=True, creationflags=flags, cwd=str(Path(exe).parent))


# --------------------------------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------------------------------
#
# The settings of the last run are kept in settings.json in the data folder (before 1.2: vmr_gui_settings.json
# next to the program, see copy_old_files), for example:
#   {"settingsVersion": 1, "createdBy": "1.2.0", "savedBy": "1.3.0", "fileName": "my rules.vmr",
#    "lastFolder": "C:\\Users\\me\\Documents\\vPilot Files", "selectedPresets": ["smartwings_group"],
#    "mtlRules": {"enabled": true, "mode": "standard"}, "communityFolder": "", "checkForUpdates": true}
# createdBy and savedBy are the program versions that created the file and wrote it last; they are only
# information. Whether a file can be used is decided by settingsVersion, the version of the file format, so
# that a new program version keeps the settings of the previous one:
#   - A new setting does not change the format: a file without it gets the default for it.
#   - A value that is missing or not valid falls back to its default; the other settings are kept.
#   - Settings this version does not know (from a newer version) are kept when the file is written.
# Only a change that old files cannot follow raises SETTINGS_VERSION, and OLDEST_SUPPORTED_SETTINGS_VERSION
# when an old file must not be used any more. Such a file, and a file that cannot be read at all, is deleted
# and the settings start from the defaults; the GUI shows a message about it once.
SETTINGS_VERSION = 1
OLDEST_SUPPORTED_SETTINGS_VERSION = 1
MTL_MODES = ("standard", "all")


def _file_name_setting(value):
    name = Path(str(value).strip()).name
    if not isinstance(value, str) or not name or len(name) > 255:
        raise ValueError(value)
    return name


def _folder_setting(value):
    if not isinstance(value, str):
        raise ValueError(value)
    return value.strip()


def _presets_setting(value):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(value)
    return list(dict.fromkeys(value))  # without duplicates, in their order


def _mtl_setting(value):
    if not isinstance(value, dict):
        raise ValueError(value)
    enabled, mode = value.get("enabled", False), value.get("mode", "standard")
    if not isinstance(enabled, bool) or mode not in MTL_MODES:
        raise ValueError(value)
    return {"enabled": enabled, "mode": mode}


def _bool_setting(value):
    if not isinstance(value, bool):
        raise ValueError(value)
    return value


# Every setting with its default and the function that checks (and cleans) a value read from the file.
SETTINGS = {
    "fileName": ("custom.vmr", _file_name_setting),
    "lastFolder": ("", _folder_setting),
    "selectedPresets": ([], _presets_setting),
    "mtlRules": ({"enabled": False, "mode": "standard"}, _mtl_setting),
    # added in 1.2: the Community folder the user chose in the GUI ("" = find it in the simulators), and the update
    # check at start
    "communityFolder": ("", _folder_setting),
    "checkForUpdates": (True, _bool_setting),
}
# The settings the page may change through /api/settings. The Community folder is not one of them: the server only
# reads folders the user picked in the folder dialog of the window or that were found in the simulators
# (see /api/community), never a path a request sends.
PAGE_SETTINGS = ("fileName", "selectedPresets", "mtlRules", "checkForUpdates")


def default_settings():
    return json.loads(json.dumps({key: default for key, (default, check) in SETTINGS.items()}))  # a deep copy


class Settings:
    """The settings of the last run. path None keeps them in memory only (used by the tests)."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.file = {}            # what the file contains, kept so that unknown settings survive a write
        self.values = default_settings()
        self.notice = None        # the message for the GUI when the file had to be deleted
        self.lock = threading.Lock()

    def load(self):
        if self.path is None or not self.path.is_file():
            return self
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict) or not isinstance(data.get("settingsVersion"), int) or isinstance(data.get("settingsVersion"), bool):
                raise ValueError("not a settings file of the IVAO VMR generator")
        except (OSError, ValueError) as err:
            return self._reset("Your settings file could not be read (%s)." % err)
        if data["settingsVersion"] < OLDEST_SUPPORTED_SETTINGS_VERSION:
            return self._reset("Your settings file was created by version %s of the IVAO VMR generator, which this version (%s) "
                               "no longer supports." % (data.get("createdBy") or "unknown", APP_VERSION))
        self.file = data
        for key, (default, check) in SETTINGS.items():
            if key in data:
                try:
                    self.values[key] = check(data[key])
                except ValueError:
                    print("  Settings: the value of %s is not valid, using the default." % key)
        return self

    def _reset(self, reason):
        try:
            self.path.unlink()
        except OSError:
            pass
        self.file, self.values = {}, default_settings()
        self.notice = reason + " It was deleted, and the settings were reset to the defaults."
        print("  " + self.notice)
        return self

    def take_notice(self):
        """The message about a deleted settings file, given out only once."""
        notice, self.notice = self.notice, None
        return notice

    def update(self, changes):
        """Takes over the valid known settings in changes and writes the file. Returns the settings."""
        with self.lock:
            for key, value in changes.items():
                if key in SETTINGS:
                    try:
                        self.values[key] = SETTINGS[key][1](value)
                    except ValueError:
                        pass
            self._write()
            return dict(self.values)

    def _write(self):
        if self.path is None:
            return
        # the versions first, so that they are the first thing one sees in the file
        data = {"settingsVersion": None, "createdBy": None, "savedBy": None}
        data.update(self.file)
        for key, value in self.values.items():
            # inside a group of settings, the parts this version does not know are kept as well
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                value = dict(data[key], **value)
            data[key] = value
        # a file written by a newer version keeps its format version, so that version can still read it
        data["settingsVersion"] = max(self.file.get("settingsVersion", 0), SETTINGS_VERSION)
        data["createdBy"] = self.file.get("createdBy") or APP_VERSION
        data["savedBy"] = APP_VERSION
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_name(self.path.name + ".part")
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            temp.replace(self.path)
            self.file = data
        except OSError as err:
            # the settings must never stop the program from working
            print("  Settings could not be saved to %s: %s" % (self.path, err))


# --------------------------------------------------------------------------------------------------
# My rules
# --------------------------------------------------------------------------------------------------

class MyRules:
    """The user's own rules ("My rules" in the GUI), kept in my_rules.vmr in the data folder (before 1.2:
    vmr_gui_my_rules.vmr next to the program, see copy_old_files).

    The file is an ordinary VMR, the format vPilot reads, so it does not change between versions of this
    program and is never deleted with the settings; it can also be opened or imported anywhere. Only complete
    rules (type and at least one livery) are in it, like in every VMR the GUI writes. path None keeps the
    rules in memory only (used by the tests)."""

    COMMENT = "My rules from the IVAO VMR generator. They are loaded again at the next start."

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.rules = None         # None: there is no file yet (the page may still have rules of an older version)
        self.notice = None        # the message for the GUI when rules had to be changed
        self.checked = False      # the rules were compared with the installed liveries in this run
        self.lock = threading.Lock()

    def load(self):
        if self.path is not None and self.path.is_file():
            try:
                self.rules = parse_vmr(_read_text(self.path))
            except OSError as err:
                print("  My rules could not be read from %s: %s" % (self.path, err))
        return self

    def save(self, rules):
        """Writes the rules (the format of parse_vmr) and returns them as they are now stored."""
        with self.lock:
            text = build_vmr(rules, self.COMMENT)
            self.rules = parse_vmr(text)
            if self.path is not None:
                try:
                    temp = self.path.with_name(self.path.name + ".part")
                    temp.write_text(text, encoding="utf-8", newline="")
                    temp.replace(self.path)
                except OSError as err:
                    print("  My rules could not be saved to %s: %s" % (self.path, err))
            return self.rules

    def remove_missing(self, library, others=()):
        """The IVAO MTL changes: liveries are removed or renamed. A rule loses the liveries that are no longer
        installed, and a rule left without any livery is removed. This is done once per run, and only when the
        MTL was found and read without problems: with a wrong models folder or a damaged aircraft.cfg the
        liveries are only missing for now, and removing rules then would throw away the user's work.
        others: the MTLs of the other simulators on this computer (a user with MSFS 2020 and 2024 can have a
        livery in one MTL only). A livery is only missing when none of them has it, and nothing is removed when
        one of them could not be read without problems either."""
        if self.checked or not self.rules:
            return
        self.checked = True
        for mtl in [library] + list(others):
            if mtl.airplanes is None or not mtl.airplanes.is_dir() or not mtl.liveries or mtl.errors:
                return
        everywhere = set(library.liveries).union(*[set(mtl.liveries) for mtl in others])
        kept, removed, shortened = [], [], []
        for rule in self.rules:
            installed = [m for m in rule["models"] if m in everywhere]
            missing = [m for m in rule["models"] if m not in everywhere]
            name = "%s %s" % (rule["callsign"] or rule.get("exactCallsign") or "*", rule["type"])
            if not installed:
                removed.append("%s (%s)" % (name, ", ".join(missing)))
            elif missing:
                shortened.append("%s (%s)" % (name, ", ".join(missing)))
                kept.append(dict(rule, models=installed))
            else:
                kept.append(rule)
        if not removed and not shortened:
            return
        self.save(kept)
        parts = []
        if removed:
            parts.append("%d of your rules %s removed, because none of %s liveries %s installed any more: %s."
                         % (len(removed), "was" if len(removed) == 1 else "were", "its" if len(removed) == 1 else "their",
                            "is" if len(removed) == 1 else "are", "; ".join(removed)))
        if shortened:
            parts.append("Liveries that are no longer installed were removed from %d of your rules: %s."
                         % (len(shortened), "; ".join(shortened)))
        self.notice = "Your IVAO MTL has changed. " + " ".join(parts)
        print("  " + self.notice)

    def take_notice(self):
        notice, self.notice = self.notice, None
        return notice


# --------------------------------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------------------------------

class App:
    def __init__(self, models_root, output_dir=None, settings=None, my_rules=None, mtl_folders=None, updater=None):
        """models_root None: no MTL was found. output_dir None: the folder the user chose or saved to last (from
        the settings), or default_output_dir() (the MTL folder). A folder given on the command line (-p) is used
        for the whole run unless the user chooses another one. mtl_folders: the simulators found by find_mtl_folders."""
        self.library = Library(models_root)
        self.settings = settings or Settings(None)
        self.my_rules = my_rules or MyRules(None)
        self.mtl_folders = mtl_folders or []
        self.mtl_reason = None    # why this MTL is used (see choose_models_root), shown in the GUI
        self.here = None          # the folder of the program (see choose_models_root), set in main()
        self.take_over_old_files = False  # copy the files of version 1.1 from an MTL the user chooses (set in main())
        self.updater = updater or Updater(APP_VERSION)
        self.files_notice = None  # the message about files copied from an older version (see copy_old_files)
        self.restart = None       # set when an update was installed: the program to start before this one ends
        self.fixed_output_dir = output_dir is not None
        self.output_dir = Path(output_dir) if output_dir is not None else self._remembered_output_dir()
        self.previews = Previews(PREVIEWS_DIR)
        self.scan_lock = threading.Lock()

    def _remembered_output_dir(self):
        last = self.settings.values["lastFolder"]
        return Path(last) if last and Path(last).is_dir() else default_output_dir(self.library.models_root)

    def use_community(self, community):
        """Switches to the MTL in another Community folder (chosen in the GUI) and remembers it for the next start.
        community None: back to finding the MTL in the simulators, the normal way."""
        if community:
            models_root, reason = str(mtl_in_community(community)), "chosen"
        else:
            models_root, reason = choose_models_root(None, "", self.mtl_folders, self.here)
        if models_root and self.take_over_old_files:
            self._take_over_old_files(models_root)
        with self.scan_lock:
            self.library, self.mtl_reason = Library(models_root), reason
        if not self.fixed_output_dir:
            self.output_dir = self._remembered_output_dir()
        self.settings.update({"communityFolder": str(community) if community else ""})

    def _take_over_old_files(self, models_root):
        """The MTL the user just chose may hold the files of version 1.1 that the start could not find (the MTL
        was not found then). When they are copied, the settings and my rules are read again from the data folder."""
        notice = copy_old_files([models_root])
        if notice:
            self.settings = Settings(self.settings.path).load()
            self.my_rules = MyRules(self.my_rules.path).load()
            self.files_notice = notice

    def set_output_dir(self, folder):
        """The output folder the user chose in the GUI; it is kept for the next start."""
        self.output_dir = Path(folder)
        self.settings.update({"lastFolder": str(self.output_dir)})

    def take_files_notice(self):
        notice, self.files_notice = self.files_notice, None
        return notice

    def saved(self, path):
        """Remembers where a VMR was saved: the next VMR goes to the same folder, under the same name."""
        path = Path(path).resolve()
        if not self.fixed_output_dir:
            self.output_dir = path.parent
        self.settings.update({"lastFolder": str(path.parent), "fileName": path.name})

    def scanned_library(self):
        """The library, scanned on first use by whichever request needs it first (the server answers
        several requests at a time, the lock keeps it to one scan)."""
        with self.scan_lock:
            if not self.library.scanned:
                self.library.scan()
        return self.library

    def checked_my_rules(self):
        """My rules without the liveries that are no longer installed in any MTL on this computer (see
        MyRules.remove_missing). None when there is no rules file yet."""
        library = self.scanned_library()
        others = []
        if not self.my_rules.checked and self.my_rules.rules and library.found():
            # the MTLs of the other simulators are only read for this check, and only when there is more than one
            others = [Library(sim["mtl"]).scan() for sim in self.mtl_folders
                      if sim["mtl"] and not _same_folder(sim["mtl"], library.models_root)]
        self.my_rules.remove_missing(library, others)
        return self.my_rules.rules


class Handler(BaseHTTPRequestHandler):
    app = None  # set in main()

    def log_message(self, fmt, *args):
        pass

    # ----- helpers -----
    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cache=False):
        path = Path(path)
        if not path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length) if length > 0 else b""

    def from_this_computer(self):
        """The server only answers the GUI itself. A web page from elsewhere that the user has open could
        otherwise send requests to it: the Host header stops pages that point their own domain name at
        127.0.0.1 (DNS rebinding), and a POST must be JSON, which a browser only sends cross-site after
        asking the server first (a CORS preflight, which this server never allows)."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in ("127.0.0.1", "localhost", "::1"):
            self.send_error(403)
            return False
        return True

    # ----- routing -----
    def do_GET(self):
        if not self.from_this_computer():
            return
        path = urllib.parse.urlparse(self.path).path
        app = self.app
        if path in ("/", "/index.html"):
            self.send_file(GUI_DIR / "index.html")
        elif path.startswith("/static/"):
            name = Path(path[len("/static/"):]).name
            self.send_file(GUI_DIR / name)
        elif path == "/api/state":
            library = app.scanned_library()
            self.send_json({
                "modelsRoot": str(library.models_root) if library.models_root else None,
                "airplanesFolder": str(library.airplanes) if library.airplanes else None,
                "libraryFound": library.found(),
                "mtlReason": app.mtl_reason,
                "mtlFolders": app.mtl_folders,
                "communityFolder": app.settings.values["communityFolder"],
                "dataDir": str(DATA_DIR),
                "presetsDir": str(DATA_DIR / "presets"),
                "outputDir": str(app.output_dir),
                "liveries": app.library.summary(),
                "errors": app.library.errors,
                "presets": list_presets(),
                "mtlRules": {"all": app.library.mtl_rules(False), "standard": app.library.mtl_rules(True)},
                "catalogSearch": CATALOG_SEARCH,
                "previewsDir": str(PREVIEWS_DIR),
                "version": APP_VERSION,
                "settings": app.settings.values,
                "settingsNotice": app.settings.take_notice(),
                "myRules": app.checked_my_rules(),
                "myRulesNotice": app.my_rules.take_notice(),
                "filesNotice": app.take_files_notice(),
            })
        elif path == "/api/rescan":
            app.library.scan()
            self.send_json({
                "liveries": app.library.summary(),
                "errors": app.library.errors,
                "mtlRules": {"all": app.library.mtl_rules(False), "standard": app.library.mtl_rules(True)},
            })
        elif path == "/api/update":
            # asks GitHub once per run, and only when the user has not switched the check off
            if not app.updater.checked and app.settings.values["checkForUpdates"] and not SELF_TEST:
                app.updater.check()
            self.send_json(dict(app.updater.status(), enabled=app.settings.values["checkForUpdates"]))
        elif path.startswith("/api/preview/"):
            # the catalog picture of a livery (downloaded on first use, then served from the previews folder)
            livery = app.scanned_library().liveries.get(urllib.parse.unquote(path[len("/api/preview/"):]))
            picture = app.previews.get(livery["catalogId"]) if livery and livery.get("catalogId") else None
            if picture:
                self.send_file(picture, cache=True)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        # Read the body before any answer: closing the connection with an unread body resets it on Windows.
        body = self.read_body()
        if not self.from_this_computer():
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self.send_json({"error": "Expected application/json"}, 415)
            return
        path = urllib.parse.urlparse(self.path).path
        app = self.app
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except ValueError as err:
            self.send_json({"error": "Invalid JSON: %s" % err}, 400)
            return
        if path == "/api/parse-vmr":
            self.send_json({"rules": parse_vmr(data.get("text", ""))})
        elif path == "/api/build":
            self.send_json({"text": build_vmr(data.get("rules", []), data.get("comment"))})
        elif path == "/api/save":
            name = Path(data.get("fileName") or "custom.vmr").name
            if not name.lower().endswith(".vmr"):
                name += ".vmr"
            target = app.output_dir / name
            try:
                app.output_dir.mkdir(parents=True, exist_ok=True)
                target.write_text(build_vmr(data.get("rules", []), data.get("comment")), encoding="utf-8", newline="")
            except OSError as err:
                self.send_json({"error": "Could not write %s: %s" % (target, err)}, 500)
                return
            app.saved(target)
            self.send_json({"path": str(target.resolve()), "outputDir": str(app.output_dir)})
        elif path == "/api/my-rules":
            # the page sends all its own rules after every change; incomplete ones are not stored
            rules = data.get("rules")
            if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
                self.send_json({"error": "Expected a list of rules"}, 400)
                return
            self.send_json({"rules": app.my_rules.save(rules)})
        elif path == "/api/settings":
            # the page sends the settings it changed (file name, ticked presets, MTL choice, update check)
            changes = data.get("settings") if isinstance(data.get("settings"), dict) else {}
            self.send_json({"settings": app.settings.update({k: v for k, v in changes.items() if k in PAGE_SETTINGS})})
        elif path == "/api/community":
            # switch to the Community folder of another simulator that was found, or (null) back to finding the
            # MTL by itself. Any other folder only through the folder dialog of the window
            # (JsApi.choose_community_folder), so that no request can make the server read a path of its choice.
            community = data.get("community")
            if community is not None and community not in [sim["community"] for sim in app.mtl_folders if sim["mtl"]]:
                self.send_json({"error": "Not a Community folder with the MTL found in your simulators"}, 400)
                return
            app.use_community(community)
            self.send_json({"modelsRoot": str(app.library.models_root) if app.library.models_root else None})
        elif path == "/api/output-folder":
            # back to the default output folder (the MTL folder); any other folder only through the folder dialog
            if not data.get("default"):
                self.send_json({"error": "Choose the folder in the window"}, 400)
                return
            app.settings.update({"lastFolder": ""})
            app.fixed_output_dir = False
            app.output_dir = app._remembered_output_dir()
            self.send_json({"outputDir": str(app.output_dir)})
        elif path == "/api/update":
            action = data.get("action")
            if action == "check":
                # "Check now": also when the check at start is switched off
                self.send_json(dict(app.updater.check(), enabled=app.settings.values["checkForUpdates"]))
            elif action == "install":
                try:
                    app.restart = app.updater.install()
                except UpdateError as err:
                    self.send_json({"error": str(err)}, 500)
                    return
                self.send_json({"installed": app.updater.latest["version"]})
                # the answer has to reach the page before the program ends
                threading.Thread(target=finish_update, args=(app,), daemon=True).start()
            else:
                self.send_json({"error": "Unknown action"}, 400)
        else:
            self.send_error(404)


def finish_update(app, delay=1.0):
    """Starts the updated program and ends this one (step 5 of the update)."""
    import time
    time.sleep(delay)
    try:
        start_program(app.restart, sys.argv[1:])
    except OSError as err:
        # the new .exe is in place already; the user only has to start it
        print("  Could not start the updated program: %s" % err)
    sys.stdout.flush()
    os._exit(0)


class JsApi:
    """Functions the page can call through window.pywebview.api when the GUI runs in its own window."""

    def __init__(self, app=None):
        # Underscore: pywebview exposes every public attribute of this object to the page and walks
        # it recursively. Walking the Window object (and the .NET form behind it) never finishes and
        # the page then never gets its window.pywebview.api.
        self._window = None
        self._app = app

    def save_as(self, file_name, text):
        """Shows the Windows "Save as" dialog, opened in the folder of the last saved VMR, and writes the VMR
        text to the chosen file."""
        import webview
        folder = str(self._app.output_dir.resolve()) if self._app else ""
        result = self._window.create_file_dialog(webview.FileDialog.SAVE, directory=folder, save_filename=file_name, file_types=("VMR files (*.vmr)", "All files (*.*)"))
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            Path(path).write_text(text, encoding="utf-8", newline="")
        except OSError as err:
            return {"error": str(err)}
        if self._app:
            self._app.saved(path)
            return {"path": str(path), "outputDir": str(self._app.output_dir)}
        return {"path": str(path)}

    def open_file(self):
        """Shows the "Open" dialog and returns the text of the chosen VMR file."""
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.OPEN, file_types=("VMR files (*.vmr)", "All files (*.*)"))
        if not result:
            return {"cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            return {"name": Path(path).name, "text": _read_text(path)}
        except OSError as err:
            return {"error": str(err)}

    def _choose_folder(self, start):
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(start or ""))
        if not result:
            return None
        return Path(result[0] if isinstance(result, (list, tuple)) else result)

    def choose_community_folder(self):
        """Shows the folder dialog and uses the MTL in the chosen Community folder. Picking the IVAO_MTL folder
        itself is accepted as well (its Community folder is remembered)."""
        library = self._app.library if self._app else None
        folder = self._choose_folder(library.models_root.parent if library and library.models_root else "")
        if folder is None:
            return {"cancelled": True}
        community = community_of(folder)
        if community is None:
            return {"error": "There is no IVAO MTL in %s. Choose the Community folder of your simulator, the one that "
                             "contains the IVAO_MTL folder." % folder}
        if self._app:
            self._app.use_community(community)
        return {"community": str(community)}

    def choose_output_folder(self):
        """Shows the folder dialog and saves the next VMRs into the chosen folder."""
        folder = self._choose_folder(self._app.output_dir if self._app else "")
        if folder is None:
            return {"cancelled": True}
        if self._app:
            self._app.set_output_dir(folder)
        return {"outputDir": str(folder)}


def show_window(url, server, app=None):
    """Shows the GUI in its own window. Returns False when pywebview is not available."""
    try:
        import webview
    except ImportError as err:
        print("pywebview is not installed (%s), opening the browser instead." % err)
        return False
    api = JsApi(app)
    print("  Opening the window (pywebview %s)." % getattr(webview, "__version__", "?"))
    window = webview.create_window("IVAO VMR generator", url, js_api=api, width=1500, height=950, min_size=(1000, 650))
    api._window = window
    loaded = threading.Event()

    def on_loaded():
        print("  Page loaded in the window.")
        loaded.set()
    window.events.loaded += on_loaded
    # Used by the build workflow to check that the window really opens: close it again once the page
    # has loaded (closing a window whose page is still loading can hang WebView2).
    if SELF_TEST:
        def close_soon():
            import time
            if not loaded.wait(30):
                print("  Self-test: the page did not load within 30 s.")
            time.sleep(2)
            print("  Self-test: closing the window.")
            window.destroy()
        webview.start(close_soon)
        if not loaded.is_set():
            raise RuntimeError("Self-test: the page never loaded in the window.")
    else:
        webview.start()
    print("  Window closed.")
    server.shutdown()
    return True


def main():
    parser = argparse.ArgumentParser(description="GUI for building a custom vPilot VMR on top of the IVAO MTL.")
    parser.add_argument("-d", "--directory", default=None, help="folder that contains SimObjects/Airplanes (default: the MTL found in the Community folder of your simulator)")
    parser.add_argument("-c", "--community", default=None, help="the Community folder that contains the IVAO_MTL folder, when it is not found by itself (default: the one chosen in the GUI, else found in your simulator)")
    parser.add_argument("-p", "--output-directory", default=None, help="folder where VMR files are saved (default: the folder chosen in the GUI or saved to last, the first time the IVAO_MTL folder)")
    parser.add_argument("--port", type=int, default=8765, help="port of the local server (default: 8765, a free port is used if it is taken)")
    parser.add_argument("--browser", action="store_true", help="show the GUI in the web browser instead of its own window")
    parser.add_argument("--no-browser", action="store_true", help="only run the server, do not open a window or a browser")
    args = parser.parse_args()

    print("IVAO VMR generator GUI " + APP_VERSION)
    # The .exe works in its own folder, because Windows does not always start a double-clicked program in the
    # folder it lies in; the script works in the folder it is run from.
    here = APP_DIR if FROZEN else Path.cwd()
    if FROZEN:
        remove_old_exe(sys.executable)
    found = find_mtl_folders()
    for sim in found:
        print("  Found %s: %s" % (sim["sim"], sim["mtl"] or "no IVAO MTL in " + sim["community"]))
    settings = Settings(SETTINGS_FILE).load()
    community = args.community or settings.values["communityFolder"]
    # the files of version 1.1, also from the MTL of the Community folder chosen before (then read the settings again)
    files_notice = copy_old_files(old_file_folders(here, args.directory, found, community))
    if files_notice:
        notice, settings = settings.notice, Settings(SETTINGS_FILE).load()
        settings.notice = settings.notice or notice
    models_root, reason = choose_models_root(args.directory, community, found, here)
    updater = Updater(APP_VERSION, sys.executable if FROZEN else None)
    app = Handler.app = App(models_root, args.output_directory, settings, MyRules(MY_RULES_FILE).load(), found, updater)
    app.mtl_reason, app.files_notice, app.here, app.take_over_old_files = reason, files_notice, here, True
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        # The port is taken (for example by a second copy of the GUI): let the system pick a free one.
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = "http://127.0.0.1:%d/" % server.server_address[1]
    print("  Settings: " + str(SETTINGS_FILE))
    print("  My rules: " + str(MY_RULES_FILE))
    print("  Models folder: " + (os.path.abspath(models_root) + " (%s)" % reason if models_root else "no IVAO MTL found"))
    print("  Output folder: " + os.path.abspath(app.output_dir))
    print("  GUI address: " + url)

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        if args.no_browser and SELF_TEST:
            # the server smoke test of the build workflow: answer requests for a while, then stop cleanly
            print("  Self-test: server only, stopping after %g s." % SELF_TEST_SERVER_SECONDS)
            server_thread.join(SELF_TEST_SERVER_SECONDS)
            print("  Self-test: stopping the server.")
        elif args.no_browser:
            print("  Server only (--no-browser). Press Ctrl+C to stop.")
            server_thread.join()
        elif not args.browser and show_window(url, server, app):
            pass
        else:
            if SELF_TEST:
                raise RuntimeError("The GUI window could not be opened (pywebview missing).")
            print("  Open " + url + " in your browser. Press Ctrl+C to stop.")
            webbrowser.open(url)
            server_thread.join()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.shutdown()


def report_crash(text):
    """Shows the error when there is no console to print it to (the .exe has none)."""
    print(text)
    if sys.platform == "win32" and not SELF_TEST:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text + "\n\nThe full log is in " + str(LOG_FILE), "IVAO VMR generator", 0x10)
        except Exception:
            pass


def open_log():
    """The .exe has no console window: what the program prints goes to vmr_gui.log in Local AppData. A log that has
    grown too long is kept once as vmr_gui.old.log."""
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.is_file() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            LOG_FILE.replace(LOG_FILE.with_name("vmr_gui.old.log"))
        sys.stdout = sys.stderr = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except OSError:
        pass


if __name__ == "__main__":
    if FROZEN:
        open_log()
    if SELF_TEST:
        # Backstop for the build workflow: never hang around, whatever the window does.
        def watchdog():
            import time
            time.sleep(max(40, SELF_TEST_SERVER_SECONDS + 10))
            print("  Self-test: watchdog fired, the program did not finish in time.")
            sys.stdout.flush()
            os._exit(3)
        threading.Thread(target=watchdog, daemon=True).start()
    exit_code = 0
    try:
        main()
    except Exception:
        import traceback
        report_crash(traceback.format_exc())
        exit_code = 1
    # The window toolkit (pywebview, .NET) can leave threads behind that would keep the process alive
    # after the window is closed; end the process explicitly.
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(exit_code)
