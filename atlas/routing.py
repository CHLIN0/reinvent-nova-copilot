"""Venue-to-venue routing for re:Invent (estimates, never official wayfinding).

Graph: one door hub and one shuttle stop per venue, plus monorail stations.
Edges: walk, shuttle (scheduled, headway-based wait), monorail (scheduled),
rideshare (pickup wait + drive). Search: time-dependent Dijkstra over arrival
time; with FIFO edges (leaving later never arrives earlier) one label per node
is exact. See docs/routing.md for the reasoning and assumptions.
"""
from __future__ import annotations

import heapq
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.models import Leg, Route

GRAPH_PATH = Path(__file__).resolve().parent.parent / "data" / "venue_graph.json"
PREFERENCES = ("fastest", "fewest_steps")
LAS_VEGAS = ZoneInfo("America/Los_Angeles")
DISCLAIMER = (
    "Estimate from a simple venue graph; not official wayfinding. Shuttle routes, "
    "headways and walk times are assumptions. Check the official re:Invent app."
)

_G = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
_D = _G["defaults"]

VENUES: dict[str, dict] = {
    key: {"name": v["name"], "lat": v["lat"], "lon": v["lon"]} for key, v in _G["venues"].items()
}

_ALIASES = {
    "venetian": "venetian", "the venetian": "venetian", "palazzo": "venetian", "venetian expo": "venetian",
    "wynn": "wynn", "wynn las vegas": "wynn",
    "encore": "encore", "encore las vegas": "encore",
    "caesars forum": "caesars_forum", "forum": "caesars_forum",
    "caesars palace": "caesars_palace", "caesars": "caesars_palace",
    "mgm": "mgm_grand", "mgm grand": "mgm_grand",
    "mandalay": "mandalay_bay", "mandalay bay": "mandalay_bay",
}


def resolve_venue(name: str) -> str | None:
    """Map a canonical key or a common venue name to a VENUES key."""
    if not name:
        return None
    s = name.strip().lower()
    if s in VENUES:
        return s
    s = re.sub(r"[^a-z ]+", " ", s.replace("_", " ")).strip()
    s = re.sub(r"\s+", " ", s)
    if s in _ALIASES:
        return _ALIASES[s]
    for alias in sorted(_ALIASES, key=len, reverse=True):
        if alias in s:
            return _ALIASES[alias]
    return None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _coord(node: str) -> tuple[float, float]:
    if node in _G["stations"]:
        st = _G["stations"][node]
        return st["lat"], st["lon"]
    v = VENUES[node.split(":")[0]]
    return v["lat"], v["lon"]


def _walk_steps(minutes: float) -> int:
    return int(round(minutes * _D["steps_per_walk_min"]))


def _build_graph() -> dict[str, list[dict]]:
    adj: dict[str, list[dict]] = {}

    def add(a: str, b: str, mode: str, minutes: float, steps: int, sched: dict | None = None, both=True):
        e = {"mode": mode, "minutes": float(minutes), "steps": int(steps), "sched": sched}
        adj.setdefault(a, []).append({"to": b, **e})
        if both:
            adj.setdefault(b, []).append({"to": a, **e})

    for v in VENUES:
        d2s = _D["door_to_shuttle_min"]
        add(f"{v}:door", f"{v}:shuttle", "walk", d2s, _walk_steps(d2s))
    for w in _G["walk"]:
        add(f"{w['a']}:door", f"{w['b']}:door", "walk", w["minutes"], _walk_steps(w["minutes"]))
    for w in _G["station_walk"]:
        add(f"{w['venue']}:door", w["station"], "walk", w["minutes"], _walk_steps(w["minutes"]))
    mono = {"headway": _D["monorail_headway_min"], "first": _hhmm(_D["monorail_first"]),
            "last": _hhmm(_D["monorail_last"])}
    line = [_G["monorail"][0]["a"]] + [m["b"] for m in _G["monorail"]]
    cum = [0.0]
    for m in _G["monorail"]:
        cum.append(cum[-1] + m["minutes"])
    for i in range(len(line)):  # one edge per station pair: riding through needs no second wait
        for j in range(i + 1, len(line)):
            add(line[i], line[j], "monorail", cum[j] - cum[i], 0, mono)
    shuttle = {"headway": _D["shuttle_headway_min"], "first": _hhmm(_D["shuttle_first"]),
               "last": _hhmm(_D["shuttle_last"])}
    for s in _G["shuttle"]:
        km = haversine_m(*_coord(s["a"]), *_coord(s["b"])) / 1000 * _D["road_factor"]
        ride = km / _D["shuttle_kmh"] * 60 + _D["shuttle_board_min"]
        add(f"{s['a']}:shuttle", f"{s['b']}:shuttle", "shuttle", round(ride, 1), 0, shuttle)
    keys = list(VENUES)
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            km = haversine_m(*_coord(a), *_coord(b)) / 1000 * _D["road_factor"]
            zone = _D["rideshare_zone_walk_min"]
            ride = zone + _D["rideshare_pickup_wait_min"] + km / _D["rideshare_kmh"] * 60
            add(f"{a}:door", f"{b}:door", "rideshare", round(ride, 1), _walk_steps(zone))
    return adj


