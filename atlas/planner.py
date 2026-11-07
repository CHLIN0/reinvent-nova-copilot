"""Itinerary checks and planning on top of atlas.routing (all travel is estimated).

plan_itinerary is a weighted-interval-scheduling style DP over sessions sorted by
start, where an edge i -> j exists only if j starts after i ends plus estimated
travel plus buffer. It is exact for this objective; see docs/routing.md.
"""
from __future__ import annotations

from datetime import datetime

from atlas.models import Session
from atlas.routing import DISCLAIMER, resolve_venue, route

UNKNOWN_VENUE_TRAVEL_MIN = 25  # conservative stand-in when a session has no known venue
TIGHT_SLACK_MIN = 5
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _label(s: Session) -> str:
    return s.get("code") or s.get("id") or s.get("title", "?")


def _brief(s: Session) -> dict:
    return {k: s.get(k) for k in ("id", "code", "title", "start", "end", "venue", "room") if s.get(k) is not None}


def _on_day(s: Session, day: str) -> bool:
    d = _dt(s["start"])
    want = day.strip().lower()
    if want[:3] in _WEEKDAYS and not want[0].isdigit():
        return _WEEKDAYS[d.weekday()] == want[:3]
    return d.date().isoformat() == want[:10]


class _Travel:
    """Memoised travel estimate between consecutive sessions."""

    def __init__(self, prefer: str):
        self.prefer = prefer
        self.cache: dict[tuple, dict] = {}

    def between(self, a: Session, b: Session) -> dict:
        key = (a.get("venue"), b.get("venue"), a["end"])
        if key not in self.cache:
            va, vb = resolve_venue(a.get("venue", "")), resolve_venue(b.get("venue", ""))
            if va is None or vb is None:
                self.cache[key] = {"minutes": UNKNOWN_VENUE_TRAVEL_MIN, "steps": 0, "modes": [],
                                   "unknown_venue": True, "legs": []}
            else:
                r = route(va, vb, depart_at=a["end"], prefer=self.prefer)
                self.cache[key] = {"minutes": r["minutes"], "steps": r["steps"], "modes": r["modes"],
                                   "unknown_venue": False, "legs": r["legs"]}
        return self.cache[key]


def _transition(a: Session, b: Session, travel: _Travel, buffer_min: int) -> dict:
    gap = (_dt(b["start"]) - _dt(a["end"])).total_seconds() / 60
    t = {"from": _label(a), "to": _label(b), "from_venue": a.get("venue"), "to_venue": b.get("venue"),
         "gap_minutes": round(gap, 1)}
    if gap >= 0 and _dt(b["start"]).date() > _dt(a["end"]).date():
        t.update(status="new_day", travel_minutes=0, steps=0, slack_minutes=None)
        return t
    tr = travel.between(a, b)
    slack = gap - tr["minutes"] - buffer_min
    if gap < 0:
        status = "overlap"
    elif slack < 0:
        status = "not_enough_time"
    elif slack < TIGHT_SLACK_MIN:
        status = "tight"
    else:
        status = "ok"
    t.update(status=status, travel_minutes=tr["minutes"], steps=tr["steps"], modes=tr["modes"],
             slack_minutes=round(slack, 1), legs=tr["legs"])
    if tr["unknown_venue"]:
        t["note"] = f"unknown venue; assumed {UNKNOWN_VENUE_TRAVEL_MIN} min travel"
    return t


def check_itinerary(sessions: list[Session], buffer_min: int = 10, prefer: str = "fastest") -> dict:
    ordered = sorted(sessions, key=lambda s: _dt(s["start"]))
    travel = _Travel(prefer)
    transitions = [_transition(a, b, travel, buffer_min) for a, b in zip(ordered, ordered[1:])]
    conflicts = [t for t in transitions if t["status"] in ("overlap", "not_enough_time")]
    return {
        "sessions": [_brief(s) for s in ordered],
        "transitions": transitions,
        "conflicts": conflicts,
        "feasible": not conflicts,
        "total_travel_minutes": round(sum(t["travel_minutes"] for t in transitions), 1),
        "total_steps": sum(t["steps"] for t in transitions),
        "buffer_min": buffer_min,
        "estimate": True,
        "notes": [DISCLAIMER],
    }


