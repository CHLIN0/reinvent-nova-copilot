"""Server-side checks on model text before it reaches the attendee."""
from __future__ import annotations

import re
from typing import Any

FEASIBILITY_WORDS = ("feasible", "no conflicts", "conflict-free", "tight transition", "enough time",
                     "can make it", "reachable")
VERIFYING_TOOLS = ("check_itinerary", "plan_itinerary")
NOT_CHECKED = "I have not checked travel feasibility yet."

_SENTENCE = re.compile(r"[^.!?\n]*(?:[.!?]+|\n|$)")


def _field(call: Any, key: str) -> Any:
    return call.get(key) if isinstance(call, dict) else getattr(call, key, None)


UNRESOLVED_KEY = "reservations_not_applied"


def _has_unresolved(result: Any) -> bool:
    if isinstance(result, dict):
        return bool(result.get(UNRESOLVED_KEY))
    return isinstance(result, str) and f'"{UNRESOLVED_KEY}"' in result  # web.py may shorten results to text


def feasibility_verified(trace: list) -> bool:
    """True if a check_itinerary or plan_itinerary call succeeded and none of them reported a reservation
    that could not be checked. Trace items are ToolCall objects or dicts."""
    checks = [c for c in trace or [] if _field(c, "name") in VERIFYING_TOOLS and _field(c, "ok")]
    return bool(checks) and not any(_has_unresolved(_field(c, "result")) for c in checks)


def strip_unverified_feasibility(text: str, trace: list) -> tuple[str, list[str]]:
    """Remove sentences that assert feasibility when no itinerary check succeeded in the trace.

    Returns (text, removed sentences). Text is unchanged when a check succeeded or nothing matched.
    """
    if not text or feasibility_verified(trace):
        return text, []
    kept, removed = [], []
    for piece in _SENTENCE.findall(text):
        if not piece:
            continue
        low = piece.lower()
        if any(w in low for w in FEASIBILITY_WORDS):
            removed.append(piece.strip())
            if piece.endswith("\n"):
                kept.append("\n")
        else:
            kept.append(piece)
    if not removed:
        return text, []
    out = re.sub(r"[ \t]{2,}", " ", "".join(kept)).strip()
    return (out + " " + NOT_CHECKED if out else NOT_CHECKED), removed
