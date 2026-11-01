# The settings of the last run (vmr_gui_settings.json): what is kept, how files from other versions are
# handled, and how the server and the "Save as" dialog use and update them.

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from support import ServerTestCase, TempDirTestCase, vmr_gui
from test_window import FakeWindow, fake_webview

DEFAULTS = {"fileName": "custom.vmr", "lastFolder": "", "selectedPresets": [], "mtlRules": {"enabled": False, "mode": "standard"},
            "communityFolder": "", "checkForUpdates": True}


class SettingsFileTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.tmp / "vmr_gui_settings.json"
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, data):
        self.path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")

    def load(self):
        return vmr_gui.Settings(self.path).load()

    def test_defaults_without_a_file(self):
        settings = self.load()
        self.assertEqual(settings.values, DEFAULTS)
        self.assertIsNone(settings.notice)
        self.assertFalse(self.path.exists())  # reading never creates the file

    def test_round_trip(self):
        settings = self.load()
        settings.update({"fileName": "my rules.vmr", "lastFolder": str(self.tmp), "selectedPresets": ["smartwings_group", "extra_rules"],
                         "mtlRules": {"enabled": True, "mode": "all"}, "communityFolder": str(self.tmp), "checkForUpdates": False})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["settingsVersion"], vmr_gui.SETTINGS_VERSION)
        self.assertEqual(data["createdBy"], vmr_gui.APP_VERSION)
        self.assertEqual(data["savedBy"], vmr_gui.APP_VERSION)
        again = self.load()
        self.assertEqual(again.values, {"fileName": "my rules.vmr", "lastFolder": str(self.tmp), "selectedPresets": ["smartwings_group", "extra_rules"],
                                        "mtlRules": {"enabled": True, "mode": "all"}, "communityFolder": str(self.tmp), "checkForUpdates": False})
        self.assertIsNone(again.notice)
        self.assertFalse(self.path.with_name(self.path.name + ".part").exists())

    def test_created_by_is_kept(self):
        self.write({"settingsVersion": 1, "createdBy": "1.0.0", "savedBy": "1.0.0"})
        self.load().update({"fileName": "x.vmr"})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((data["createdBy"], data["savedBy"]), ("1.0.0", vmr_gui.APP_VERSION))

    def test_file_from_an_older_compatible_version(self):
        # an older version that did not know every setting yet: the missing ones get their defaults
        self.write({"settingsVersion": vmr_gui.OLDEST_SUPPORTED_SETTINGS_VERSION, "createdBy": "1.0.0", "fileName": "old.vmr"})
        settings = self.load()
        self.assertEqual(settings.values, dict(DEFAULTS, fileName="old.vmr"))
        self.assertIsNone(settings.notice)
        self.assertTrue(self.path.exists())

    def test_file_of_version_1_1(self):
        # 1.2 added communityFolder and checkForUpdates without changing settingsVersion: a 1.1 file keeps all its settings
        self.write({"settingsVersion": 1, "createdBy": "1.1.0", "savedBy": "1.1.0", "fileName": "mine.vmr", "lastFolder": "C:\\vPilot Files",
                    "selectedPresets": ["extra_rules"], "mtlRules": {"enabled": True, "mode": "all"}})
        settings = self.load()
        self.assertIsNone(settings.notice)
        self.assertEqual(settings.values, dict(DEFAULTS, fileName="mine.vmr", lastFolder="C:\\vPilot Files", selectedPresets=["extra_rules"],
                                               mtlRules={"enabled": True, "mode": "all"}))

    def test_settings_of_a_newer_version_are_kept(self):
        newer = {"settingsVersion": vmr_gui.SETTINGS_VERSION + 1, "createdBy": "9.0.0", "fileName": "n.vmr",
                 "futureSetting": {"x": 1}, "mtlRules": {"enabled": True, "mode": "standard", "futureOption": 3}}
        self.write(newer)
        settings = self.load()
        self.assertIsNone(settings.notice)
        self.assertEqual(settings.values["fileName"], "n.vmr")
        self.assertTrue(settings.values["mtlRules"]["enabled"])
        settings.update({"fileName": "changed.vmr"})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["futureSetting"], {"x": 1})
        self.assertEqual(data["mtlRules"], {"enabled": True, "mode": "standard", "futureOption": 3})
        self.assertEqual(data["settingsVersion"], vmr_gui.SETTINGS_VERSION + 1)  # the newer version can still read it
        self.assertEqual(data["fileName"], "changed.vmr")

    def test_invalid_values_fall_back_one_by_one(self):
        self.write({"settingsVersion": 1, "fileName": 42, "lastFolder": ["x"], "selectedPresets": "smartwings_group",
                    "mtlRules": {"enabled": "yes", "mode": "standard"}, "communityFolder": 3, "checkForUpdates": "no"})
        self.assertEqual(self.load().values, DEFAULTS)
        self.write({"settingsVersion": 1, "fileName": "  ..\\..\\evil\\a.vmr ", "selectedPresets": ["a", "b", "a"],
                    "mtlRules": {"enabled": True, "mode": "everything"}})
        values = self.load().values
        self.assertEqual(values["fileName"], "a.vmr")  # only a file name, never a path
        self.assertEqual(values["selectedPresets"], ["a", "b"])
        self.assertEqual(values["mtlRules"], DEFAULTS["mtlRules"])

    def test_unsupported_version_is_deleted_with_a_message(self):
        self.write({"settingsVersion": vmr_gui.OLDEST_SUPPORTED_SETTINGS_VERSION - 1, "createdBy": "0.9.0", "fileName": "old.vmr"})
        settings = self.load()
        self.assertFalse(self.path.exists())
        self.assertEqual(settings.values, DEFAULTS)
        self.assertIn("created by version 0.9.0", settings.notice)
        self.assertIn("no longer supports", settings.notice)
        self.assertIn("It was deleted, and the settings were reset to the defaults.", settings.notice)

    def test_notice_is_given_once(self):
        self.write({"settingsVersion": 0})
        settings = self.load()
        first = settings.take_notice()
        self.assertIn("reset to the defaults", first)
        self.assertIsNone(settings.take_notice())

    def test_unreadable_files_are_deleted_with_a_message(self):
        for content in ("{not json", "[1, 2]", '{"fileName": "x.vmr"}', '{"settingsVersion": "1"}', '{"settingsVersion": true}', "\xff\xfe"):
            if content == "\xff\xfe":
                self.path.write_bytes(b"\xff\xfe\x00")
            else:
                self.write(content)
            settings = self.load()
            self.assertFalse(self.path.exists(), content)
            self.assertIn("could not be read", settings.notice, content)
            self.assertEqual(settings.values, DEFAULTS)

    def test_a_reset_file_can_be_written_again(self):
        self.write("{broken")
        settings = self.load()
        settings.update({"fileName": "new.vmr"})
        self.assertEqual(vmr_gui.Settings(self.path).load().values["fileName"], "new.vmr")

    def test_unknown_and_invalid_changes_are_ignored(self):
        settings = self.load()
        values = settings.update({"fileName": "", "selectedPresets": None, "somethingElse": 1})
        self.assertEqual(values, DEFAULTS)
        self.assertNotIn("somethingElse", json.loads(self.path.read_text(encoding="utf-8")))

    def test_a_failing_write_does_not_stop_the_program(self):
        settings = vmr_gui.Settings(self.tmp / "missing" / "file.json")
        with mock.patch.object(Path, "replace", side_effect=OSError("disk full")):
            self.assertEqual(settings.update({"fileName": "x.vmr"})["fileName"], "x.vmr")

    def test_in_memory_settings_never_write(self):
        settings = vmr_gui.Settings(None).load()
        settings.update({"fileName": "x.vmr"})
        self.assertEqual(settings.values["fileName"], "x.vmr")
        self.assertEqual(list(self.tmp.iterdir()), [])


