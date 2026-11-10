"""T9c: conference weekday words resolve to dates in code, tool results name the weekday, and an
answer whose plan is on another day than the one the attendee named says so (append only)."""
import unittest
from unittest import mock

from atlas import format as answer_format, tools
from atlas.agent import Agent
from tests.test_agent import FakeBedrock, final
from tests.test_locked import RESERVED, Base, fixture_backend

TUE = "Tuesday = 2026-12-01 (Las Vegas)"


class DayFactsTest(unittest.TestCase):
    def test_each_language_form(self):
        for text in ("Plan my Tuesday", "plan my tuesday", "Tue please", "TUES morning", "幫我排週二的議程", "周二",
                     "星期二有什麼", "禮拜二", "幫我排Tuesday的議程", "Tuesday's keynotes"):
            with self.subTest(text=text):
                self.assertEqual(tools.day_facts(text), TUE)
        cases = {"Monday": "Monday = 2026-11-30", "Mon": "Monday = 2026-11-30", "Wed": "Wednesday = 2026-12-02",
                 "Wednesday": "Wednesday = 2026-12-02", "Thu": "Thursday = 2026-12-03", "Thurs": "Thursday = 2026-12-03",
                 "Thursday": "Thursday = 2026-12-03", "Fri": "Friday = 2026-12-04", "Friday": "Friday = 2026-12-04",
                 "週一": "Monday = 2026-11-30", "星期三": "Wednesday = 2026-12-02", "禮拜四": "Thursday = 2026-12-03",
                 "週五": "Friday = 2026-12-04"}
        for text, fact in cases.items():
            with self.subTest(text=text):
                self.assertEqual(tools.day_facts(text), fact + " (Las Vegas)")

    def test_several_days_in_order_once_each(self):
        self.assertEqual(tools.day_facts("Wednesday or Tue? I mean Wed."),
                         "Wednesday = 2026-12-02; Tuesday = 2026-12-01 (Las Vegas)")

    def test_no_weekday_no_fact(self):
        for text in ("Plan my day", "Find GenAI sessions", "monitoring and frisbee", "Saturday flight", "週六", "",
                     "Thumbs up, thanks", "Wedding", "wednesdays_only"):
            with self.subTest(text=text):
                self.assertEqual(tools.day_facts(text), "")

    def test_agent_adds_the_fact_block_only_when_a_weekday_is_named(self):
        fake = FakeBedrock([final("ok"), final("ok")])
        agent = Agent(client=fake, backend=fixture_backend({"reserved": [], "favorites": [], "personalTime": []}))
        with mock.patch("atlas.agent.append_usage"):
            agent.ask("Plan my Tuesday")
            agent.ask("And what about lunch?")
        self.assertEqual(fake.requests[0]["messages"][-1]["content"], [{"text": "Plan my Tuesday"}, {"text": TUE}])
        self.assertEqual(fake.requests[1]["messages"][-1]["content"], [{"text": "And what about lunch?"}])
        self.assertEqual(fake.requests[1]["messages"][0]["content"][1], {"text": TUE})  # kept in history


class ToolWeekdayTest(Base):
    def setUp(self):
        super().setUp()
        mock.patch.object(tools, "official_tools", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)
        self.be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []})

    def run_tool(self, name, args):
        result, ok = tools.dispatch(name, args, self.be)
        self.assertTrue(ok, result)
        return result

    def test_search_names_the_filtered_day(self):
        for day in ("Tue", "2026-12-01"):
            r = self.run_tool("search_sessions", {"query": "AI", "day": day})
            self.assertEqual((r["day"], r["weekday"]), ("2026-12-01", "Tue"))

    def test_search_without_day_lists_the_days_found(self):
        r = self.run_tool("search_sessions", {"query": "AI", "limit": 30})
        self.assertTrue(r["days"])
        for row in r["days"]:
            self.assertEqual(tools.weekday_of(row["day"]), row["weekday"])

    def test_plan_names_the_planned_day(self):
        r = self.run_tool("plan_itinerary", {"query": "AI", "day": "Wed"})
        self.assertEqual((r["day"], r["weekday"]), ("2026-12-02", "Wed"))
        r = self.run_tool("plan_itinerary", {"candidate_ids": ["syn-k001", "syn-0002"], "day": "2026-12-01"})
        self.assertEqual((r["day"], r["weekday"]), ("2026-12-01", "Tue"))

    def test_check_names_the_day(self):
        r = self.run_tool("check_itinerary", {"session_ids": ["syn-k001"]})
        self.assertIn(r["weekday"], tools.WEEKDAY_ABBR)
        self.assertEqual(tools.weekday_of(r["day"]), r["weekday"])


class MismatchTest(unittest.TestCase):
    def plan(self, day):
        return {"name": "plan_itinerary", "ok": True, "input": {"day": day},
                "result": {"day": day, "weekday": tools.weekday_of(day), "plan": {"day": day, "chosen": []}}}

    def test_only_with_exactly_one_named_day(self):
        trace = [self.plan("2026-12-02")]
        f = answer_format.add_day_mismatch
        self.assertIn("you asked for Tuesday 2026-12-01", f("Plan.", trace, "Plan my Tuesday"))
        self.assertEqual(f("Plan.", trace, "Plan my Tuesday or Wednesday"), "Plan.")
        self.assertEqual(f("Plan.", trace, "Plan my day"), "Plan.")
        self.assertEqual(f("Plan.", trace, "Plan my Wednesday"), "Plan.")
        self.assertEqual(f("Plan.", [], "Plan my Tuesday"), "Plan.")

    def test_idempotent_and_append_only(self):
        once = answer_format.format_answer("Here's your Tuesday.", [self.plan("2026-12-02")], "Plan my Tuesday")
        self.assertTrue(once.startswith("Here's your Tuesday."))
        self.assertEqual(answer_format.format_answer(once, [self.plan("2026-12-02")], "Plan my Tuesday"), once)

    def test_failed_plan_does_not_count(self):
        bad = {**self.plan("2026-12-02"), "ok": False}
        self.assertEqual(answer_format.add_day_mismatch("Plan.", [bad], "Plan my Tuesday"), "Plan.")


if __name__ == "__main__":
    unittest.main()
