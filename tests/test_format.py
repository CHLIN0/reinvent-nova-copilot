"""Offline unit tests for atlas/format.py (panel-sized answers, M0 T4) and the derived max_sessions."""
import dataclasses
import tempfile
import unittest
from unittest import mock

from atlas import format as fmt
from atlas import official_auth, profile, tools
from atlas.agent import ToolCall
from tests.test_locked import RESERVED, FakeAuth, fixture_backend

KEY02 = {"id": "syn-k002", "code": "SYN-KEY02", "start": "2026-12-02T08:00:00-08:00", "end": "2026-12-02T10:00:00-08:00"}
AI407 = {"id": "syn-0007", "code": "SYN-AI407", "start": "2026-12-02T10:30:00-08:00", "end": "2026-12-02T11:30:00-08:00"}
GEN101 = {"id": "syn-0011", "code": "SYN-GEN101", "start": "2026-12-02T12:00:00-08:00", "end": "2026-12-02T13:00:00-08:00"}
DROPPED = [{"id": f"d-{i}", "code": f"SYN-DRP{100 + i}", "reason": "overlaps"} for i in range(12)]


def plan_call(chosen, dropped=(), locked=("SYN-KEY02", "SYN-AI407"), must=(), day="Wed"):
    result = {"plan": {"feasible": True, "day": day, "chosen": list(chosen), "dropped": list(dropped)},
              "not_found": [], "free_windows": [], "locked_from_schedule": list(locked)}
    return ToolCall("plan_itinerary", {"day": day, "must": list(must)}, True, result)


class MarkdownTest(unittest.TestCase):
    def test_strips_symbols(self):
        text = "## Plan\n**Yes**, you can make *both*.\n- 10:00 `SYN-AI407` Wynn\n* back to hotel"
        self.assertEqual(fmt.strip_markdown(text), "Plan\nYes, you can make both.\n10:00 SYN-AI407 Wynn\nback to hotel")

    def test_keeps_plain_text(self):
        text = "Leave the hotel at 08:12. 2026-12-02 is Wednesday; 3 - 1 = 2."
        self.assertEqual(fmt.strip_markdown(text), text)


class HonestAdditionsTest(unittest.TestCase):
    def test_replaces_claim_when_only_reservations_kept(self):
        trace = [plan_call([KEY02, AI407], DROPPED)]
        out = fmt.honest_additions("Your Wednesday is feasible with the added sessions. Leave at 07:30.", trace)
        self.assertEqual(out, "No additional session fits around your reservations on Wednesday. Leave at 07:30.")

    def test_keeps_true_claim(self):
        trace = [plan_call([KEY02, AI407, GEN101])]
        text = "I added SYN-GEN101 between your reservations."
        self.assertEqual(fmt.honest_additions(text, trace), text)

    def test_must_attend_counts_as_base(self):
        trace = [plan_call([GEN101], locked=(), must=("syn-0011",))]
        out = fmt.honest_additions("Plan with two additional sessions is ready.", trace)
        self.assertEqual(out, "No additional session fits around your must-attend sessions on Wednesday.")

    def test_model_already_honest_only_drops_claim(self):
        trace = [plan_call([KEY02, AI407])]
        text = "No additional session fits around your reservations on Wednesday. Feasible with the added sessions."
        self.assertEqual(fmt.honest_additions(text, trace),
                         "No additional session fits around your reservations on Wednesday.")

    def test_live_wording_counts_as_honest(self):
        """Nova Pro's own wording in the live Wednesday run (2026-11-07)."""
        trace = [plan_call([KEY02, AI407])]
        text = ("No additional security or architecture sessions fit around your reservations. "
                "The plan is feasible with the added sessions.")
        self.assertEqual(fmt.honest_additions(text, trace),
                         "No additional security or architecture sessions fit around your reservations.")

    def test_negated_mention_is_not_a_claim(self):
        trace = [plan_call([KEY02, AI407])]
        text = "Nothing was added because every candidate overlaps a reservation."
        self.assertEqual(fmt.honest_additions(text, trace), text)

    def test_chinese(self):
        trace = [plan_call([KEY02, AI407])]
        out = fmt.honest_additions("週三已為你新增兩場。出發前確認座位。", trace)
        self.assertEqual(out, "週三除了你的預約，沒有其他場次排得進去。出發前確認座位。")

    def test_no_plan_no_change(self):
        text = "I added two sessions."
        self.assertEqual(fmt.honest_additions(text, []), text)


