"""Offline tests: official reservations are locked by the tools, and the briefing cannot claim
feasibility without an itinerary check (T2).

The Wednesday case is rebuilt on the synthetic fixture: SYN-KEY02 (08:00-10:00, Venetian),
SYN-AI407 (10:30-11:30, Wynn) and SYN-GEN309 (15:00-16:00, Caesars Forum) stand in for the
attendee's real reservations. Sign-in is a fake auth object; the schedule comes from a Backend stub.
"""
import json
import tempfile
import unittest
from datetime import datetime
from unittest import mock

from atlas import catalog, guard, official_auth, planner, profile, routing, tools
from atlas.agent import Agent, ToolCall
from tests.test_agent import FakeBedrock, final, tool_use

RESERVED = ["syn-k002", "syn-0007", "syn-0019"]
RESERVED_CODES = ["SYN-KEY02", "SYN-AI407", "SYN-GEN309"]
FAVORITE = "syn-0011"  # SYN-GEN101 12:00-13:00, fits between the reservations


class FakeAuth:
    def status(self):
        return {"connected": True, "auth_status": "authenticated"}

    def access_token(self, force_refresh=False):
        raise AssertionError("tests must not reach the official API")


def fixture_backend(schedule, calls=None):
    def get_schedule():
        if calls is not None:
            calls.append("get_schedule")
        if isinstance(schedule, Exception):
            raise schedule
        return schedule

    return tools.Backend(
        search_sessions=lambda **kw: catalog.search_sessions(source="fixture", **kw),
        get_session=lambda sid: catalog.get_session(sid, source="fixture"),
        get_schedule=get_schedule,
        add_favorites=lambda ids: {"added": ids},
        route=routing.route,
        check_itinerary=planner.check_itinerary,
        plan_itinerary=planner.plan_itinerary,
    )


def fixture_catalog():
    """Signed in, the briefing loads the catalog itself; serve the fixture (not official) instead of the API."""
    real = catalog.load_sessions
    return mock.patch.object(catalog, "load_sessions", side_effect=lambda source="auto": real("fixture"))


def wednesday_ids():
    return [s["id"] for s in catalog.load_fixture() if s["start"].startswith("2026-12-02")]


def overlaps(a, b):
    return (datetime.fromisoformat(a["start"]) < datetime.fromisoformat(b["end"])
            and datetime.fromisoformat(b["start"]) < datetime.fromisoformat(a["end"]))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(profile, "PROFILE_DIR", profile.Path(self.tmp.name))
        self.patch.start()
        official_auth.set_auth(FakeAuth())

    def tearDown(self):
        official_auth.set_auth(None)
        self.patch.stop()
        self.tmp.cleanup()


