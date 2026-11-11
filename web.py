"""Local web app for re:Invent Nova Copilot.

    python3 web.py            # then open http://127.0.0.1:8500/

Binds 127.0.0.1 only. Rejects requests whose Host or Origin is not this server
(DNS-rebinding / cross-site protection) and accepts only JSON POST bodies.
Tokens stay in this process's memory; the browser never sees them.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from atlas.env import load_dotenv

load_dotenv()

from atlas import catalog, official_auth, profile, translate  # noqa: E402
from atlas.agent import Agent  # noqa: E402
from atlas.prompts import BRIEFING_SYSTEM_PROMPT  # noqa: E402

ROOT = Path(__file__).resolve().parent / "web"
EXPLORER_DIST = Path(__file__).resolve().parent / "explorer" / "ui" / "dist"
EXPLORER_PATHS = {"/app.js", "/app.css", "/maplibre-worker.js", "/translations.json",
                  "/api/catalog", "/api/auth/status", "/api/health"}
EXPLORER_CSP = ("default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self'; style-src-elem 'self'; "
                "style-src-attr 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; "
                "frame-src 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'")
RESERVED = {8484, 8485, 8486, 8487, 8488, 8489}  # OAuth loopback callbacks
MAX_BODY = 64 * 1024
RESTARTED_AT = time.time()

_state_lock = threading.Lock()
_state: dict = {"agent": None, "allow_write": False, "signed_in_once": False,
                "sign_in": {"running": False, "url": None, "error": None}}


def _agent() -> Agent:
    if _state["agent"] is None:
        _state["agent"] = Agent(confirm=lambda name, args: bool(_state["allow_write"]))
    return _state["agent"]


def _short(result, limit=1500):
    text = json.dumps(result, ensure_ascii=False, default=str)
    return result if len(text) <= limit else text[:limit] + "..."


def _status() -> dict:
    auth = official_auth.current_auth()
    status = auth.status() if auth else {}
    connected = bool(status.get("connected"))
    if connected:
        _state["signed_in_once"] = True
    expires_at = status.get("expires_at")
    now = time.time()
    seconds_left = max(0, int(expires_at - now)) if expires_at is not None else None
    refreshable = connected and bool(status.get("refreshable"))
    signed = connected and (expires_at is None or expires_at > now or refreshable)
    reason = (None if signed else "restarted" if not _state["signed_in_once"] else
              "expired" if connected and seconds_left == 0 else "sign_in_required")
    return {
        "signed_in": signed,
        "reason": reason,
        "expires_at": expires_at,
        "seconds_left": seconds_left,
        "restarted_at": RESTARTED_AT,
        "refreshable": refreshable,
        "auth_status": status.get("auth_status", "unauthenticated"),
        "catalog": "official AWS Events API (live)" if signed else "synthetic demo catalog",
        "model": os.environ.get("NOVA_MODEL_ID") or "us.amazon.nova-pro-v1:0",
        "profile": profile.load_profile()["profile"],
        "sign_in": dict(_state["sign_in"]),
        "explorer_url": _state.get("explorer_url"),
    }


def _start_sign_in(origin: str) -> dict:
    si = _state["sign_in"]
    if si["running"]:
        return _status()
    si.update(running=True, url=None, error=None)
    ready = threading.Event()

    def announce(msg: str) -> None:
        si["url"] = msg.rsplit("\n", 1)[-1].strip()
        ready.set()

    def run() -> None:
        try:
            official_auth.sign_in(open_browser=False, announce=announce, return_url=origin + "/?signin=complete")
            _state["signed_in_once"] = True
            catalog.clear_cache()
            from atlas import tools
            tools._official_cache["tools"] = None
        except Exception as e:  # report the code only, never secrets
            si["error"] = getattr(e, "code", type(e).__name__)
        finally:
            si["running"] = False
            ready.set()

    threading.Thread(target=run, daemon=True).start()
    ready.wait(10)
    return _status()


def _my_schedule() -> dict:
    """The signed-in attendee's official schedule (GetSchedule), resolved to sessions from the official catalog."""
    from datetime import datetime, timezone

    if not official_auth.is_signed_in():
        return {"signed_in": False}
    sched = catalog.get_schedule()

    def ids(items):
        out = []
        for x in items:
            sid = x if isinstance(x, str) else (x.get("sessionId") or x.get("session_id") or x.get("id")) if isinstance(x, dict) else None
            if sid:
                out.append(sid)
        return out

    def resolve(items):
        rows = []
        for sid in ids(items):
            s = catalog.get_session(sid)
            rows.append({k: s.get(k) for k in ("id", "code", "title", "start", "end", "venue", "venue_name", "room", "type")} if s
                        else {"id": sid, "title": "(not in the loaded catalog)"})
        return sorted(rows, key=lambda r: r.get("start") or "~")

    return {"signed_in": True, "source": "official AWS Events API GetSchedule",
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reserved": resolve(sched["reserved"]), "favorites": resolve(sched["favorites"]),
            "personal_time_count": len(sched["personalTime"])}