class DroppedTest(unittest.TestCase):
    def test_sentence_collapsed_with_reason(self):
        codes = ", ".join(d["code"] for d in DROPPED)
        trace = [plan_call([KEY02, AI407, GEN101], DROPPED)]
        out = fmt.collapse_dropped(f"Dropped: {codes} because they overlap your reservations. Next, reserve.", trace)
        self.assertEqual(out, "12 dropped (3 shown: SYN-DRP100, SYN-DRP101, SYN-DRP102) because they overlap "
                              "your reservations. Next, reserve.")

    def test_one_per_line_list_collapsed(self):
        lines = "\n".join(f"{d['code']} 09:00 overlaps SYN-KEY02 window" for d in DROPPED[:5])
        trace = [plan_call([GEN101], DROPPED[:5], locked=())]
        out = fmt.collapse_dropped(f"10:00 SYN-GEN101 Forum\nDropped sessions:\n{lines}\nNext, reserve.", trace)
        self.assertEqual(out, "10:00 SYN-GEN101 Forum\n5 dropped (3 shown: SYN-DRP100, SYN-DRP101, SYN-DRP102).\nNext, reserve.")

    def test_three_or_fewer_untouched(self):
        trace = [plan_call([GEN101], DROPPED[:3], locked=())]
        text = "Dropped SYN-DRP100, SYN-DRP101 and SYN-DRP102 because they overlap."
        self.assertEqual(fmt.collapse_dropped(text, trace), text)

    def test_prefix_codes_do_not_match(self):
        dropped = [{"id": "x", "code": "DVT415"}] + DROPPED[:3]
        trace = [plan_call([{"id": "y", "code": "DVT415-R2"}], dropped, locked=())]
        text = "Keep DVT415-R2, SYN-DRP100, SYN-DRP101 and SYN-DRP102."
        self.assertEqual(fmt.collapse_dropped(text, trace), text)


class CapTest(unittest.TestCase):
    def test_plan_lines_and_first_sentence_survive(self):
        plan = "\n".join(f"{9 + i}:00-{9 + i}:45 SYN-X{100 + i} Session title number {i}, Venetian" for i in range(6))
        prose = " ".join(f"Filler sentence number {i} explains a detail at length." for i in range(30))
        text = f"Yes, it works.\n{plan}\n{prose} Next, reserve SYN-X100."
        out = fmt.cap_words(text)
        self.assertLessEqual(fmt.count_words(out), fmt.MAX_WORDS)
        self.assertTrue(out.startswith("Yes, it works.\n"))
        self.assertIn(plan, out)
        self.assertTrue(out.endswith("Next, reserve SYN-X100."))

    def test_cjk_counts_characters(self):
        self.assertEqual(fmt.count_words("週三 SYN-AI407 at 10:30"), 5)

    def test_short_text_unchanged(self):
        self.assertEqual(fmt.cap_words("Short answer."), "Short answer.")

    def test_pipeline_idempotent(self):
        trace = [plan_call([KEY02, AI407], DROPPED)]
        codes = ", ".join(d["code"] for d in DROPPED)
        text = f"**Feasible with the added sessions.**\n- 08:00 SYN-KEY02\nDropped {codes}. " + "More words here. " * 60
        once = fmt.format_answer(text, trace)
        self.assertEqual(fmt.format_answer(once, trace), once)
        self.assertLessEqual(fmt.count_words(once), fmt.MAX_WORDS)


class DerivedMaxSessionsTest(unittest.TestCase):
    """plan_itinerary derives max_sessions from free windows when the model does not pass it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(profile, "PROFILE_DIR", profile.Path(self.tmp.name))
        self.patch.start()
        official_auth.set_auth(FakeAuth())
        self.addCleanup(official_auth.set_auth, None)
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.tmp.cleanup)
        self.be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []})
        self.seen = {}
        real = self.be.plan_itinerary

        def spy(pool, **kw):
            self.seen.update(kw)
            return real(pool, **kw)

        self.be = dataclasses.replace(self.be, plan_itinerary=spy)

    def plan(self, **args):
        out, ok = tools.dispatch("plan_itinerary", {"day": "Wed", "use_profile": False, **args}, self.be)
        self.assertTrue(ok, out)
        return out

    def test_wednesday_windows_between_reservations(self):
        out = self.plan(candidate_ids=["syn-0011", "syn-0015", "syn-0047"])  # 12:00, 13:30, 16:30
        self.assertEqual(out["free_windows"], [{"day": "2026-12-02", "start": "11:30", "end": "15:00", "minutes": 210},
                                               {"day": "2026-12-02", "start": "16:00", "end": "17:30", "minutes": 90}])
        self.assertEqual(self.seen["max_sessions"], 3 + 3 + 1)

    def test_back_by_and_blocked_shrink_windows(self):
        out = self.plan(candidate_ids=["syn-0011", "syn-0015", "syn-0047"], back_by="16:30",
                        blocked=[{"start": "12:00", "end": "13:00", "label": "lunch"}])
        self.assertEqual([(w["start"], w["end"]) for w in out["free_windows"]], [("13:00", "15:00")])
        self.assertEqual(self.seen["max_sessions"], 3 + 2)

    def test_model_value_wins_and_cap_is_eight(self):
        self.plan(candidate_ids=["syn-0011"], max_sessions=2)
        self.assertEqual(self.seen["max_sessions"], 2)
        official_auth.set_auth(None)
        out, ok = tools.dispatch("plan_itinerary", {"query": "AI", "day": "Tue", "use_profile": False}, self.be)
        self.assertTrue(ok, out)
        self.assertEqual(self.seen["max_sessions"], 8)

    def test_no_window_means_one(self):
        self.assertEqual(tools._default_max_sessions([], [], {"2026-12-02"}), 1)


if __name__ == "__main__":
    unittest.main()
