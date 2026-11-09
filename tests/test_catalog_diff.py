"""Offline tests: new and changed sessions since the last visit (T6).

The official catalog is the synthetic fixture served through the real `catalog.load_sessions` as if
ListSessions had returned it (source "official_api"). The modified catalog adds SYN-SEC999 (on the
profile's interest, security) and SYN-MUS998 (off-interest), moves the reservation SYN-AI407 from
Wynn 10:30 to Mandalay Bay 13:00, and removes the reservation SYN-GEN309. Bedrock is a scripted fake.
"""
import json
import os
import stat
import unittest
from unittest import mock

import web
from atlas import catalog, profile, tools
from atlas.agent import Agent
from tests.test_agent import FakeBedrock, final, tool_use
from tests.test_locked import RESERVED, Base, fixture_backend

SCHEDULE = {"signed_in": True, "favorites": [], "reserved": [
    {"id": "syn-k002", "code": "SYN-KEY02", "start": "2026-12-02T08:00:00-08:00"},
    {"id": "syn-0007", "code": "SYN-AI407", "start": "2026-12-02T10:30:00-08:00"},
    {"id": "syn-0019", "code": "SYN-GEN309", "start": "2026-12-02T15:00:00-08:00"}]}
NEW_ON_TOPIC = {"id": "syn-new1", "code": "SYN-SEC999", "title": "Securing agent tool calls end to end",
                "abstract": "Guardrails for agents that call tools. (Synthetic demo session.)", "type": "Breakout",
                "level": "300", "topics": ["Security", "Agents"], "start": "2026-12-03T11:30:00-08:00",
                "end": "2026-12-03T12:30:00-08:00", "venue": "venetian", "room": "Level 3, Synthetic Room 199",
                "seats": "available", "speakers": ["Demo Speaker 99"]}
NEW_OFF_TOPIC = dict(NEW_ON_TOPIC, id="syn-new2", code="SYN-MUS998", title="Music of the cloud", topics=["Community"],
                     abstract="A jam session. (Synthetic demo session.)")
MOVED_TO = {"start": "2026-12-02T13:00:00-08:00", "end": "2026-12-02T14:00:00-08:00",
            "room": "South Convention, Room 101", "venue": "mandalay_bay"}


def official(rows):
    return [dict(r, source="official_api") for r in rows]


def modified_catalog():
    rows = [dict(s, **MOVED_TO) if s["id"] == "syn-0007" else s for s in catalog.load_fixture() if s["id"] != "syn-0019"]
    return official(rows + [NEW_ON_TOPIC, NEW_OFF_TOPIC])


