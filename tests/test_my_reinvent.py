"""Signed-in first screen "My re:Invent" (M0 T3): view choice and day agenda (node), and the built bundle."""
import shutil
import subprocess
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
