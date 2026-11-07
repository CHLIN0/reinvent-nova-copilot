import os
import stat
import tempfile
import unittest
from unittest import mock

from atlas import profile, tools


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(profile, "PROFILE_DIR", profile.Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_update_and_load_with_private_file_mode(self):
        out = profile.update_profile({"hotel": "Park MGM", "transport": "monorail", "max_steps_per_day": "8000"})
        self.assertEqual(out["fields"]["transport"], ["monorail"])
        self.assertEqual(out["fields"]["max_steps_per_day"], 8000)
        self.assertEqual(out["home_base"], {"venue": "mgm_grand", "exact": False,
                                            "note": out["home_base"]["note"]})
        mode = stat.S_IMODE(os.stat(profile._path(None)).st_mode)
        self.assertEqual(mode, 0o600)

    def test_unknown_field_rejected(self):
        res, ok = tools.dispatch("update_profile", {"updates": {"password": "x"}})
        self.assertFalse(ok)
        self.assertIn("Unknown profile field", res["error"])

    def test_plan_adds_hotel_travel(self):
        profile.update_profile({"hotel": "The Venetian"})
        r, _ = tools.dispatch("search_sessions", {"day": "Tue", "limit": 30})
        ids = [s["id"] for s in r["sessions"]]
        res, ok = tools.dispatch("plan_itinerary", {"candidate_ids": ids, "day": "Tue"})
        self.assertTrue(ok, res)
        hb = res["home_base_travel"]
        self.assertEqual(hb["home_venue"], "venetian")
        self.assertIn("leave_hotel_by", hb["to_first"])
        self.assertTrue(hb["back_to_hotel"]["estimate"])

    def test_back_by_drops_sessions_that_cannot_return_to_hotel(self):
        profile.update_profile({"hotel": "Park MGM"})
        r, _ = tools.dispatch("search_sessions", {"day": "Tue", "limit": 30})
        ids = [s["id"] for s in r["sessions"]]
        res, ok = tools.dispatch("plan_itinerary", {"candidate_ids": ids, "day": "Tue", "back_by": "17:15",
                                                    "blocked": [{"start": "12:00", "end": "13:00", "label": "lunch"}]})
        self.assertTrue(ok, res)
        for s in res["plan"]["chosen"]:
            self.assertLessEqual(s["end"][11:16], "17:15")
            self.assertFalse("12:00" <= s["start"][11:16] < "13:00")
        reasons = " ".join(d["reason"] for d in res["plan"]["dropped"])
        self.assertIn("back to the hotel", reasons)
        self.assertIn("blocked time", reasons)

    def test_profile_name_is_sanitised(self):
        self.assertEqual(profile._safe_name("../../etc"), "etc")


if __name__ == "__main__":
    unittest.main()
