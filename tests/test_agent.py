"""Offline tests for the tool dispatcher, the Nova tool-use loop and the write confirmation gate.

Bedrock is replaced by a scripted fake client; catalog/routing/planner by a stub Backend.
"""
import asyncio
import json
import unittest

from atlas import tools
from atlas.agent import Agent
from atlas.prompts import SYSTEM_PROMPT

S1 = {"id": "s-1", "code": "AIM301", "title": "Agents on Bedrock", "type": "Workshop", "level": "300",
      "start": "2026-12-01T10:00:00-08:00", "end": "2026-12-01T12:00:00-08:00", "venue": "venetian",
      "room": "Level 3", "abstract": "x" * 500}
S2 = {"id": "s-2", "code": "SVS210", "title": "Serverless patterns", "type": "Breakout", "level": "200",
      "start": "2026-12-01T13:00:00-08:00", "end": "2026-12-01T14:00:00-08:00", "venue": "mandalay_bay", "room": "Ballroom"}
CATALOG = {s["id"]: s for s in (S1, S2)} | {s["code"]: s for s in (S1, S2)}


def stub_backend(calls):
    def rec(name, ret):
        def f(*a, **kw):
            calls.append((name, a, kw))
            return ret(*a, **kw) if callable(ret) else ret
        return f
    return tools.Backend(
        search_sessions=rec("search_sessions", [S1, S2]),
        get_session=rec("get_session", lambda sid: CATALOG.get(sid)),
        get_schedule=rec("get_schedule", {"favorites": []}),
        add_favorites=rec("add_favorites", lambda ids: {"added": ids}),
        route=rec("route", {"from_venue": "venetian", "to_venue": "mandalay_bay", "minutes": 25, "steps": 1200, "legs": [], "estimate": True}),
        check_itinerary=rec("check_itinerary", {"conflicts": [], "transitions": []}),
        plan_itinerary=rec("plan_itinerary", lambda c, **kw: {"sessions": [s["id"] for s in c], "dropped": []}),
    )


