import itertools
import unittest

from atlas.planner import check_itinerary, plan_itinerary


def S(sid, start, end, venue, day="2026-12-01", **kw):
    return {"id": sid, "code": sid, "title": f"Session {sid}", "start": f"{day}T{start}:00-08:00",
            "end": f"{day}T{end}:00-08:00", "venue": venue, **kw}


class CheckTests(unittest.TestCase):
    def test_ok_and_conflict(self):
        r = check_itinerary([
            S("A", "09:00", "10:00", "venetian"),
            S("B", "10:30", "11:30", "venetian"),       # same venue, 30 min gap: ok
            S("C", "11:40", "12:40", "mandalay_bay"),   # 10 min gap to Mandalay: impossible
        ])
        self.assertEqual([t["status"] for t in r["transitions"]], ["ok", "not_enough_time"])
        self.assertFalse(r["feasible"])
        self.assertEqual(len(r["conflicts"]), 1)
        self.assertTrue(r["estimate"])
        self.assertEqual(r["total_steps"], sum(t["steps"] for t in r["transitions"]))

    def test_overlap_and_sorting(self):
        r = check_itinerary([S("B", "09:30", "10:30", "wynn"), S("A", "09:00", "10:00", "wynn")])
        self.assertEqual(r["sessions"][0]["id"], "A")
        self.assertEqual(r["transitions"][0]["status"], "overlap")

    def test_buffer_changes_verdict(self):
        pair = [S("A", "09:00", "10:00", "wynn"), S("B", "10:12", "11:00", "encore")]  # walk 6 min
        self.assertTrue(check_itinerary(pair, buffer_min=5)["feasible"])
        self.assertFalse(check_itinerary(pair, buffer_min=10)["feasible"])

    def test_new_day_is_not_a_conflict(self):
        r = check_itinerary([S("A", "16:00", "17:00", "mandalay_bay"),
                             S("B", "08:00", "09:00", "encore", day="2026-12-02")])
        self.assertEqual(r["transitions"][0]["status"], "new_day")
        self.assertTrue(r["feasible"])

    def test_overlap_across_midnight(self):
        a = {"id": "A", "start": "2026-12-01T23:00:00-08:00", "end": "2026-12-02T01:00:00-08:00", "venue": "wynn"}
        b = {"id": "B", "start": "2026-12-02T00:30:00-08:00", "end": "2026-12-02T01:30:00-08:00", "venue": "wynn"}
        r = check_itinerary([a, b])
        self.assertEqual(r["transitions"][0]["status"], "overlap")
        self.assertFalse(r["feasible"])

    def test_unknown_venue_is_flagged(self):
        r = check_itinerary([S("A", "09:00", "10:00", "venetian"), S("B", "11:00", "12:00", "somewhere")])
        self.assertIn("note", r["transitions"][0])


CANDS = [
    S("K1", "08:00", "09:00", "venetian"),
    S("M1", "09:00", "10:00", "mandalay_bay"),   # conflicts with K1 by travel
    S("V2", "09:15", "10:15", "venetian"),
    S("V3", "10:30", "11:30", "venetian"),
    S("W3", "10:30", "11:30", "wynn"),           # same slot as V3
    S("F4", "12:00", "13:00", "caesars_forum"),
    S("X4", "12:00", "12:30", "mandalay_bay"),
    S("V5", "13:30", "14:30", "venetian"),
]


class PlanTests(unittest.TestCase):
    def test_result_is_feasible_and_complete(self):
        r = plan_itinerary(CANDS)
        self.assertTrue(r["feasible"])
        self.assertTrue(check_itinerary(
            [c for c in CANDS if c["id"] in {x["id"] for x in r["chosen"]}])["feasible"])
        ids = {x["id"] for x in r["chosen"]} | {x["id"] for x in r["dropped"]}
        self.assertEqual(ids, {c["id"] for c in CANDS})
        for d in r["dropped"]:
            self.assertTrue(d["reason"])

    def test_matches_brute_force_count(self):
        best = 0
        for k in range(len(CANDS), 0, -1):
            if any(check_itinerary(list(c))["feasible"] for c in itertools.combinations(CANDS, k)):
                best = k
                break
        self.assertEqual(len(plan_itinerary(CANDS, max_sessions=10)["chosen"]), best)

    def test_must_is_kept(self):
        r = plan_itinerary(CANDS, must=["M1"])
        chosen = [x["id"] for x in r["chosen"]]
        self.assertIn("M1", chosen)
        self.assertNotIn("K1", chosen)
        k1 = next(d for d in r["dropped"] if d["id"] == "K1")
        self.assertIn("M1", k1["reason"])

    def test_conflicting_musts_reported(self):
        r = plan_itinerary(CANDS, must=["K1", "M1"])
        self.assertFalse(r["feasible"])
        self.assertTrue(r["must_conflicts"])

    def test_max_sessions_cap(self):
        r = plan_itinerary(CANDS, max_sessions=2)
        self.assertEqual(len(r["chosen"]), 2)
        self.assertTrue(any("max_sessions" in d["reason"] for d in r["dropped"]))

    def test_priority_wins(self):
        cands = [S("A", "10:30", "11:30", "venetian"), S("B", "10:30", "11:30", "wynn", priority=3)]
        r = plan_itinerary(cands)
        self.assertEqual([x["id"] for x in r["chosen"]], ["B"])

    def test_less_travel_breaks_ties(self):
        cands = [S("A", "09:00", "10:00", "venetian"), S("B", "11:00", "12:00", "mandalay_bay"),
                 S("C", "11:00", "12:00", "venetian")]
        r = plan_itinerary(cands, max_sessions=2)
        self.assertEqual([x["id"] for x in r["chosen"]], ["A", "C"])

    def test_day_filter(self):
        cands = CANDS + [S("T1", "09:00", "10:00", "venetian", day="2026-12-02")]
        r = plan_itinerary(cands, day="2026-12-02")
        self.assertEqual([x["id"] for x in r["chosen"]], ["T1"])
        r2 = plan_itinerary(cands, day="Wednesday")
        self.assertEqual([x["id"] for x in r2["chosen"]], ["T1"])
        self.assertTrue(any(d["reason"].startswith("not on") for d in r["dropped"]))

    def test_unknown_must_warns(self):
        r = plan_itinerary(CANDS, must=["NOPE"])
        self.assertTrue(r["warnings"])

    def test_zero_cap_and_negative_priority(self):
        self.assertEqual(plan_itinerary(CANDS[:1], max_sessions=0)["chosen"], [])
        neg = [S("A", "09:00", "10:00", "venetian", priority=-1)]
        self.assertEqual(plan_itinerary(neg)["chosen"], [])

    def test_off_day_reported_when_musts_conflict(self):
        cands = CANDS + [S("T1", "09:00", "10:00", "venetian", day="2026-12-02")]
        r = plan_itinerary(cands, must=["K1", "M1"], day="2026-12-01")
        self.assertIn("T1", {d["id"] for d in r["dropped"]})

    def test_empty(self):
        r = plan_itinerary([])
        self.assertEqual(r["chosen"], [])
        self.assertTrue(r["feasible"])


if __name__ == "__main__":
    unittest.main()
