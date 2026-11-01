# Files around the code: presets, license files, the license collector, the exe build and the workflow.

import importlib.util
import re
import unittest
import xml.etree.ElementTree as ET
from collections import Counter
from unittest import mock

from support import ROOT, TempDirTestCase, vmr_gui


def load_collector():
    spec = importlib.util.spec_from_file_location("collect_licenses", ROOT / "tools" / "collect_licenses.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PresetFilesTest(unittest.TestCase):
    def test_presets(self):
        files = sorted((ROOT / "presets").glob("*.vmr"))
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            ET.fromstring(text.split("<!--")[0].split("?>", 1)[-1].strip())  # well-formed
            rules = vmr_gui.parse_vmr(text)
            self.assertTrue(rules, path.name)
            for rule in rules:
                self.assertRegex(rule["callsign"], r"^([A-Z]{3})?$", path.name)
                self.assertRegex(rule["type"], r"^[A-Z0-9]{2,4}$", path.name)
                self.assertTrue(rule["models"], path.name)
            # a second rule with the same callsign and type would never be used by vPilot
            twice = [k for k, n in Counter((r["callsign"], r["type"]) for r in rules).items() if n > 1]
            self.assertEqual(twice, [], path.name)


class LicenseFilesTest(unittest.TestCase):
    def test_license_is_the_unmodified_apache_text(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License\n                           Version 2.0, January 2004", text)
        self.assertIn("END OF TERMS AND CONDITIONS", text)
        self.assertIn("Copyright [yyyy] [name of copyright owner]", text)  # the template appendix stays as it is

    def test_notice(self):
        text = (ROOT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("Andrew Ward", text)
        self.assertIn("THIRD-PARTY-LICENSES.txt", text)
        self.assertIn("not affiliated", text)

    def test_headers(self):
        self.assertIn("Apache License, Version 2.0", (ROOT / "create_vmr.py").read_text(encoding="utf-8")[:600])
        self.assertIn("Apache License, Version 2.0", (ROOT / "vmr_gui.py").read_text(encoding="utf-8")[:600])
        self.assertIn("Andrew Ward", (ROOT / "build_exe.spec").read_text(encoding="utf-8"))


class CollectLicensesTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.collector = load_collector()

    def test_fallback_texts_exist(self):
        for name in ("proxy_tools.LICENSE.txt", "Microsoft.Web.WebView2.LICENSE.md"):
            self.assertIn("Copyright", (self.collector.FALLBACK_DIR / name).read_text(encoding="utf-8"), name)

    def test_section(self):
        self.assertEqual(self.collector.section("T", "  body \n"), "=" * 78 + "\nT\n" + "=" * 78 + "\n\nbody\n\n")

    def test_missing_license_fails_and_writes_nothing(self):
        target = self.tmp / "THIRD-PARTY-LICENSES.txt"
        with mock.patch.object(self.collector, "PACKAGES", ["surely-not-installed-package"]), mock.patch("builtins.print"):
            self.assertEqual(self.collector.main(target), 1)
        self.assertFalse(target.exists())

    def test_installed_package(self):
        # pip is installed everywhere and has license files in its .dist-info
        import webview  # noqa: F401  (skips below when the GUI dependencies are not installed)
        target = self.tmp / "THIRD-PARTY-LICENSES.txt"
        with mock.patch("builtins.print"):
            self.assertEqual(self.collector.main(target), 0)
        text = target.read_text(encoding="utf-8")
        for name in ["Python"] + self.collector.PACKAGES + ["Microsoft WebView2 SDK"]:
            self.assertIn(name.replace("_", "").lower(), text.replace("_", "").replace("-", "").lower(), name)

    try:
        import webview  # noqa: F401
    except ImportError:
        test_installed_package = unittest.skip("pywebview not installed")(test_installed_package)


class BuildFilesTest(unittest.TestCase):
    def test_exe_bundles_gui_and_presets(self):
        spec = (ROOT / "build_exe.spec").read_text(encoding="utf-8")
        self.assertIn('datas=[("gui", "gui"), ("presets", "presets"), (write_app_version(os.path.join(workpath, "version.txt")), ".")]', spec)
        self.assertIn('["vmr_gui.py"]', spec)

    def test_workflow(self):
        workflow = (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")
        self.assertIn("python -m unittest discover -s tests", workflow)
        self.assertLess(workflow.index("unittest discover"), workflow.index("pyinstaller build_exe.spec"))
        self.assertIn("tools/collect_licenses.py", workflow)
        for name in ("LICENSE", "NOTICE", "THIRD-PARTY-LICENSES.txt"):
            self.assertRegex(workflow, r"release/%s\b" % re.escape(name))

    def test_smoke_tests_never_kill_the_exe(self):
        # a one-file exe is a launcher plus the real program: killing the launcher leaves the program running,
        # so both smoke tests use the self-test mode, in which the program ends by itself
        workflow = (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")
        server = workflow[workflow.index("Smoke test the exe (server)"):workflow.index("Smoke test the exe (window)")]
        self.assertIn('IVAO_VMR_GUI_SELFTEST: "1"', server)
        self.assertIn("WaitForExit", server)
        self.assertNotIn("Stop-Process", server)
        self.assertIn("$state.version -ne $env:EXPECTED_VERSION", server)

    def test_smoke_tests_keep_out_of_the_runners_appdata(self):
        # both smoke tests use their own data folder, and the log of the window test is read from there
        workflow = (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")
        start = workflow.index("Smoke test the exe (server)")
        server, window = workflow[start:workflow.index("Smoke test the exe (window)")], workflow[workflow.index("Smoke test the exe (window)"):]
        window = window[:window.index("- name:", 10)]
        for step in (server, window):
            self.assertIn("IVAO_VMR_GUI_DATA_DIR: ${{ runner.temp }}", step)
        self.assertIn("$state.dataDir -ne $env:IVAO_VMR_GUI_DATA_DIR", server)
        self.assertIn('$log = Join-Path $env:IVAO_VMR_GUI_DATA_DIR "vmr_gui.log"', window)
        self.assertNotIn("dist\\vmr_gui.log", window)

    def test_gitignore(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
        for name in ("build/", "dist/", "previews/", "/licenses/", "__pycache__/", "create_vmr.log", "vmr_gui.log", "vmr_gui_settings.json", "vmr_gui_my_rules.vmr"):
            self.assertIn(name, ignored)
        # only the folder CI generates at the top: tools/licenses/ holds license texts that must be committed
        self.assertNotIn("licenses/", ignored)

    def test_privacy_policy_names_every_host(self):
        # invariant 7: the README privacy policy is part of the code signing requirements and has to stay true
        source = (ROOT / "vmr_gui.py").read_text(encoding="utf-8")
        hosts = set(re.findall(r'"https://([^/"%]+)', source))
        self.assertLessEqual({"download.ivao.aero", "api.github.com", "github.com"}, hosts)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        policy = readme[readme.index("**Privacy policy.**"):readme.index("**Reporting a problem.**")]
        for host in hosts:
            self.assertIn("`%s`" % host, policy, host)
        self.assertIn("Check for a new version at start", policy)  # how to switch the update check off

    def test_create_vmr_stays_standalone(self):
        # Users drop create_vmr.py alone into their MTL folder: standard library imports only (AGENTS.md, invariant 2)
        source = (ROOT / "create_vmr.py").read_text(encoding="utf-8")
        imports = set(re.findall(r"^(?:import|from) (\w+)", source, re.M))
        self.assertLessEqual(imports, {"configparser", "getopt", "os", "re", "pathlib", "sys", "traceback", "collections"})


if __name__ == "__main__":
    unittest.main()
