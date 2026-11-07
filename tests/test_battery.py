"""Scenario battery for panel-sized answers (M0 T4), offline.

Each case runs the real Agent loop over a scripted (mocked) Bedrock client: the script issues tool
calls that run against the synthetic fixture catalog through the real tool dispatcher, then returns
a final text written the way Nova Pro answered in live runs (Markdown, long dropped lists, claims of
added sessions). The answer then goes through the real web.py `_chat` / `_briefing` or chat.py path,
and the battery checks what reaches the attendee: no Markdown symbols, yes/no answered in the first
sentence, the honest "no additional session fits" line when the planner added nothing beyond the
reservations, and <= 160 words (length is the prompt's job, so the scripted texts follow the prompt's
limit and the check catches a post-processing regression that inflates them).

Sign-in is a fake auth object; the attendee's reservations are SYN-KEY02 (Wed 08:00-10:00, Venetian),
SYN-AI407 (Wed 10:30-11:30, Wynn) and SYN-GEN309 (Wed 15:00-16:00, Caesars Forum).
"""
import contextlib
import io
import re
import unittest
from unittest import mock

import chat
import web
from atlas import tools
from atlas.agent import Agent
from atlas.prompts import SYSTEM_PROMPT
from tests.test_agent import FakeBedrock, final, tool_use
from tests.test_locked import RESERVED, Base, fixture_backend

# Wednesday candidates that all overlap a reservation or cannot reach the next one in time.
WED_NONE_FIT = ["syn-0003", "syn-0027", "syn-0051", "syn-0031", "syn-0055", "syn-0043", "syn-0039"]
WED_ALL = ["syn-0003", "syn-0027", "syn-0051", "syn-0031", "syn-0055", "syn-0043", "syn-0039", "syn-0011",
           "syn-0015", "syn-0035", "syn-0023", "syn-0047"]
MARKDOWN = re.compile(r"\*\*|`|^\s*#|^\s*[*\-•]\s", re.M)
NO_WED = "No additional session fits around your reservations on Wednesday."


MAX_WORDS = 160  # the prompt's limit ("Keep every answer under 160 words")
_CJK = "\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff"
_WORD = re.compile(f"[{_CJK}]|[^\\s{_CJK}]*[A-Za-z0-9][^\\s{_CJK}]*")


def count_words(text):
    """Latin words plus CJK characters (each counts as one word)."""
    return len(_WORD.findall(text))


def first_sentence(text):
    return re.split(r"(?<=[.!?。！？])\s", text.split("\n")[0], maxsplit=1)[0].strip()


