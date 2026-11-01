# The parts of the GUI that use pywebview: the file dialogs of the window and the fallback without pywebview.
# pywebview itself is replaced by a fake module, so these tests run without it and without a screen.

import sys
import types
import unittest
from unittest import mock

from support import TempDirTestCase, vmr_gui


def fake_webview():
    module = types.ModuleType("webview")
    module.FileDialog = types.SimpleNamespace(SAVE="save", OPEN="open", FOLDER="folder")
    return module


class FakeWindow:
    def __init__(self, result):
        self.result, self.calls = result, []

    def create_file_dialog(self, kind, **options):
        self.calls.append((kind, options))
        return self.result


class JsApiTest(TempDirTestCase):
    def api(self, result):
        api = vmr_gui.JsApi()
        api._window = FakeWindow(result)
        return api

    def test_window_is_not_exposed_to_the_page(self):
        # pywebview walks every public attribute of the api object; the window must stay private
        self.assertEqual([n for n in vars(vmr_gui.JsApi()) if not n.startswith("_")], [])

    def test_save_as(self):
        target = self.tmp / "out.vmr"
        with mock.patch.dict(sys.modules, {"webview": fake_webview()}):
            api = self.api([str(target)])
            self.assertEqual(api.save_as("custom.vmr", "A\r\nB"), {"path": str(target)})
            kind, options = api._window.calls[0]
        self.assertEqual((kind, options["save_filename"]), ("save", "custom.vmr"))
        self.assertEqual(target.read_bytes(), b"A\r\nB")  # line endings are kept

    def test_save_as_cancelled_and_failing(self):
        with mock.patch.dict(sys.modules, {"webview": fake_webview()}):
            self.assertEqual(self.api(None).save_as("x.vmr", "t"), {"cancelled": True})
            self.assertIn("error", self.api(str(self.tmp / "missing" / "x.vmr")).save_as("x.vmr", "t"))

    def test_open_file(self):
        source = self.tmp / "in.vmr"
        source.write_bytes(b"\xef\xbb\xbf<ModelMatchRuleSet />")
        with mock.patch.dict(sys.modules, {"webview": fake_webview()}):
            self.assertEqual(self.api((str(source),)).open_file(), {"name": "in.vmr", "text": "<ModelMatchRuleSet />"})
            self.assertEqual(self.api([]).open_file(), {"cancelled": True})
            self.assertIn("error", self.api([str(self.tmp / "missing.vmr")]).open_file())


class WithoutPywebviewTest(unittest.TestCase):
    def test_show_window_falls_back_to_the_browser(self):
        server = mock.Mock()
        with mock.patch.dict(sys.modules, {"webview": None}), mock.patch("builtins.print"):
            self.assertFalse(vmr_gui.show_window("http://127.0.0.1:1/", server))
        server.shutdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
