"""T11: the briefing runs its fixed steps in code; Nova gets one request with no tools (matrix T11-1…T11-3).

The server calls get_profile and check_itinerary (once per reserved day) through atlas.tools.dispatch, states the
results as facts, and sends one Converse request without a toolConfig. If that request fails with a Bedrock error,
the response carries a briefing written by code and the code model_unavailable. Bedrock is a scripted fake; the
catalog is the synthetic fixture; sign-in is a fake auth object.
"""
import contextlib
import io
import json
import threading
import unittest
from unittest import mock
from urllib.request import Request, urlopen

import web
from atlas import tools
from atlas.agent import Agent
from atlas.prompts import BRIEFING_SYSTEM_PROMPT
from tests.test_agent import FakeBedrock, final, tool_use
from tests.test_errors import ClientError
from tests.test_locked import Base, fixture_backend, fixture_catalog

# Tue: SYN-AI202 and SYN-SEC406 both 09:00-10:00 (overlap); Wed: SYN-KEY02; Thu: SYN-AI208.
RESERVED = ["syn-0002", "syn-0026", "syn-k002", "syn-0008"]
STARTS = {"syn-0002": "2026-12-01T09:00:00-08:00", "syn-0026": "2026-12-01T09:00:00-08:00",
          "syn-k002": "2026-12-02T08:00:00-08:00", "syn-0008": "2026-12-03T10:30:00-08:00"}
SCHEDULE = {"signed_in": True, "favorites": [], "reserved": [{"id": i, "start": STARTS[i]} for i in RESERVED]}
TOOL_NAMES = [s["name"] for s in tools.TOOL_SPECS]


def model_error():
    return ClientError({"Error": {"Code": "ModelErrorException",
                                  "Message": "Model produced invalid sequence as part of ToolUse."}}, "Converse")


class Failing:
    """A Bedrock client whose every call fails like the live first-briefing failure."""

    def __init__(self):
        self.requests = []

    def converse(self, **kw):
        self.requests.append(kw)
        raise model_error()


