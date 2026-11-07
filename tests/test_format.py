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

    def test_profile_addition_is_not_a_session_claim(self):
        """Codex review: 'added your hotel' is not an added session."""
        trace = [plan_call([KEY02, AI407])]
        text = "I added your hotel to your profile. Your Wednesday reservations were kept."
        self.assertEqual(fmt.honest_additions(text, trace), text)

    def test_claim_checked_against_its_own_day(self):
        """Codex review: Tuesday's plan added SYN-AI202, Wednesday's kept only reservations."""
        ai202 = {"id": "syn-0002", "code": "SYN-AI202", "start": "2026-12-01T09:00:00-08:00"}
        trace = [plan_call([ai202], locked=(), day="Tue"), plan_call([KEY02, AI407])]
        text = ("I added SYN-AI202 on Tuesday. On Tuesday I also added two more sessions. "
                "On Wednesday I added two extra sessions.")
        self.assertEqual(fmt.honest_additions(text, trace),
                         "I added SYN-AI202 on Tuesday. On Tuesday I also added two more sessions. "
                         "No additional session fits around your reservations on Wednesday.")

    def test_unnamed_day_with_mixed_plans_is_kept(self):
        ai202 = {"id": "syn-0002", "code": "SYN-AI202", "start": "2026-12-01T09:00:00-08:00"}
        trace = [plan_call([ai202], locked=(), day="Tue"), plan_call([KEY02, AI407])]
        text = "Both plans have the added sessions."
        self.assertEqual(fmt.honest_additions(text, trace), text)

    def test_replanned_day_uses_latest_plan(self):
        """Codex round 2: Wednesday planned twice, the second plan adds a session."""
        trace = [plan_call([KEY02, AI407]), plan_call([KEY02, AI407, GEN101])]
        text = "I added a session on Wednesday."
        self.assertEqual(fmt.honest_additions(text, trace), text)
        self.assertEqual(fmt.honest_additions(text, list(reversed(trace))),
                         "No additional session fits around your reservations on Wednesday.")

    def test_suggestions_and_questions_are_not_claims(self):
        """Codex round 2: offers to search are next steps, not claims."""
        trace = [plan_call([KEY02, AI407])]
        for text in ("Next, search for additional sessions on Thursday.",
                     "Would you like me to look for extra sessions?",
                     "You could add a session on Thursday instead."):
            self.assertEqual(fmt.honest_additions(text, trace), text)

    def test_session_removed_by_replan_is_not_added(self):
        """Codex round 3: the re-plan dropped SYN-GEN101 again, so the claim is false."""
        trace = [plan_call([KEY02, AI407, GEN101]), plan_call([KEY02, AI407])]
        self.assertEqual(fmt.honest_additions("I added SYN-GEN101 on Wednesday.", trace),
                         "No additional session fits around your reservations on Wednesday.")

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

    def test_only_the_list_fragment_is_replaced(self):
        """Codex review: the advice around the list survives."""
        trace = [plan_call([GEN101], DROPPED[:4], locked=())]
        text = "Keep SYN-GEN101 instead of SYN-DRP100, SYN-DRP101, SYN-DRP102 and SYN-DRP103 because they overlap."
        self.assertEqual(fmt.collapse_dropped(text, trace),
                         "Keep SYN-GEN101 instead of 4 dropped (3 shown: SYN-DRP100, SYN-DRP101, SYN-DRP102) "
                         "because they overlap.")

    def test_chosen_code_ends_a_run(self):
        """Codex round 2: two short runs separated by planned sessions are not one long list."""
        trace = [plan_call([GEN101, AI407], DROPPED[:4], locked=())]
        text = "Choose SYN-GEN101 over SYN-DRP100 or SYN-DRP101, and SYN-AI407 over SYN-DRP102 or SYN-DRP103."
        self.assertEqual(fmt.collapse_dropped(text, trace), text)

    def test_other_days_sessions_are_not_dropped(self):
        """Codex round 3: Wednesday's plan lists Tuesday's chosen sessions as "not on Wed"."""
        tue = [{"id": f"t{i}", "code": f"SYN-TUE{100 + i}", "start": "2026-12-01T09:00:00-08:00"} for i in range(6)]
        trace = [plan_call(tue, [{**GEN101, "reason": "not on Tue"}], locked=(), day="Tue"),
                 plan_call([KEY02, AI407], [{**r, "reason": "not on Wed"} for r in tue] + DROPPED[:2])]
        text = "Tuesday:\n" + "\n".join(f"{9 + i}:00 {r['code']} Title" for i, r in enumerate(tue)) + "\nWednesday keeps SYN-KEY02."
        self.assertEqual(fmt.collapse_dropped(text, trace), text)

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

    def test_long_plan_line_is_protected(self):
        """Codex review: a session line with a long title is a plan line, whatever its length."""
        long_line = "12:00-13:00 SYN-GEN101 " + "Retrieval that survives messy PDFs and very long titles " * 4 + "Caesars Forum"
        prose = " ".join(f"Filler sentence number {i} explains a detail at length." for i in range(30))
        out = fmt.cap_words(f"Yes, it works.\n{long_line}\n{prose}", [plan_call([GEN101], locked=())])
        self.assertIn(long_line, out)
        self.assertLessEqual(fmt.count_words(out), fmt.MAX_WORDS)

    def test_transit_lines_without_clock_are_protected(self):
        """Codex round 2: transition lines in minutes survive the cap."""
        transit = ["Venetian to Wynn, 6 min walk, tight", "Wynn to Caesars Forum, 18 minutes by shuttle, fine",
                   "Back to Park MGM, about 32 min by shuttle and walk"]
        prose = " ".join(f"Filler sentence number {i} explains a detail at length." for i in range(30))
        out = fmt.cap_words("Yes, it works.\n" + "\n".join(transit) + "\n" + prose + " Next, reserve.")
        for line in transit:
            self.assertIn(line, out)
        self.assertLessEqual(fmt.count_words(out), fmt.MAX_WORDS)

    def test_prose_naming_a_code_is_not_a_plan_line(self):
        """Codex round 3: a long paragraph that names a planned code is still capped."""
        para = "Yes, SYN-GEN101 fits. " + " ".join(f"It also matters that point {i} is explained here." for i in range(25))
        out = fmt.format_answer(para, [plan_call([GEN101], locked=())])
        self.assertLessEqual(fmt.count_words(out), fmt.MAX_WORDS)
        self.assertTrue(out.startswith("Yes, SYN-GEN101 fits."))

    def test_long_first_sentence_is_shortened_last(self):
        first = "Yes " + "and it also works because of many reasons " * 30 + "today."
        out = fmt.cap_words(first + " Next, reserve.")
        self.assertLessEqual(fmt.count_words(out), fmt.MAX_WORDS)
        self.assertTrue(out.startswith("Yes and it also works"))

    def test_eight_session_plan_stays_intact_over_the_cap(self):
        """Documented limit: plan lines are never cut, so the largest derived plan may exceed 160 words."""
        rows = [{"id": f"p{i}", "code": f"SYN-P{100 + i}"} for i in range(8)]
        lines = []
        for i in range(8):
            lines.append(f"{8 + i}:00-{8 + i}:45 SYN-P{100 + i} A fairly long session title about agents and data, Venetian Level 3")
            if i < 7:
                lines.append(f"{8 + i}:45 to {9 + i}:00 Venetian to Venetian, 5 min walk, fine")
        text = "Yes, all eight fit.\n" + "\n".join(lines) + "\nTravel is an estimate. Next, reserve."
        self.assertGreater(fmt.count_words(text), fmt.MAX_WORDS)
        out = fmt.cap_words(text, [plan_call(rows, locked=())])
        for line in lines:
            self.assertIn(line, out)
        self.assertGreater(fmt.count_words(out), fmt.MAX_WORDS)

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