class FakeBedrock:
    """Returns scripted Converse responses and records each request."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def converse(self, **kw):
        self.requests.append(json.loads(json.dumps(kw)))
        return self.script.pop(0)


def tool_use(name, inp, tid="t1"):
    return {"output": {"message": {"role": "assistant", "content": [
        {"text": "<thinking>need data</thinking>"}, {"toolUse": {"toolUseId": tid, "name": name, "input": inp}}]}},
        "stopReason": "tool_use"}


def final(text):
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": "end_turn"}


class DispatcherTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.be = stub_backend(self.calls)

    def test_specs_are_valid_converse_tools(self):
        cfg = tools.bedrock_tool_config()
        names = [t["toolSpec"]["name"] for t in cfg["tools"]]
        self.assertEqual(names, ["search_sessions", "get_session", "route_between", "check_itinerary",
                                 "plan_itinerary", "get_my_schedule", "add_favorites"])
        for t in cfg["tools"]:
            self.assertEqual(t["toolSpec"]["inputSchema"]["json"]["type"], "object")

    def test_search_trims_and_passes_filters(self):
        out, ok = tools.dispatch("search_sessions", {"query": "agents", "day": "Tue", "types": []}, self.be)
        self.assertTrue(ok)
        self.assertEqual(out["count"], 2)
        self.assertLessEqual(len(out["sessions"][0]["abstract"]), 163)
        self.assertEqual(self.calls[0][2], {"query": "agents", "day": "Tue", "limit": 10})

    def test_get_session_missing_is_error_not_exception(self):
        out, ok = tools.dispatch("get_session", {"session_id": "NOPE"}, self.be)
        self.assertFalse(ok)
        self.assertIn("NOPE", out["error"])

    def test_missing_required_arg_and_unknown_tool(self):
        self.assertFalse(tools.dispatch("route_between", {"from_venue": "wynn"}, self.be)[1])
        self.assertFalse(tools.dispatch("teleport", {}, self.be)[1])

    def test_check_itinerary_resolves_codes_and_sorts(self):
        out, ok = tools.dispatch("check_itinerary", {"session_ids": ["SVS210", "AIM301", "ZZZ"]}, self.be)
        self.assertTrue(ok)
        sessions_arg = [c for c in self.calls if c[0] == "check_itinerary"][0][1][0]
        self.assertEqual([s["code"] for s in sessions_arg], ["AIM301", "SVS210"])
        self.assertEqual(out["not_found"], ["ZZZ"])

    def test_plan_itinerary_merges_must_and_query(self):
        out, ok = tools.dispatch("plan_itinerary", {"query": "serverless", "must": ["AIM301"], "day": "Tue"}, self.be)
        self.assertTrue(ok)
        _, args, kw = [c for c in self.calls if c[0] == "plan_itinerary"][0]
        self.assertEqual(kw["must"], ["s-1"])
        self.assertEqual({s["id"] for s in args[0]}, {"s-1", "s-2"})

    def test_backend_exception_becomes_error(self):
        def boom():
            raise RuntimeError("not signed in")
        self.be.get_schedule = boom
        out, ok = tools.dispatch("get_my_schedule", {}, self.be)
        self.assertFalse(ok)
        self.assertIn("not signed in", out["error"])


class AgentLoopTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.be = stub_backend(self.calls)

    def test_tool_use_then_final_text(self):
        fake = FakeBedrock([tool_use("search_sessions", {"query": "agents"}), final("<thinking>ok</thinking>Go to AIM301.")])
        res = Agent(client=fake, backend=self.be).ask("agent workshops?")
        self.assertEqual(res.text, "Go to AIM301.")
        self.assertEqual([c.name for c in res.trace], ["search_sessions"])
        self.assertEqual(res.rounds, 1)
        req = fake.requests[0]
        self.assertEqual(req["modelId"], "us.amazon.nova-pro-v1:0")
        self.assertEqual(req["inferenceConfig"]["temperature"], 0.3)
        self.assertEqual(req["system"][0]["text"], SYSTEM_PROMPT)
        tr = fake.requests[1]["messages"][-1]["content"][0]["toolResult"]
        self.assertEqual(tr["toolUseId"], "t1")
        self.assertEqual(tr["status"], "success")
        self.assertIn("AIM301", tr["content"][0]["text"])

    def test_write_tool_declined_does_not_call_backend(self):
        asked = []
        fake = FakeBedrock([tool_use("add_favorites", {"session_ids": ["s-1"]}), final("Nothing was saved.")])
        res = Agent(client=fake, backend=self.be, confirm=lambda n, a: asked.append((n, a)) or False).ask("save it")
        self.assertEqual(asked, [("add_favorites", {"session_ids": ["s-1"]})])
        self.assertFalse(any(c[0] == "add_favorites" for c in self.calls))
        self.assertIs(res.trace[0].confirmed, False)
        self.assertEqual(fake.requests[1]["messages"][-1]["content"][0]["toolResult"]["status"], "error")

    def test_write_tool_without_confirm_callback_is_denied(self):
        fake = FakeBedrock([tool_use("add_favorites", {"session_ids": ["s-1"]}), final("Not saved.")])
        Agent(client=fake, backend=self.be).ask("save it")
        self.assertFalse(any(c[0] == "add_favorites" for c in self.calls))

    def test_write_tool_confirmed_runs(self):
        fake = FakeBedrock([tool_use("add_favorites", {"session_ids": ["s-1"]}), final("Saved AIM301.")])
        res = Agent(client=fake, backend=self.be, confirm=lambda n, a: True).ask("save it")
        self.assertTrue(any(c[0] == "add_favorites" for c in self.calls))
        self.assertIs(res.trace[0].confirmed, True)
        self.assertEqual(res.trace[0].result, {"result": {"added": ["s-1"]}})

    def test_round_limit(self):
        script = [tool_use("search_sessions", {"query": str(i)}, f"t{i}") for i in range(4)] + [final("Best effort.")]
        fake = FakeBedrock(script)
        res = Agent(client=fake, backend=self.be, max_rounds=3).ask("loop")
        self.assertEqual(res.text, "Best effort.")
        self.assertEqual(len(res.trace), 3)
        last = fake.requests[-1]["messages"][-1]["content"][0]["toolResult"]
        self.assertEqual(last["status"], "error")

    def test_truncated_tool_use_is_not_run_or_kept(self):
        cut = tool_use("add_favorites", {"session_ids": ["s-1"]})
        cut["stopReason"] = "max_tokens"
        fake = FakeBedrock([cut, final("ok")])
        agent = Agent(client=fake, backend=self.be, confirm=lambda n, a: True)
        res = agent.ask("save it")
        self.assertEqual(res.trace, [])
        self.assertFalse(any(c[0] == "add_favorites" for c in self.calls))
        agent.ask("again")
        for m in fake.requests[1]["messages"]:
            self.assertFalse(any("toolUse" in b for b in m["content"]))

    def test_history_carries_to_follow_up(self):
        fake = FakeBedrock([final("Hi."), final("Again.")])
        agent = Agent(client=fake, backend=self.be)
        agent.ask("one")
        agent.ask("two")
        self.assertEqual(len(fake.requests[1]["messages"]), 3)


class McpServerTest(unittest.TestCase):
    def test_lists_same_tools_and_gates_write(self):
        from atlas import mcp_server
        listed = asyncio.run(mcp_server.mcp.list_tools())
        self.assertEqual({t.name for t in listed}, {s["name"] for s in tools.TOOL_SPECS})
        with self.assertRaises(ValueError):
            mcp_server.add_favorites(["s-1"])
        res = asyncio.run(mcp_server.mcp._mcp_server.request_handlers[__import__("mcp").types.CallToolRequest](
            __import__("mcp").types.CallToolRequest(method="tools/call", params={"name": "add_favorites", "arguments": {"session_ids": ["s-1"]}})))
        self.assertTrue(res.root.isError)


if __name__ == "__main__":
    unittest.main()