class BriefingWorkflowTest(Base):
    def setUp(self):
        super().setUp()
        self.saved_agent = web._state["agent"]
        for p in (mock.patch.object(web, "_my_schedule", return_value=SCHEDULE), fixture_catalog(),
                  mock.patch.object(tools, "official_tools", return_value=[])):
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.be = fixture_backend({"reserved": RESERVED, "favorites": [], "personalTime": []})

    def tearDown(self):
        web._state["agent"] = self.saved_agent
        super().tearDown()

    def brief(self, client):
        web._state["agent"] = Agent(client=client, backend=self.be)
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            out = web._briefing()
        return out, log.getvalue()

    # T11-1 ---------------------------------------------------------------------------------------
    def test_one_request_without_tools(self):
        fake = FakeBedrock([final("Tuesday has a conflict: SYN-AI202 overlaps SYN-SEC406. Which hotel are you at?")])
        out, _ = self.brief(fake)
        self.assertEqual(len(fake.requests), 1)
        req = fake.requests[0]
        self.assertNotIn("toolConfig", req)
        self.assertEqual(req["system"], [{"text": BRIEFING_SYSTEM_PROMPT}])
        self.assertEqual(req["inferenceConfig"], {"temperature": 0, "maxTokens": web.BRIEFING_MAX_TOKENS})
        self.assertEqual(web.BRIEFING_MAX_TOKENS, 500)
        self.assertEqual(req["additionalModelRequestFields"], {"inferenceConfig": {"topK": 1}})
        self.assertEqual(len(req["messages"]), 1)
        prompt = req["messages"][0]["content"][0]["text"]
        for text in (prompt, BRIEFING_SYSTEM_PROMPT):  # facts and output shape only: no rule about tools
            for name in TOOL_NAMES:
                self.assertNotIn(name, text)
            self.assertNotIn("call ", text.lower())
        self.assertNotIn("error", out)
        self.assertEqual(out["text"], "Tuesday has a conflict: SYN-AI202 overlaps SYN-SEC406. Which hotel are you at?")
        self.assertEqual(out["rounds"], 0)
        for key in ("text", "trace", "schedule_diff", "catalog_diff", "first_visit", "facts"):
            self.assertIn(key, out)

    def test_earlier_tool_turns_stay_out_of_the_briefing_request(self):
        """Bedrock rejects toolUse/toolResult blocks without a toolConfig: the briefing request carries no history."""
        fake = FakeBedrock([tool_use("get_session", {"session_id": "SYN-GEN205"}, "g"), final("A chalk talk."),
                            final("Welcome back.")])
        web._state["agent"] = Agent(client=fake, backend=self.be)
        web._chat("Tell me about SYN-GEN205.", allow_write=False)
        with contextlib.redirect_stderr(io.StringIO()):
            web._briefing()
        self.assertNotIn("toolConfig", fake.requests[-1])
        self.assertEqual(len(fake.requests[-1]["messages"]), 1)

    # T11-2 ---------------------------------------------------------------------------------------
    def test_check_itinerary_runs_once_per_reserved_day(self):
        fake = FakeBedrock([final("Hello.")])
        out, _ = self.brief(fake)
        self.assertEqual([c["name"] for c in out["trace"]], ["get_profile"] + ["check_itinerary"] * 3)
        self.assertEqual([c["input"] for c in out["trace"][1:]],
                         [{"session_ids": ["syn-0002", "syn-0026"]}, {"session_ids": ["syn-k002"]},
                          {"session_ids": ["syn-0008"]}])
        self.assertTrue(all(c["by"] == "server" and c["ok"] for c in out["trace"]))
        prompt = fake.requests[0]["messages"][0]["content"][0]["text"]
        days = [line for line in out["facts"] if line[:3] in ("Tue", "Wed", "Thu")]
        self.assertEqual([d[:14] for d in days], ["Tue 2026-12-01", "Wed 2026-12-02", "Thu 2026-12-03"])
        self.assertIn("conflict, SYN-AI202 overlaps SYN-SEC406", days[0])
        self.assertTrue(days[1].endswith("no conflicts or tight transitions."), days[1])
        for line in days:  # Nova gets the same results the panel shows
            self.assertIn(line, prompt)

    def test_feasibility_claims_are_kept_because_the_checks_ran(self):
        out, _ = self.brief(FakeBedrock([final("Wednesday and Thursday have no conflicts; fix Tuesday.")]))
        self.assertEqual(out["removed"], [])
        self.assertEqual(out["text"], "Wednesday and Thursday have no conflicts; fix Tuesday.")

    def test_a_reservation_without_a_time_is_stated_once(self):
        """Live smoke: a reservation missing from the catalog has no day, so every day's check reported it."""
        self.be = fixture_backend({"reserved": RESERVED + ["syn-gone"], "favorites": [], "personalTime": []})
        out, _ = self.brief(FakeBedrock([final("Wednesday has no conflicts.")]))
        self.assertEqual(len([c for c in out["trace"] if c["name"] == "check_itinerary"]), 3)
        left = [line for line in out["facts"] if "syn-gone" in line]
        self.assertEqual(left, ["Left out of the travel checks: syn-gone (reserved, but without a time in the loaded catalog)."])
        wed = next(line for line in out["facts"] if line.startswith("Wed"))
        self.assertTrue(wed.endswith("no conflicts or tight transitions among the sessions checked."), wed)
        self.assertEqual(out["removed"], ["Wednesday has no conflicts."])  # the guard still treats it as unverified

    def test_the_request_carries_the_saved_profile_and_the_favorites(self):
        """Codex r1 (P2): with no tools and no history, Nova sees only the prompt, so the facts the server read go in it."""
        from atlas import profile

        profile.update_profile({"hotel": "Park MGM", "max_steps_per_day": 8000, "interests": ["security"], "language": "en"})
        web._my_schedule.return_value = dict(SCHEDULE, favorites=[
            {"id": "syn-0011", "code": "SYN-GEN101", "start": "2026-12-02T12:00:00-08:00",
             "end": "2026-12-02T13:00:00-08:00", "venue": "venetian"}])
        fake = FakeBedrock([final("Hello.")])
        self.brief(fake)
        prompt = fake.requests[0]["messages"][0]["content"][0]["text"]
        self.assertIn("What my profile already says: hotel Park MGM; at most 8000 steps a day; interests security. ", prompt)
        self.assertIn("My official favorites: SYN-GEN101 (Wed 2026-12-02 12:00-13:00, venetian). ", prompt)
        self.assertIn("My profile does not yet say my arrival and departure dates. ", prompt)
        self.assertIn("Answer in en. ", prompt)

    def test_reservations_without_a_time_are_not_reported_as_none(self):
        """Codex r1 (P2): when no reservation has a time, the briefing must not say there are none."""
        web._my_schedule.return_value = dict(SCHEDULE, reserved=[{"id": "syn-gone", "title": "(not in the loaded catalog)"}])
        fake = FakeBedrock([final("Hello.")])
        out, _ = self.brief(fake)
        prompt = fake.requests[0]["messages"][0]["content"][0]["text"]
        self.assertNotIn("I have no reserved sessions", prompt)
        line = "Left out of the travel checks: syn-gone (reserved, but without a time in the loaded catalog)."
        self.assertIn("No travel was checked. " + line, prompt)
        self.assertIn(line, out["facts"])
        self.assertEqual([c["name"] for c in out["trace"]], ["get_profile"])
        out, _ = self.brief(Failing())
        self.assertIn(line, out["text"])

    # T11-3 ---------------------------------------------------------------------------------------
    def test_model_error_returns_the_briefing_written_by_code(self):
        self.brief(FakeBedrock([final("Welcome.")]))  # first visit: records the schedule
        SCHEDULE_NOW = dict(SCHEDULE, reserved=SCHEDULE["reserved"][1:])  # SYN-AI202 no longer reserved
        web._my_schedule.return_value = SCHEDULE_NOW
        failing = Failing()
        out, log = self.brief(failing)
        self.assertEqual(len(failing.requests), 1)  # no retry loop
        self.assertEqual(out["error"], "model_unavailable")
        self.assertEqual(out["message"], web.BRIEFING_FALLBACK_NOTE)
        self.assertEqual(out["facts"][0], "Since your last visit: reserved +0/−1.")
        self.assertEqual([line[:3] for line in out["facts"][1:4]], ["Tue", "Wed", "Thu"])
        self.assertEqual(out["facts"][4], "Your profile does not yet say your hotel: tell me in the chat to plan around it.")
        self.assertEqual(out["text"], "\n".join(out["facts"] + [web.BRIEFING_FALLBACK_NOTE]))
        self.assertEqual(out["schedule_diff"]["reserved"], {"added": [], "removed": ["syn-0002"]})
        self.assertEqual(len([c for c in out["trace"] if c["name"] == "check_itinerary"]), 3)
        self.assertEqual(out["removed"], [])
        self.assertIn("nova-copilot briefing: ClientError (ModelErrorException) -> model_unavailable", log)
        self.assertIn("bedrock-message briefing: Model produced invalid sequence as part of ToolUse.", log)
        self.assertNotIn("invalid sequence", json.dumps(out))

    def test_an_empty_summary_also_falls_back(self):
        out, _ = self.brief(FakeBedrock([final("<thinking>nothing to say</thinking>")]))
        self.assertEqual(out["error"], "model_unavailable")
        self.assertTrue(out["text"].endswith(web.BRIEFING_FALLBACK_NOTE))

    def test_the_http_route_returns_the_facts_when_nova_fails(self):
        web._state["agent"] = Agent(client=Failing(), backend=self.be)
        server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        req = Request(f"http://127.0.0.1:{port}/api/briefing", data=b"{}", method="POST",
                      headers={"Content-Type": "application/json"})
        with contextlib.redirect_stderr(io.StringIO()), urlopen(req, timeout=10) as r:
            status, body = r.status, json.loads(r.read())
        self.assertEqual(status, 200)
        self.assertEqual(body["error"], "model_unavailable")
        self.assertIn("Tue 2026-12-01", body["text"])
        self.assertEqual(len(body["facts"]), 4)  # first visit: no since-last-visit line; 3 days and the question

    # Conversation context ------------------------------------------------------------------------
    def test_a_follow_up_chat_turn_sees_the_briefing_and_is_forced(self):
        fake = FakeBedrock([final("Tuesday has a conflict: SYN-AI202 overlaps SYN-SEC406."),
                            tool_use("get_session", {"session_id": "SYN-AI202"}, "g"), final("Drop SYN-SEC406.")])
        out, _ = self.brief(fake)
        web._chat("Which one should I drop?", allow_write=False)
        chat = fake.requests[1]
        self.assertEqual(chat["toolConfig"]["toolChoice"], {"any": {}})
        msgs = chat["messages"]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "user"])
        self.assertEqual(msgs[0]["content"], fake.requests[0]["messages"][0]["content"])
        self.assertEqual(msgs[1]["content"], [{"text": out["text"]}])
        self.assertEqual(msgs[2]["content"][0]["text"], "Which one should I drop?")

    def test_after_a_model_error_the_chat_sees_the_briefing_written_by_code(self):
        fake = FakeBedrock([tool_use("get_profile", {}, "p"), final("Your hotel is not saved.")])
        web._state["agent"] = Agent(client=Failing(), backend=self.be)
        with contextlib.redirect_stderr(io.StringIO()):
            out = web._briefing()
        web._state["agent"].client = fake
        web._chat("What should I fix first?", allow_write=False)
        self.assertEqual(fake.requests[0]["messages"][1]["content"], [{"text": out["text"]}])
        self.assertEqual(fake.requests[0]["toolConfig"]["toolChoice"], {"any": {}})


if __name__ == "__main__":
    unittest.main()