_MOVE_KEYS = ("start", "end", "room", "venue")


def _catalog_changes(before: dict, live: dict, reserved: list[str], reserved_then: list[str]) -> dict:
    """Catalog snapshot vs live official catalog: new session ids, current reservations that moved, and
    reservations (current or as of the snapshot; a cancelled one may also have left GetSchedule) no longer listed."""
    was_reserved = list(dict.fromkeys(reserved + reserved_then))
    return {
        "new": [sid for sid in live if sid not in before],
        "moved": [{"id": sid, "code": live[sid].get("code") or "",
                   "from": {k: before[sid].get(k) or "" for k in _MOVE_KEYS},
                   "to": {k: live[sid].get(k) or "" for k in _MOVE_KEYS}}
                  for sid in reserved if sid in before and sid in live
                  and any((before[sid].get(k) or "") != (live[sid].get(k) or "") for k in _MOVE_KEYS)],
        "cancelled": [{"id": sid, "code": before[sid].get("code") or ""} for sid in was_reserved if sid in before and sid not in live],
    }


def _recommend_new(new_ids: list[str], live: dict, limit: int = 10) -> list[dict]:
    """Up to `limit` new sessions matching the profile: one search per interest (then role), union in ranked order."""
    fields = profile.load_profile()["fields"]
    queries = list(fields.get("interests") or []) + ([fields["role"]] if fields.get("role") else [])
    level = str(fields.get("experience_level") or "")
    new, picked = set(new_ids), {}
    for q in queries:
        for s in catalog.search_sessions(query=str(q), levels=[level] if level else None, limit=len(live)):
            if s["id"] in new:
                picked.setdefault(s["id"], s)
    return list(picked.values())[:limit]


def _when(s: dict) -> str:
    from datetime import datetime

    start, end = s.get("start") or "", s.get("end") or ""
    return f"{datetime.fromisoformat(start):%a} {start[:10]} {start[11:16]}-{end[11:16]}" if start else "(no time)"


