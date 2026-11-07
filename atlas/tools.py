"""Tool specs (JSON Schema) and a dispatcher shared by the Nova agent and the MCP server.

The backend functions live in atlas.catalog (Owner A), atlas.routing and
atlas.planner (Owner B); signatures follow CONTRACTS.md. They are imported
lazily so this module loads even when a backend is missing, and tests can
inject a stub backend with `Backend(...)`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

WRITE_TOOLS = frozenset({"add_favorites"})

_PREFER = {"type": "string", "enum": ["fastest", "fewest_steps"], "description": "Optimise travel for time (fastest) or walking (fewest_steps)."}
_BUFFER = {"type": "integer", "minimum": 0, "maximum": 60, "description": "Minutes of slack wanted between sessions. Default 10."}
_IDS = {"type": "array", "items": {"type": "string"}}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "search_sessions",
        "description": "Search the official re:Invent session catalog. Returns sessions with id, code, title, type, level, start, end, venue and room. Call this before naming any session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text keywords, e.g. 'bedrock agents' or 'serverless'."},
                "types": {**_IDS, "description": "Session types, e.g. Breakout, Workshop, Chalk talk, Builders' session, Code talk, Keynote."},
                "levels": {**_IDS, "description": "Levels: 100, 200, 300, 400."},
                "topics": {**_IDS, "description": "Topic names."},
                "day": {"type": "string", "description": "Day filter, e.g. 'Tue' or an ISO date."},
                "venue": {"type": "string", "description": "Venue key: venetian, wynn, encore, caesars_forum, caesars_palace, mgm_grand, mandalay_bay."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 30, "description": "Max results. Default 10."},
            },
        },
    },
    {
        "name": "get_session",
        "description": "Get full details (including abstract) of one session by its id or session code.",
        "input_schema": {
            "type": "object",
            "properties": {"session_id": {"type": "string", "description": "Session id or code from a search result."}},
            "required": ["session_id"],
        },
    },
    {
        "name": "route_between",
        "description": "Estimate door-to-door travel between two venues: minutes, walking steps and legs (walk, shuttle, monorail, rideshare).",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_venue": {"type": "string", "description": "Venue key, e.g. venetian."},
                "to_venue": {"type": "string", "description": "Venue key, e.g. mandalay_bay."},
                "depart_at": {"type": "string", "description": "Optional ISO 8601 departure time."},
                "prefer": _PREFER,
            },
            "required": ["from_venue", "to_venue"],
        },
    },
    {
        "name": "check_itinerary",
        "description": "Check whether a list of sessions can be attended in order: transitions with travel time and slack, conflicts, total steps.",
        "input_schema": {
            "type": "object",
            "properties": {"session_ids": {**_IDS, "description": "Session ids or codes the attendee plans to attend."}, "buffer_min": _BUFFER},
            "required": ["session_ids"],
        },
    },
    {
        "name": "plan_itinerary",
        "description": "Pick the best feasible set of sessions from candidates, keeping must-attend ones, and explain what was dropped and why. Pass candidate_ids from search results, or a query to search for candidates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_ids": {**_IDS, "description": "Candidate session ids or codes."},
                "query": {"type": "string", "description": "Search keywords used to find candidates when candidate_ids is empty."},
                "must": {**_IDS, "description": "Session ids or codes that must be in the plan."},
                "day": {"type": "string", "description": "Day to plan, e.g. 'Tue' or an ISO date."},
                "prefer": _PREFER,
                "buffer_min": _BUFFER,
                "max_sessions": {"type": "integer", "minimum": 1, "maximum": 10, "description": "Max sessions in the plan. Default 6."},
                "use_profile": {"type": "boolean", "description": "Add hotel-to-first-session and last-session-to-hotel travel from the attendee profile. Default true."},
                "back_by": {"type": "string", "description": "Latest time to be back at the hotel (home base), 'HH:MM' local time, e.g. '17:15' for a 17:30 call in the room. Sessions that would make this impossible are dropped."},
                "blocked": {"type": "array", "items": {"type": "object", "properties": {"start": {"type": "string"}, "end": {"type": "string"}, "label": {"type": "string"}}}, "description": "Time windows the attendee is busy ('HH:MM' local), e.g. a lunch meeting. Overlapping sessions are dropped."},
            },
        },
    },
    {
        "name": "get_profile",
        "description": "Read the attendee's saved profile (hotel and home-base venue, transport preferences, walking limit, mobility, diet, fixed commitments, special arrangements, interests, goals). Call this at the start of planning; ask about missing fields that matter for the question.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_profile",
        "description": "Save facts the attendee stated about themselves (only what they actually said). Fields: name, role, experience_level, interests, goals, hotel, arrival, departure, transport, max_steps_per_day, mobility, diet, fixed_commitments, special_arrangements, language. Stored only on this machine. Pass an empty value to clear a field.",
        "input_schema": {
            "type": "object",
            "properties": {"updates": {"type": "object", "description": "Field name -> value, e.g. {\"hotel\": \"Park MGM\", \"max_steps_per_day\": 8000}."}},
            "required": ["updates"],
        },
    },
    {
        "name": "get_my_schedule",
        "description": "Read the signed-in attendee's own schedule from AWS Events: reservations, favorites and personal time. Requires sign-in.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_favorites",
        "description": "WRITE: add sessions to the signed-in attendee's favorites in AWS Events. Only when the attendee asked for it; the attendee must confirm.",
        "input_schema": {
            "type": "object",
            "properties": {"session_ids": {**_IDS, "description": "Exact session ids from a tool result."}},
            "required": ["session_ids"],
        },
    },
]

_SPEC_BY_NAME = {s["name"]: s for s in TOOL_SPECS}


def bedrock_tool_config() -> dict[str, Any]:
    """toolConfig for the Bedrock Converse API."""
    return {
        "tools": [
            {"toolSpec": {"name": s["name"], "description": s["description"], "inputSchema": {"json": s["input_schema"]}}}
            for s in TOOL_SPECS
        ]
    }


@dataclass
class Backend:
    search_sessions: Callable[..., list]
    get_session: Callable[[str], Any]
    get_schedule: Callable[[], dict]
    add_favorites: Callable[[list[str]], dict]
    route: Callable[..., dict]
    check_itinerary: Callable[..., dict]
    plan_itinerary: Callable[..., dict]


def _lazy(module: str, fn: str) -> Callable[..., Any]:
    def call(*a: Any, **kw: Any) -> Any:
        import importlib

        return getattr(importlib.import_module(f"atlas.{module}"), fn)(*a, **kw)

    return call


def default_backend() -> Backend:
    """Each tool imports its own module on first use, so one missing module only breaks its tools."""
    return Backend(
        search_sessions=_lazy("catalog", "search_sessions"),
        get_session=_lazy("catalog", "get_session"),
        get_schedule=_lazy("catalog", "get_schedule"),
        add_favorites=_lazy("catalog", "add_favorites"),
        route=_lazy("routing", "route"),
        check_itinerary=_lazy("planner", "check_itinerary"),
        plan_itinerary=_lazy("planner", "plan_itinerary"),
    )


class ToolError(Exception):
    pass


_BRIEF_KEYS = ("id", "code", "title", "type", "level", "topics", "start", "end", "venue", "room", "seats")


def _brief(s: dict, abstract_chars: int = 160) -> dict:
    out = {k: s[k] for k in _BRIEF_KEYS if s.get(k)}
    if s.get("abstract") and abstract_chars:
        a = s["abstract"]
        out["abstract"] = a if len(a) <= abstract_chars else a[:abstract_chars].rstrip() + "..."
    return out


def _resolve(be: Backend, ids: list[str]) -> tuple[list[dict], list[str]]:
    found, missing = [], []
    for sid in ids or []:
        s = be.get_session(sid)
        (found.append(s) if s else missing.append(sid))
    return found, missing


def _call(name: str, args: dict, be: Backend) -> Any:
    if name == "search_sessions":
        kw = {k: args[k] for k in ("query", "types", "levels", "topics", "day", "venue") if args.get(k)}
        kw["limit"] = int(args.get("limit") or 10)
        rows = be.search_sessions(**kw)
        return {"count": len(rows), "sessions": [_brief(s) for s in rows]}
    if name == "get_session":
        s = be.get_session(args["session_id"])
        if not s:
            raise ToolError(f"No session with id or code {args['session_id']!r} in the catalog.")
        return {"session": _brief(s, abstract_chars=1200)}
    if name == "route_between":
        kw = {"prefer": args.get("prefer") or "fastest"}
        if args.get("depart_at"):
            kw["depart_at"] = args["depart_at"]
        return {"route": be.route(args["from_venue"], args["to_venue"], **kw)}
    if name == "check_itinerary":
        sessions, missing = _resolve(be, args.get("session_ids", []))
        if not sessions:
            raise ToolError(f"None of these session ids were found: {missing}")
        sessions.sort(key=lambda s: s.get("start", ""))
        result = be.check_itinerary(sessions, buffer_min=int(args.get("buffer_min", 10)))
        return {"sessions": [_brief(s, 0) for s in sessions], "check": result, "not_found": missing}
    if name == "plan_itinerary":
        candidates, missing = _resolve(be, args.get("candidate_ids", []))
        must_sessions, must_missing = _resolve(be, args.get("must", []))
        if not candidates and args.get("query"):
            kw = {"query": args["query"], "limit": 30}
            if args.get("day"):
                kw["day"] = args["day"]
            candidates = be.search_sessions(**kw)
        by_id = {s["id"]: s for s in candidates}
        for s in must_sessions:
            by_id.setdefault(s["id"], s)
        if not by_id:
            raise ToolError("No candidate sessions: pass candidate_ids from a search, or a query.")
        pool, pre_dropped = _apply_time_limits(be, list(by_id.values()), args, {s["id"] for s in must_sessions})
        if not pool:
            raise ToolError(f"Every candidate conflicts with the stated time limits: {pre_dropped}")
        result = be.plan_itinerary(
            pool,
            must=[s["id"] for s in must_sessions],
            day=args.get("day"),
            prefer=args.get("prefer") or "fastest",
            buffer_min=int(args.get("buffer_min", 10)),
            max_sessions=int(args.get("max_sessions", 6)),
        )
        if pre_dropped and isinstance(result, dict):
            result.setdefault("dropped", [])
            result["dropped"] = pre_dropped + list(result["dropped"])
        out = {"plan": result, "not_found": missing + must_missing}
        if args.get("use_profile", True):
            out["home_base_travel"] = _home_base_travel(be, result, args.get("prefer") or "fastest")
        return out
    if name == "get_profile":
        from atlas import profile
        return profile.load_profile()
    if name == "update_profile":
        from atlas import profile
        updates = args.get("updates")
        if not isinstance(updates, dict) or not updates:
            raise ToolError("updates must be a non-empty object of profile fields.")
        try:
            return profile.update_profile(updates)
        except ValueError as e:
            raise ToolError(str(e)) from e
    if name == "get_my_schedule":
        return {"schedule": be.get_schedule()}
    if name == "add_favorites":
        ids = args.get("session_ids") or []
        if not ids:
            raise ToolError("session_ids is empty.")
        return {"result": be.add_favorites(ids)}
    raise ToolError(f"Unknown tool {name!r}.")


def _hm(value: str, ref_iso: str) -> "datetime":
    from datetime import datetime

    ref = datetime.fromisoformat(ref_iso)
    hh, mm = (value.strip().split(":") + ["0"])[:2]
    return ref.replace(hour=int(hh), minute=int(mm[:2]), second=0, microsecond=0)


def _apply_time_limits(be: Backend, sessions: list[dict], args: dict, must_ids: set[str]) -> tuple[list[dict], list[dict]]:
    """Drop candidates that overlap a blocked window or cannot get back to the hotel by back_by."""
    from datetime import datetime, timedelta

    from atlas import profile

    blocked = args.get("blocked") or []
    back_by = args.get("back_by")
    if not blocked and not back_by:
        return sessions, []
    home = (profile.load_profile().get("home_base") or {}).get("venue")
    keep, dropped = [], []
    for s in sessions:
        if not s.get("start") or not s.get("end"):
            keep.append(s)
            continue
        st, en = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
        reason = None
        for w in blocked:
            if w.get("start") and w.get("end") and st < _hm(w["end"], s["start"]) and en > _hm(w["start"], s["start"]):
                reason = f"overlaps blocked time {w['start']}-{w['end']} {w.get('label', '')}".strip()
                break
        if not reason and back_by:
            limit = _hm(back_by, s["start"])
            travel = 0.0
            if home and s.get("venue"):
                travel = float(be.route(s["venue"], home, depart_at=s["end"], prefer=args.get("prefer") or "fastest")["minutes"])
            if en + timedelta(minutes=travel) > limit:
                reason = f"ends {en:%H:%M} and needs about {travel:.0f} min back to the hotel, after the {back_by} limit"
        if reason and s["id"] in must_ids:
            reason += " (must-attend: kept, conflict flagged)"
            s = {**s, "conflict": reason}
            reason = None
        if reason:
            dropped.append({**_brief(s, 0), "reason": reason})
        else:
            keep.append(s)
    return keep, dropped


def _home_base_travel(be: Backend, plan: dict, prefer: str) -> dict | None:
    """Hotel -> first session and last session -> hotel, from the local profile. Estimates only."""
    from datetime import datetime, timedelta

    from atlas import profile

    home = (profile.load_profile().get("home_base") or {})
    chosen = (plan or {}).get("chosen") or []
    if not home.get("venue") or not chosen:
        return None if not home else {"note": home.get("note")}
    first, last = chosen[0], chosen[-1]
    out: dict[str, Any] = {"home_venue": home["venue"], "note": home.get("note")}
    if first.get("venue") and first.get("start"):
        probe = (datetime.fromisoformat(first["start"]) - timedelta(minutes=60)).isoformat()
        r = be.route(home["venue"], first["venue"], depart_at=probe, prefer=prefer)
        leave = datetime.fromisoformat(first["start"]) - timedelta(minutes=float(r["minutes"]) + 15)
        out["to_first"] = {"session": first.get("code"), "minutes": r["minutes"], "steps": r["steps"],
                           "modes": sorted({leg["mode"] for leg in r["legs"]}),
                           "leave_hotel_by": leave.isoformat(timespec="minutes"), "estimate": True}
    if last.get("venue") and last.get("end"):
        r = be.route(last["venue"], home["venue"], depart_at=last["end"], prefer=prefer)
        out["back_to_hotel"] = {"session": last.get("code"), "minutes": r["minutes"], "steps": r["steps"],
                                "modes": sorted({leg["mode"] for leg in r["legs"]}), "estimate": True}
    return out


def dispatch(name: str, args: dict | None, backend: Backend | None = None) -> tuple[dict, bool]:
    """Run one tool. Returns (json-serialisable result, ok). Never raises."""
    if name not in _SPEC_BY_NAME:
        return {"error": f"Unknown tool {name!r}."}, False
    args = args or {}
    missing = [k for k in _SPEC_BY_NAME[name]["input_schema"].get("required", []) if k not in args]
    if missing:
        return {"error": f"Missing required argument(s): {', '.join(missing)}"}, False
    try:
        be = backend or default_backend()
        result = _call(name, args, be)
        return json.loads(json.dumps(result, default=str)), True
    except ToolError as e:
        return {"error": str(e)}, False
    except Exception as e:  # backend failures (not signed in, network) go back to the model as text
        return {"error": f"{type(e).__name__}: {e}"}, False
