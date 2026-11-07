"""Offline unit tests for atlas/format.py (panel-sized answers, M0 T4) and the derived max_sessions.

format.py never deletes model text: it strips Markdown symbols, appends the plain "no additional
session fits" line, and shortens a sentence that lists more than three dropped codes.
"""
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
NO_WED = "No additional session fits around your reservations on Wednesday."


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


class NoAdditionTest(unittest.TestCase):
    def test_appends_when_only_reservations_kept(self):
        """The live finding: the claim stays (never deleted); the plain statement is appended."""
        text = "Your Wednesday is feasible with the added sessions."
        self.assertEqual(fmt.add_no_addition(text, [plan_call([KEY02, AI407], DROPPED)]), text + "\n" + NO_WED)

    def test_nothing_appended_when_the_planner_added(self):
        text = "I added SYN-GEN101 between your reservations."
        self.assertEqual(fmt.add_no_addition(text, [plan_call([KEY02, AI407, GEN101])]), text)

    def test_model_already_said_it(self):
        """Nova Pro's own wording in the live Wednesday run (2026-11-07)."""
        text = "No additional security or architecture sessions fit around your reservations."
        self.assertEqual(fmt.add_no_addition(text, [plan_call([KEY02, AI407])]), text)

    def test_must_attend_base(self):
        out = fmt.add_no_addition("Plan ready.", [plan_call([GEN101], locked=(), must=("syn-0011",))])
        self.assertEqual(out, "Plan ready.\nNo additional session fits around your must-attend sessions on Wednesday.")

    def test_chinese_answer_gets_chinese_line(self):
        out = fmt.add_no_addition("週三已為你新增兩場。", [plan_call([KEY02, AI407])])
        self.assertEqual(out, "週三已為你新增兩場。\n週三除了你的預約，沒有其他場次排得進去。")

    def test_latest_plan_per_day_and_one_line_per_day(self):
        tue = [{"id": "syn-0002", "code": "SYN-AI202", "start": "2026-12-01T09:00:00-08:00"}]
        replanned = [plan_call([KEY02, AI407]), plan_call([KEY02, AI407, GEN101])]
        self.assertEqual(fmt.add_no_addition("Done.", replanned), "Done.")
        self.assertEqual(fmt.add_no_addition("Done.", list(reversed(replanned))), "Done.\n" + NO_WED)
        both = [plan_call(tue, locked=(), day="Tue", must=("syn-0002",)), plan_call([KEY02, AI407])]
        self.assertEqual(fmt.add_no_addition("Done.", both),
                         "Done.\nNo additional session fits around your must-attend sessions on Tuesday.\n" + NO_WED)

    def test_stated_day_covers_only_itself(self):
        """Codex on e4acb09: Tuesday stated plainly does not cover Wednesday's false claim."""
        tue = [{"id": "syn-0002", "code": "SYN-AI202", "start": "2026-12-01T09:00:00-08:00"}]
        trace = [plan_call(tue, locked=("SYN-AI202",), day="Tue"), plan_call([KEY02, AI407])]
        text = "No additional session fits around your reservations on Tuesday. Wednesday has two added sessions."
        self.assertEqual(fmt.add_no_addition(text, trace), text + "\n" + NO_WED)
        both = "No additional session fits around your reservations on Tuesday or Wednesday."
        self.assertEqual(fmt.add_no_addition(both, trace), both)
        dayless = "No additional session fits around your reservations."
        self.assertEqual(fmt.add_no_addition(dayless, trace),
                         dayless + "\nNo additional session fits around your reservations on Tuesday.\n" + NO_WED)
        self.assertEqual(fmt.add_no_addition(dayless, trace[1:]), dayless)  # one plan: a dayless sentence covers it

    def test_chinese_stated_day(self):
        trace = [plan_call([KEY02, AI407])]
        text = "週三除了你的預約，沒有其他場次排得進去。"
        self.assertEqual(fmt.add_no_addition(text, trace), text)

    def test_no_plan_no_change(self):
        self.assertEqual(fmt.add_no_addition("I added two sessions.", []), "I added two sessions.")