GRAPH = _build_graph()


def _wait(sched: dict | None, t: float | None) -> float | None:
    """Minutes to wait for the next scheduled departure; None if no service.

    t is minutes since local midnight; None means unknown departure time, so the
    expected wait (half a headway) is used and service hours are ignored.
    """
    if not sched:
        return 0.0
    if t is None:
        return sched["headway"] / 2
    m = t % 1440
    if m < sched["first"]:
        return sched["first"] - m
    k = math.ceil((m - sched["first"]) / sched["headway"] - 1e-9)
    dep = sched["first"] + k * sched["headway"]
    if dep > sched["last"]:
        return None
    return dep - m


def _parse(ts: str) -> datetime:
    """Parse ISO 8601; aware times are converted to Las Vegas local, naive ones are taken as local."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.astimezone(LAS_VEGAS) if dt.tzinfo else dt


def route(from_venue: str, to_venue: str, depart_at: str | None = None, prefer: str = "fastest") -> Route:
    if prefer not in PREFERENCES:
        raise ValueError(f"prefer must be one of {PREFERENCES}")
    a, b = resolve_venue(from_venue), resolve_venue(to_venue)
    if a is None or b is None:
        bad = from_venue if a is None else to_venue
        raise ValueError(f"unknown venue {bad!r}; known: {', '.join(VENUES)}")
    start_dt = _parse(depart_at) if depart_at else None
    t0 = start_dt.hour * 60 + start_dt.minute + start_dt.second / 60 if start_dt else None

    if a == b:
        mins = float(_G["venues"][a]["intra_minutes"])
        legs = [Leg(mode="walk", from_node=f"{a}:door", to_node=f"{a}:door", minutes=mins, steps=_walk_steps(mins))]
        return _result(a, b, legs, start_dt, prefer, ["Same venue: typical indoor walk between rooms (estimate)."])

    def keyfn(elapsed: float, steps: int) -> tuple:
        return (round(elapsed, 6), steps) if prefer == "fastest" else (steps, round(elapsed, 6))

    src, dst = f"{a}:door", f"{b}:door"
    best: dict[str, tuple] = {src: (0.0, 0)}
    prev: dict[str, tuple] = {}
    heap = [((0, 0.0), 0.0, 0, src)]
    while heap:
        key, elapsed, steps, node = heapq.heappop(heap)
        if best.get(node) != (elapsed, steps):
            continue
        if node == dst:
            break
        now = None if t0 is None else t0 + elapsed
        for e in GRAPH.get(node, []):
            w = _wait(e["sched"], now)
            if w is None:
                continue
            ne, ns = elapsed + w + e["minutes"], steps + e["steps"]
            nk = keyfn(ne, ns)
            old = best.get(e["to"])
            if old is None or nk < keyfn(*old):
                best[e["to"]] = (ne, ns)
                prev[e["to"]] = (node, e, w)
                heapq.heappush(heap, (nk, ne, ns, e["to"]))
    if dst not in best:
        raise ValueError(f"no route from {a} to {b} at that time")

    legs: list[Leg] = []
    node = dst
    while node != src:
        p, e, w = prev[node]
        leg = Leg(mode=e["mode"], from_node=p, to_node=node, minutes=round(w + e["minutes"], 1), steps=e["steps"])
        if e["sched"]:
            leg["wait_minutes"] = round(w, 1)
        legs.append(leg)
        node = p
    legs.reverse()
    notes = []
    if t0 is None and any(l["mode"] in ("shuttle", "monorail") for l in legs):
        notes.append("No departure time given: scheduled legs use an expected wait of half a headway.")
    return _result(a, b, legs, start_dt, prefer, notes)


def _result(a, b, legs, start_dt, prefer, notes) -> Route:
    minutes = round(sum(l["minutes"] for l in legs), 1)
    r = Route(from_venue=a, to_venue=b, minutes=minutes, steps=sum(l["steps"] for l in legs),
              legs=legs, estimate=True)
    r["prefer"] = prefer
    r["modes"] = sorted({l["mode"] for l in legs})
    if start_dt:
        r["depart_at"] = start_dt.isoformat()
        r["arrive_at"] = (start_dt + timedelta(minutes=minutes)).isoformat(timespec="minutes")
    r["notes"] = notes + [DISCLAIMER]
    return r