class Battery(Base):
    def setUp(self):
        super().setUp()
        self.saved_agent = web._state["agent"]
        mock.patch.object(tools, "official_tools", return_value=[]).start()
        self.addCleanup(mock.patch.stopall)
        self.be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []})

    def tearDown(self):
        web._state["agent"] = self.saved_agent
        super().tearDown()

    def chat(self, question, script):
        self.fake = FakeBedrock(script)
        web._state["agent"] = Agent(client=self.fake, backend=self.be)
        return web._chat(question, allow_write=False)

    def assertPanel(self, text):
        self.assertTrue(text)
        self.assertLessEqual(count_words(text), MAX_WORDS, text)
        self.assertIsNone(MARKDOWN.search(text), text)

    def plan_result(self, out):
        return next(c for c in out["trace"] if c["name"] == "plan_itinerary" and c["ok"])

    # 1 ------------------------------------------------------------------------------------------
    def test_wednesday_nothing_fits(self):
        """Live finding: the planner kept only the reservations, the answer claimed added sessions."""
        q = "Plan my Wednesday around my reservations and add security or architecture sessions."
        out = self.chat(q, [
            tool_use("get_profile", {}, "p"),
            tool_use("plan_itinerary", {"candidate_ids": WED_NONE_FIT, "day": "Wed"}, "a"),
            final("**Your Wednesday is feasible with the added sessions.**\n"
                  "## Plan\n"
                  "- 08:00-10:00 SYN-KEY02 Synthetic keynote: data and AI together, Venetian\n"
                  "- 10:30-11:30 SYN-AI407 Running agents on serverless, Wynn\n"
                  "- 15:00-16:00 SYN-GEN309 AI pair programming for legacy codebases, Caesars Forum\n"
                  "Dropped: SYN-AI303, SYN-SEC107, SYN-ARC301, SYN-SVS201, SYN-ARC405, SYN-DAT203 and SYN-SVS409 "
                  "because they overlap your reservations or leave too little travel time. "
                  "Travel times are estimates. Next, look for a security workshop on Thursday."),
        ])
        text = out["text"]
        self.assertPanel(text)
        plan = out["plan"]["plan"]
        self.assertEqual({c["code"] for c in plan["chosen"]}, {"SYN-KEY02", "SYN-AI407", "SYN-GEN309"})
        self.assertTrue(text.endswith("\n" + NO_WED), text)  # appended; the model's own words are kept
        self.assertTrue(text.startswith("Your Wednesday is feasible with the added sessions."), text)
        self.assertIn(f"Dropped: {len(plan['dropped'])} dropped (3 shown: SYN-AI303, SYN-SEC107, SYN-ARC301) because", text)
        for line in ("08:00-10:00 SYN-KEY02", "10:30-11:30 SYN-AI407", "15:00-16:00 SYN-GEN309"):
            self.assertIn(line, text)
        self.assertNotIn("max_sessions", self.plan_result(out)["input"])
        self.assertIn("free_windows", out["plan"])

    # 2 ------------------------------------------------------------------------------------------
    def test_tuesday_profile_plan(self):
        """Attendee states profile facts and asks for a Tuesday plan; the answer runs long."""
        q = "I'm a developer staying at Park MGM, into generative AI. Plan my Tuesday."
        prose = ("These sessions match your interest in generative AI and keep you inside one venue for most of the day, "
                 "which matters because the walk from Park MGM to the north end of the Strip is long and the rideshare "
                 "lines at the Wynn can get slow around lunch. ")
        out = self.chat(q, [
            tool_use("update_profile", {"updates": {"role": "developer", "hotel": "Park MGM",
                                                    "interests": ["Generative AI"]}}, "u"),
            tool_use("search_sessions", {"query": "Generative AI", "day": "Tue"}, "s"),
            tool_use("plan_itinerary", {"candidate_ids": ["syn-k001", "syn-0002", "syn-0006", "syn-0010", "syn-0014",
                                                          "syn-0018", "syn-0050"], "day": "Tue"}, "a"),
            final("I added three sessions to your Tuesday, all at the Wynn.\n"
                  "Leave Park MGM by 08:12 (rideshare, about 33 min, estimate)\n"
                  "09:00-10:00 SYN-DAT210 Synthetic data for testing and training, Wynn\n"
                  "10:00 to 10:30 Wynn to Wynn, 6 min, fine\n"
                  "10:30-11:30 SYN-AI306 Guardrails for agents that can take actions, Wynn\n"
                  "11:30 to 13:30 Wynn to Wynn, 6 min, fine\n"
                  "13:30-14:30 SYN-GEN104 Fine-tune or prompt? A decision framework, Wynn\n"
                  "Back to Park MGM about 32 min by shuttle and walk (estimate)\n"
                  + prose
                  + "4 sessions were dropped, mostly for overlaps. Next, save these three as favorites."),
        ])
        text = out["text"]
        self.assertPanel(text)
        self.assertTrue(first_sentence(text).startswith("I added three sessions"), text)
        self.assertNotIn("No additional session", text)  # the planner did add sessions
        for line in ("Leave Park MGM by 08:12", "09:00-10:00 SYN-DAT210", "10:30-11:30 SYN-AI306",
                     "13:30-14:30 SYN-GEN104", "10:00 to 10:30 Wynn to Wynn", "Back to Park MGM"):
            self.assertIn(line, text)
        self.assertTrue(text.endswith("Next, save these three as favorites."), text)
        self.assertEqual(out["plan"]["free_windows"][0]["minutes"], 540)

    # 3 ------------------------------------------------------------------------------------------
    def test_yes_no_feasibility(self):
        q = "Can I make both SYN-AI407 and SYN-GEN101 on Wednesday?"
        out = self.chat(q, [
            tool_use("check_itinerary", {"session_ids": ["syn-0007", "syn-0011"]}, "c"),
            final("**Yes** - you can make both SYN-AI407 and SYN-GEN101 on Wednesday; the check found no conflicts.\n"
                  "* 10:30-11:30 SYN-AI407, Wynn\n* 12:00-13:00 SYN-GEN101, Caesars Forum\n"
                  "Your reservations SYN-KEY02 and SYN-GEN309 were kept. Travel is an estimate. "
                  "Next, leave the Wynn right at 11:30."),
        ])
        text = out["text"]
        self.assertPanel(text)
        self.assertRegex(first_sentence(text), r"^Yes\b")
        self.assertTrue(out["trace"][0]["ok"])

    # 8 ------------------------------------------------------------------------------------------
    def test_yes_no_infeasible_cli(self):
        """chat.py applies the same post-processing."""
        q = "Is SYN-SVS409 then SYN-GEN309 on Wednesday feasible?"
        self.fake = FakeBedrock([
            tool_use("check_itinerary", {"session_ids": ["syn-0039", "syn-0019"]}, "c"),
            final("`No`, not as planned: SYN-SVS409 ends at 14:30 at MGM Grand and SYN-GEN309 starts at 15:00 "
                  "at Caesars Forum, which the check marks as not enough time. Next, pick one of them."),
        ])
        agent = Agent(client=self.fake, backend=self.be)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            chat.run_one(agent, q, trace=False)
        text = buf.getvalue().strip()
        self.assertPanel(text)
        self.assertRegex(first_sentence(text), r"^No\b")

    # 4 ------------------------------------------------------------------------------------------
    def test_route_question(self):
        q = "How long from the Venetian to Mandalay Bay on Tuesday at 10:00?"
        out = self.chat(q, [
            tool_use("route_between", {"from_venue": "venetian", "to_venue": "mandalay_bay",
                                       "depart_at": "Tue 10:00"}, "r"),
            final("### Route\nAbout **30 minutes** by the `badge shuttle` plus a short walk, an estimate from the "
                  "venue graph, not official wayfinding. Indoor directions and live shuttle times are in the AWS "
                  "Events app. Tip: Mandalay Bay is at the far south end, so give yourself a margin."),
        ])
        text = out["text"]
        self.assertPanel(text)
        self.assertTrue(first_sentence(text).startswith("Route"), text)
        self.assertIn("About 30 minutes by the badge shuttle", text)

    # 5 ------------------------------------------------------------------------------------------
    def test_briefing(self):
        schedule = {"signed_in": True, "reserved": [
            {"id": "syn-k002", "code": "SYN-KEY02", "start": "2026-12-02T08:00:00-08:00"},
            {"id": "syn-0007", "code": "SYN-AI407", "start": "2026-12-02T10:30:00-08:00"},
            {"id": "syn-0019", "code": "SYN-GEN309", "start": "2026-12-02T15:00:00-08:00"}], "favorites": []}
        mock.patch.object(web, "_my_schedule", return_value=schedule).start()
        long_tail = "Remember that walking between the Venetian and the Wynn takes longer than the map suggests. " * 2
        self.fake = FakeBedrock([
            tool_use("get_profile", {}, "p"),
            tool_use("check_itinerary", {"session_ids": RESERVED}, "c"),
            final("## Welcome back\n**Wednesday has no conflicts** and one tight transition at 10:00 to 10:30.\n"
                  + long_tail + "Your profile has no hotel yet: which hotel are you staying at?"),
        ])
        web._state["agent"] = Agent(client=self.fake, backend=self.be)
        out = web._briefing()
        text = out["text"]
        self.assertPanel(text)
        self.assertIn("check_itinerary", [c["name"] for c in out["trace"]])
        self.assertTrue(text.startswith("Welcome back\nWednesday has no conflicts"), text)
        self.assertTrue(text.endswith("which hotel are you staying at?"), text)

    # 6 ------------------------------------------------------------------------------------------
    def test_dropped_list_dump(self):
        """The answer listed every dropped session in one sentence."""
        q = "Fill my Wednesday with as many sessions as fit."
        result, ok = tools.dispatch("plan_itinerary", {"candidate_ids": WED_ALL, "day": "Wed"}, self.be)
        self.assertTrue(ok, result)
        plan = result["plan"]  # the deterministic result the scripted call below gets too
        chosen = [c["code"] for c in plan["chosen"]]
        dropped = [d["code"] for d in plan["dropped"]]
        self.assertGreater(len(set(chosen) - {"SYN-KEY02", "SYN-AI407", "SYN-GEN309"}), 0)
        self.assertGreater(len(dropped), 3)
        raw = ("Your Wednesday now has extra sessions added between your reservations.\n"
               + "\n".join(f"{c['start'][11:16]}-{c['end'][11:16]} {c['code']} {c['title']}" for c in plan["chosen"])
               + "\nThe planner dropped " + ", ".join(dropped) + " because they overlap a reservation or a chosen session."
               + "\nNext, reserve seats for the added sessions.")
        out = self.chat(q, [tool_use("plan_itinerary", {"candidate_ids": WED_ALL, "day": "Wed"}, "a"), final(raw)])
        text = out["text"]
        self.assertPanel(text)
        self.assertIn(f"The planner dropped {len(dropped)} dropped (3 shown: {', '.join(dropped[:3])}) because", text)
        for code in dropped[3:]:
            self.assertNotIn(code, text)
        for code in chosen:
            self.assertIn(code, text)
        self.assertTrue(first_sentence(text).startswith("Your Wednesday now has extra sessions added"), text)

    # 7 ------------------------------------------------------------------------------------------
    def test_chinese_answer_nothing_fits(self):
        """Profile language zh-Hant: the honest sentence and the dropped summary follow the answer's language."""
        q = "週三除了我的預約，還能排什麼保安相關的場次？"
        out = self.chat(q, [
            tool_use("update_profile", {"updates": {"language": "zh-Hant"}}, "u"),
            tool_use("plan_itinerary", {"candidate_ids": WED_NONE_FIT, "day": "Wed"}, "a"),
            final("**好消息：已為你新增兩場保安場次。**\n"
                  "08:00-10:00 SYN-KEY02 Synthetic keynote: data and AI together，Venetian\n"
                  "10:30-11:30 SYN-AI407 Running agents on serverless，Wynn\n"
                  "15:00-16:00 SYN-GEN309 AI pair programming for legacy codebases，Caesars Forum\n"
                  "未排入：SYN-AI303、SYN-SEC107、SYN-ARC301、SYN-SVS201、SYN-ARC405、SYN-DAT203、SYN-SVS409，"
                  "因為與預約重疊或交通時間不足。下一步：看看週四的保安工作坊。"),
        ])
        text = out["text"]
        self.assertPanel(text)
        n = len(out["plan"]["plan"]["dropped"])
        self.assertTrue(text.endswith("\n週三除了你的預約，沒有其他場次排得進去。"), text)
        self.assertIn(f"未排入：另有 {n} 場未排入（列出 3 場：SYN-AI303、SYN-SEC107、SYN-ARC301），因為", text)
        self.assertIn("Running agents on serverless", text)  # titles stay in the original

    # prompt -------------------------------------------------------------------------------------
    def test_prompt_carries_the_panel_rules(self):
        """The system prompt sent to Bedrock carries the T4 rules and the language rule."""
        self.chat("Hi", [final("Hi! Ask me about sessions, routes or your day.")])
        system = self.fake.requests[0]["system"][0]["text"]
        self.assertEqual(system, SYSTEM_PROMPT)
        for rule in ("under 160 words", "FIRST sentence starts with the answer", "No additional session fits",
                     "NEVER say sessions were added unless", "3 shown", "one line per session",
                     "Put each transition on its own line", "language field", "unofficial translation"):
            self.assertIn(rule, system)
        # A prompt rule about omitting max_sessions made Nova Pro emit an invalid tool-use sequence in
        # every signed-in briefing; the tool spec carries that guidance instead.
        self.assertNotIn("max_sessions", system)


if __name__ == "__main__":
    unittest.main()
