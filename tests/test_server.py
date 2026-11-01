# The local HTTP server of the GUI: every endpoint, and that it only answers this computer.

import json
import unittest
import xml.etree.ElementTree as ET

from support import ALL_TITLES, LEFT_OUT, ServerTestCase, gui_rules, vmr_gui


class PagesTest(ServerTestCase):
    def test_index_and_static_files(self):
        for path in ("/", "/index.html"):
            status, headers, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn("text/html", headers["Content-Type"])
            self.assertIn(b"<script src=\"/static/app.js\">", body)
        for name, kind in (("app.js", "javascript"), ("style.css", "text/css")):
            status, headers, _ = self.request("GET", "/static/" + name)
            self.assertEqual(status, 200)
            self.assertIn(kind, headers["Content-Type"])

    def test_static_cannot_leave_the_gui_folder(self):
        for path in ("/static/../vmr_gui.py", "/static/..%2Fvmr_gui.py", "/static/%2e%2e/LICENSE", "/static/missing.js"):
            status, _, body = self.request("GET", path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"import", body)

    def test_unknown_paths(self):
        self.assertEqual(self.request("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.post_json("/api/nothing", {})[0], 404)


class StateTest(ServerTestCase):
    def test_state(self):
        status, headers, body = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        state = json.loads(body)
        self.assertTrue(state["libraryFound"])
        self.assertEqual(sorted(l["id"] for l in state["liveries"]), sorted(ALL_TITLES))
        self.assertEqual(state["errors"], [])
        self.assertEqual({p["id"] for p in state["presets"]} >= {"smartwings_group", "extra_rules"}, True)
        self.assertEqual([(r["callsign"], r["type"], tuple(r["models"])) for r in state["mtlRules"]["standard"]], gui_rules(self.app.library, True))
        self.assertEqual(state["catalogSearch"], vmr_gui.CATALOG_SEARCH)
        self.assertEqual(state["outputDir"], str(self.out))
        self.assertEqual({l["id"] for l in state["liveries"] if not l["inVmr"]}, LEFT_OUT)

    def test_progress(self):
        # what the loading screen asks for while /api/state reads the MTL
        self.request("GET", "/api/state")
        status, _, body = self.request("GET", "/api/progress")
        self.assertEqual(status, 200)
        progress = json.loads(body)
        self.assertEqual(set(progress), {"scanned", "done", "total", "liveries", "modelsRoot"})
        self.assertTrue(progress["scanned"])
        self.assertEqual(progress["done"], progress["total"])
        self.assertGreater(progress["total"], 0)
        self.assertEqual(progress["liveries"], len(self.app.library.liveries))
        self.assertEqual(progress["modelsRoot"], str(self.app.library.models_root))

    def test_rescan(self):
        status, _, body = self.request("GET", "/api/rescan")
        self.assertEqual(status, 200)
        self.assertEqual(set(json.loads(body)), {"liveries", "errors", "mtlRules"})

    def test_no_livery_list_any_more(self):
        self.assertEqual(self.request("GET", "/api/livery-list.csv")[0], 404)


class PreviewEndpointTest(ServerTestCase):
    def test_preview(self):
        picture = self.tmp / "101.png"
        picture.write_bytes(b"PNG")

        class FakePreviews:
            asked = []

            def get(self, catalog_id):
                self.asked.append(catalog_id)
                return picture if catalog_id == 101 else None

        self.app.previews = FakePreviews()
        status, headers, body = self.request("GET", "/api/preview/F100DLA")
        self.assertEqual((status, body), (200, b"PNG"))
        self.assertEqual(headers["Cache-Control"], "max-age=3600")
        self.assertEqual(self.request("GET", "/api/preview/F100KLM")[0], 404)   # no picture
        self.assertEqual(self.request("GET", "/api/preview/NOPE")[0], 404)      # not installed
        self.assertEqual(FakePreviews.asked, [101, 102])


class PostTest(ServerTestCase):
    def test_parse_and_build(self):
        status, _, body = self.post_json("/api/parse-vmr", {"text": '<ModelMatchRuleSet><ModelMatchRule Callsign="OKABC" TypeCode="C172" ModelName="C172" /></ModelMatchRuleSet>'})
        self.assertEqual(status, 200)
        rules = json.loads(body)["rules"]
        self.assertEqual(rules, [{"callsign": "", "type": "C172", "models": ["C172"], "exactCallsign": "OKABC"}])
        status, _, body = self.post_json("/api/build", {"rules": rules, "comment": "c"})
        self.assertEqual(json.loads(body)["text"], vmr_gui.build_vmr(rules, "c"))

    def test_save(self):
        rules = [{"callsign": "DLH", "type": "A320", "models": ["A320DLH"]}]
        # an old GUI page may still send liveryList: it is ignored, only the VMR is written
        status, _, body = self.post_json("/api/save", {"fileName": "..\\..\\evil/../my rules", "rules": rules, "comment": "x", "liveryList": True})
        self.assertEqual(status, 200)
        saved = self.out / "my rules.vmr"
        self.assertEqual(json.loads(body), {"path": str(saved.resolve()), "outputDir": str(self.out)})
        self.assertEqual(saved.read_bytes().decode("utf-8"), vmr_gui.build_vmr(rules, "x"))
        ET.fromstring(saved.read_text(encoding="utf-8").split("<!--")[0].split("?>", 1)[1])
        self.assertEqual(sorted(p.name for p in self.out.iterdir() if p.name.startswith("my rules")), ["my rules.vmr"])

    def test_save_default_name(self):
        status, _, body = self.post_json("/api/save", {"rules": []})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["path"].endswith("custom.vmr"))

    def test_invalid_json(self):
        status, _, body = self.request("POST", "/api/build", "{nope", {"Content-Type": "application/json"})
        self.assertEqual(status, 400)
        self.assertIn("Invalid JSON", json.loads(body)["error"])

    def test_empty_body(self):
        status, _, body = self.request("POST", "/api/build", "", {"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertIn("<ModelMatchRuleSet>", json.loads(body)["text"])


class OnlyThisComputerTest(ServerTestCase):
    def test_allowed_hosts(self):
        for host in ("127.0.0.1:%d", "localhost:%d", "LOCALHOST", "[::1]:%d"):
            self.assertEqual(self.request("GET", "/api/rescan", headers={"Host": host.replace("%d", str(self.port))})[0], 200, host)

    def test_foreign_host_is_refused(self):
        for host in ("evil.example", "evil.example:%d" % self.port, "127.0.0.1.evil.example", ""):
            self.assertEqual(self.request("GET", "/api/state", headers={"Host": host})[0], 403, host)
            self.assertEqual(self.request("POST", "/api/save", "{}", {"Host": host, "Content-Type": "application/json"})[0], 403, host)

    def test_post_must_be_json(self):
        body = json.dumps({"fileName": "plain.vmr", "rules": []})
        for content_type in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data", ""):
            self.assertEqual(self.request("POST", "/api/save", body, {"Content-Type": content_type})[0], 415, content_type)
        self.assertFalse((self.out / "plain.vmr").exists())
        self.assertEqual(self.request("POST", "/api/save", body, {"Content-Type": "application/json; charset=utf-8"})[0], 200)

    def test_no_endpoint_reads_files_from_disk(self):
        status, _, _ = self.request("GET", "/api/parse-vmr?file=" + str(vmr_gui.__file__))
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