def _briefing() -> dict:
    """Welcome-back: compare the official schedule with the last saved snapshot, run the fixed checks in code, then
    ask Nova for a short summary in one request with no tools. If Bedrock fails, the facts come back on their own."""
    from atlas import guard, tools

    sched = _my_schedule() if official_auth.is_signed_in() else {"signed_in": False}
    live = None  # the catalog, only when it fully loaded from the official API (never the fixture or a fallback)
    if sched.get("signed_in"):
        sessions = catalog.load_sessions()
        if sessions and all(s.get("source") == "official_api" for s in sessions):  # the rows, not the global last_source()
            live = {s["id"]: s for s in sessions}

    def visit(state: dict):  # locked read-modify-write: never overwrites a plan saved meanwhile
        diff = changes = None
        if sched.get("signed_in"):
            now = {"reserved": [r["id"] for r in sched["reserved"]], "favorites": [r["id"] for r in sched["favorites"]]}
            before = state.get("schedule") or {}
            diff = {k: {"added": [i for i in now[k] if i not in (before.get(k) or [])],
                        "removed": [i for i in (before.get(k) or []) if i not in now[k]]} for k in now} if before else None
            state["schedule"] = now
            if live is not None:
                snapshot = profile.load_catalog_snapshot()
                if snapshot:
                    changes = _catalog_changes(snapshot["sessions"], live, now["reserved"], snapshot.get("reserved") or [])
                profile.save_catalog_snapshot(list(live.values()), now["reserved"])
        first_visit = not state.get("visits")
        state["visits"] = int(state.get("visits") or 0) + 1
        return diff, first_visit, changes

    diff, first_visit, changes = profile.update_state(visit)
    recommended = _recommend_new(changes["new"], live) if changes else []
    by_day: dict[str, list[str]] = {}
    for r in sched.get("reserved") or []:
        if r.get("start"):
            by_day.setdefault(r["start"][:10], []).append(r["id"])
    # The fixed steps, run by the server through the tools' own dispatcher (T11): the profile, then check_itinerary
    # once for every day with reservations. Nova used to choose these calls and sometimes checked one day or none.
    backend = _agent().backend
    calls: list[dict] = []

    def run(name: str, args: dict) -> tuple[dict, bool]:
        result, ok = tools.dispatch(name, args, backend)
        calls.append({"name": name, "input": args, "ok": ok, "result": result})
        return result, ok

    got, ok = run("get_profile", {})
    day_lines = [_day_check_line(day, *run("check_itinerary", {"session_ids": ids})) for day, ids in sorted(by_day.items())]
    # A reservation without a time in the loaded catalog has no day: it is left out of the day checks (which all
    # report it) and stated once, also when no reservation has a time.
    unplaced = list(dict.fromkeys([r["id"] for r in sched.get("reserved") or [] if not r.get("start")]
                                  + [i for c in calls if c["name"] == "check_itinerary" and c["ok"]
                                     for i in (c["result"].get("reservations_not_applied") or {}).get("ids") or []]))
    code_of = {c["id"]: c["code"] for c in (changes or {}).get("cancelled", []) if c.get("code")}
    left_out = (f"Left out of the travel checks: {', '.join(code_of.get(i, i) for i in unplaced)} "
                "(reserved, but without a time in the loaded catalog)." if unplaced else None)
    # At most one profile question, chosen here: the first planning detail still missing, in profile.PLANNING_PRIORITY order.
    saved = got["fields"] if ok else profile.load_profile()["fields"]
    words = {"hotel": "my hotel", "max_steps_per_day": "my daily walking limit", "arrival": "my arrival date",
             "departure": "my departure date", "interests": "the topics I am interested in", "role": "my job role",
             "experience_level": "my experience level", "transport": "how I prefer to get around"}
    gap = next((f for f in profile.PLANNING_PRIORITY if f not in saved), None)
    both_dates = gap == "arrival" and "departure" not in saved
    ask = "my arrival and departure dates" if both_dates else words.get(gap)
    facts = ([f"The complete list of sessions new in the official catalog since my last visit that match my profile: "
              + "; ".join(f'{s["code"]} "{s["title"]}" ({_when(s)}, {s.get("venue_name") or s.get("venue")})' for s in recommended) + ". "]
             if recommended else []) \
        + [f"My reservation {m['code']} moved from {_when(m['from'])}, {m['from']['room']}, {m['from']['venue']} "
           f"to {_when(m['to'])}, {m['to']['room']}, {m['to']['venue']}. " for m in (changes or {}).get("moved", [])] \
        + [f"My reservation {c['code']} is no longer in the official catalog. " for c in (changes or {}).get("cancelled", [])] \
        + ([f"My official favorites: " + "; ".join(f"{r.get('code') or r['id']} ({_when(r).strip('()')}, {r.get('venue') or ''})"
                                                   for r in sched["favorites"]) + ". "] if sched.get("favorites") else []) \
        + ([f"What my profile already says: {_saved_profile(saved)}. "] if _saved_profile(saved) else []) \
        + [f"My profile does not yet say {ask}. " if ask else "My profile has what you need for planning. "]
    # Only a real change is stated: an empty diff in the prompt ("changed: {...: []}") sent Nova Pro into a runaway
    # tool call on every first briefing after a restart ("invalid sequence as part of ToolUse", T9a round 3 replay).
    changed = diff if diff and any(v["added"] or v["removed"] for v in diff.values()) else None
    prompt = ("Brief me as I open the app (this is not a new question). "
              + ("This is my first visit. " if first_visit else f"Since my last visit my official schedule changed: {json.dumps(changed)}. " if changed else "")
              + "".join(facts)
              + ("Travel checks between my reserved sessions, one per conference day: " + " ".join(day_lines) + " "
                 if day_lines else "No travel was checked. " if unplaced else "I have no reserved sessions, so no travel was checked. ")
              + (left_out + " " if left_out else "")
              + "In under 120 words: 1) name any "
              + ("moved or cancelled reservation, " if changes and (changes["moved"] or changes["cancelled"]) else "")
              + "conflict or tight transition the checks found, "
              "2) recommend what to do next ("
              + ("the new sessions above, " if recommended else "")
              + "sessions to add on days with gaps, or what to fix), "
              + ("3) ask me for that one missing profile detail in one short line, and ask nothing else about my profile."
                 if ask else "3) ask me nothing about my profile."))
    # The panel's facts, written by code: shown with Nova's summary, and on their own when Nova fails.
    since = None if first_visit or diff is None else _since_line(changed, changes, recommended)
    profile_line = f"Your profile does not yet say {_yours(ask)}: tell me in the chat to plan around it." if ask else None
    facts_out = [line for line in [since, *day_lines, left_out, profile_line] if line]
    trace = [{**c, "confirmed": None, "by": "server"} for c in calls]
    agent = _agent()
    with _state_lock:  # one conversation at a time; Bedrock calls are serialised
        try:
            summary = agent.summarize(prompt, BRIEFING_SYSTEM_PROMPT, BRIEFING_MAX_TOKENS, feature="briefing")
            error = None
        except Exception as e:
            if type(e).__module__.split(".")[0] != "botocore":  # only Bedrock failures fall back; bugs still surface
                raise
            _log_failure("briefing", e, "model_unavailable")
            summary, error = "", "model_unavailable"
        removed: list[str] = []
        if summary:
            from atlas import format as answer_format

            text, removed = guard.strip_unverified_feasibility(answer_format.format_answer(summary, trace, prompt), trace)
        else:
            error = "model_unavailable"
            text = "\n".join(facts_out + [BRIEFING_FALLBACK_NOTE])
        agent.remember(prompt, text)
    out = {"text": text, "removed": removed, "rounds": 0, "plan": None,
           "trace": [{**c, "result": _short(c["result"])} for c in trace],
           "suggested": _suggested(SimpleNamespace(text=text, trace=[SimpleNamespace(**c) for c in trace])),
           "facts": facts_out, "status": _status(), "schedule_diff": diff, "first_visit": first_visit,
           "catalog_diff": {"new": len(changes["new"]), "moved": changes["moved"], "cancelled": changes["cancelled"],
                            "recommended": [s["code"] for s in recommended]} if changes else None}
    if error:
        out.update(error=error, message=BRIEFING_FALLBACK_NOTE)
    return out