class LockedReservationsTest(Base):
    def test_wednesday_plan_keeps_reservations_without_must(self):
        """The model asks for a Wednesday plan and forgets `must`: the tool keeps the reservations anyway."""
        be = fixture_backend({"reserved": RESERVED, "favorites": [FAVORITE], "personalTime": []})
        out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": wednesday_ids(), "day": "Wed",
                                                    "use_profile": False}, be)
        self.assertTrue(ok, out)
        self.assertEqual(out["locked_from_schedule"], RESERVED_CODES)
        chosen = out["plan"]["chosen"]
        chosen_ids = [s["id"] for s in chosen]
        for rid in RESERVED:
            self.assertIn(rid, chosen_ids)
        reserved = [catalog.get_session(r, source="fixture") for r in RESERVED]
        for s in chosen:
            if s["id"] in RESERVED:
                continue
            for r in reserved:
                self.assertFalse(overlaps(s, r), f"{s['code']} overlaps reserved {r['code']}")
        self.assertTrue(out["plan"]["feasible"])
        dropped = {d["code"]: d["reason"] for d in out["plan"]["dropped"]}
        self.assertIn("reserved SYN-KEY02", dropped["SYN-AI303"])  # 09:00-11:00 overlaps two reservations

    def test_reservations_on_other_days_are_not_forced_in(self):
        tue = [s["id"] for s in catalog.load_fixture() if s["start"].startswith("2026-12-01")]
        be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []})
        out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": tue, "day": "Tue", "use_profile": False}, be)
        self.assertTrue(ok, out)
        self.assertEqual(out["locked_from_schedule"], [])
        self.assertFalse(set(RESERVED) & {s["id"] for s in out["plan"]["chosen"]})
        self.assertFalse(out["plan"]["warnings"])

    def test_without_day_lock_follows_candidate_days(self):
        be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []})
        out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": ["syn-0011", "syn-0015"], "use_profile": False}, be)
        self.assertTrue(ok, out)
        self.assertEqual(out["locked_from_schedule"], RESERVED_CODES)

    def test_favorites_join_candidates_with_priority(self):
        fav = "syn-0015"  # SYN-GEN205 13:30-14:30 Venetian: not a candidate, fits between reservations
        be = fixture_backend({"reserved": RESERVED, "favorites": [fav], "personalTime": []})
        seen = {}
        real = be.plan_itinerary

        def spy(pool, **kw):
            seen["pool"], seen["must"] = pool, kw["must"]
            return real(pool, **kw)

        be.plan_itinerary = spy
        out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": ["syn-0039"], "day": "Wed", "use_profile": False}, be)
        self.assertTrue(ok, out)
        prio = {s["id"]: s.get("priority", 1) for s in seen["pool"]}
        self.assertEqual(prio[fav], tools.FAVORITE_PRIORITY)
        self.assertEqual(prio["syn-0039"], 1)
        self.assertEqual(sorted(seen["must"]), sorted(RESERVED))
        self.assertEqual([s["id"] for s in out["plan"]["chosen"]], ["syn-k002", "syn-0007", fav, "syn-0019"])

    def test_caller_must_is_unioned(self):
        be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []})
        out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": wednesday_ids(), "must": ["SYN-GEN205"],
                                                    "day": "2026-12-02", "use_profile": False}, be)
        self.assertTrue(ok, out)
        self.assertEqual(sorted(out["plan"]["must"]), sorted(RESERVED_CODES + ["SYN-GEN205"]))

    def test_reservation_breaking_a_caller_limit_is_not_feasible(self):
        be = fixture_backend({"reserved": ["syn-0019"], "favorites": [], "personalTime": []})  # GEN309 15:00-16:00
        for extra in ({"blocked": [{"start": "15:00", "end": "16:00", "label": "customer meeting"}]},
                      {"back_by": "14:00"}):
            out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": ["syn-0011"], "day": "Wed",
                                                        "use_profile": False, **extra}, be)
            self.assertTrue(ok, out)
            self.assertEqual(out["locked_from_schedule"], ["SYN-GEN309"])
            self.assertFalse(out["plan"]["feasible"], extra)
            self.assertEqual([c["code"] for c in out["plan"]["limit_conflicts"]], ["SYN-GEN309"])
            self.assertTrue(any("SYN-GEN309 is must-attend" in w for w in out["plan"]["warnings"]))

    def unresolved_backend(self):
        def get_session(sid):
            if sid == "no-times":
                return {"id": "no-times", "code": "X1", "start": "", "end": ""}
            return catalog.get_session(sid, source="fixture")

        be = fixture_backend({"reserved": ["syn-0007", "missing-id", "no-times"], "favorites": []})
        be.get_session = get_session
        return be

    def test_unresolved_reservations_make_check_unverified(self):
        out, ok = tools.dispatch("check_itinerary", {"session_ids": ["SYN-AI407"]}, self.unresolved_backend())
        self.assertTrue(ok, out)  # not a hard failure: a cancelled session must not block checking forever
        self.assertEqual(out["locked_from_schedule"], ["SYN-AI407"])
        self.assertEqual(out["reservations_not_applied"]["ids"], ["missing-id", "no-times"])
        self.assertFalse(out["check"]["feasible"])
        self.assertIn("2 reservation(s) could not be checked: missing-id, no-times", out["check"]["warnings"])
        self.assertEqual(next(iter(out)), "reservations_not_applied")

    def test_unresolved_reservations_make_plan_unverified(self):
        out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": ["syn-0011"], "day": "Wed", "use_profile": False},
                                 self.unresolved_backend())
        self.assertTrue(ok, out)
        self.assertIn("SYN-AI407", [s["code"] for s in out["plan"]["chosen"]])  # resolved reservation still locked
        self.assertFalse(out["plan"]["feasible"])
        self.assertIn("2 reservation(s) could not be checked: missing-id, no-times", out["plan"]["warnings"])
        for trace in ([ToolCall("plan_itinerary", {}, ok, out)],
                      [{"name": "plan_itinerary", "ok": ok, "result": json.dumps(out)[:200] + "..."}]):
            _, removed = guard.strip_unverified_feasibility("Your Wednesday is feasible. Enjoy.", trace)
            self.assertEqual(removed, ["Your Wednesday is feasible."])

    def test_check_itinerary_adds_reservations_of_the_same_day(self):
        be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []})
        out, ok = tools.dispatch("check_itinerary", {"session_ids": ["SYN-AI303"]}, be)  # 09:00-11:00 Wed
        self.assertTrue(ok, out)
        self.assertEqual(out["locked_from_schedule"], RESERVED_CODES)
        self.assertEqual({s["code"] for s in out["sessions"]}, set(RESERVED_CODES) | {"SYN-AI303"})
        self.assertFalse(out["check"]["feasible"])
        self.assertIn("overlap", {c["status"] for c in out["check"]["conflicts"]})

    def test_not_signed_in_leaves_tools_unchanged(self):
        official_auth.set_auth(None)
        calls = []
        be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []}, calls)
        out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": wednesday_ids(), "day": "Wed", "use_profile": False}, be)
        self.assertTrue(ok, out)
        self.assertNotIn("locked_from_schedule", out)
        self.assertEqual(calls, [])

    def test_schedule_failure_is_a_tool_error_not_an_unlocked_plan(self):
        be = fixture_backend(catalog.CatalogError("official_rate_limited"))
        for name, args in (("plan_itinerary", {"candidate_ids": wednesday_ids(), "day": "Wed", "use_profile": False}),
                           ("check_itinerary", {"session_ids": ["SYN-SEC107"]})):
            out, ok = tools.dispatch(name, args, be)
            self.assertFalse(ok, out)
            self.assertNotIn("plan", out)
            self.assertIn("reservations could not be loaded", out["error"])
            self.assertIn("official_rate_limited", out["error"])
        trace = [ToolCall("plan_itinerary", {}, False, out)]
        _, removed = guard.strip_unverified_feasibility("Your Wednesday is feasible.", trace)
        self.assertEqual(removed, ["Your Wednesday is feasible."])

    def test_limit_conflicts_ignore_must_sessions_off_the_plan_day(self):
        be = fixture_backend({"reserved": [], "favorites": [], "personalTime": []})
        off_day = catalog.get_session("syn-0018", source="fixture")
        self.assertFalse(off_day["start"].startswith("2026-12-02"))
        out, ok = tools.dispatch("plan_itinerary", {"candidate_ids": ["syn-0011"], "must": ["syn-0018"], "day": "Wed",
                                                    "back_by": "14:00", "use_profile": False}, be)
        self.assertTrue(ok, out)
        self.assertNotIn("limit_conflicts", out["plan"])
        self.assertTrue(out["plan"]["feasible"])
        self.assertNotIn("syn-0018", [s["id"] for s in out["plan"]["chosen"]])

    def test_auth_failure_is_tolerated(self):
        class Broken:
            def status(self):
                raise RuntimeError("boom")

        official_auth.set_auth(Broken())
        be = fixture_backend({"reserved": RESERVED})
        out, ok = tools.dispatch("check_itinerary", {"session_ids": ["SYN-AI303"]}, be)
        self.assertTrue(ok, out)
        self.assertNotIn("locked_from_schedule", out)


