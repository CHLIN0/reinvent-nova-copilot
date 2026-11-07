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
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from atlas.env import load_dotenv

load_dotenv()

from atlas import catalog, official_auth, profile  # noqa: E402
from atlas.agent import Agent  # noqa: E402

ROOT = Path(__file__).resolve().parent / "web"
EXPLORER_DIST = Path(__file__).resolve().parent / "explorer" / "ui" / "dist"
EXPLORER_PATHS = {"/app.js", "/app.css", "/maplibre-worker.js", "/translations.json",
                  "/api/catalog", "/api/auth/status", "/api/health"}
EXPLORER_CSP = ("default-src 'self'; script-src 'self'; worker-src 'self'; style-src 'self'; style-src-elem 'self'; "
                "style-src-attr 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; "
                "frame-src 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'")
RESERVED = {8484, 8485, 8486, 8487, 8488, 8489}  # OAuth loopback callbacks
MAX_BODY = 64 * 1024

_state_lock = threading.Lock()
_state: dict = {"agent": None, "allow_write": False, "sign_in": {"running": False, "url": None, "error": None}}


def _agent() -> Agent:
    if _state["agent"] is None:
        _state["agent"] = Agent(confirm=lambda name, args: bool(_state["allow_write"]))
    return _state["agent"]


def _short(result, limit=1500):
    text = json.dumps(result, ensure_ascii=False, default=str)
    return result if len(text) <= limit else text[:limit] + "..."


def _status() -> dict:
    signed = official_auth.is_signed_in()
    return {
        "signed_in": signed,
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


def _briefing() -> dict:
    """Welcome-back: compare the official schedule with the last saved snapshot, then ask Nova for a short plan."""
    sched = _my_schedule() if official_auth.is_signed_in() else {"signed_in": False}

    def visit(state: dict):  # locked read-modify-write: never overwrites a plan saved meanwhile
        diff = None
        if sched.get("signed_in"):
            now = {"reserved": [r["id"] for r in sched["reserved"]], "favorites": [r["id"] for r in sched["favorites"]]}
            before = state.get("schedule") or {}
            diff = {k: {"added": [i for i in now[k] if i not in (before.get(k) or [])],
                        "removed": [i for i in (before.get(k) or []) if i not in now[k]]} for k in now} if before else None
            state["schedule"] = now
        first_visit = not state.get("visits")
        state["visits"] = int(state.get("visits") or 0) + 1
        return diff, first_visit

    diff, first_visit = profile.update_state(visit)
    prompt = ("Brief me as I open the app (this is not a new question). Call get_profile and get_my_schedule. "
              + ("This is my first visit. " if first_visit else f"Since my last visit my official schedule changed: {json.dumps(diff)}. " if diff else "")
              + "In under 120 words: 1) check_itinerary on my reserved sessions day by day and name any conflict or tight transition, "
              "2) recommend what to do next (sessions to add on days with gaps, or what to fix), "
              "3) if my profile is missing my hotel or walking limit, ask for it in one line.")
    out = _chat(prompt, allow_write=False)
    out["schedule_diff"] = diff
    out["first_visit"] = first_visit
    return out


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
    return [{k: s.get(k) for k in ("id", "code", "title", "start", "end", "venue")} for s in rows][:10]


def _chat(message: str, allow_write: bool) -> dict:
    with _state_lock:  # one conversation at a time; Bedrock calls are serialised
        _state["allow_write"] = allow_write
        try:
            res = _agent().ask(message)
        finally:
            _state["allow_write"] = False
    plan = None
    for call in res.trace:
        if call.name == "plan_itinerary" and call.ok:
            plan = call.result
    return {
        "text": res.text,
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
            official = {"status": "error", "error": getattr(e, "code", type(e).__name__)}
    items, seen = [], set()
    for source, rows in (("reserved", [(i, "") for i in reserved]), ("favorite", [(i, "") for i in favorites]),
                         ("local", [(x["session_id"], str(x.get("added_at") or "")) for x in _local_picks(profile.load_state())])):
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
        if path_only in ("/", "/index.html") and _state.get("explorer_port"):
            html = (EXPLORER_DIST / "index.html").read_text(encoding="utf-8")
            html = html.replace("</head>", '<link rel="stylesheet" href="/copilot.css" />\n</head>', 1)
            html = html.replace("</body>", '<script src="/copilot.js" defer></script>\n</body>', 1)
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8", csp=True)
        if self.path in ("/copilot.js", "/copilot.css"):
            ctype = "text/javascript; charset=utf-8" if self.path.endswith(".js") else "text/css; charset=utf-8"
            return self._send(200, (ROOT / self.path[1:]).read_bytes(), ctype)
        if self.path in EXPLORER_PATHS or self.path.startswith("/geo/"):
            return self._proxy_explorer()
        if self.path in ("/", "/index.html", "/copilot"):
            return self._send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self._json(200, _status())
        if self.path == "/api/my-schedule":
            try:
                return self._json(200, _my_schedule())
            except Exception as e:
                return self._json(502, {"signed_in": official_auth.is_signed_in(), "error": getattr(e, "code", type(e).__name__)})
        if self.path == "/api/profile":
            return self._json(200, {**profile.load_profile(), "fields_help": profile.FIELDS})
        if path_only == "/api/plan":
            try:
                return self._json(200, _plan())
            except Exception as e:
                return self._json(500, {"error": getattr(e, "code", type(e).__name__)})
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
            if self.path == "/api/briefing":
                return self._json(200, _briefing())
            if self.path == "/api/reset":
                if _state["agent"]:
                    _state["agent"].reset()
                return self._json(200, {"ok": True})
            if self.path == "/api/signin":
                return self._json(200, _start_sign_in(self._origin()))
            if self.path == "/api/auth/start":  # Event Atlas sign-in button: same shared login
                st = _start_sign_in(self._origin())
                if not st["sign_in"]["url"]:
                    return self._json(503, {"error": "callback_unavailable"})
                return self._json(200, {"authorization_url": st["sign_in"]["url"]})
            if self.path == "/api/plan":
                ids = body.get("session_ids") if isinstance(body.get("session_ids"), list) else [body.get("session_id")]
                return self._json(200, _change_plan(body.get("action"), ids))
            if self.path == "/api/profile":
                updates = body.get("updates") or {}
                return self._json(200, profile.update_profile(updates))
        except ValueError as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
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
    print(f"re:Invent Nova Copilot + Event Atlas: http://127.0.0.1:{a.port}/   (chat-only view: /copilot)  Ctrl-C to stop")
    srv.serve_forever()


if __name__ == "__main__":
    main()