# 120 words is about 160 English tokens, or up to about 240 when the profile language is Chinese; 500 leaves room.
BRIEFING_MAX_TOKENS = 500
BRIEFING_FALLBACK_NOTE = ("Nova's summary is missing right now; these lines come straight from your official schedule "
                          "and the travel checks.")


def _saved_profile(fields: dict) -> str:
    """The saved details that shape a plan, as short facts. Worded without the names of the profile questions (T9a: only the one
    question chosen in code may name a missing item)."""
    def text(v):
        return ", ".join(map(str, v)) if isinstance(v, list) else str(v)

    arrival, departure = fields.get("arrival"), fields.get("departure")
    stay = (f"here from {arrival} to {departure}" if arrival and departure else
            f"here from {arrival}" if arrival else f"here until {departure}" if departure else None)
    parts = [f"hotel {fields['hotel']}" if fields.get("hotel") else None,
             f"at most {fields['max_steps_per_day']} steps a day" if fields.get("max_steps_per_day") else None,
             stay,
             f"interests {text(fields['interests'])}" if fields.get("interests") else None,
             f"role {fields['role']}" if fields.get("role") else None,
             f"level {fields['experience_level']}" if fields.get("experience_level") else None,
             f"transport {text(fields['transport'])}" if fields.get("transport") else None,
             f"goals {text(fields['goals'])}" if fields.get("goals") else None,
             f"mobility {text(fields['mobility'])}" if fields.get("mobility") else None,
             f"fixed commitments {text(fields['fixed_commitments'])}" if fields.get("fixed_commitments") else None,
             f"special arrangements {text(fields['special_arrangements'])}" if fields.get("special_arrangements") else None,
             f"diet {text(fields['diet'])}" if fields.get("diet") else None,
             f"preferred language for answers {fields['language']}" if fields.get("language") else None]
    return "; ".join(p for p in parts if p)


def _yours(phrase: str) -> str:
    """The attendee's own words in the briefing prompt ("my hotel") as the panel says them ("your hotel")."""
    return phrase.replace("my ", "your ").replace("I am", "you are").replace(" I ", " you ")


def _day_check_line(day: str, result: dict, ok: bool) -> str:
    """What the server's check_itinerary found for one reserved day, as one line."""
    from datetime import date

    label = f"{date.fromisoformat(day):%a} {day}"
    if not ok:
        return f"{label}: the reservations could not be checked."
    rows = [f"{s.get('code') or s.get('id')} {(s.get('start') or '')[11:16]}-{(s.get('end') or '')[11:16]} {s.get('venue') or ''}".strip()
            for s in result.get("sessions") or []]
    found, buffer = [], (result.get("check") or {}).get("buffer_min")
    for t in (result.get("check") or {}).get("transitions") or []:
        a, b, status = t.get("from"), t.get("to"), t.get("status")
        if status == "overlap":
            found.append(f"conflict, {a} overlaps {b}")
        elif status == "not_enough_time":
            found.append(f"conflict, {a} to {b} has {t.get('gap_minutes')} min for {t.get('travel_minutes')} min of travel "
                         f"plus a {buffer} min buffer")
        elif status == "tight":
            found.append(f"tight transition {a} to {b} ({t.get('travel_minutes')} min of travel, {t.get('slack_minutes')} min to spare)")
    return (f"{label}, {len(rows)} reserved ({', '.join(rows)}): "
            + ("; ".join(found) if found else "no conflicts or tight transitions"
               + (" among the sessions checked" if result.get("reservations_not_applied") else "")) + ".")


def _since_line(changed: dict | None, changes: dict | None, recommended: list[dict]) -> str:
    """Since the last visit: the official schedule diff and the catalog changes, as one line."""
    parts = [f"{key} +{len(v['added'])}/−{len(v['removed'])}" for key, v in (changed or {}).items() if v["added"] or v["removed"]]
    for m in (changes or {}).get("moved", []):
        parts.append(f"{m['code']} moved to {_when(m['to'])}, {m['to']['room']}, {m['to']['venue']}")
    parts += [f"{c['code']} is no longer in the official catalog" for c in (changes or {}).get("cancelled", [])]
    if (changes or {}).get("new"):
        n = len(changes["new"])
        parts.append(f"{n} new session{'' if n == 1 else 's'} in the catalog"
                     + (f", matching your profile: {', '.join(s['code'] for s in recommended)}" if recommended else ""))
    return "Since your last visit: " + "; ".join(parts) + "." if parts else "Nothing changed in your official schedule since your last visit."


