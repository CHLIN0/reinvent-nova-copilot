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
            },
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
        result = be.plan_itinerary(
            list(by_id.values()),
            must=[s["id"] for s in must_sessions],
            day=args.get("day"),
            prefer=args.get("prefer") or "fastest",
            buffer_min=int(args.get("buffer_min", 10)),
            max_sessions=int(args.get("max_sessions", 6)),
        )
        return {"plan": result, "not_found": missing + must_missing}
    if name == "get_my_schedule":
        return {"schedule": be.get_schedule()}
    if name == "add_favorites":
        ids = args.get("session_ids") or []
        if not ids:
            raise ToolError("session_ids is empty.")
        return {"result": be.add_favorites(ids)}
    raise ToolError(f"Unknown tool {name!r}.")


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
