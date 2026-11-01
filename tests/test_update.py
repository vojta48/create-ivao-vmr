# The update from GitHub releases: finding a newer release, downloading and checking the new .exe, putting it in
# place of the running one, and the /api/update endpoint. The network, the signature check and starting the new
# program are mocked: these tests never go online and never start anything.

import hashlib
import io
import json
import threading
import unittest
import urllib.error
from unittest import mock

from support import ServerTestCase, TempDirTestCase, vmr_gui

EXE = b"MZ new program " * 1000
SIGNER = "CN=SignPath Foundation, O=SignPath Foundation, L=Lewes, S=Delaware, C=US"


def release(tag="v1.3.0", exe=EXE, digest=True, **changes):
    """The JSON GitHub returns for releases/latest."""
    asset = {"name": "IVAO_VMR_Generator.exe", "size": len(exe),
             "browser_download_url": "https://github.com/vojta48/create-ivao-vmr/releases/download/%s/IVAO_VMR_Generator.exe" % tag}
    if digest:
        asset["digest"] = "sha256:" + hashlib.sha256(exe).hexdigest()
    data = {"tag_name": tag, "html_url": "https://github.com/vojta48/create-ivao-vmr/releases/tag/" + tag, "body": "What is new",
            "assets": [{"name": "LICENSE", "size": 10, "browser_download_url": "https://github.com/vojta48/create-ivao-vmr/releases/download/x/LICENSE"}, asset]}
    data.update(changes)
    return data


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeGitHub:
    """Answers urlopen like GitHub: the release JSON for the API, the bytes of the .exe for the download."""

    def __init__(self, data, exe=EXE):
        self.data, self.exe, self.urls = data, exe, []

    def __call__(self, request, timeout=None):
        url = request.full_url
        self.urls.append(url)
        if isinstance(self.data, Exception):
            raise self.data
        if url == vmr_gui.LATEST_RELEASE_API:
            return FakeResponse(json.dumps(self.data).encode("utf-8"))
        return FakeResponse(self.exe)


class VersionTest(unittest.TestCase):
    def test_version_numbers(self):
        self.assertEqual(vmr_gui.version_numbers("1.2.0"), (1, 2, 0))
        self.assertEqual(vmr_gui.version_numbers("v1.10.3"), (1, 10, 3))
        self.assertEqual(vmr_gui.version_numbers("1.2.0-test"), (1, 2, 0))
        for text in ("dev", "", None, "1.2", "version 1.2.0"):
            self.assertIsNone(vmr_gui.version_numbers(text), text)
        self.assertGreater(vmr_gui.version_numbers("1.10.0"), vmr_gui.version_numbers("1.9.9"))  # numbers, not text

    def test_parse_release(self):
        info = vmr_gui.parse_release(release())
        self.assertEqual((info["version"], info["numbers"], info["notes"]), ("1.3.0", (1, 3, 0), "What is new"))
        self.assertEqual(info["page"], "https://github.com/vojta48/create-ivao-vmr/releases/tag/v1.3.0")
        self.assertEqual(info["asset"], {"url": release()["assets"][1]["browser_download_url"], "size": len(EXE), "sha256": hashlib.sha256(EXE).hexdigest()})
        self.assertIsNone(vmr_gui.parse_release(release(digest=False))["asset"]["sha256"])

    def test_only_files_of_this_repository(self):
        data = release()
        data["assets"][1]["browser_download_url"] = "https://evil.example/IVAO_VMR_Generator.exe"
        data["html_url"] = "https://evil.example/"
        info = vmr_gui.parse_release(data)
        self.assertIsNone(info["asset"])
        self.assertEqual(info["page"], vmr_gui.RELEASES_PAGE)
        data["assets"][1]["browser_download_url"] = "https://github.com/someone/else/releases/download/v1/IVAO_VMR_Generator.exe"
        self.assertIsNone(vmr_gui.parse_release(data)["asset"])

    def test_not_a_release(self):
        for data in ([], {"tag_name": "latest"}, {"message": "API rate limit exceeded"}):
            with self.assertRaises(vmr_gui.UpdateError):
                vmr_gui.parse_release(data)

    def test_release_signer(self):
        self.assertTrue(vmr_gui.signed_by_release_signer(SIGNER))
        for subject in (None, "", "CN=Someone Else", "CN=SignPath Foundation Fake, O=x", "CN=Evil, O=SignPath Foundation"):
            self.assertFalse(vmr_gui.signed_by_release_signer(subject), subject)