CLAIM = "Your Wednesday is feasible with no conflicts. Add SYN-GEN101 at lunch.\nTransitions leave enough time."


class GuardTest(unittest.TestCase):
    def test_claims_removed_when_trace_lacks_a_check(self):
        trace = [ToolCall("get_profile", {}, True, {}), ToolCall("get_my_schedule", {}, True, {})]
        text, removed = guard.strip_unverified_feasibility(CLAIM, trace)
        self.assertEqual(len(removed), 2)
        self.assertNotIn("feasible", text)
        self.assertIn("SYN-GEN101", text)
        self.assertTrue(text.endswith(guard.NOT_CHECKED))

    def test_failed_check_does_not_count(self):
        text, removed = guard.strip_unverified_feasibility(CLAIM, [{"name": "check_itinerary", "ok": False}])
        self.assertTrue(removed)

    def test_untouched_when_a_check_succeeded(self):
        for name in ("check_itinerary", "plan_itinerary"):
            for trace in ([ToolCall(name, {}, True, {})], [{"name": name, "ok": True}]):
                self.assertEqual(guard.strip_unverified_feasibility(CLAIM, trace), (CLAIM, []))

    def test_unresolved_reservations_make_any_check_unverified(self):
        clean = ToolCall("check_itinerary", {}, True, {"check": {"feasible": True}})
        dirty = ToolCall("check_itinerary", {}, True, {"reservations_not_applied": {"ids": ["x"]}, "check": {}})
        self.assertEqual(guard.strip_unverified_feasibility(CLAIM, [clean]), (CLAIM, []))
        self.assertTrue(guard.strip_unverified_feasibility(CLAIM, [clean, dirty])[1])

    def test_untouched_without_claims(self):
        text = "SYN-GEN101 covers retrieval. Want me to check your Wednesday?"
        self.assertEqual(guard.strip_unverified_feasibility(text, []), (text, []))

    def test_each_keyword_is_caught(self):
        for w in guard.FEASIBILITY_WORDS:
            _, removed = guard.strip_unverified_feasibility(f"Good news. It is {w} for you. Bye.", [])
            self.assertEqual(removed, [f"It is {w} for you."], w)


