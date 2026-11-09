"""Offline tests for the RSVP lifecycle (M0 T7): official cancel with read-back, its click-only route,
seat words and plain-words results in the Copilot panel and on Event Atlas cards. No real API call."""
import io
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import web
from atlas import catalog, official_auth, tools
from atlas.agent import ToolCall

from tests.test_catalog import Base, FakeAuth, Recorder

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "explorer" / "ui"


def schedule(reserved):
    return {"reserved": list(reserved), "favorites": [], "personalTime": [], "source": "official_api"}


class CancelReservationsTest(Base):
    def setUp(self):
        super().setUp()
        official_auth.set_auth(FakeAuth())

    def cancel(self, ids, errors=None, still_reserved=()):
        """Run cancel_reservations with a mocked _request: `errors` maps a session id to a CatalogError code."""
        calls = []

        def request(method, path, *a, **k):
            calls.append((method, path))
            if method == "GET":
                return {"schedule": schedule(still_reserved)}
            code = (errors or {}).get(path.rsplit("/", 1)[1])
            if code:
                raise catalog.CatalogError(code)
            return {}

        with mock.patch.object(catalog, "_request", side_effect=request):
            return catalog.cancel_reservations(ids), calls

    def test_all_cancelled_and_verified_by_read_back(self):
        out, calls = self.cancel(["a1", "b/2", "a1"])
        self.assertEqual(calls, [("DELETE", "/v1/events/reinvent2026/reservations/a1"),
                                 ("DELETE", "/v1/events/reinvent2026/reservations/b%2F2"),
                                 ("GET", "/v1/events/reinvent2026/schedule")])
        self.assertEqual(out["results"], [{"session_id": "a1", "ok": True, "in_schedule_reserved": False},
                                          {"session_id": "b/2", "ok": True, "in_schedule_reserved": False}])
        self.assertTrue(out["verified"])

    def test_partial_failure_reports_per_item(self):
        out, _ = self.cancel(["a1", "b2", "c3"], errors={"b2": "official_operation_closed",
                                                          "c3": "official_event_not_found"},
                             still_reserved=["b2"])
        by_id = {r["session_id"]: r for r in out["results"]}
        self.assertEqual(by_id["a1"], {"session_id": "a1", "ok": True, "in_schedule_reserved": False})
        self.assertEqual(by_id["b2"], {"session_id": "b2", "ok": False, "code": "operationClosed",
                                       "in_schedule_reserved": True})
        # 404: there was no reservation; the developer guide says to treat it as already done.
        self.assertEqual(by_id["c3"], {"session_id": "c3", "ok": True, "already_gone": True,
                                       "in_schedule_reserved": False})
        self.assertTrue(out["verified"])  # failed items do not count against the read-back

    def test_read_back_mismatch_is_not_verified(self):
        out, _ = self.cancel(["a1"], still_reserved=["a1"])
        self.assertTrue(out["results"][0]["ok"])
        self.assertTrue(out["results"][0]["in_schedule_reserved"])
        self.assertFalse(out["verified"])

    def test_ids_are_validated(self):
        for bad in ([], [""], [None, 3], [f"x{i}" for i in range(11)]):
            with self.assertRaises(ValueError):
                catalog.cancel_reservations(bad)
        official_auth.set_auth(None)
        with self.assertRaises(catalog.CatalogError) as ctx:
            catalog.cancel_reservations(["a1"])
        self.assertEqual(ctx.exception.code, "official_sign_in_required")

    def test_wire_codes_204_404_409(self):
        """CancelReservation answers 204 with no body; 404 = no reservation; 409 = operation closed."""
        rec = Recorder([(204, {}, None), (404, {}, None), (409, {}, {"message": "closed"}),
                        (200, {}, {"schedule": {"reserved": ["c3"], "favorites": [], "personalTime": []}})])
        catalog._transport = rec
        out = catalog.cancel_reservations(["a1", "b2", "c3"])
        self.assertEqual([c["method"] for c in rec.calls], ["DELETE", "DELETE", "DELETE", "GET"])
        self.assertEqual(rec.calls[0]["token"], "test-token-not-real")
        self.assertIsNone(rec.calls[0]["body"])
        self.assertEqual([(r["ok"], r.get("code"), r.get("already_gone")) for r in out["results"]],
                         [(True, None, None), (True, None, True), (False, "operationClosed", None)])


