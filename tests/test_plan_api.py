import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import web
from atlas import catalog, official_auth, profile

DIST = Path(__file__).resolve().parent.parent / "explorer" / "ui" / "dist" / "app.js"
PLAN_CHANGED = "atlas:plan-changed"  # window event: Copilot dispatches it, Event Atlas re-reads /api/plan


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

    def test_plan_saved_during_a_briefing_survives(self):
        a, b = self.ids[:2]
        sched = {"signed_in": True, "reserved": [{"id": b}], "favorites": []}

        def schedule_read_while_user_adds():  # the user adds a session while the briefing reads GetSchedule
            web._change_plan("add", [a])
            return sched

        patches = self.signed_in([b], []) + [
            mock.patch.object(web, "_my_schedule", side_effect=schedule_read_while_user_adds),
            mock.patch.object(web, "_chat", return_value={"text": "ok", "trace": []}),
        ]
        for p in patches:
            p.start()
        try:
            out = web._briefing()
        finally:
            for p in patches:
                p.stop()
        state = profile.load_state()
        self.assertTrue(out["first_visit"])
        self.assertEqual(state["visits"], 1)
        self.assertEqual(state["schedule"], {"reserved": [b], "favorites": []})
        self.assertEqual([x["session_id"] for x in state["plan"]["local"]], [a])

    def test_concurrent_state_updates_are_serialised(self):
        import threading
        import time

        def slow_visit(state):
            state["visits"] = int(state.get("visits") or 0) + 1
            time.sleep(0.2)  # a plan write arriving now must wait, not be overwritten

        t = threading.Thread(target=profile.update_state, args=(slow_visit,))
        t.start()
        time.sleep(0.05)
        web._change_plan("add", [self.ids[0]])
        t.join()
        state = profile.load_state()
        self.assertEqual(state["visits"], 1)
        self.assertEqual([x["session_id"] for x in state["plan"]["local"]], [self.ids[0]])

    def test_reader_during_a_write_never_sees_invalid_json(self):
        import threading

        big = {"plan": {"version": 1, "local": [{"session_id": f"s{i:05d}", "added_at": "x" * 40} for i in range(3000)]}}
        profile.save_state(big)
        errors, done = [], threading.Event()

        def writer():
            for i in range(60):
                big["visits"] = i
                profile.save_state(big)
            done.set()

        t = threading.Thread(target=writer)
        t.start()
        reads = 0
        while not done.is_set() or reads == 0:
            try:  # unlocked on purpose: the file itself must never be half-written
                state = profile.load_state()
                self.assertEqual(len(state["plan"]["local"]), 3000)
            except (ValueError, KeyError) as e:
                errors.append(type(e).__name__)
            reads += 1
        t.join()
        self.assertEqual(errors, [], f"{len(errors)} bad reads out of {reads}")
        leftovers = [p.name for p in Path(self.tmp.name).iterdir() if p.name != "default.state.json"]
        self.assertEqual(leftovers, [])
        self.assertEqual(stat.S_IMODE(os.stat(Path(self.tmp.name) / "default.state.json").st_mode), 0o600)

    def test_atlas_listener_and_stack_marks(self):
        """Node tests: Atlas re-reads /api/plan on Copilot's event; stacked cards follow plan updates."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        ui = Path(__file__).resolve().parent.parent / "explorer" / "ui"
        run = subprocess.run([node, "--test", "test-plan-store.mjs", "test-stack-plan-marks.mjs"],
                             cwd=ui, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])
        source = (ui / "src" / "plan-store.mjs").read_text(encoding="utf-8")
        self.assertIn(f'export const PLAN_CHANGED = "{PLAN_CHANGED}";', source)  # the event Copilot dispatches

    def test_copilot_add_updates_atlas_without_reload(self):
        """Copilot's add posts to /api/plan and fires the event the built Atlas bundle listens for."""
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        here = Path(__file__).resolve().parent
        run = subprocess.run([node, str(here / "copilot_plan_event.mjs"), str(here.parent / "web" / "copilot.js")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        report = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual(report["post"], {"action": "add", "session_ids": ["syn-0001"]})
        self.assertEqual(report["events"], [PLAN_CHANGED])  # refresh event fired; no page reload
        self.assertIn("Added 1 session", report["message"])
        self.assertEqual(report["tabs"], ["Ask"])  # no "Your day" or "Profile" tab: Atlas shows the plan
        briefing = report["briefing"]  # a briefing that carries a plan offers the same local add
        self.assertEqual(briefing["post"], {"action": "add", "session_ids": ["syn-0002"]})
        self.assertEqual(briefing["events"], [PLAN_CHANGED])
        self.assertIn("Added 1 session", briefing["message"])

    def test_built_atlas_has_no_browser_storage_for_the_plan(self):
        bundle = DIST.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"indexedDB|localStorage", bundle))
        self.assertIn("/api/plan", bundle)


if __name__ == "__main__":
    unittest.main()