class BriefingTest(Base):
    """web._briefing with a real Agent over a scripted (mocked) Bedrock client."""

    SCHEDULE = {"signed_in": True, "reserved": [
        {"id": "syn-k002", "code": "SYN-KEY02", "start": "2026-12-02T08:00:00-08:00"},
        {"id": "syn-0007", "code": "SYN-AI407", "start": "2026-12-02T10:30:00-08:00"},
        {"id": "syn-0002", "code": "SYN-AI202", "start": "2026-12-01T09:00:00-08:00"},
    ], "favorites": []}

    def setUp(self):
        super().setUp()
        import web

        self.web = web
        self.saved_agent = web._state["agent"]
        mock.patch.object(web, "_my_schedule", return_value=self.SCHEDULE).start()
        fixture_catalog().start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.web._state["agent"] = self.saved_agent
        super().tearDown()

    def brief(self, script):
        fake = FakeBedrock(script)
        be = fixture_backend({"reserved": [r["id"] for r in self.SCHEDULE["reserved"]], "favorites": []})
        self.web._state["agent"] = Agent(client=fake, backend=be)
        with mock.patch.object(tools, "official_tools", return_value=[]):
            return self.web._briefing(), fake

    def test_server_checks_itinerary_once_per_reserved_day(self):
        """T11 (was: the prompt asked Nova to call check_itinerary once per day; Nova sometimes checked one day or
        none). The server runs the check for every reserved day with that day's ids, and the prompt states each result."""
        out, fake = self.brief([final("Hello.")])
        checks = [c for c in out["trace"] if c["name"] == "check_itinerary"]
        self.assertEqual([c["input"] for c in checks], [{"session_ids": ["syn-0002"]}, {"session_ids": ["syn-k002", "syn-0007"]}])
        self.assertTrue(all(c["by"] == "server" for c in out["trace"]))
        prompt = fake.requests[0]["messages"][-1]["content"][0]["text"]
        self.assertIn("Tue 2026-12-01, 1 reserved (SYN-AI202 09:00-10:00 ", prompt)
        self.assertIn("Wed 2026-12-02, 2 reserved (SYN-KEY02 08:00-10:00 venetian, SYN-AI407 10:30-11:30 wynn)", prompt)

    def test_failed_checks_mean_claims_are_stripped(self):
        """No successful itinerary check (here: the official reservations cannot be read) still strips feasibility
        claims. T11: the server always runs the checks, so "no check" now means "the check failed"."""
        fake = FakeBedrock([final("Your week is feasible, no conflicts. Consider SYN-GEN101 on Wednesday.")])
        self.web._state["agent"] = Agent(client=fake, backend=fixture_backend(RuntimeError("schedule down")))
        with mock.patch.object(tools, "official_tools", return_value=[]):
            out = self.web._briefing()
        checks = [c for c in out["trace"] if c["name"] == "check_itinerary"]
        self.assertEqual(len(checks), 2)
        self.assertFalse(any(c["ok"] for c in checks))
        self.assertEqual(out["removed"], ["Your week is feasible, no conflicts."])
        self.assertEqual(out["text"], "Consider SYN-GEN101 on Wednesday. " + guard.NOT_CHECKED)

    def test_checks_per_day_keep_the_text(self):
        real, results = tools.dispatch, []

        def record(name, args, backend=None):  # the full results (the response shortens them for the panel)
            result, ok = real(name, args, backend)
            results.extend([result] if name == "check_itinerary" else [])
            return result, ok

        with mock.patch.object(tools, "dispatch", side_effect=record):
            out, fake = self.brief([final("Both days are feasible; Wednesday 10:00 to 10:30 is a tight transition.")])
        checks = [c for c in out["trace"] if c["name"] == "check_itinerary"]
        self.assertEqual(len(checks), 2)
        self.assertTrue(all(c["ok"] for c in checks))
        self.assertEqual(out["removed"], [])
        self.assertIn("feasible", out["text"])
        self.assertEqual([r["locked_from_schedule"] for r in results], [["SYN-AI202"], ["SYN-KEY02", "SYN-AI407"]])


if __name__ == "__main__":
    unittest.main()
