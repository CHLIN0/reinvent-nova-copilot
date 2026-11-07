import os
import re
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import web
from atlas import catalog, official_auth, profile

DIST = Path(__file__).resolve().parent.parent / "explorer" / "ui" / "dist" / "app.js"


class PlanApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(profile, "PROFILE_DIR", Path(self.tmp.name))]
        for p in self.patches:
            p.start()
        self.ids = [s["id"] for s in catalog.load_fixture()[:4]]

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def signed_in(self, reserved, favorites):
        sched = {"reserved": reserved, "favorites": [{"sessionId": i} for i in favorites], "personalTime": []}
        return [mock.patch.object(official_auth, "is_signed_in", return_value=True),
                mock.patch.object(catalog, "get_schedule", return_value=sched),
                mock.patch.object(catalog, "load_sessions", side_effect=lambda source="auto": catalog.load_fixture())]

    def test_plan_merges_official_and_local_with_sources(self):
        a, b, c, d = self.ids
        web._change_plan("add", [c, a])  # a is also reserved: shown once, as reserved
        patches = self.signed_in([a], [b])
        for p in patches:
            p.start()
        try:
            out = web._plan()
        finally:
            for p in patches:
                p.stop()
        by_id = {i["session_id"]: i["source"] for i in out["items"]}
        self.assertEqual(by_id, {a: "reserved", b: "favorite", c: "local"})
        self.assertEqual(out["counts"], {"reserved": 1, "favorite": 1, "local": 1})
        self.assertEqual(out["official"]["status"], "live")
        item = next(i for i in out["items"] if i["session_id"] == c)
        self.assertNotIn(" ", item["placement"])  # same text as the browser's JSON.stringify
        for k in ("placement", "key", "code", "title", "start", "end", "location", "addedAt", "source"):
            self.assertIsInstance(item[k], str)

    def test_signed_out_shows_local_picks_only(self):
        web._change_plan("add", [self.ids[0]])
        out = web._plan()
        self.assertEqual([i["source"] for i in out["items"]], ["local"])
        self.assertEqual(out["official"], {"status": "signed_out"})

    def test_remove_and_duplicate_add(self):
        a, b = self.ids[:2]
        self.assertEqual(web._change_plan("add", [a, b])["changed"], 2)
        self.assertEqual(web._change_plan("add", [a])["changed"], 0)
        out = web._change_plan("remove", [a])
        self.assertEqual(out["changed"], 1)
        self.assertEqual([i["session_id"] for i in out["items"]], [b])
        self.assertEqual([x["session_id"] for x in profile.load_state()["plan"]["local"]], [b])

    def test_rejects_unknown_ids_and_actions_without_writing(self):
        with self.assertRaises(ValueError):
            web._change_plan("add", ["no-such-session"])
        with self.assertRaises(ValueError):
            web._change_plan("toggle", [self.ids[0]])
        self.assertEqual(profile.load_state(), {})

    def test_state_file_is_private(self):
        web._change_plan("add", [self.ids[0]])
        path = Path(self.tmp.name) / "default.state.json"
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_built_atlas_has_no_browser_storage_for_the_plan(self):
        bundle = DIST.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"indexedDB|localStorage", bundle))
        self.assertIn("/api/plan", bundle)


if __name__ == "__main__":
    unittest.main()