def _suggested(res) -> list[dict]:
    """Sessions to offer RSVP/favorite buttons for: the plan's picks, else sessions the answer cites by code."""
    plan_rows, seen_rows = [], {}
    for call in res.trace:
        r = call.result if isinstance(call.result, dict) else {}
        if call.name == "plan_itinerary" and call.ok:
            plan_rows = (r.get("plan") or {}).get("chosen") or []
        for s in (r.get("sessions") or []) + ([r["session"]] if isinstance(r.get("session"), dict) else []):
            if isinstance(s, dict) and s.get("code"):
                seen_rows[s["code"]] = s
    rows = plan_rows or [s for code, s in seen_rows.items() if code in (res.text or "")]
    be = getattr(_state["agent"], "backend", None)  # the catalog the tools just used

    def seats(s):  # plan rows carry no seat band: take it from a search row in this trace, else the catalog
        found = s.get("seats") or seen_rows.get(s.get("code"), {}).get("seats")
        if not found and s.get("id"):
            try:
                found = ((be.get_session if be else catalog.get_session)(s["id"]) or {}).get("seats")
            except Exception:  # seat words are optional; never fail the answer for them
                found = ""
        return found or ""

    return [{**{k: s.get(k) for k in ("id", "code", "title", "start", "end", "venue")}, "seats": seats(s)}
            for s in rows[:10]]


def _chat(message: str, allow_write: bool, feature: str = "chat") -> dict:
    with _state_lock:  # one conversation at a time; Bedrock calls are serialised
        agent = _agent()
        previous_feature = agent.feature
        _state["allow_write"] = allow_write
        agent.feature = feature
        try:
            res = agent.ask(message)
        finally:
            agent.feature = previous_feature
            _state["allow_write"] = False
    from atlas import format as answer_format

    plan = None
    for call in res.trace:
        if call.name == "plan_itinerary" and call.ok:
            plan = call.result
    return {
        "text": answer_format.format_answer(res.text, res.trace, message),
        "rounds": res.rounds,
        "trace": [{"name": c.name, "input": c.input, "ok": c.ok, "confirmed": c.confirmed, "result": _short(c.result)}
                  for c in res.trace],
        "plan": plan,
        "suggested": _suggested(res),
        "status": _status(),
    }


# "My plan" (我的安排) lives on the server, never in browser storage: official reserved and favorite
# sessions read live from GetSchedule, plus local picks saved in the profile state file (key "plan").
MAX_LOCAL_PLAN = 500
MAX_PLAN_CHANGE = 50
_ATLAS_SOURCE = {"official_api": "aws_events_api"}  # Event Atlas's name for the official catalog


def _schedule_ids(items) -> list[str]:
    out = []
    for x in items:
        sid = x if isinstance(x, str) else (x.get("sessionId") or x.get("session_id") or x.get("id")) if isinstance(x, dict) else None
        if isinstance(sid, str) and sid and sid not in out:
            out.append(sid)
    return out


def _compact(value) -> str:
    """JSON text identical to the browser's JSON.stringify, so placements match Event Atlas's records."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _plan_item(sid: str, source: str, added_at: str, sessions: dict) -> dict:
    """One plan entry in Event Atlas's plan-item format, plus session_id and source (reserved | favorite | local)."""
    s = sessions.get(sid)
    if not s:
        return {"placement": _compact(["aws_events_api", sid, None, None]), "key": _compact(["aws_events_api", sid]),
                "session_id": sid, "code": sid, "title": "(not in the loaded catalog)", "start": "", "end": "",
                "location": "", "addedAt": added_at, "source": source}
    src = _ATLAS_SOURCE.get(s.get("source"), str(s.get("source") or ""))
    start, end = s.get("start") or None, s.get("end") or None
    return {"placement": _compact([src, sid, start, end]), "key": _compact([src, sid]), "session_id": sid,
            "code": str(s.get("code") or ""), "title": str(s.get("title") or ""), "start": start or "", "end": end or "",
            "location": str(s.get("room") or s.get("venue_name") or ""), "addedAt": added_at, "source": source}


def _local_picks(state: dict) -> list[dict]:
    plan = state.get("plan") if isinstance(state.get("plan"), dict) else {}
    return [x for x in plan.get("local") or [] if isinstance(x, dict) and isinstance(x.get("session_id"), str)]