@unittest.skipUnless(vmr_gui.sys.platform == "win32", "Windows only")
class SignatureTest(TempDirTestCase):
    """The real check through PowerShell's Get-AuthenticodeSignature, on files every Windows has."""

    @unittest.skip("the release exe is not code signed (PR #14 dropped SignPath); the signed-file check is not needed and "
                   "depends on which signature the runner's notepad.exe carries")
    def test_signed_windows_file(self):
        subject = vmr_gui.signer_of(vmr_gui.Path(vmr_gui.os.environ["SystemRoot"]) / "System32" / "notepad.exe")
        self.assertIn("O=Microsoft Corporation", subject)
        self.assertFalse(vmr_gui.signed_by_release_signer(subject))

    def test_unsigned_and_odd_paths(self):
        unsigned = self.tmp / "it's $(unsigned).exe"  # the path never becomes part of the PowerShell command
        unsigned.write_bytes(b"MZ nothing")
        self.assertIsNone(vmr_gui.signer_of(unsigned))
        self.assertIsNone(vmr_gui.signer_of(self.tmp / "missing.exe"))


class CheckTest(unittest.TestCase):
    def check(self, current, data):
        github = FakeGitHub(data)
        updater = vmr_gui.Updater(current, "C:\\x\\IVAO_VMR_Generator.exe")
        with mock.patch("urllib.request.urlopen", github), mock.patch("builtins.print"), mock.patch.object(vmr_gui.sys, "platform", "win32"):
            status = updater.check()
        return status, github

    def test_newer_release(self):
        status, github = self.check("1.2.0", release("v1.3.0"))
        self.assertEqual(github.urls, [vmr_gui.LATEST_RELEASE_API])
        self.assertEqual((status["available"], status["latest"], status["current"], status["canInstall"]), (True, "1.3.0", "1.2.0", True))
        self.assertEqual(status["notes"], "What is new")
        self.assertIsNone(status["error"])

    def test_same_release(self):
        status, _ = self.check("1.3.0", release("v1.3.0"))
        self.assertEqual((status["available"], status["development"], status["canInstall"], status["notes"]), (False, False, False, ""))

    def test_newer_than_the_latest_release_is_a_development_version(self):
        # a build of a branch that is not released yet: never asked to "update" to the older release
        for current in ("1.4.0", "1.3.1", "2.0.0-test"):
            status, _ = self.check(current, release("v1.3.0"))
            self.assertEqual((status["available"], status["development"], status["canInstall"]), (False, True, False), current)

    def test_workflow_builds_never_ask(self):
        # every build of the workflow that is not a release is 0.0.0
        status, github = self.check("0.0.0", release())
        self.assertEqual(github.urls, [])
        self.assertEqual((status["available"], status["development"]), (False, True))
        self.assertTrue(vmr_gui.is_development_version("dev"))
        self.assertFalse(vmr_gui.is_development_version("1.2.0"))

    def test_release_without_the_exe(self):
        status, _ = self.check("1.2.0", release(assets=[]))
        self.assertTrue(status["available"])
        self.assertFalse(status["canInstall"])  # the page links to the release instead

    def test_running_from_source_never_asks(self):
        status, github = self.check("dev", release())
        self.assertEqual(github.urls, [])
        self.assertEqual((status["checked"], status["available"], status["latest"]), (True, False, None))

    def test_running_from_source_cannot_install(self):
        updater = vmr_gui.Updater("1.2.0", None)
        with mock.patch("urllib.request.urlopen", FakeGitHub(release())), mock.patch.object(vmr_gui.sys, "platform", "win32"):
            status = updater.check()
        self.assertEqual((status["available"], status["canInstall"]), (True, False))

    def test_no_network(self):
        for error in (urllib.error.URLError("offline"), OSError("reset"), ValueError("bad JSON")):
            status, _ = self.check("1.2.0", error)
            self.assertIn("Could not check for a new version", status["error"])
            self.assertFalse(status["available"])


class InstallTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.exe = self.tmp / "IVAO_VMR_Generator.exe"
        self.exe.write_bytes(b"MZ old program")
        for patcher in (mock.patch("builtins.print"), mock.patch.object(vmr_gui.sys, "platform", "win32")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def updater(self, data=None, exe=EXE, signer=SIGNER, running_signer=SIGNER):
        """signer: who signed the downloaded .exe; running_signer: who signed the running one (None: not signed)."""
        github = FakeGitHub(data or release(), exe)
        updater = vmr_gui.Updater("1.2.0", self.exe)
        with mock.patch("urllib.request.urlopen", github):
            updater.check()
        signers = {self.exe.name: running_signer, self.exe.name + ".new": signer}
        self.patches = [mock.patch("urllib.request.urlopen", github),
                        mock.patch.object(vmr_gui, "signer_of", side_effect=lambda path: signers[vmr_gui.Path(path).name])]
        return updater

    def install(self, updater):
        with self.patches[0], self.patches[1]:
            return updater.install()

    def files(self):
        return sorted(p.name for p in self.tmp.iterdir())

    def assert_untouched(self):
        self.assertEqual(self.exe.read_bytes(), b"MZ old program")
        self.assertEqual(self.files(), ["IVAO_VMR_Generator.exe"])

    def test_install(self):
        self.assertEqual(self.install(self.updater()), self.exe)
        self.assertEqual(self.exe.read_bytes(), EXE)
        # the running program could only be renamed; the next start deletes it
        self.assertEqual((self.tmp / "IVAO_VMR_Generator.exe.old").read_bytes(), b"MZ old program")
        self.assertEqual(self.files(), ["IVAO_VMR_Generator.exe", "IVAO_VMR_Generator.exe.old"])
        vmr_gui.remove_old_exe(self.exe)
        self.assertEqual(self.files(), ["IVAO_VMR_Generator.exe"])

    def test_without_a_checksum_from_github(self):
        self.install(self.updater(release(digest=False)))
        self.assertEqual(self.exe.read_bytes(), EXE)

    def test_an_old_file_of_a_previous_update_is_replaced(self):
        (self.tmp / "IVAO_VMR_Generator.exe.old").write_bytes(b"older")
        self.install(self.updater())
        self.assertEqual((self.tmp / "IVAO_VMR_Generator.exe.old").read_bytes(), b"MZ old program")

    def test_signed_program_only_takes_a_signed_update(self):
        for signer in (None, "CN=Someone Else"):
            with self.assertRaises(vmr_gui.UpdateError) as caught:
                self.install(self.updater(signer=signer))
            self.assertIn("not signed by SignPath Foundation", str(caught.exception))
            self.assert_untouched()

    def test_unsigned_program_takes_an_unsigned_update_with_a_checksum(self):
        # releases made before code signing was set up (1.1.0) are not signed; GitHub's checksum vouches for the file
        self.install(self.updater(signer=None, running_signer=None))
        self.assertEqual(self.exe.read_bytes(), EXE)

    def test_unsigned_update_without_a_checksum_is_not_installed(self):
        with self.assertRaises(vmr_gui.UpdateError) as caught:
            self.install(self.updater(release(digest=False), signer=None, running_signer=None))
        self.assertIn("not signed and GitHub gives no checksum", str(caught.exception))
        self.assert_untouched()

    def test_unsigned_program_takes_a_signed_update(self):
        self.install(self.updater(release(digest=False), running_signer=None))
        self.assertEqual(self.exe.read_bytes(), EXE)

    def test_wrong_checksum(self):
        with self.assertRaises(vmr_gui.UpdateError) as caught:
            self.install(self.updater(release(exe=b"something else" * 1000), exe=b"x" * len(b"something else" * 1000)))
        self.assertIn("checksum", str(caught.exception))
        self.assert_untouched()

    def test_incomplete_or_too_large_download(self):
        for exe in (EXE[:-10], EXE + b"more"):
            with self.assertRaises(vmr_gui.UpdateError) as caught:
                self.install(self.updater(release(digest=False), exe=exe))
            self.assertIn("incomplete or too large", str(caught.exception))
            self.assert_untouched()

    def test_download_fails(self):
        updater = self.updater()
        self.patches[0] = mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline"))
        with self.assertRaises(vmr_gui.UpdateError) as caught:
            self.install(updater)
        self.assertIn("Download it from https://github.com/vojta48/create-ivao-vmr/releases/tag/v1.3.0", str(caught.exception))
        self.assert_untouched()

    def test_folder_not_writable(self):
        updater = self.updater()
        with mock.patch("builtins.open", side_effect=PermissionError("access denied")), self.assertRaises(vmr_gui.UpdateError):
            self.install(updater)
        self.assert_untouched()

    def test_failed_swap_puts_the_old_program_back(self):
        updater = self.updater()
        real_replace = vmr_gui.Path.replace

        def replace(path, target):
            if path.name.endswith(".new"):
                raise PermissionError("in use")
            return real_replace(path, target)
        with mock.patch.object(vmr_gui.Path, "replace", replace), self.assertRaises(vmr_gui.UpdateError):
            self.install(updater)
        self.assert_untouched()

    def test_nothing_to_install(self):
        updater = self.updater(release("v1.2.0"))
        with self.assertRaises(vmr_gui.UpdateError):
            self.install(updater)
        self.assert_untouched()

    def test_start_program_resets_the_pyinstaller_environment(self):
        with mock.patch.object(vmr_gui.subprocess, "Popen") as popen:
            vmr_gui.start_program(self.exe, ["--port", "8765"])
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [str(self.exe), "--port", "8765"])
        self.assertEqual(kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")


class UpdateServerTest(ServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.github = FakeGitHub(release())
        cls.app = vmr_gui.App(cls.mtl, cls.out, vmr_gui.Settings(None), None, None, vmr_gui.Updater("1.2.0", None))
        vmr_gui.Handler.app = cls.app

    def setUp(self):
        patcher = mock.patch("urllib.request.urlopen", self.github)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.github.urls.clear()

    def get(self):
        return json.loads(self.request("GET", "/api/update")[2])

    def test_1_check_is_off(self):
        self.app.settings.values["checkForUpdates"] = False
        status = self.get()
        self.assertEqual((status["enabled"], status["checked"], status["available"]), (False, False, False))
        self.assertEqual(self.github.urls, [])  # the user switched it off: GitHub is not asked

    def test_2_check_once_per_run(self):
        self.app.settings.values["checkForUpdates"] = True
        status = self.get()
        self.assertEqual((status["checked"], status["available"], status["latest"]), (True, True, "1.3.0"))
        self.get()
        self.assertEqual(self.github.urls, [vmr_gui.LATEST_RELEASE_API])

    def test_3_check_now(self):
        self.app.settings.values["checkForUpdates"] = False
        status, _, body = self.post_json("/api/update", {"action": "check"})
        self.assertEqual((status, json.loads(body)["latest"]), (200, "1.3.0"))
        self.assertEqual(self.github.urls, [vmr_gui.LATEST_RELEASE_API])

    def test_4_install_from_source_is_refused(self):
        status, _, body = self.post_json("/api/update", {"action": "install"})
        self.assertEqual(status, 500)
        self.assertIn("Download the new version from", json.loads(body)["error"])
        self.assertIsNone(self.app.restart)

    def test_5_install_restarts(self):
        finished = threading.Event()
        with mock.patch.object(self.app.updater, "install", return_value="C:\\new.exe"), \
                mock.patch.object(vmr_gui, "finish_update", side_effect=lambda app: finished.set()):
            status, _, body = self.post_json("/api/update", {"action": "install"})
            self.assertTrue(finished.wait(5))
        self.assertEqual((status, json.loads(body)), (200, {"installed": "1.3.0"}))
        self.assertEqual(self.app.restart, "C:\\new.exe")
        self.app.restart = None

    def test_6_unknown_action(self):
        self.assertEqual(self.post_json("/api/update", {"action": "download", "url": "https://evil.example/x.exe"})[0], 400)

    def test_7_self_test_never_asks(self):
        self.app.updater = vmr_gui.Updater("1.2.0", None)
        self.app.settings.values["checkForUpdates"] = True
        with mock.patch.object(vmr_gui, "SELF_TEST", True):
            self.assertFalse(self.get()["checked"])
        self.assertEqual(self.github.urls, [])


class FinishUpdateTest(unittest.TestCase):
    def test_starts_the_new_program_and_ends(self):
        app = mock.Mock(restart="C:\\new.exe")
        with mock.patch.object(vmr_gui, "start_program") as start, mock.patch.object(vmr_gui.os, "_exit") as end:
            vmr_gui.finish_update(app, delay=0)
        start.assert_called_once_with("C:\\new.exe", vmr_gui.sys.argv[1:])
        end.assert_called_once_with(0)

    def test_ends_even_when_the_start_fails(self):
        with mock.patch.object(vmr_gui, "start_program", side_effect=OSError("blocked")), mock.patch.object(vmr_gui.os, "_exit") as end, \
                mock.patch("builtins.print"):
            vmr_gui.finish_update(mock.Mock(restart="x"), delay=0)
        end.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
