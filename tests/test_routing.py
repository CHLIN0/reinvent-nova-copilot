import unittest

from atlas import routing
from atlas.routing import VENUES, haversine_m, resolve_venue, route

DAY = "2026-12-01T{}:00-08:00"


class VenueTests(unittest.TestCase):
    def test_canonical_keys(self):
        self.assertEqual(
            set(VENUES),
            {"venetian", "wynn", "encore", "caesars_forum", "caesars_palace", "mgm_grand", "mandalay_bay"},
        )
        for v in VENUES.values():
            self.assertTrue(36.0 < v["lat"] < 36.2 and -115.2 < v["lon"] < -115.1)

    def test_resolve_aliases(self):
        self.assertEqual(resolve_venue("The Venetian"), "venetian")
        self.assertEqual(resolve_venue("MGM Grand Conference Center"), "mgm_grand")
        self.assertEqual(resolve_venue("caesars_forum"), "caesars_forum")
        self.assertIsNone(resolve_venue("Bellagio"))

    def test_haversine_sane(self):
        v, m = VENUES["venetian"], VENUES["mandalay_bay"]
        d = haversine_m(v["lat"], v["lon"], m["lat"], m["lon"])
        self.assertTrue(3000 < d < 4000, d)


class RouteTests(unittest.TestCase):
    def test_every_pair_routes_and_is_estimate(self):
        for a in VENUES:
            for b in VENUES:
                r = route(a, b, depart_at=DAY.format("10:00"))
                self.assertTrue(r["estimate"])
                self.assertGreater(r["minutes"], 0)
                self.assertTrue(r["legs"])
                self.assertAlmostEqual(sum(l["minutes"] for l in r["legs"]), r["minutes"], places=0)
                self.assertEqual(sum(l["steps"] for l in r["legs"]), r["steps"])
                self.assertIn("not official wayfinding", " ".join(r["notes"]))

    def test_walkable_neighbours_walk(self):
        r = route("wynn", "encore")
        self.assertEqual(r["modes"], ["walk"])
        self.assertEqual(r["minutes"], 6)

    def test_legs_are_connected(self):
        r = route("caesars_forum", "mandalay_bay", depart_at=DAY.format("09:58"))
        self.assertEqual(r["legs"][0]["from_node"], "caesars_forum:door")
        self.assertEqual(r["legs"][-1]["to_node"], "mandalay_bay:door")
        for x, y in zip(r["legs"], r["legs"][1:]):
            self.assertEqual(x["to_node"], y["from_node"])

    def test_shuttle_wait_depends_on_departure(self):
        # headway 15 from 06:30: leaving at 10:00 waits 0, 10:01 waits 14
        self.assertEqual(routing._wait({"headway": 15, "first": 390, "last": 1320}, 600), 0)
        self.assertEqual(routing._wait({"headway": 15, "first": 390, "last": 1320}, 601), 14)
        self.assertEqual(routing._wait({"headway": 15, "first": 390, "last": 1320}, 300), 90)
        self.assertIsNone(routing._wait({"headway": 15, "first": 390, "last": 1320}, 1330))
        self.assertEqual(routing._wait({"headway": 15, "first": 390, "last": 1320}, None), 7.5)

    def test_time_dependent_arrival_is_fifo(self):
        prev = None
        for minute in range(0, 30):
            r = route("venetian", "mandalay_bay", depart_at=f"2026-12-01T10:{minute:02d}:00-08:00")
            arrive = minute + r["minutes"]
            if prev is not None:
                self.assertGreaterEqual(arrive + 1e-6, prev)
            prev = arrive

    def test_no_shuttle_after_service(self):
        r = route("venetian", "mandalay_bay", depart_at=DAY.format("23:30"))
        self.assertNotIn("shuttle", r["modes"])
        self.assertIn("arrive_at", r)

    def test_monorail_rides_through_without_second_wait(self):
        r = route("caesars_forum", "mgm_grand", depart_at=DAY.format("10:00"))
        mono = [l for l in r["legs"] if l["mode"] == "monorail"]
        self.assertLessEqual(len(mono), 1)

    def test_fewest_steps_never_more_steps(self):
        for a in VENUES:
            for b in VENUES:
                f = route(a, b, DAY.format("14:00"), prefer="fastest")
                s = route(a, b, DAY.format("14:00"), prefer="fewest_steps")
                self.assertLessEqual(s["steps"], f["steps"])
                self.assertGreaterEqual(s["minutes"] + 1e-6, f["minutes"])

    def test_offsets_are_converted_to_las_vegas_time(self):
        a = route("venetian", "mandalay_bay", depart_at="2026-12-01T06:11:00-08:00")
        b = route("venetian", "mandalay_bay", depart_at="2026-12-01T14:11:00Z")
        self.assertEqual(a["minutes"], b["minutes"])
        self.assertEqual(a["legs"], b["legs"])

    def test_same_venue(self):
        r = route("venetian", "Venetian")
        self.assertEqual(len(r["legs"]), 1)
        self.assertTrue(r["estimate"])

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            route("venetian", "bellagio")
        with self.assertRaises(ValueError):
            route("venetian", "wynn", prefer="scenic")


if __name__ == "__main__":
    unittest.main()
