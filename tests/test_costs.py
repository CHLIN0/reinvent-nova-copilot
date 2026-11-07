"""Offline accounting tests: scripted Converse only, never a Bedrock client."""
import importlib
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atlas import costs, pricing
from atlas.agent import Agent


def response(*, tool=False, usage=True):
    content = ([{"toolUse": {"toolUseId": "t1", "name": "search_sessions", "input": {"query": "x"}}}]
               if tool else [{"text": "Private response text"}])
    out = {"output": {"message": {"role": "assistant", "content": content}},
           "stopReason": "tool_use" if tool else "end_turn"}
    if usage:
        out["usage"] = {"inputTokens": 1000, "outputTokens": 250, "totalTokens": 1250}
    return out


class CostTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ledger = self.root / "local-private" / "costs.jsonl"
        patch = mock.patch.object(costs, "LEDGER_PATH", self.ledger)
        patch.start()
        self.addCleanup(patch.stop)
        # Even an accidental attempt to construct a live client fails offline.
        patch = mock.patch("atlas.agent.make_client", side_effect=AssertionError("Live client forbidden"))
        patch.start()
        self.addCleanup(patch.stop)

    def rows(self):
        return [json.loads(line) for line in self.ledger.read_text().splitlines()]

    def test_response_appends_only_metadata_and_repairs_permissions(self):
        fake = mock.Mock()
        fake.converse.return_value = response()
        agent = Agent(client=fake, model_id="us.amazon.nova-pro-v1:0")
        agent.ask("Private prompt text")
        row = self.rows()[0]
        self.assertEqual(set(row), {"ts", "model", "feature", "input_tokens", "output_tokens",
                                    "total_tokens", "usd", "rounds"})
        self.assertEqual(row["model"], "us.amazon.nova-pro-v1:0")
        self.assertEqual(row["feature"], "chat")
        self.assertEqual((row["input_tokens"], row["output_tokens"], row["total_tokens"]), (1000, 250, 1250))
        self.assertAlmostEqual(row["usd"], 0.0016)
        self.assertEqual(row["rounds"], 0)
        self.assertTrue(row["ts"].endswith("+00:00"))
        self.assertNotIn("Private", self.ledger.read_text())
        self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode), 0o600)
        self.ledger.chmod(0o644)
        agent.ask("Another private prompt")
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(stat.S_IMODE(self.ledger.stat().st_mode), 0o600)

    def test_tool_rounds_budget_final_and_followup_all_recorded(self):
        fake = mock.Mock()
        fake.converse.side_effect = [response(tool=True), response(tool=True), response(), response()]
        agent = Agent(client=fake, model_id="us.amazon.nova-pro-v1:0", feature="briefing", max_rounds=1)
        with mock.patch("atlas.agent.dispatch", return_value=({"sessions": []}, True)):
            agent.ask("Plan")
            agent.ask("Followup")
        self.assertEqual([r["rounds"] for r in self.rows()], [0, 1, 1, 0])
        self.assertEqual([r["feature"] for r in self.rows()], ["briefing"] * 4)
        self.assertEqual(fake.converse.call_count, 4)

    def test_validation_retry_records_only_successful_response(self):
        fake = mock.Mock()
        fake.converse.side_effect = [ValueError("Validation rejected official specs"), response()]
        config = {"tools": [{"toolSpec": {"name": "aws_events__list_sessions"}}]}
        with mock.patch("atlas.agent.bedrock_tool_config", return_value=config), \
             mock.patch("atlas.tools.disable_official_tools") as disable:
            Agent(client=fake, model_id="us.amazon.nova-pro-v1:0").ask("Question")
        disable.assert_called_once()
        self.assertEqual(fake.converse.call_count, 2)
        self.assertEqual(len(self.rows()), 1)

    def test_failed_request_is_not_a_successful_call(self):
        fake = mock.Mock()
        fake.converse.side_effect = RuntimeError("offline request failed")
        with self.assertRaises(RuntimeError):
            Agent(client=fake).ask("Question")
        self.assertFalse(self.ledger.exists())

    def test_ledger_error_is_visible_and_never_retries_converse(self):
        fake = mock.Mock()
        fake.converse.return_value = response()
        with mock.patch("atlas.costs.os.open", side_effect=PermissionError("Cannot append ledger")), \
             self.assertRaises(PermissionError):
            Agent(client=fake).ask("Question")
        self.assertEqual(fake.converse.call_count, 1)

    def test_missing_usage_and_unknown_model_are_not_free(self):
        fake = mock.Mock()
        fake.converse.side_effect = [response(usage=False), response()]
        Agent(client=fake, model_id="unknown").ask("Question")
        Agent(client=fake, model_id="unknown").ask("Question")
        rows = self.rows()
        self.assertIsNone(rows[0]["input_tokens"])
        self.assertIsNone(rows[0]["total_tokens"])
        self.assertTrue(all(r["usd"] is None for r in rows))
        t = costs.summarize()["feature"]["chat"]
        self.assertEqual((t.calls, t.total_tokens, t.unknown_usd, t.missing_usage), (2, 1250, 2, 1))

    def write_fixture(self):
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        base = {"model": "us.amazon.nova-pro-v1:0", "input_tokens": 1000,
                "output_tokens": 250, "total_tokens": 1250, "usd": 0.0016, "rounds": 0}
        rows = [base | {"ts": "2026-11-06T23:30:00+00:00", "feature": "chat"},
                base | {"ts": "2026-11-07T01:00:00+00:00", "feature": "briefing", "usd": 0.002},
                base | {"ts": "2026-11-06T23:00:00-08:00", "feature": "chat"}]
        self.ledger.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    def test_summary_groups_days_in_utc_and_sums_recorded_usd(self):
        self.write_fixture()
        groups = costs.summarize()
        chat = groups["feature"]["chat"]
        self.assertEqual((chat.calls, chat.input_tokens, chat.output_tokens, chat.total_tokens), (2, 2000, 500, 2500))
        self.assertAlmostEqual(chat.usd, 0.0032)
        self.assertAlmostEqual(groups["feature"]["briefing"].usd, 0.002)
        self.assertEqual(groups["day"]["2026-11-07"].calls, 2)
        self.assertAlmostEqual(groups["day"]["2026-11-07"].usd, 0.0036)

    def test_cli_on_missing_empty_and_test_ledger(self):
        for state in ("missing", "empty", "fixture"):
            with self.subTest(state=state):
                if state == "empty":
                    self.ledger.parent.mkdir()
                    self.ledger.touch()
                elif state == "fixture":
                    self.write_fixture()
                output = self.root / "docs" / "costs.md"
                result = subprocess.run([sys.executable, "-m", "atlas.costs", "--ledger", str(self.ledger),
                                         "--output", str(output)], cwd=costs.ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, output.read_text())
                self.assertIn(pricing.READ_DATE, result.stdout)
                self.assertIn(pricing.SOURCE_URL, result.stdout)
                self.assertIn("unverified", result.stdout)
                if state == "fixture":
                    self.assertIn("| chat | 2 | 2000 | 500 | 2500 | 0.00320000 |", result.stdout)
                    self.assertIn("| 2026-11-07 | 2 | 2000 | 500 | 2500 | 0.00360000 |", result.stdout)
                else:
                    self.assertIn("No calls recorded", result.stdout)

    def test_invalid_ledger_reports_line_number_without_payload(self):
        self.ledger.parent.mkdir()
        self.ledger.write_text("Private malformed entry\n")
        with self.assertRaisesRegex(ValueError, "^Invalid cost ledger entry at line 1$"):
            costs.summarize()

    def test_web_briefing_tag_restores_chat_on_success_and_failure(self):
        # Import without loading any credential file; exercise helpers without a web server.
        with mock.patch("atlas.env.load_dotenv"):
            web = importlib.import_module("web")
        fake = mock.Mock()
        fake.converse.return_value = response()
        agent = Agent(client=fake, model_id="us.amazon.nova-pro-v1:0")
        with mock.patch.dict(web._state, {"agent": agent, "allow_write": False}), \
             mock.patch.object(web.profile, "load_state", return_value={}), \
             mock.patch.object(web.profile, "save_state"), \
             mock.patch.object(web.official_auth, "is_signed_in", return_value=False), \
             mock.patch.object(web, "_status", return_value={}):
            web._briefing()
            web._chat("Hello", allow_write=False)
            self.assertEqual([r["feature"] for r in self.rows()], ["briefing", "chat"])
            self.assertEqual(agent.feature, "chat")
            fake.converse.side_effect = RuntimeError("offline failure")
            with self.assertRaises(RuntimeError):
                web._briefing()
            self.assertEqual(agent.feature, "chat")
            self.assertFalse(web._state["allow_write"])


class PricingTests(unittest.TestCase):
    def test_base_and_us_models_and_unknown_versions(self):
        for model, (inp, out) in pricing.PRICES.items():
            with self.subTest(model=model):
                self.assertAlmostEqual(pricing.estimate_usd(model, 1000, 1000), inp + out)
                self.assertAlmostEqual(pricing.estimate_usd("us." + model, 1000, 1000), inp + out)
                self.assertEqual(pricing.estimate_usd(model, 0, 0), 0.0)
        self.assertIsNone(pricing.estimate_usd("amazon.nova-pro-v2:0", 1000, 1000))
        self.assertIsNone(pricing.estimate_usd("eu.amazon.nova-pro-v1:0", 1000, 1000))
        with self.assertRaises(ValueError):
            pricing.estimate_usd("amazon.nova-pro-v1:0", -1, 0)


if __name__ == "__main__":
    unittest.main()