class RouteTest(unittest.TestCase):
    def post(self, path, body):
        handler = web.Handler.__new__(web.Handler)
        raw = json.dumps(body).encode()
        handler.path = path
        handler.headers = {"Content-Type": "application/json", "Content-Length": str(len(raw))}
        handler.rfile = io.BytesIO(raw)
        handler._host_ok = mock.Mock(return_value=True)
        handler._json = mock.Mock()
        handler.do_POST()
        return handler._json.call_args.args

    def test_cancel_route_validates_like_rsvp(self):
        result = {"results": [{"session_id": "a1", "ok": True, "in_schedule_reserved": False}], "verified": True}
        with mock.patch.object(catalog, "cancel_reservations", return_value=result) as fn:
            self.assertEqual(self.post("/api/rsvp/cancel", {"session_ids": ["a1", 7, None]}), (200, result))
        fn.assert_called_once_with(["a1"])
        with mock.patch.object(official_auth, "is_signed_in", return_value=True):
            code, body = self.post("/api/rsvp/cancel", {"session_ids": []})
        self.assertEqual(code, 400)
        self.assertIn("1 to 10", body["error"])

    def test_cancel_is_click_only(self):
        self.assertEqual(tools.WRITE_TOOLS, frozenset({"add_favorites"}))
        self.assertFalse([s["name"] for s in tools.TOOL_SPECS if "cancel" in s["name"] or "reserv" in s["name"]])

    def test_suggested_cards_carry_seat_band(self):
        first = tools._brief(catalog.load_fixture()[0])  # what search_sessions returns, seat band included
        chosen = {k: first[k] for k in ("id", "code", "title", "start", "end", "venue")}  # plan rows have none
        res = mock.Mock(text="", trace=[ToolCall("search_sessions", {}, True, {"sessions": [first]}),
                                        ToolCall("plan_itinerary", {}, True, {"plan": {"chosen": [chosen]}})])
        self.assertEqual(web._suggested(res)[0]["seats"], first["seats"])
        self.assertTrue(first["seats"])

    def test_planner_suggestions_carry_seat_band_without_a_search(self):
        """Codex round 1: plan_itinerary(query=...) searches internally, so no search row is in the trace."""
        first = catalog.load_fixture()[0]
        chosen = {k: first[k] for k in ("id", "code", "title", "start", "end", "venue")}
        res = mock.Mock(text="", trace=[ToolCall("plan_itinerary", {"query": "agents"}, True, {"plan": {"chosen": [chosen]}})])
        be = mock.Mock(get_session=mock.Mock(return_value=first))
        with mock.patch.dict(web._state, {"agent": mock.Mock(backend=be)}):
            self.assertEqual(web._suggested(res)[0]["seats"], first["seats"])  # the backend the tools used
        be.get_session.assert_called_once_with(first["id"])
        with mock.patch.dict(web._state, {"agent": None}), \
                mock.patch.object(catalog, "get_session", return_value=first):
            self.assertEqual(web._suggested(res)[0]["seats"], first["seats"])  # default backend = the catalog
        with mock.patch.dict(web._state, {"agent": None}), \
                mock.patch.object(catalog, "get_session", side_effect=catalog.CatalogError("catalog_unavailable")):
            self.assertEqual(web._suggested(res)[0]["seats"], "")  # optional: never fails the answer

    def test_atlas_catalog_keeps_seat_availability(self):
        sys.path.insert(0, str(ROOT / "explorer"))
        import server as atlas_server  # explorer/server.py

        out = atlas_server.project_catalog({"version": 1, "meta": {}, "sessions": [
            {"session_id": "s1", "title": "T", "seat_availability": "veryLimited"}, {"session_id": "s2", "title": "T"}]})
        self.assertEqual([s["seat_availability"] for s in out["sessions"]], ["veryLimited", None])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class NodeTest(unittest.TestCase):
    def test_copilot_cards(self):
        run = subprocess.run(["node", str(ROOT / "tests" / "copilot_rsvp_cards.mjs"), str(ROOT / "web" / "copilot.js")],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])
        self.assertIn("copilot rsvp checks passed", run.stdout)

    def test_atlas_wiring(self):
        """The tested rsvp.mjs pieces are the ones the Atlas card uses; a cancel tells both views to re-read the plan."""
        app = (UI / "src" / "app.mjs").read_text(encoding="utf-8")
        self.assertIn('if (planItem(r)?.source === "reserved") return cancelOfficial(r);', app)
        self.assertIn("confirm(cancelConfirmText(p, timeText(r)))", app)
        self.assertIn("await cancelReservation(r.session.session_id)", app)
        self.assertIn("window.dispatchEvent(new Event(PLAN_CHANGED));", app)

    def test_atlas_rsvp_module_and_bundle(self):
        run = subprocess.run(["node", "--test", "test-rsvp.mjs"], cwd=UI, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout[-3000:] + run.stderr[-2000:])
        bundle = (UI / "dist" / "app.js").read_text(encoding="utf-8")
        # dist was rebuilt with the cancel action (esbuild writes non-ASCII text as \u escapes)
        self.assertTrue("/api/rsvp/cancel" in bundle)
        self.assertTrue(r"\u53D6\u6D88\u5B98\u65B9\u9810\u7D04" in bundle)  # 取消官方預約


if __name__ == "__main__":
    unittest.main()