def plan_itinerary(candidates: list[Session], must: list[str] | None = None, day: str | None = None,
                   prefer: str = "fastest", buffer_min: int = 10, max_sessions: int = 6) -> dict:
    must = list(must or [])
    warnings: list[str] = []
    seen: set[str] = set()
    pool: list[Session] = []
    off_day: list[Session] = []
    for s in candidates:
        sid = s.get("id") or s.get("code")
        if not sid or sid in seen or not s.get("start") or not s.get("end"):
            continue
        seen.add(sid)
        if day and not _on_day(s, day):
            off_day.append(s)
        else:
            pool.append(s)
    pool.sort(key=lambda s: (_dt(s["start"]), _dt(s["end"])))
    ids = [s.get("id") or s.get("code") for s in pool]

    def is_must(s: Session) -> bool:
        return s.get("id") in must or s.get("code") in must

    known = {k for s in pool for k in (s.get("id"), s.get("code")) if k}
    for m in must:
        if m not in known:
            warnings.append(f"must-have {m} is not among the candidates for this day; ignored")
    must_idx = [i for i, s in enumerate(pool) if is_must(s)]
    cap = max(0, int(max_sessions))
    if len(must_idx) > cap:
        warnings.append(f"{len(must_idx)} must-haves exceed max_sessions={max_sessions}; cap raised")
        cap = len(must_idx)

    travel = _Travel(prefer)
    n = len(pool)

    def fits(i: int, j: int) -> tuple[bool, dict]:
        t = _transition(pool[i], pool[j], travel, buffer_min)
        return t["status"] in ("ok", "tight", "new_day"), t

    # must-haves that cannot coexist: report and plan nothing else around a broken core
    must_conflicts = []
    for a, b in zip(must_idx, must_idx[1:]):
        ok, t = fits(a, b)
        if not ok:
            must_conflicts.append(t)
    if must_conflicts:
        chosen = [pool[i] for i in must_idx]
        chk = check_itinerary(chosen, buffer_min, prefer)
        return {
            "feasible": False,
            "chosen": chk["sessions"],
            "transitions": chk["transitions"],
            "dropped": [{**_brief(pool[i]), "reason": "not planned: must-have sessions conflict with each other"}
                        for i in range(n) if i not in must_idx]
            + [{**_brief(s), "reason": f"not on {day}"} for s in off_day],
            "must_conflicts": must_conflicts,
            "total_travel_minutes": chk["total_travel_minutes"],
            "total_steps": chk["total_steps"],
            "warnings": warnings + ["Must-have sessions conflict; drop or move one of them."],
            "estimate": True, "method": _METHOD, "notes": [DISCLAIMER],
        }

    def prio(s: Session) -> float:
        try:
            return float(s.get("priority", 1))
        except (TypeError, ValueError):
            return 1.0

    def must_between(i: int, j: int) -> bool:
        return any(i < m < j for m in must_idx)

    first_must = must_idx[0] if must_idx else n
    last_must = must_idx[-1] if must_idx else -1
    # score: (priority sum, -primary travel cost, -secondary); larger is better
    dp: list[dict[int, tuple]] = [dict() for _ in range(n)]  # dp[j][k] = (score, prev_i)
    for j in range(n):
        p = prio(pool[j])
        if j <= first_must and cap >= 1:
            dp[j][1] = ((p, 0.0, 0.0), None)
        for i in range(j):
            if not dp[i] or must_between(i, j):
                continue
            ok, t = fits(i, j)
            if not ok:
                continue
            cost = (t["travel_minutes"], t["steps"]) if prefer == "fastest" else (t["steps"], t["travel_minutes"])
            for k, (sc, _) in dp[i].items():
                if k + 1 > cap:
                    continue
                cand = (sc[0] + p, sc[1] - cost[0], sc[2] - cost[1])
                if k + 1 not in dp[j] or cand > dp[j][k + 1][0]:
                    dp[j][k + 1] = (cand, i)
    best = ((0.0, 0.0, 0.0), None, 0) if not must_idx else None  # empty plan is a valid baseline
    for j in range(max(last_must, 0), n):
        for k, (sc, _) in dp[j].items():
            if best is None or sc > best[0]:
                best = (sc, j, k)
    chosen_idx: list[int] = []
    if best and best[1] is not None:
        _, j, k = best
        while j is not None:
            chosen_idx.append(j)
            j = dp[j][k][1]
            k -= 1
        chosen_idx.reverse()
    chosen_set = set(chosen_idx)
    chosen = [pool[i] for i in chosen_idx]

    dropped = []
    for i in range(n):
        if i in chosen_set:
            continue
        dropped.append({**_brief(pool[i]), "reason": _why_dropped(i, pool, chosen_idx, fits, cap)})
    for s in off_day:
        dropped.append({**_brief(s), "reason": f"not on {day}"})

    chk = check_itinerary(chosen, buffer_min, prefer)
    return {
        "feasible": chk["feasible"],
        "day": day,
        "chosen": chk["sessions"],
        "must": [_label(pool[i]) for i in must_idx],
        "transitions": chk["transitions"],
        "dropped": dropped,
        "total_travel_minutes": chk["total_travel_minutes"],
        "total_steps": chk["total_steps"],
        "buffer_min": buffer_min,
        "prefer": prefer,
        "max_sessions": cap,
        "warnings": warnings,
        "estimate": True,
        "method": _METHOD,
        "notes": [DISCLAIMER],
    }


_METHOD = ("Exact DP over sessions sorted by start: keep all must-haves, maximise count (or priority sum), "
           "then minimise estimated travel; a pair is compatible only if gap >= travel + buffer.")


def _why_dropped(i: int, pool: list[Session], chosen_idx: list[int], fits, cap: int) -> str:
    s = pool[i]
    s0, e0 = _dt(s["start"]), _dt(s["end"])
    for c in chosen_idx:
        cs, ce = _dt(pool[c]["start"]), _dt(pool[c]["end"])
        if cs < e0 and s0 < ce:
            return f"time overlap with chosen {_label(pool[c])}"
    prev = [c for c in chosen_idx if c < i]
    nxt = [c for c in chosen_idx if c > i]
    if prev:
        ok, t = fits(prev[-1], i)
        if not ok:
            return (f"not enough time after {_label(pool[prev[-1]])}: gap {t['gap_minutes']} min, "
                    f"travel ~{t['travel_minutes']} min + buffer")
    if nxt:
        ok, t = fits(i, nxt[0])
        if not ok:
            return (f"not enough time before {_label(pool[nxt[0]])}: gap {t['gap_minutes']} min, "
                    f"travel ~{t['travel_minutes']} min + buffer")
    if len(chosen_idx) >= cap:
        return f"max_sessions={cap} reached; kept higher-priority or less-travel options"
    return "a different combination fit more sessions or needed less travel"
