# Where the GUI keeps its files (AppData), how it finds the IVAO MTL in the Community folder of MSFS 2020 and
# 2024 (Steam and Microsoft Store), and how the files of version 1.1 (next to the program) are taken over.

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from support import ServerTestCase, TempDirTestCase, make_mtl, vmr_gui
from test_window import FakeWindow, fake_webview


class UserFoldersTest(unittest.TestCase):
    def test_windows(self):
        env = {"APPDATA": r"C:\Users\me\AppData\Roaming", "LOCALAPPDATA": r"C:\Users\me\AppData\Local", "USERPROFILE": r"C:\Users\me"}
        data, cache = vmr_gui.user_folders(env, "win32")
        self.assertEqual(data, Path(r"C:\Users\me\AppData\Roaming") / "IVAO VMR Generator")
        self.assertEqual(cache, Path(r"C:\Users\me\AppData\Local") / "IVAO VMR Generator")

    def test_windows_without_the_variables(self):
        data, cache = vmr_gui.user_folders({"USERPROFILE": "/home/me"}, "win32")
        self.assertEqual(data, Path("/home/me") / "AppData" / "Roaming" / "IVAO VMR Generator")
        self.assertEqual(cache, Path("/home/me") / "AppData" / "Local" / "IVAO VMR Generator")

    def test_other_systems(self):
        self.assertEqual(vmr_gui.user_folders({"HOME": "/home/me"}, "linux"),
                         (Path("/home/me/.config/ivao-vmr-generator"), Path("/home/me/.cache/ivao-vmr-generator")))

    def test_override_puts_everything_in_one_folder(self):
        self.assertEqual(vmr_gui.user_folders({"IVAO_VMR_GUI_DATA_DIR": "/tmp/x", "APPDATA": "C:\\"}, "win32"), (Path("/tmp/x"), Path("/tmp/x")))

    def test_the_tests_never_use_the_real_folders(self):
        # support.py sets IVAO_VMR_GUI_DATA_DIR before vmr_gui is imported
        import support
        for path in (vmr_gui.DATA_DIR, vmr_gui.CACHE_DIR, vmr_gui.SETTINGS_FILE.parent, vmr_gui.MY_RULES_FILE.parent, vmr_gui.PREVIEWS_DIR.parent):
            self.assertEqual(path, Path(support.DATA_DIR))

    def test_nothing_is_written_next_to_the_program(self):
        for path in (vmr_gui.SETTINGS_FILE, vmr_gui.MY_RULES_FILE, vmr_gui.LOG_FILE, vmr_gui.PREVIEWS_DIR):
            self.assertNotEqual(path.parent, vmr_gui.APP_DIR, path)
        self.assertEqual((vmr_gui.SETTINGS_FILE.name, vmr_gui.MY_RULES_FILE.name), ("settings.json", "my_rules.vmr"))

    def test_presets_folders(self):
        # bundled presets first, own presets in the data folder last (a later one replaces one of the same name)
        self.assertEqual(vmr_gui.PRESETS_DIRS[0], vmr_gui.BUNDLE_DIR / "presets")
        self.assertEqual(vmr_gui.PRESETS_DIRS[-1], vmr_gui.DATA_DIR / "presets")


class LogTest(TempDirTestCase):
    def test_a_long_log_is_kept_once(self):
        log = self.tmp / "logs" / "vmr_gui.log"
        log.parent.mkdir()
        log.write_text("x" * 50, encoding="utf-8")
        stdout, stderr = sys.stdout, sys.stderr
        try:
            with mock.patch.object(vmr_gui, "LOG_FILE", log), mock.patch.object(vmr_gui, "LOG_MAX_BYTES", 10):
                vmr_gui.open_log()
                print("new run")
                sys.stdout.close()
        finally:
            sys.stdout, sys.stderr = stdout, stderr
        self.assertEqual((log.parent / "vmr_gui.old.log").read_text(encoding="utf-8"), "x" * 50)
        self.assertEqual(log.read_text(encoding="utf-8"), "new run\n")


def write_user_cfg(path, packages, encoding="utf-8", quoted=True):
    """A UserCfg.opt like the simulators write it, with the packages folder near the end."""
    path.parent.mkdir(parents=True, exist_ok=True)
    value = '"%s"' % packages if quoted else packages
    text = "Version 54\r\n{Graphics\r\n\tVersion 1.1\r\n}\r\nInstalledPackagesPath %s\r\n" % value
    path.write_bytes(text.encode(encoding))
    return path


class FindMtlTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.env = {"APPDATA": str(self.tmp / "Roaming"), "LOCALAPPDATA": str(self.tmp / "Local")}

    def sim(self, name, packages, **options):
        """Installs one of the four simulators (its UserCfg.opt) with the given packages folder."""
        for sim, variable, parts in vmr_gui.SIMULATORS:
            if sim == name:
                return write_user_cfg(Path(self.env[variable]).joinpath(*parts), packages, **options)
        raise KeyError(name)

    def test_nothing_installed(self):
        self.assertEqual(vmr_gui.find_mtl_folders(self.env), [])
        self.assertEqual(vmr_gui.find_mtl_folders({}), [])

    def test_every_simulator(self):
        # Steam and Microsoft Store versions of both simulators keep UserCfg.opt in different places
        expected = []
        for i, (sim, variable, parts) in enumerate(vmr_gui.SIMULATORS):
            packages = self.tmp / ("packages%d" % i)
            make_mtl(packages / "Community" / "IVAO_MTL")
            self.sim(sim, packages)
            expected.append({"sim": sim, "community": str(packages / "Community"), "mtl": str(packages / "Community" / "IVAO_MTL")})
        self.assertEqual(vmr_gui.find_mtl_folders(self.env), expected)
        self.assertEqual([s[0] for s in vmr_gui.SIMULATORS], ["MSFS 2024 (Steam)", "MSFS 2024 (Microsoft Store)", "MSFS 2020 (Steam)", "MSFS 2020 (Microsoft Store)"])

    def test_simulator_without_the_mtl(self):
        (self.tmp / "p" / "Community" / "other-addon").mkdir(parents=True)
        self.sim("MSFS 2020 (Steam)", self.tmp / "p")
        self.assertEqual(vmr_gui.find_mtl_folders(self.env), [{"sim": "MSFS 2020 (Steam)", "community": str(self.tmp / "p" / "Community"), "mtl": None}])

    def test_renamed_mtl_folder(self):
        # an add-on manager may link the MTL under another name; only a folder starting with IVAO that is an MTL counts
        (self.tmp / "p" / "Community" / "ivao-fake").mkdir(parents=True)
        make_mtl(self.tmp / "p" / "Community" / "IVAO_MTL_linked")
        self.sim("MSFS 2024 (Steam)", self.tmp / "p")
        self.assertEqual(vmr_gui.find_mtl_folders(self.env)[0]["mtl"], str(self.tmp / "p" / "Community" / "IVAO_MTL_linked"))

    def test_user_cfg_variants(self):
        packages = self.tmp / "Packages é"
        make_mtl(packages / "Community" / "IVAO_MTL")
        for options in ({"quoted": False}, {"encoding": "utf-8-sig"}, {"encoding": "cp1252"}):
            self.sim("MSFS 2024 (Microsoft Store)", packages, **options)
            self.assertEqual(vmr_gui.find_mtl_folders(self.env)[0]["mtl"], str(packages / "Community" / "IVAO_MTL"), options)

    def test_user_cfg_without_packages_path(self):
        path = self.sim("MSFS 2024 (Steam)", "x")
        path.write_text("Version 54\n{Graphics\n}\nInstalledPackagesPath \"\"\n", encoding="utf-8")
        self.assertEqual(vmr_gui.find_mtl_folders(self.env), [])
        path.write_text("Version 54\n", encoding="utf-8")
        self.assertEqual(vmr_gui.find_mtl_folders(self.env), [])

    def test_read_packages_path(self):
        path = self.tmp / "UserCfg.opt"
        path.write_text('{Video\n\tInstalledPackagesPathX 1\n}\n  InstalledPackagesPath "D:\\MSFS\\Packages"  \n', encoding="utf-8")
        self.assertEqual(vmr_gui.read_packages_path(path), "D:\\MSFS\\Packages")
        with self.assertRaises(OSError):
            vmr_gui.read_packages_path(self.tmp / "missing.opt")


class ChooseModelsRootTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.found_mtl = make_mtl(self.tmp / "found" / "IVAO_MTL")
        self.community = self.tmp / "chosen" / "Community"
        self.chosen = make_mtl(self.community / "IVAO_MTL")
        self.here = make_mtl(self.tmp / "here")
        self.found = [{"sim": "MSFS 2024 (Steam)", "community": "x", "mtl": None},
                      {"sim": "MSFS 2020 (Steam)", "community": "y", "mtl": str(self.found_mtl)}]

    def choose(self, directory=None, community="", found=None, here=None):
        return vmr_gui.choose_models_root(directory, community, self.found if found is None else found, here or self.tmp / "nothing")

    def test_command_line_wins(self):
        self.assertEqual(self.choose("D:\\x", str(self.community), here=self.here), ("D:\\x", "command line"))

    def test_community_folder_chosen_by_the_user(self):
        self.assertEqual(self.choose(community=str(self.community), here=self.here), (str(self.chosen), "chosen"))

    def test_chosen_community_folder_without_the_mtl_any_more(self):
        # back to the automatic lookup
        for community in (str(self.tmp / "gone"), str(self.tmp)):
            self.assertEqual(self.choose(community=community), (str(self.found_mtl), "MSFS 2020 (Steam)"))

    def test_program_in_the_mtl_folder_like_version_1_1(self):
        self.assertEqual(self.choose(here=self.here), (str(self.here), "program folder"))
        self.assertEqual(self.choose(found=[], here=None), (None, None))

    def test_found_in_a_simulator(self):
        self.assertEqual(self.choose(), (str(self.found_mtl), "MSFS 2020 (Steam)"))

    def test_nothing(self):
        self.assertEqual(self.choose(found=[]), (None, None))

    def test_community_of_a_picked_folder(self):
        self.assertEqual(vmr_gui.community_of(self.community), self.community)
        self.assertEqual(vmr_gui.community_of(self.chosen), self.community)  # the IVAO_MTL folder itself
        self.assertIsNone(vmr_gui.community_of(self.tmp))
        self.assertIsNone(vmr_gui.community_of(self.here))  # an MTL, but not in a Community folder of its own name


class DefaultOutputFolderTest(TempDirTestCase):
    def test_the_mtl_folder(self):
        mtl = make_mtl(self.tmp / "IVAO_MTL")
        self.assertEqual(vmr_gui.default_output_dir(str(mtl)), mtl)

    def test_without_an_mtl(self):
        (self.tmp / "vPilot Files").mkdir()
        with mock.patch.object(vmr_gui, "documents_folder", return_value=self.tmp):
            self.assertEqual(vmr_gui.default_output_dir(None), self.tmp / "vPilot Files")
            self.assertEqual(vmr_gui.default_output_dir(self.tmp / "not an mtl"), self.tmp / "vPilot Files")

    def test_app_saves_into_the_mtl_until_the_user_chooses(self):
        mtl = make_mtl(self.tmp / "IVAO_MTL")
        app = vmr_gui.App(mtl, None, vmr_gui.Settings(None))
        self.assertEqual(app.output_dir, mtl)
        app.set_output_dir(self.tmp / "mine")
        self.assertEqual((app.output_dir, app.settings.values["lastFolder"]), (self.tmp / "mine", str(self.tmp / "mine")))

    def test_vpilot_files(self):
        (self.tmp / "vPilot Files").mkdir()
        with mock.patch.object(vmr_gui, "documents_folder", return_value=self.tmp):
            self.assertEqual(vmr_gui.default_output_dir(), self.tmp / "vPilot Files")

    def test_documents_without_vpilot(self):
        with mock.patch.object(vmr_gui, "documents_folder", return_value=self.tmp):
            self.assertEqual(vmr_gui.default_output_dir(), self.tmp)

    def test_no_documents(self):
        with mock.patch.object(vmr_gui, "documents_folder", return_value=self.tmp / "missing"):
            self.assertEqual(vmr_gui.default_output_dir(), Path.home())

    @unittest.skipUnless(sys.platform == "win32", "Windows only")
    def test_documents_folder_comes_from_windows(self):
        self.assertTrue(vmr_gui.documents_folder().is_dir())


class CopyOldFilesTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.data = self.tmp / "AppData" / "IVAO VMR Generator"
        self.old = self.tmp / "IVAO_MTL"
        self.old.mkdir()
        files = {self.data / "settings.json": "vmr_gui_settings.json", self.data / "my_rules.vmr": "vmr_gui_my_rules.vmr"}
        for patcher in (mock.patch.object(vmr_gui, "OLD_FILE_NAMES", files), mock.patch.object(vmr_gui, "DATA_DIR", self.data),
                        mock.patch("builtins.print")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_files_are_copied_once_and_the_old_ones_stay(self):
        (self.old / "vmr_gui_settings.json").write_text('{"settingsVersion": 1, "fileName": "old.vmr"}', encoding="utf-8")
        vmr_gui.MyRules(self.old / "vmr_gui_my_rules.vmr").save([{"callsign": "DLH", "type": "A320", "models": ["A320DLH"]}])
        notice = vmr_gui.copy_old_files([self.tmp / "empty", self.old])
        self.assertIn(str(self.data), notice)
        self.assertIn(str(self.old / "vmr_gui_settings.json"), notice)
        self.assertEqual(vmr_gui.Settings(self.data / "settings.json").load().values["fileName"], "old.vmr")
        self.assertEqual(vmr_gui.MyRules(self.data / "my_rules.vmr").load().rules, [{"callsign": "DLH", "type": "A320", "models": ["A320DLH"]}])
        self.assertTrue((self.old / "vmr_gui_settings.json").exists())
        self.assertTrue((self.old / "vmr_gui_my_rules.vmr").exists())
        # the next start: the files are there already, nothing is copied (and nothing said) again
        (self.old / "vmr_gui_settings.json").write_text('{"settingsVersion": 1, "fileName": "changed.vmr"}', encoding="utf-8")
        self.assertIsNone(vmr_gui.copy_old_files([self.old]))
        self.assertEqual(vmr_gui.Settings(self.data / "settings.json").load().values["fileName"], "old.vmr")

    def test_the_first_folder_with_the_file_wins(self):
        second = self.tmp / "second"
        second.mkdir()
        (second / "vmr_gui_settings.json").write_text('{"settingsVersion": 1, "fileName": "second.vmr"}', encoding="utf-8")
        (self.old / "vmr_gui_settings.json").write_text('{"settingsVersion": 1, "fileName": "first.vmr"}', encoding="utf-8")
        vmr_gui.copy_old_files([self.old, second])
        self.assertEqual(vmr_gui.Settings(self.data / "settings.json").load().values["fileName"], "first.vmr")

    def test_nothing_to_copy(self):
        self.assertIsNone(vmr_gui.copy_old_files([self.old, self.tmp / "missing"]))
        self.assertFalse(self.data.exists())

    def test_a_failing_copy_does_not_stop_the_program(self):
        (self.old / "vmr_gui_my_rules.vmr").write_text("<ModelMatchRuleSet />", encoding="utf-8")
        with mock.patch.object(vmr_gui.shutil, "copy2", side_effect=OSError("disk full")):
            self.assertIsNone(vmr_gui.copy_old_files([self.old]))

    def test_an_empty_rules_file_is_replaced(self):
        # the page writes an empty rules file at the first start, before the user showed where the old files are
        vmr_gui.MyRules(self.data / "my_rules.vmr").save([])
        vmr_gui.MyRules(self.old / "vmr_gui_my_rules.vmr").save([{"callsign": "DLH", "type": "A320", "models": ["A320DLH"]}])
        self.assertIsNotNone(vmr_gui.copy_old_files([self.old]))
        self.assertEqual(len(vmr_gui.MyRules(self.data / "my_rules.vmr").load().rules), 1)
        # rules of the user are never replaced, and an empty old file never replaces anything
        vmr_gui.MyRules(self.old / "vmr_gui_my_rules.vmr").save([{"callsign": "AAA", "type": "B738", "models": ["X"]}, {"callsign": "BBB", "type": "B738", "models": ["X"]}])
        self.assertIsNone(vmr_gui.copy_old_files([self.old]))
        self.assertEqual(len(vmr_gui.MyRules(self.data / "my_rules.vmr").load().rules), 1)

    def test_own_presets_are_copied_but_not_the_bundled_ones(self):
        presets = self.old / "presets"
        presets.mkdir()
        (presets / "my_airline.vmr").write_text("<ModelMatchRuleSet />", encoding="utf-8")
        (presets / "smartwings_group.vmr").write_text("<ModelMatchRuleSet />", encoding="utf-8")  # an old copy of a bundled one
        notice = vmr_gui.copy_old_files([self.old], self.data / "presets")
        self.assertIn(str(presets / "my_airline.vmr"), notice)
        self.assertEqual(sorted(p.name for p in (self.data / "presets").iterdir()), ["my_airline.vmr"])
        # an own preset that the user changed in the data folder is not replaced again
        (self.data / "presets" / "my_airline.vmr").write_text("changed", encoding="utf-8")
        self.assertIsNone(vmr_gui.copy_old_files([self.old], self.data / "presets"))
        self.assertEqual((self.data / "presets" / "my_airline.vmr").read_text(encoding="utf-8"), "changed")

    def test_the_bundled_presets_folder_is_never_copied(self):
        # running from source in the repository: its presets folder holds the bundled presets
        self.assertIsNone(vmr_gui.copy_old_files([vmr_gui.BUNDLE_DIR], self.data / "presets"))

    def test_old_file_folders(self):
        mtl = str(self.tmp / "mtl")
        community = self.tmp / "Community"
        chosen = make_mtl(community / "IVAO_MTL")
        folders = vmr_gui.old_file_folders(self.old, str(self.old), [{"sim": "s", "community": "c", "mtl": mtl}, {"sim": "t", "community": "d", "mtl": None}], str(community))
        self.assertEqual(folders, [self.old, Path.cwd(), chosen, Path(mtl)])  # -d is the same folder as the program: once


class TakeOverOnChoiceTest(TempDirTestCase):
    """The MTL with the files of 1.1 was not found at start; the user then chooses its Community folder."""

    def test_old_files_of_the_chosen_mtl_are_taken_over(self):
        data = self.tmp / "AppData"
        files = {data / "settings.json": "vmr_gui_settings.json", data / "my_rules.vmr": "vmr_gui_my_rules.vmr"}
        mtl = make_mtl(self.tmp / "Community" / "IVAO_MTL")
        (mtl / "vmr_gui_settings.json").write_text(json.dumps({"settingsVersion": 1, "fileName": "old.vmr", "lastFolder": str(self.tmp)}), encoding="utf-8")
        vmr_gui.MyRules(mtl / "vmr_gui_my_rules.vmr").save([{"callsign": "", "type": "C172", "models": ["C172"]}])
        with mock.patch.object(vmr_gui, "OLD_FILE_NAMES", files), mock.patch.object(vmr_gui, "DATA_DIR", data), mock.patch("builtins.print"):
            app = vmr_gui.App(None, None, vmr_gui.Settings(data / "settings.json"), vmr_gui.MyRules(data / "my_rules.vmr").load())
            app.take_over_old_files = True
            app.my_rules.save([])  # what the page writes at the first start
            app.use_community(self.tmp / "Community")
            self.assertEqual(app.settings.values["fileName"], "old.vmr")
            self.assertEqual(app.settings.values["communityFolder"], str(self.tmp / "Community"))
            self.assertEqual(app.checked_my_rules(), [{"callsign": "", "type": "C172", "models": ["C172"]}])
            self.assertEqual(app.output_dir, self.tmp)  # the last folder of the old settings
            self.assertIn("vmr_gui_settings.json", app.take_files_notice())


class CommunityServerTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other = make_mtl(cls.tmp / "other" / "IVAO_MTL")
        cls.app = vmr_gui.App(cls.mtl, None, vmr_gui.Settings(None), None,
                              [{"sim": "MSFS 2024 (Steam)", "community": str(cls.mtl.parent), "mtl": str(cls.mtl)},
                               {"sim": "MSFS 2020 (Steam)", "community": str(cls.other.parent), "mtl": str(cls.other)},
                               {"sim": "MSFS 2020 (Microsoft Store)", "community": str(cls.tmp / "empty"), "mtl": None}])
        cls.app.mtl_reason = "MSFS 2024 (Steam)"
        vmr_gui.Handler.app = cls.app

    def state(self):
        return json.loads(self.request("GET", "/api/state")[2])

    def test_1_state(self):
        state = self.state()
        self.assertEqual(state["modelsRoot"], str(self.mtl))
        self.assertEqual(state["mtlReason"], "MSFS 2024 (Steam)")
        self.assertEqual([s["sim"] for s in state["mtlFolders"]], ["MSFS 2024 (Steam)", "MSFS 2020 (Steam)", "MSFS 2020 (Microsoft Store)"])
        self.assertEqual(state["dataDir"], str(vmr_gui.DATA_DIR))
        self.assertEqual(state["presetsDir"], str(vmr_gui.DATA_DIR / "presets"))
        self.assertEqual(state["communityFolder"], "")
        self.assertEqual(state["outputDir"], str(self.mtl))  # the IVAO_MTL folder is the first output folder
        self.assertIsNone(state["filesNotice"])

    def test_2_only_folders_found_in_the_simulators(self):
        # invariant 6: no request can make the server read a folder of its choice
        for community in (str(self.tmp / "elsewhere"), str(self.other.parent) + "\\", 5, str(self.other), str(self.tmp / "empty")):
            self.assertEqual(self.post_json("/api/community", {"community": community})[0], 400, community)
        self.assertEqual(self.post_json("/api/output-folder", {"folder": str(self.tmp)})[0], 400)
        self.assertEqual(self.state()["modelsRoot"], str(self.mtl))

    def test_3_switch_to_the_other_simulator(self):
        status, _, body = self.post_json("/api/community", {"community": str(self.other.parent)})
        self.assertEqual((status, json.loads(body)), (200, {"modelsRoot": str(self.other)}))
        state = self.state()
        self.assertEqual((state["modelsRoot"], state["mtlReason"], state["communityFolder"]), (str(self.other), "chosen", str(self.other.parent)))
        self.assertTrue(state["libraryFound"])
        self.assertEqual(state["outputDir"], str(self.other))  # the output folder follows the MTL until the user chooses one

    def test_4_back_to_the_automatic_lookup(self):
        status, _, body = self.post_json("/api/community", {"community": None})
        self.assertEqual((status, json.loads(body)), (200, {"modelsRoot": str(self.mtl)}))
        state = self.state()
        self.assertEqual((state["mtlReason"], state["communityFolder"]), ("MSFS 2024 (Steam)", ""))

    def test_5_output_folder_back_to_the_mtl(self):
        self.app.set_output_dir(self.out)
        status, _, body = self.post_json("/api/output-folder", {"default": True})
        self.assertEqual((status, json.loads(body)), (200, {"outputDir": str(self.mtl)}))
        self.assertEqual(self.app.settings.values["lastFolder"], "")


class NoMtlTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.app = vmr_gui.App(None, cls.out)
        vmr_gui.Handler.app = cls.app

    def test_state_without_an_mtl(self):
        state = json.loads(self.request("GET", "/api/state")[2])
        self.assertEqual((state["modelsRoot"], state["airplanesFolder"], state["libraryFound"]), (None, None, False))
        self.assertEqual((state["liveries"], state["mtlRules"]["all"]), ([], []))
        self.assertEqual(self.request("GET", "/api/rescan")[0], 200)


class FolderDialogTest(TempDirTestCase):
    def api(self, result):
        app = vmr_gui.App(None, self.tmp, vmr_gui.Settings(None))
        api = vmr_gui.JsApi(app)
        api._window = FakeWindow(result)
        return api, app

    def test_the_community_folder(self):
        community = self.tmp / "Community"
        mtl = make_mtl(community / "IVAO_MTL")
        api, app = self.api([str(community)])
        with mock.patch.dict(sys.modules, {"webview": fake_webview()}):
            self.assertEqual(api.choose_community_folder(), {"community": str(community)})
        self.assertEqual(api._window.calls[0][0], "folder")
        self.assertEqual((app.library.models_root, app.mtl_reason), (mtl, "chosen"))
        self.assertEqual(app.settings.values["communityFolder"], str(community))

    def test_the_mtl_folder_itself(self):
        mtl = make_mtl(self.tmp / "Community" / "IVAO_MTL")
        api, app = self.api(str(mtl))
        with mock.patch.dict(sys.modules, {"webview": fake_webview()}):
            self.assertEqual(api.choose_community_folder(), {"community": str(self.tmp / "Community")})
        self.assertEqual(app.library.models_root, mtl)

    def test_a_folder_without_the_mtl(self):
        api, app = self.api([str(self.tmp)])
        with mock.patch.dict(sys.modules, {"webview": fake_webview()}):
            self.assertIn("There is no IVAO MTL in", api.choose_community_folder()["error"])
            self.assertEqual(self.api(None)[0].choose_community_folder(), {"cancelled": True})
        self.assertIsNone(app.library.models_root)
        self.assertEqual(app.settings.values["communityFolder"], "")

    def test_the_output_folder(self):
        api, app = self.api([str(self.tmp / "vmrs")])
        with mock.patch.dict(sys.modules, {"webview": fake_webview()}):
            self.assertEqual(api.choose_output_folder(), {"outputDir": str(self.tmp / "vmrs")})
            self.assertEqual(self.api([])[0].choose_output_folder(), {"cancelled": True})
        self.assertEqual(api._window.calls[0][1]["directory"], str(self.tmp))  # opens in the current output folder
        self.assertEqual((app.output_dir, app.settings.values["lastFolder"]), (self.tmp / "vmrs", str(self.tmp / "vmrs")))


if __name__ == "__main__":
    unittest.main()