class CatalogDiffTest(Base):
    def setUp(self):
        super().setUp()
        self.saved_agent = web._state["agent"]
        catalog.clear_cache()
        self.addCleanup(catalog.clear_cache)
        mock.patch.object(web, "_my_schedule", return_value=SCHEDULE).start()
        mock.patch.object(tools, "official_tools", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)
        profile.update_profile({"interests": ["security"]})
        self.snapshot_path = profile.PROFILE_DIR / "default.catalog.json"

    def tearDown(self):
        web._state["agent"] = self.saved_agent
        super().tearDown()

    def brief(self, live, script=None, reserved=None):
        """One briefing; `live` is what ListSessions returns, or an exception (the fixture fallback).
        `reserved` keeps only these of SCHEDULE's reservations in GetSchedule."""
        catalog.clear_cache()
        rows = [r for r in SCHEDULE["reserved"] if reserved is None or r["id"] in reserved]
        web._my_schedule.return_value = dict(SCHEDULE, reserved=rows)
        self.fake = FakeBedrock(script or [final("Hello.")])
        web._state["agent"] = Agent(client=self.fake, backend=fixture_backend(
            {"reserved": RESERVED, "favorites": [], "personalTime": []}))
        kw = {"side_effect": live} if isinstance(live, Exception) else {"return_value": live}
        with mock.patch.object(catalog, "list_sessions_live", **kw):
            out = web._briefing()
        return out, self.fake.requests[0]["messages"][-1]["content"][0]["text"]

    def test_first_visit_records_and_reports_nothing(self):
        self.assertFalse(self.snapshot_path.exists())
        out, prompt = self.brief(official(catalog.load_fixture()))
        self.assertIsNone(out["catalog_diff"])
        self.assertNotIn("official catalog", prompt)
        snap = json.loads(self.snapshot_path.read_text())
        self.assertEqual(len(snap["sessions"]), len(catalog.load_fixture()))
        self.assertEqual(set(snap["sessions"]["syn-0007"]), {"code", "start", "end", "room", "venue", "hash"})
        self.assertEqual(snap["reserved"], RESERVED)
        self.assertEqual(stat.S_IMODE(os.stat(self.snapshot_path).st_mode), 0o600)
        self.assertNotIn("sessions", profile.load_state())  # the snapshot stays out of state.json

    def test_diff_is_exact_and_reaches_prompt_and_response(self):
        self.brief(official(catalog.load_fixture()))
        out, prompt = self.brief(modified_catalog())
        self.assertEqual(out["catalog_diff"], {
            "new": 2,
            "moved": [{"id": "syn-0007", "code": "SYN-AI407",
                       "from": {"start": "2026-12-02T10:30:00-08:00", "end": "2026-12-02T11:30:00-08:00",
                                "room": "Convention Promenade, Room 178", "venue": "wynn"},
                       "to": MOVED_TO}],
            "cancelled": [{"id": "syn-0019", "code": "SYN-GEN309"}],
            "recommended": ["SYN-SEC999"]})
        self.assertIn("The complete list of sessions new in the official catalog since my last visit that match my profile: "
                      'SYN-SEC999 "Securing agent tool calls end to end" (Thu 2026-12-03 11:30-12:30, venetian).', prompt)
        self.assertNotIn("SYN-MUS998", prompt)
        self.assertIn("My reservation SYN-AI407 moved from Wed 2026-12-02 10:30-11:30, Convention Promenade, Room 178, "
                      "wynn to Wed 2026-12-02 13:00-14:00, South Convention, Room 101, mandalay_bay.", prompt)
        self.assertIn("My reservation SYN-GEN309 is no longer in the official catalog.", prompt)
        self.assertIn("check_itinerary once per conference day", prompt)
        self.assertIn("under 120 words", prompt)
        self.assertNotIn("abstract", json.dumps(out["catalog_diff"]))
        snap = json.loads(self.snapshot_path.read_text())["sessions"]  # updated to what this visit saw
        self.assertIn("syn-new1", snap)
        self.assertNotIn("syn-0019", snap)
        self.assertEqual(snap["syn-0007"]["room"], MOVED_TO["room"])
        self.assertEqual(len(self.fake.requests), 1)  # still one model conversation

    def test_failed_load_leaves_snapshot_and_reports_no_cancellation(self):
        self.brief(official(catalog.load_fixture()))
        before = self.snapshot_path.read_bytes()
        out, prompt = self.brief(catalog.CatalogError("catalog_unavailable"))  # falls back to the fixture
        self.assertEqual(catalog.last_source()["source"], "synthetic_fixture")
        self.assertIsNone(out["catalog_diff"])
        self.assertNotIn("no longer in the official catalog", prompt)
        self.assertEqual(self.snapshot_path.read_bytes(), before)

    def test_fixture_rows_never_write_a_snapshot_even_if_last_source_says_official(self):
        """Codex T6 r1 P1: another request may set the process-global last_source() to official_api
        after this briefing received fixture rows; the rows decide."""
        with mock.patch.object(catalog, "load_sessions", side_effect=lambda source="auto": catalog.load_fixture()), \
             mock.patch.object(catalog, "last_source", return_value={"source": "official_api", "reason": "live"}):
            out, _ = self.brief(official(catalog.load_fixture()))
        self.assertIsNone(out["catalog_diff"])
        self.assertFalse(self.snapshot_path.exists())

    def test_cancellation_survives_a_fallback_visit(self):
        """Codex T6 r1 P2: SYN-GEN309 leaves GetSchedule and the catalog during an outage visit;
        the next live visit still reports it cancelled."""
        self.brief(official(catalog.load_fixture()))
        without_gen309 = ["syn-k002", "syn-0007"]
        self.brief(catalog.CatalogError("catalog_unavailable"), reserved=without_gen309)
        out, prompt = self.brief(modified_catalog(), reserved=without_gen309)
        self.assertEqual(out["catalog_diff"]["cancelled"], [{"id": "syn-0019", "code": "SYN-GEN309"}])
        self.assertIn("My reservation SYN-GEN309 is no longer in the official catalog.", prompt)

    def test_unreserved_session_that_moved_is_not_a_moved_reservation(self):
        """Codex T6 r1 P2: the attendee unreserved SYN-AI407 and it then moved: not 'My reservation ... moved'."""
        self.brief(official(catalog.load_fixture()))
        out, prompt = self.brief(modified_catalog(), reserved=["syn-k002", "syn-0019"])
        self.assertEqual(out["catalog_diff"]["moved"], [])
        self.assertNotIn("SYN-AI407 moved", prompt)

    def test_unchanged_catalog_reports_nothing_in_the_prompt(self):
        self.brief(official(catalog.load_fixture()))
        out, prompt = self.brief(official(catalog.load_fixture()))
        self.assertEqual(out["catalog_diff"], {"new": 0, "moved": [], "cancelled": [], "recommended": []})
        self.assertNotIn("official catalog", prompt)
        self.assertIn("1) name any conflict or tight transition", prompt)


if __name__ == "__main__":
    unittest.main()
