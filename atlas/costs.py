"""Private per-response cost ledger and offline Markdown summary.

Run ``python3 -m atlas.costs``; no credentials or network access are needed.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from atlas import pricing

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER_PATH = ROOT / "local-private" / "costs.jsonl"
# ATLAS_COSTS_LEDGER redirects the ledger (the offline tests point it at a temporary file).
LEDGER_PATH = Path(os.environ["ATLAS_COSTS_LEDGER"]) if os.environ.get("ATLAS_COSTS_LEDGER") else DEFAULT_LEDGER_PATH
REPORT_PATH = ROOT / "docs" / "costs.md"
_write_lock = Lock()


def append_usage(model: str, feature: str, usage: dict, rounds: int) -> None:
    """Append only billing metadata. Missing usage/cost stays unknown.

    rounds is the number of completed tool rounds before this response (initial
    response = 0). Ledger failures propagate so accounting cannot silently stop.
    """
    input_tokens = usage.get("inputTokens")
    output_tokens = usage.get("outputTokens")
    total_tokens = usage.get("totalTokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    usd = (pricing.estimate_usd(model, input_tokens, output_tokens)
           if input_tokens is not None and output_tokens is not None else None)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "model": model, "feature": feature,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": total_tokens, "usd": usd, "rounds": rounds,
    }
    payload = (json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    with _write_lock:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(LEDGER_PATH, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(fd, 0o600)  # also repair permissions on an existing ledger
            if os.write(fd, payload) != len(payload):
                raise OSError("Incomplete cost ledger write")
        finally:
            os.close(fd)


@dataclass
class Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    usd: float = 0.0
    unknown_usd: int = 0
    missing_usage: int = 0

    def add(self, row: dict) -> None:
        self.calls += 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            value = row.get(key)
            if key == "total_tokens" and value is None:
                a, b = row.get("input_tokens"), row.get("output_tokens")
                value = a + b if a is not None and b is not None else None
            if value is not None:
                setattr(self, key, getattr(self, key) + value)
        self.missing_usage += any(row.get(k) is None for k in ("input_tokens", "output_tokens"))
        if row.get("usd") is None:
            self.unknown_usd += 1
        else:
            self.usd += row["usd"]


def summarize(path: Path | None = None) -> dict[str, dict[str, Totals]]:
    """Sum the recorded estimates, without repricing historical calls."""
    path = LEDGER_PATH if path is None else path
    groups: dict[str, dict[str, Totals]] = {"feature": {}, "day": {}}
    if not path.exists():
        return groups
    with path.open(encoding="utf-8") as ledger:
        for number, line in enumerate(ledger, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                day = datetime.fromisoformat(row["ts"]).astimezone(timezone.utc).date().isoformat()
                for group, key in (("feature", row["feature"]), ("day", day)):
                    groups[group].setdefault(key, Totals()).add(row)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                # Do not echo ledger content, which may have been edited locally.
                raise ValueError(f"Invalid cost ledger entry at line {number}") from exc
    return groups


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def render_report(groups: dict[str, dict[str, Totals]]) -> str:
    lines = [
        "# Model costs", "",
        "Run `python3 -m atlas.costs` to refresh this report offline. "
        "The private ledger is `local-private/costs.jsonl` (git-ignored, mode 0600).", "",
        "## Price table", "",
        f"Source: [Amazon Bedrock pricing]({pricing.SOURCE_URL}). Read date: {pricing.READ_DATE}. "
        f"Region: `{pricing.REGION}`. Status: **{pricing.STATUS}**.", "",
        "The live page was readable, but its dynamic Nova rate table could not be read. "
        "These fallback rates require verification before billing decisions. "
        "Estimates assume standard on-demand input/output tokens in us-east-1, "
        "including US cross-region IDs. Other regions, cache pricing, batch, service-tier "
        "discounts, taxes, and non-model services are outside this estimate.", "",
        "| Model ID | Input USD / 1K tokens | Output USD / 1K tokens | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for model, (inp, out) in pricing.PRICES.items():
        lines.append(f"| `{model}` | {inp:.6f} | {out:.6f} | {pricing.STATUS} |")
    lines += ["", "Unknown model IDs have `usd: null`. Missing usage has null token counts and cost. "
              "USD columns sum known recorded estimates; unknown costs are counted separately "
              "and must not be interpreted as free calls. Token sums include known usage only. "
              "Historical entries retain their recorded USD when the table changes.", "",
              "Each call is one successful Converse response, including tool rounds and the final "
              "budget-exhausted request. `rounds` counts completed tool rounds before that response "
              "(starting at 0). Failed requests without a response cannot supply usage. "
              "Days are UTC. No prompt or response text is recorded. "
              "Ledger write errors fail the request visibly.", ""]
    for group, title in (("feature", "Per feature"), ("day", "Per day (UTC)")):
        lines += [f"## {title}", "",
                  "| Group | Calls | Input tokens | Output tokens | Total tokens | Estimated USD (known) | Unknown USD calls | Missing usage calls |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for key, t in sorted(groups[group].items()):
            lines.append(f"| {_cell(key)} | {t.calls} | {t.input_tokens} | {t.output_tokens} | "
                         f"{t.total_tokens} | {t.usd:.8f} | {t.unknown_usd} | {t.missing_usage} |")
        if not groups[group]:
            lines.append("| No calls recorded | 0 | 0 | 0 | 0 | 0.00000000 | 0 | 0 |")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = render_report(summarize(args.ledger))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
