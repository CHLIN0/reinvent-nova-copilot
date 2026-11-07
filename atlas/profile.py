"""Attendee profile: the personal context a re:Invent veteran would ask about first.

Stored only on this machine, one JSON file per profile name, under
`local-private/profiles/` (git-ignored, file mode 0600). Nothing here is sent to
AWS Events; the model sees it only through the get_profile tool.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from atlas.routing import resolve_venue

PROFILE_DIR = Path(os.environ.get("ATLAS_PROFILE_DIR") or Path(__file__).resolve().parent.parent / "local-private" / "profiles")

# Hotels that are not session venues, mapped to the nearest venue node in the routing graph.
# These are approximations for planning, labelled as such in every result.
_NEAREST_VENUE = {
    "palazzo": "venetian", "treasure island": "venetian", "resorts world": "wynn", "fontainebleau": "encore",
    "sahara": "encore", "linq": "caesars_palace", "flamingo": "caesars_palace", "harrah": "caesars_forum",
    "paris": "caesars_palace", "horseshoe": "caesars_palace", "bellagio": "caesars_palace",
    "cosmopolitan": "mgm_grand", "aria": "mgm_grand", "vdara": "mgm_grand", "park mgm": "mgm_grand",
    "new york new york": "mgm_grand", "tropicana": "mgm_grand", "excalibur": "mandalay_bay",
    "luxor": "mandalay_bay", "delano": "mandalay_bay", "w las vegas": "mandalay_bay",
}

FIELDS: dict[str, str] = {
    "name": "What to call the attendee.",
    "role": "Job role, e.g. 'backend developer', 'solutions architect'.",
    "experience_level": "Self-assessed level: 100, 200, 300 or 400.",
    "interests": "Topics they care about (list).",
    "goals": "What they want to take home from re:Invent (list).",
    "hotel": "Hotel name as the attendee said it.",
    "arrival": "Arrival date/time as stated (keep the attendee's wording, add a timezone if known).",
    "departure": "Departure date/time as stated.",
    "transport": "Preferred ways to move: walk, shuttle, monorail, rideshare (list).",
    "max_steps_per_day": "Walking limit per day, if any (integer).",
    "mobility": "Accessibility or mobility needs, in their words.",
    "diet": "Dietary needs, in their words.",
    "fixed_commitments": "Things already fixed, e.g. 'customer call Tue 18:00' (list).",
    "special_arrangements": "Anything else to plan around: lactation room, prayer times, quiet time, family, etc. (list).",
    "language": "Preferred language for answers.",
}
_LIST_FIELDS = {"interests", "goals", "transport", "fixed_commitments", "special_arrangements"}


def _safe_name(name: str | None) -> str:
    n = re.sub(r"[^a-z0-9_-]+", "-", (name or os.environ.get("ATLAS_PROFILE") or "default").lower()).strip("-")
    return n or "default"


def _path(name: str | None) -> Path:
    return PROFILE_DIR / f"{_safe_name(name)}.json"


def hotel_venue(hotel: str | None) -> dict | None:
    """Resolve a hotel to a routing node. exact=False means nearest-venue approximation."""
    if not hotel:
        return None
    h = re.sub(r"[^a-z ]+", " ", hotel.lower())
    for alias in sorted(_NEAREST_VENUE, key=len, reverse=True):  # specific hotels first ("Park MGM" is not MGM Grand)
        if alias in h:
            return {"venue": _NEAREST_VENUE[alias], "exact": False}
    key = resolve_venue(hotel)
    return {"venue": key, "exact": True} if key else None


def load_profile(name: str | None = None) -> dict[str, Any]:
    p = _path(name)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    out: dict[str, Any] = {"profile": _safe_name(name), "fields": data, "missing": [f for f in FIELDS if f not in data]}
    hv = hotel_venue(data.get("hotel"))
    if hv:
        out["home_base"] = {**hv, "note": "Hotel matched to a venue node for route estimates." if hv["exact"]
                            else "Hotel is not a session venue; using the nearest venue node as an approximation."}
    elif data.get("hotel"):
        out["home_base"] = {"venue": None, "note": "Hotel not in the routing graph; routes from the hotel are unknown."}
    return out


def update_profile(updates: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    unknown = [k for k in updates if k not in FIELDS]
    if unknown:
        raise ValueError(f"Unknown profile field(s): {unknown}. Allowed: {list(FIELDS)}")
    p = _path(name)
    data = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    for k, v in updates.items():
        if v in (None, "", []):
            data.pop(k, None)
        elif k in _LIST_FIELDS and not isinstance(v, list):
            data[k] = [v]
        elif k == "max_steps_per_day":
            data[k] = int(v)
        else:
            data[k] = v
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return load_profile(name)


def load_state(name: str | None = None) -> dict[str, Any]:
    """Last-visit snapshot (official schedule ids, last plan) kept next to the profile."""
    p = PROFILE_DIR / f"{_safe_name(name)}.state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def save_state(state: dict[str, Any], name: str | None = None) -> None:
    """Atomic: write a 0600 temp file in the same directory, then rename it over the state file.

    A reader (here or in another process) sees either the old or the new file, never a half-written one.
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    p = PROFILE_DIR / f"{_safe_name(name)}.state.json"
    fd, tmp = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=PROFILE_DIR)  # mkstemp creates 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_state_lock = threading.Lock()


def read_state(name: str | None = None) -> dict[str, Any]:
    """load_state under the same lock as update_state, for readers in this process."""
    with _state_lock:
        return load_state(name)


def update_state(change: Callable[[dict[str, Any]], Any], name: str | None = None) -> Any:
    """Read, change and save the state file as one step for this process; nothing is saved if `change` raises."""
    with _state_lock:
        state = load_state(name)
        result = change(state)
        save_state(state, name)
        return result
