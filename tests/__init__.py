"""Offline test package: every test writes the cost ledger to a temporary file, never local-private/.

`python3 -m unittest discover -s tests` imports the test modules as top-level modules and skips this
file, so tests/test_ledger_isolation.py imports it; discovery imports every module before any test runs.
Subprocesses inherit ATLAS_COSTS_LEDGER.
"""
import atexit
import os
import shutil
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="atlas-test-ledger-")
atexit.register(shutil.rmtree, _tmp, ignore_errors=True)
TEST_LEDGER = Path(_tmp) / "costs.jsonl"
os.environ["ATLAS_COSTS_LEDGER"] = str(TEST_LEDGER)

from atlas import costs  # noqa: E402

costs.LEDGER_PATH = TEST_LEDGER  # also covers an atlas.costs imported before this package
