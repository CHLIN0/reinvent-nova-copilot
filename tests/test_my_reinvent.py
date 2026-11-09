"""Signed-in first screen "My re:Invent" (M0 T3): view choice and day agenda (node), and the built bundle."""
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import web

UI = Path(__file__).resolve().parent.parent / "explorer" / "ui"


class MyReInventTest(unittest.TestCase):
    def test_view_selection_and_gaps(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")
        run = subprocess.run([node, "--test", "test-my-day.mjs", "test-official-connection.mjs"],
                             cwd=UI, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])

    def test_atlas_wiring(self):
        """The tested pieces are the ones Atlas uses: every calendar move goes through the day sync, the plan
        response feeds the tab choice, and Copilot's status poll reaches the one sign-in button."""
        app = (UI / "src" / "app.mjs").read_text(encoding="utf-8")
        self.assertNotRegex(app, r"calendar\.(changeView|gotoDate)\(")
        self.assertIn("calendarSync.go(state.view, state.day);", app)
        self.assertIn("homeChoice.plan(official?.status);", app)
        self.assertIn("const tab = state.tab && homeChoice.urlTab;", app)  # fallback Explore is not saved
        self.assertIn("officialConnection.applyStatus(", app)
        copilot = (UI.parent.parent / "web" / "copilot.js").read_text(encoding="utf-8")
        self.assertIn('"atlas:auth-status"', copilot)
        self.assertIn('export const AUTH_STATUS_EVENT = "atlas:auth-status";',
                      (UI / "src" / "official-connection.mjs").read_text(encoding="utf-8"))

    def test_built_page_has_both_tabs_and_the_header_toggle(self):
        html = (UI / "dist" / "index.html").read_text(encoding="utf-8")
        for marker in ('id="tab-mine"', 'id="tab-explore"', 'id="mine-briefing"', 'id="copilot-toggle"',
                       'id="week-view"', 'id="filter-more"'):
            self.assertIn(marker, html)
        bundle = (UI / "dist" / "app.js").read_text(encoding="utf-8")
        self.assertIn("mine-agenda", bundle)  # dist was rebuilt with the My re:Invent view


class OneFrontEndTest(unittest.TestCase):
    """T8: Event Atlas with the docked panel is the only web page; /copilot and its own sign-in are gone."""

    def call(self, method, path, explorer_port=8541, dist=web.EXPLORER_DIST):
        handler = web.Handler.__new__(web.Handler)
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 8510))
        handler.headers = {"Host": "127.0.0.1:8510", "Content-Type": "application/json", "Content-Length": "2"}
        handler.path = path
        handler.rfile = io.BytesIO(b"{}")
        handler._send = mock.Mock()
        with mock.patch.dict(web._state, {"explorer_port": explorer_port}), mock.patch.object(web, "EXPLORER_DIST", dist):
            getattr(handler, f"do_{method}")()
        code, body, ctype = handler._send.call_args.args[:3]
        return code, body.decode("utf-8"), ctype

    def test_chat_only_page_is_gone(self):
        for port in (8541, None):
            self.assertEqual(self.call("GET", "/copilot", port)[0], 404)
        for path in ("/api/signin", "/api/profile"):  # only the removed page and profile tab posted here
            self.assertEqual(self.call("POST", path)[0], 404)

    def test_root_serves_atlas_with_the_panel(self):
        code, body, _ = self.call("GET", "/")
        self.assertEqual(code, 200)
        self.assertIn('<script src="/copilot.js" defer></script>', body)

    def test_root_without_atlas_says_how_to_build_it(self):
        with tempfile.TemporaryDirectory() as empty:
            for port, dist in ((None, web.EXPLORER_DIST), (0, web.EXPLORER_DIST), (8541, Path(empty))):
                code, body, ctype = self.call("GET", "/", port, dist)
                self.assertEqual(code, 503)
                self.assertTrue(ctype.startswith("text/plain"))
                self.assertIn("cd explorer/ui && node build.mjs", body)


if __name__ == "__main__":
    unittest.main()