class DroppedTest(unittest.TestCase):
    def test_run_replaced_rest_of_sentence_kept(self):
        codes = ", ".join(d["code"] for d in DROPPED)
        trace = [plan_call([KEY02, AI407, GEN101], DROPPED)]
        out = fmt.collapse_dropped(f"Keep SYN-GEN101; dropped {codes} because they overlap. Next, reserve.", trace)
        self.assertEqual(out, "Keep SYN-GEN101; dropped 12 dropped (3 shown: SYN-DRP100, SYN-DRP101, SYN-DRP102) "
                              "because they overlap. Next, reserve.")

    def test_three_or_fewer_untouched(self):
        trace = [plan_call([GEN101], DROPPED[:3], locked=())]
        text = "Dropped SYN-DRP100, SYN-DRP101 and SYN-DRP102 because they overlap."
        self.assertEqual(fmt.collapse_dropped(text, trace), text)

    def test_one_per_line_list_untouched(self):
        """Only the single-sentence case collapses; a one-per-line list is left as the model wrote it."""
        text = "\n".join(f"{d['code']}: overlaps" for d in DROPPED[:5])
        self.assertEqual(fmt.collapse_dropped(text, [plan_call([GEN101], DROPPED[:5], locked=())]), text)

    def test_planned_code_inside_the_run_blocks_it(self):
        trace = [plan_call([GEN101, AI407], DROPPED[:4], locked=())]
        text = "Choose SYN-GEN101 over SYN-DRP100 or SYN-DRP101, and SYN-AI407 over SYN-DRP102 or SYN-DRP103."
        self.assertEqual(fmt.collapse_dropped(text, trace), text)

    def test_prefix_codes_do_not_match(self):
        dropped = [{"id": "x", "code": "DVT415"}] + DROPPED[:3]
        trace = [plan_call([{"id": "y", "code": "DVT415-R2"}], dropped, locked=())]
        text = "Keep DVT415-R2, SYN-DRP100, SYN-DRP101 and SYN-DRP102."
        self.assertEqual(fmt.collapse_dropped(text, trace), text)

    def test_other_days_sessions_are_not_dropped(self):
        tue = [{"id": f"t{i}", "code": f"SYN-TUE{100 + i}", "start": "2026-12-01T09:00:00-08:00"} for i in range(6)]
        trace = [plan_call(tue, locked=(), day="Tue"),
                 plan_call([KEY02, AI407], [{**r, "reason": "not on Wed"} for r in tue] + DROPPED[:2])]
        text = "Tuesday keeps " + ", ".join(r["code"] for r in tue) + "."
        self.assertEqual(fmt.collapse_dropped(text, trace), text)

    def test_count_is_the_owning_plans(self):
        tue = [{"id": "syn-0002", "code": "SYN-AI202", "start": "2026-12-01T09:00:00-08:00"}]
        tue_drop = [{"id": f"e-{i}", "code": f"SYN-TDR{100 + i}"} for i in range(4)]
        trace = [plan_call(tue, tue_drop, locked=(), day="Tue"), plan_call([KEY02, AI407], DROPPED[:6])]
        own = fmt.collapse_dropped("Tuesday dropped " + ", ".join(d["code"] for d in tue_drop) + ".", trace)
        self.assertEqual(own, "Tuesday dropped 4 dropped (3 shown: SYN-TDR100, SYN-TDR101, SYN-TDR102).")
        mixed = fmt.collapse_dropped("Dropped SYN-TDR100, SYN-TDR101, SYN-DRP100 and SYN-DRP101.", trace)
        self.assertEqual(mixed, "Dropped 10 dropped (3 shown: SYN-TDR100, SYN-TDR101, SYN-DRP100).")

    def test_chinese(self):
        trace = [plan_call([KEY02, AI407], DROPPED[:4])]
        out = fmt.collapse_dropped("未排入：SYN-DRP100、SYN-DRP101、SYN-DRP102、SYN-DRP103，因為與預約重疊。", trace)
        self.assertEqual(out, "未排入：另有 4 場未排入（列出 3 場：SYN-DRP100、SYN-DRP101、SYN-DRP102），因為與預約重疊。")


class PipelineTest(unittest.TestCase):
    def test_idempotent_and_never_removes_words(self):
        trace = [plan_call([KEY02, AI407], DROPPED)]
        text = "**Feasible with the added sessions.**\n- 08:00 SYN-KEY02\nLong prose sentence here. " * 3
        once = fmt.format_answer(text, trace)
        self.assertEqual(fmt.format_answer(once, trace), once)
        for word in ("Feasible", "added", "08:00", "SYN-KEY02", "Long prose sentence here."):
            self.assertIn(word, once)
        self.assertTrue(once.endswith(NO_WED))


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