def _plan() -> dict:
    from datetime import datetime, timezone

    sessions = {s["id"]: s for s in catalog.load_sessions()}
    reserved, favorites, official = [], [], {"status": "signed_out"}
    if official_auth.is_signed_in():
        try:
            sched = catalog.get_schedule()
            reserved, favorites = _schedule_ids(sched["reserved"]), _schedule_ids(sched["favorites"])
            official = {"status": "live", "read_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        except Exception as e:  # local picks still show; report the code only
            code = _error_code(e) or "server_error"
            _log_failure("plan official read", e, code)
            official = {"status": "error", "error": code}
    items, seen = [], set()
    for source, rows in (("reserved", [(i, "") for i in reserved]), ("favorite", [(i, "") for i in favorites]),
                         ("local", [(x["session_id"], str(x.get("added_at") or "")) for x in _local_picks(profile.read_state())])):
        for sid, added_at in rows:
            if sid not in seen:
                seen.add(sid)
                items.append(_plan_item(sid, source, added_at, sessions))
    items.sort(key=lambda r: r["start"] or "~")
    counts = {k: sum(1 for r in items if r["source"] == k) for k in ("reserved", "favorite", "local")}
    return {"version": 1, "items": items, "counts": counts, "official": official}


def _change_plan(action, session_ids) -> dict:
    """Add or remove local picks by session id. Official reservations and favorites change only in AWS Events."""
    from datetime import datetime, timezone

    if action not in ("add", "remove"):
        raise ValueError("action must be 'add' or 'remove'")
    ids = list(dict.fromkeys(i for i in session_ids if isinstance(i, str) and 0 < len(i) <= 128))
    if not 1 <= len(ids) <= MAX_PLAN_CHANGE:
        raise ValueError(f"give 1 to {MAX_PLAN_CHANGE} session ids")
    if action == "add":
        known = {s["id"] for s in catalog.load_sessions()}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise ValueError(f"session id(s) not in the loaded catalog: {unknown}")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def change(state: dict) -> int:
        local = _local_picks(state)
        before = len(local)
        if action == "add":
            have = {x["session_id"] for x in local}
            local += [{"session_id": i, "added_at": now} for i in ids if i not in have]
            if len(local) > MAX_LOCAL_PLAN:
                raise ValueError(f"the local plan holds at most {MAX_LOCAL_PLAN} sessions")
        else:
            local = [x for x in local if x["session_id"] not in ids]
        state["plan"] = {"version": 1, "local": local}
        return abs(len(local) - before)

    changed = profile.update_state(change)
    return {**_plan(), "changed": changed}


# Failures the attendee can act on, as a short code and one plain sentence. Exception text never reaches the UI.
_ERRORS = {
    "signin_expired": (401, "Your AWS Events sign-in has expired. Sign in again from the top of the page."),
    "forbidden": (403, "AWS Events refused this request for your account."),
    "rate_limited": (429, "AWS Events is busy. Wait a minute and try again."),
    "model_unavailable": (503, "Nova is unavailable right now. Your plan and the official schedule are unaffected; "
                               "try again shortly."),
    "server_error": (500, "Something went wrong on this computer's Nova Copilot service. "
                          "Try again; if it repeats, restart it."),
}
_OFFICIAL_ERRORS = {"official_sign_in_required": "signin_expired", "official_event_access_required": "forbidden",
                    "official_rate_limited": "rate_limited"}
_HTTP_ERRORS = {401: "signin_expired", 403: "forbidden", 429: "rate_limited"}


def _error_code(e: Exception) -> str | None:
    """The _ERRORS code for a failure, or None when it is not one of the known kinds."""
    from urllib.error import HTTPError

    if isinstance(e, HTTPError):
        return _HTTP_ERRORS.get(e.code)
    if isinstance(e, catalog.CatalogError):
        return _OFFICIAL_ERRORS.get(e.code)
    if isinstance(e, official_auth.OAuthError):
        return "signin_expired" if e.terminal or e.code == "sign_in_required" else None
    if type(e).__module__.split(".")[0] == "botocore":  # Bedrock: ClientError, NoCredentialsError, connection errors
        return "model_unavailable"
    return None


_LOGGED_MESSAGES = {"ModelErrorException", "ValidationException"}  # Bedrock errors whose message says what went wrong
_TOKEN_LIKE = re.compile(r"[A-Za-z0-9+/=_.\-]{24,}")


def _log_failure(route: str, e: Exception, code: str) -> None:
    """The "nova-copilot" line: exception class and fixed public code only. Never a token, credentials or request body.

    For Bedrock ModelErrorException / ValidationException a second line, "bedrock-message", carries the first 300
    characters of Bedrock's own message with token-like runs redacted: the T9a briefing failure could not be
    diagnosed from the class alone."""
    detail = getattr(e, "code", None)
    message = None
    if type(e).__module__.split(".")[0] == "botocore":
        error = (getattr(e, "response", None) or {}).get("Error") or {}
        detail = error.get("Code")
        if detail in _LOGGED_MESSAGES and isinstance(error.get("Message"), str):
            message = _TOKEN_LIKE.sub("[redacted]", " ".join(error["Message"].split()))[:300]  # redact, then cut
    detail = f" ({detail})" if isinstance(detail, (str, int)) and str(detail).replace("_", "").isalnum() else ""
    print(f"nova-copilot {route}: {type(e).__name__}{detail} -> {code}", file=sys.stderr, flush=True)
    if message:
        print(f"bedrock-message {route}: {message}", file=sys.stderr, flush=True)


# Official outcomes that already read well keep their own code and fixed sentence (atlas.catalog._MESSAGES).
_KEPT_OFFICIAL = {"official_event_not_found": 404, "official_operation_closed": 409}


def _failure(route: str, e: Exception) -> tuple[int, dict]:
    if isinstance(e, catalog.CatalogError) and e.code in _KEPT_OFFICIAL:
        _log_failure(route, e, e.code)
        return _KEPT_OFFICIAL[e.code], {"error": e.code, "message": catalog._MESSAGES[e.code]}
    code = _error_code(e) or "server_error"
    _log_failure(route, e, code)
    status, message = _ERRORS[code]
    return status, {"error": code, "message": message}


class Handler(BaseHTTPRequestHandler):
    server_version = "NovaCopilot"

    def log_message(self, fmt, *args):  # keep request bodies and URLs out of logs
        pass

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in allowed:
            return False
        origin = self.headers.get("Origin")
        return origin is None or origin in {f"http://{h}" for h in allowed}

    def _origin(self) -> str:
        """Origin to return to after sign-in: the validated loopback origin that started it (no open redirect)."""
        port = self.server.server_address[1]
        origin = self.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        return origin if origin in allowed else f"http://{self.headers.get('Host')}" if self._host_ok() else f"http://127.0.0.1:{port}"

    def _send(self, code: int, body: bytes, ctype: str, csp: bool = False) -> None:
        self.send_response(code)
        if csp:
            self.send_header("Content-Security-Policy", EXPLORER_CSP)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

    def _proxy_explorer(self) -> None:
        """Serve Event Atlas assets and read APIs from the in-process explorer server (same origin for the user)."""
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen

        port = _state.get("explorer_port")
        if not port:
            return self._json(404, {"error": "explorer disabled"})
        req = Request(f"http://127.0.0.1:{port}{self.path}", headers={"Host": f"127.0.0.1:{port}"})
        try:
            with urlopen(req, timeout=60) as r:
                body, code, ctype = r.read(), r.status, r.headers.get("Content-Type", "application/octet-stream")
        except HTTPError as e:
            body, code, ctype = e.read(), e.code, e.headers.get("Content-Type", "application/json")
        self._send(code, body, ctype)

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        path_only = self.path.split("?", 1)[0]
        if path_only.startswith("/api/translate/"):
            from urllib.parse import parse_qs, unquote, urlsplit

            try:
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                lang = (query["lang"][0] if "lang" in query else
                        profile.load_profile()["fields"].get("language") or "zh-Hant")
                result = translate.translate_session(unquote(path_only[len("/api/translate/"):]), lang)
                return self._json(200, result)
            except ValueError as e:
                return self._json(400, {"error": str(e)})
            except translate.TranslationError as e:
                return self._json(404 if e.code == "session_not_found" else 502, {"error": e.code})
            except Exception as e:  # Never expose Bedrock errors or credential details.
                if _error_code(e):
                    return self._json(*_failure("translate", e))
                _log_failure("translate", e, "translation_unavailable")
                return self._json(502, {"error": "translation_unavailable"})
        if path_only in ("/", "/index.html"):
            if not (_state.get("explorer_port") and (EXPLORER_DIST / "index.html").is_file()):
                return self._send(503, b"Event Atlas is not built. Build it with: cd explorer/ui && node build.mjs\n",
                                  "text/plain; charset=utf-8")
            html = (EXPLORER_DIST / "index.html").read_text(encoding="utf-8")
            html = html.replace("</head>", '<link rel="stylesheet" href="/copilot.css" />\n</head>', 1)
            html = html.replace("</body>", '<script src="/copilot.js" defer></script>\n</body>', 1)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8", csp=True)
        if self.path in ("/copilot.js", "/copilot.css"):
            ctype = "text/javascript; charset=utf-8" if self.path.endswith(".js") else "text/css; charset=utf-8"
            return self._send(200, (ROOT / self.path[1:]).read_bytes(), ctype)
        if self.path in EXPLORER_PATHS or self.path.startswith("/geo/"):
            return self._proxy_explorer()
        if self.path == "/api/status":
            return self._json(200, _status())
        if self.path == "/api/my-schedule":
            try:
                return self._json(200, _my_schedule())
            except Exception as e:
                status, body = _failure("my-schedule", e)
                return self._json(status, {"signed_in": official_auth.is_signed_in(), **body})
        if self.path == "/api/profile":
            return self._json(200, {**profile.load_profile(), "fields_help": profile.FIELDS})
        if path_only == "/api/plan":
            try:
                return self._json(200, _plan())
            except Exception as e:
                return self._json(*_failure("plan", e))
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._json(403, {"error": "forbidden host"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"error": "JSON only"})
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json(413, {"error": "too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad JSON"})
        try:
            if self.path == "/api/chat":
                msg = str(body.get("message") or "").strip()
                if not msg:
                    return self._json(400, {"error": "empty message"})
                return self._json(200, _chat(msg[:4000], bool(body.get("allow_write"))))
            if self.path in ("/api/rsvp", "/api/favorite"):
                ids = [i for i in (body.get("session_ids") or []) if isinstance(i, str)]
                fn = catalog.reserve_sessions if self.path == "/api/rsvp" else catalog.add_favorites
                return self._json(200, fn(ids))
            if self.path == "/api/rsvp/cancel":  # click-only, like /api/rsvp; never a model tool
                ids = [i for i in (body.get("session_ids") or []) if isinstance(i, str)]
                return self._json(200, catalog.cancel_reservations(ids))
            if self.path == "/api/briefing":
                return self._json(200, _briefing())
            if self.path == "/api/reset":
                if _state["agent"]:
                    _state["agent"].reset()
                return self._json(200, {"ok": True})
            if self.path == "/api/auth/start":  # Event Atlas sign-in button: same shared login
                st = _start_sign_in(self._origin())
                if not st["sign_in"]["url"]:
                    return self._json(503, {"error": "callback_unavailable"})
                return self._json(200, {"authorization_url": st["sign_in"]["url"]})
            if self.path == "/api/plan":
                ids = body.get("session_ids") if isinstance(body.get("session_ids"), list) else [body.get("session_id")]
                return self._json(200, _change_plan(body.get("action"), ids))
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            return self._json(*_failure(self.path.split("?", 1)[0].removeprefix("/api/"), e))
        return self._json(404, {"error": "not found"})


def start_explorer(port: int) -> None:
    """Run Event Atlas (agenda explorer, calendars, 3D campus) in this process, sharing the copilot's sign-in."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent / "explorer"))
    import server as atlas_server  # explorer/server.py
    from official_catalog import OfficialCatalog  # explorer/official_catalog.py

    class SharedConnection(atlas_server.OfficialConnection):
        """Event Atlas connection backed by the copilot's in-memory login (one sign-in for both views)."""

        def status(self):
            auth = official_auth.current_auth()
            base = auth.status() if auth else {"connected": False, "auth_status": "unauthenticated",
                                                "pending_sign_in": bool(_state["sign_in"]["running"]),
                                                "error": None, "expires_at": None, "memory_only": True}
            return {"provider": "aws_events_api", **base, "callback_available": True, "memory_only": True}

        def access_token(self):
            return official_auth.get_access_token()

        def start(self, origin=None):
            st = _start_sign_in(origin or f"http://127.0.0.1:{_state.get('port', 8500)}")
            if not st["sign_in"]["url"]:
                raise atlas_server.OAuthError("sign_in_required")
            return {"authorization_url": st["sign_in"]["url"]}

    srv = atlas_server.ExclusiveHTTPServer(("127.0.0.1", port), atlas_server.SpatialHandler)
    srv.connection = SharedConnection(port)
    srv.catalog = OfficialCatalog(official_auth.get_access_token)
    srv.connection.catalog = srv.catalog
    srv.static_root = Path(__file__).resolve().parent / "explorer" / "ui" / "dist"
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main() -> None:
    p = argparse.ArgumentParser(description="re:Invent Nova Copilot web app (local)")
    p.add_argument("--port", type=int, default=8500)
    p.add_argument("--explorer-port", type=int, default=8493, help="Internal Event Atlas port, proxied through --port (0 disables it)")
    p.add_argument("--profile", default=None, help="Attendee profile name (default: 'default')")
    a = p.parse_args()
    if a.port in RESERVED:
        raise SystemExit(f"Port {a.port} is reserved for the OAuth callback; pick another.")
    if a.profile:
        os.environ["ATLAS_PROFILE"] = a.profile
    _state["port"] = a.port
    if a.explorer_port in RESERVED | {8490, 8491, 8492}:
        raise SystemExit(f"Port {a.explorer_port} is reserved; pick another.")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    if a.explorer_port:
        start_explorer(a.explorer_port)
        _state["explorer_port"] = a.explorer_port
        _state["explorer_url"] = f"http://127.0.0.1:{a.port}/"
    print(f"re:Invent Nova Copilot + Event Atlas: http://127.0.0.1:{a.port}/   Ctrl-C to stop")
    srv.serve_forever()


if __name__ == "__main__":
    main()