class AppVersionTest(TempDirTestCase):
    def test_version_file(self):
        (self.tmp / "version.txt").write_text("1.4.2\n", encoding="utf-8")
        with mock.patch.object(vmr_gui, "BUNDLE_DIR", self.tmp):
            self.assertEqual(vmr_gui.read_app_version(), "1.4.2")

    def test_from_source(self):
        with mock.patch.object(vmr_gui, "BUNDLE_DIR", self.tmp):
            self.assertEqual(vmr_gui.read_app_version(), "dev")


class OutputFolderTest(TempDirTestCase):
    def settings(self, **values):
        settings = vmr_gui.Settings(None)
        settings.values.update(values)
        return settings

    def test_last_folder_is_the_next_output_folder(self):
        app = vmr_gui.App(self.tmp, None, self.settings(lastFolder=str(self.tmp)))
        self.assertEqual(app.output_dir, self.tmp)

    def test_missing_last_folder_falls_back(self):
        with mock.patch.object(vmr_gui, "default_output_dir", return_value=self.tmp / "vPilot Files"):
            app = vmr_gui.App(self.tmp, None, self.settings(lastFolder=str(self.tmp / "gone")))
        self.assertEqual(app.output_dir, self.tmp / "vPilot Files")

    def test_command_line_folder_wins_and_stays(self):
        fixed = self.tmp / "fixed"
        app = vmr_gui.App(self.tmp, fixed, self.settings(lastFolder=str(self.tmp)))
        self.assertEqual(app.output_dir, fixed)
        app.saved(self.tmp / "elsewhere" / "x.vmr")
        self.assertEqual(app.output_dir, fixed)
        self.assertEqual(app.settings.values["lastFolder"], str((self.tmp / "elsewhere").resolve()))

    def test_saved_updates_folder_and_name(self):
        app = vmr_gui.App(self.tmp, None, self.settings())
        app.saved(self.tmp / "sub" / "named.vmr")
        self.assertEqual(app.output_dir, (self.tmp / "sub").resolve())
        self.assertEqual(app.settings.values["fileName"], "named.vmr")


class SettingsServerTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.settings_path = cls.tmp / "vmr_gui_settings.json"
        cls.settings_path.write_text(json.dumps({"settingsVersion": 0, "createdBy": "0.1.0"}), encoding="utf-8")
        with mock.patch("builtins.print"):
            settings = vmr_gui.Settings(cls.settings_path).load()
        cls.app = vmr_gui.App(cls.mtl, None, settings)
        vmr_gui.Handler.app = cls.app

    def test_1_state_shows_the_notice_once(self):
        state = json.loads(self.request("GET", "/api/state")[2])
        self.assertIn("created by version 0.1.0", state["settingsNotice"])
        self.assertEqual(state["settings"], DEFAULTS)
        self.assertEqual(state["version"], vmr_gui.APP_VERSION)
        self.assertIsNone(json.loads(self.request("GET", "/api/state")[2])["settingsNotice"])

    def test_2_settings_are_saved(self):
        status, _, body = self.post_json("/api/settings", {"settings": {"fileName": "mine.vmr", "selectedPresets": ["extra_rules"],
                                                                       "mtlRules": {"enabled": True, "mode": "all"}, "lastFolder": 5}})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["settings"]["fileName"], "mine.vmr")
        data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual((data["fileName"], data["selectedPresets"], data["mtlRules"]["mode"]), ("mine.vmr", ["extra_rules"], "all"))
        self.assertEqual(json.loads(self.request("GET", "/api/state")[2])["settings"]["fileName"], "mine.vmr")

    def test_2b_the_page_cannot_set_the_community_folder(self):
        status, _, body = self.post_json("/api/settings", {"settings": {"communityFolder": str(self.tmp), "checkForUpdates": False}})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["settings"]["communityFolder"], "")
        self.assertFalse(json.loads(body)["settings"]["checkForUpdates"])
        self.assertEqual(self.post_json("/api/settings", {"settings": "x"})[0], 200)  # not a dict: nothing changes

    def test_3_saving_a_vmr_remembers_the_folder(self):
        self.app.output_dir = self.out
        status, _, body = self.post_json("/api/save", {"fileName": "saved here", "rules": [{"callsign": "", "type": "C172", "models": ["C172"]}]})
        self.assertEqual(status, 200)
        result = json.loads(body)
        self.assertEqual(result["outputDir"], str(self.out.resolve()))
        data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual((data["lastFolder"], data["fileName"]), (str(self.out.resolve()), "saved here.vmr"))
        # the next start of the program saves into the same folder again
        with mock.patch("builtins.print"):
            restarted = vmr_gui.App(self.mtl, None, vmr_gui.Settings(self.settings_path).load())
        self.assertEqual(restarted.output_dir, self.out.resolve())


class SaveAsDialogTest(TempDirTestCase):
    def test_opens_in_the_last_folder_and_remembers_the_new_one(self):
        start = self.tmp / "start"
        start.mkdir()
        settings = vmr_gui.Settings(self.tmp / "settings.json")
        app = vmr_gui.App(self.tmp, None, settings)
        app.output_dir = start
        api = vmr_gui.JsApi(app)
        target = self.tmp / "chosen" / "picked.vmr"
        target.parent.mkdir()
        api._window = FakeWindow([str(target)])
        with mock.patch.dict(sys.modules, {"webview": fake_webview()}):
            result = api.save_as("custom.vmr", "text")
        self.assertEqual(api._window.calls[0][1]["directory"], str(start.resolve()))
        self.assertEqual(result, {"path": str(target), "outputDir": str(target.parent.resolve())})
        self.assertEqual(app.output_dir, target.parent.resolve())
        saved = json.loads((self.tmp / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["lastFolder"], saved["fileName"]), (str(target.parent.resolve()), "picked.vmr"))


if __name__ == "__main__":
    unittest.main()
