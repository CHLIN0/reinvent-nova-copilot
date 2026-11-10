"""Row B1: the offline suite never writes to the private ledger local-private/costs.jsonl."""
import os
import subprocess
import sys
import unittest

import tests  # noqa: F401  # applies the temporary ledger when discovery skips tests/__init__.py
from atlas import costs
from atlas.agent import Agent

from tests.test_agent import FakeBedrock, final, stub_backend, tool_use


def _stat(path):
    return (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None


class LedgerIsolationTest(unittest.TestCase):
    def test_suite_ledger_is_temporary(self):
        self.assertEqual(costs.LEDGER_PATH, tests.TEST_LEDGER)
        self.assertNotEqual(costs.LEDGER_PATH, costs.DEFAULT_LEDGER_PATH)
        self.assertEqual(os.environ["ATLAS_COSTS_LEDGER"], str(tests.TEST_LEDGER))

    def test_mocked_agent_turn_leaves_private_ledger_unchanged(self):
        before = _stat(costs.DEFAULT_LEDGER_PATH)
        written = _stat(tests.TEST_LEDGER)
        fake = FakeBedrock([tool_use("search_sessions", {"query": "agents"}), final("Go to AIM301.")])
        Agent(client=fake, backend=stub_backend([])).ask("agent workshops?")
        self.assertEqual(_stat(costs.DEFAULT_LEDGER_PATH), before)
        self.assertNotEqual(_stat(tests.TEST_LEDGER), written)  # the turn's rows went to the temporary ledger

    def test_environment_override_reaches_a_fresh_process(self):
        out = subprocess.run([sys.executable, "-c", "from atlas import costs; print(costs.LEDGER_PATH)"],
                             cwd=costs.ROOT, capture_output=True, text=True, check=True,
                             env={**os.environ, "ATLAS_COSTS_LEDGER": str(tests.TEST_LEDGER.parent / "child.jsonl")})
        self.assertEqual(out.stdout.strip(), str(tests.TEST_LEDGER.parent / "child.jsonl"))


if __name__ == "__main__":
    unittest.main()
