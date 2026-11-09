"""Session catalog: official AWS Events REST API (live) or a synthetic fixture.

Adapted from the verified event-atlas adapter. The official API has no
server-side search, so ``search_sessions`` filters locally after a full,
paginated ListSessions read (pagination runs until ``nextToken`` is absent).
The bearer token is fetched per request from ``official_auth`` and never logged,
cached here, or included in errors.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import official_auth

ORIGIN = "https://api.awsevents.com"
EVENT_ID = "reinvent2026"
FIXTURE_PATH = Path(__file__).resolve().parent.parent / "data" / "fixture_sessions.json"
LOCAL_ZONE = ZoneInfo("America/Los_Angeles")
REQUEST_TIMEOUT = 15.0
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_PAGES = 200
MAX_429_RETRIES = 3
MAX_RETRY_AFTER = 30.0
LIVE_CACHE_SECONDS = 300.0
TOPIC_FIELDS = ("topics", "tracks", "areasOfInterest", "services", "focusAreas")

# Canonical venue keys shared with atlas.routing.VENUES. Order matters:
# "caesars forum" must win over "caesars palace", "encore" over "wynn".
_VENUE_PATTERNS = (
    ("caesars_forum", ("caesars forum",)),
    ("caesars_palace", ("caesars palace",)),
    ("encore", ("encore",)),
    ("wynn", ("wynn",)),
    ("venetian", ("venetian", "palazzo")),
    ("mgm_grand", ("mgm grand", "mgm")),
    ("mandalay_bay", ("mandalay",)),
)


class CatalogError(Exception):
    """Fixed public code only; upstream bodies and token values never appear here."""

    def __init__(self, code, retry_after=None, message=None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(message or code)


_MESSAGES = {
    "official_sign_in_required": "Not signed in or token expired (401). Run sign-in again.",
    "official_event_access_required": "Signed in but not registered for this event (403).",
    "official_event_not_found": "Event or session not found (404).",
    "official_rate_limited": "Rate limited by the AWS Events API (429) after retries.",
    "official_operation_closed": "AWS Events has closed this operation for now (409); retrying will not help yet.",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def _http(method, path, query, body, token):
    """Default transport -> (status, headers, bytes). Tests replace ``_transport``."""
    url = ORIGIN + path + ("?" + urlencode(query) if query else "")
    headers = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read(MAX_PAGE_BYTES + 1)
            if len(raw) > MAX_PAGE_BYTES:
                raise CatalogError("catalog_too_large")
            return response.status, {k: v for k, v in response.headers.items()}, raw
    except HTTPError as error:
        try:
            return error.code, {"Retry-After": error.headers.get("Retry-After")}, b""
        finally:
            error.close()
    except (URLError, OSError, ValueError):
        raise CatalogError("catalog_unavailable") from None


_transport = _http
_sleep = time.sleep


def _retry_after(headers):
    for key, value in (headers or {}).items():
        if key.lower() == "retry-after" and value is not None:
            try:
                seconds = float(value)
            except (TypeError, ValueError):
                return 1.0
            if math.isfinite(seconds) and seconds >= 0:
                return seconds
    return 1.0


def _request(method, path, query=None, body=None, authenticated=True, response_headers=None):
    """One API call with 401/403 mapping and Retry-After-aware 429 retries."""
    for attempt in range(MAX_429_RETRIES + 1):
        token = None
        if authenticated:
            try:
                token = official_auth.get_access_token()
            except official_auth.OAuthError as error:
                code = ("official_sign_in_required"
                        if error.terminal or error.code == "sign_in_required" else "catalog_unavailable")
                raise CatalogError(code, message=_MESSAGES.get(code)) from None
        try:
            status, headers, raw = _transport(method, path, query, body, token)
        finally:
            token = None
        if status == 429:
            wait = _retry_after(headers)
            if attempt < MAX_429_RETRIES and wait <= MAX_RETRY_AFTER:
                _sleep(wait)
                continue
            raise CatalogError("official_rate_limited", retry_after=wait,
                               message=_MESSAGES["official_rate_limited"])
        if status == 401:
            auth = official_auth.current_auth()
            if auth is not None:
                auth.invalidate()
            raise CatalogError("official_sign_in_required", message=_MESSAGES["official_sign_in_required"])
        if status in (403, 404):
            code = "official_event_access_required" if status == 403 else "official_event_not_found"
            raise CatalogError(code, message=_MESSAGES[code])
        if status == 409:
            raise CatalogError("official_operation_closed", message=_MESSAGES["official_operation_closed"])
        if status not in (200, 201, 204):
            raise CatalogError("catalog_unavailable", message=f"AWS Events API returned HTTP {status}.")
        try:
            data = json.loads(raw) if raw else {}
        except (ValueError, UnicodeError):
            raise CatalogError("catalog_invalid") from None
        if not isinstance(data, dict):
            raise CatalogError("catalog_invalid")
        if response_headers is not None:
            response_headers.update({k.lower(): v for k, v in (headers or {}).items()})
        return data
    raise CatalogError("official_rate_limited")


# ---------------------------------------------------------------------------
# Normalization (official item -> atlas.models.Session)
# ---------------------------------------------------------------------------

def venue_key(name):
    """Map an official venue display string to a canonical key, or None."""
    if not isinstance(name, str):
        return None
    lowered = name.lower()
    for key, needles in _VENUE_PATTERNS:
        if any(needle in lowered for needle in needles):
            return key
    return None


def _times(value, event_zone):
    """(start_iso, end_iso) in Las Vegas time; unknown/ambiguous stays None."""
    if not isinstance(value, dict):
        return None, None
    raw_date, raw_time = value.get("date"), value.get("time")
    if not (isinstance(raw_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date)
            and isinstance(raw_time, str) and re.fullmatch(r"\d{2}:\d{2}", raw_time)):
        return None, None
    try:
        zone = ZoneInfo(value.get("timezone") or event_zone)
        naive = datetime.combine(date.fromisoformat(raw_date),
                                 datetime.strptime(raw_time, "%H:%M").time())
        start_utc = naive.replace(tzinfo=zone).astimezone(timezone.utc)
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return None, None
    end = None
    length = value.get("length")
    if isinstance(length, str) and re.fullmatch(r"\d{1,5}", length) and 0 < int(length) <= 1440:
        end = (start_utc + timedelta(minutes=int(length))).astimezone(LOCAL_ZONE).isoformat()
    return start_utc.astimezone(LOCAL_ZONE).isoformat(), end


def normalize_session(item, event_zone="America/Los_Angeles"):
    if not isinstance(item, dict) or not isinstance(item.get("sessionId"), str) \
            or not isinstance(item.get("title"), str):
        raise CatalogError("catalog_invalid")
    start, end = _times(item.get("sessionTime"), event_zone)
    topics = []
    for field in TOPIC_FIELDS:
        if isinstance(item.get(field), list):
            topics.extend(t for t in item[field] if isinstance(t, str) and t)
    venue_name = item.get("venue") if isinstance(item.get("venue"), str) else ""
    level = item.get("level")
    level = re.sub(r"\D.*$", "", level.strip()) if isinstance(level, str) else ""
    speakers = item.get("speakers") if isinstance(item.get("speakers"), list) else []
    return {
        "id": item["sessionId"],
        "code": item.get("abbreviation") or "",
        "title": item["title"],
        "abstract": item.get("abstract") or "",
        "type": item.get("type") or "",
        "level": level,
        "topics": list(dict.fromkeys(topics)),
        "start": start or "",
        "end": end or "",
        "venue": venue_key(venue_name) or "",
        "venue_name": venue_name,
        "room": item.get("room") or "",
        "seats": item.get("seatAvailability") or "",
        "speakers": [s["name"] for s in speakers if isinstance(s, dict) and isinstance(s.get("name"), str)],
        "source": "official_api",
    }


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_live_cache = {"at": None, "sessions": None}
_last_source = {"source": None, "reason": None}


def list_sessions_live(event_id=EVENT_ID):
    """Full ListSessions read; follows nextToken until it is absent."""
    path = "/v1/events/" + quote(event_id, safe="")
    event = _request("GET", path, authenticated=False).get("event") or {}
    event_zone = event.get("timezone") or "America/Los_Angeles"
    rows, seen_tokens, seen_ids = [], set(), set()
    next_token, total = None, None
    for _page in range(MAX_PAGES):
        query = {"includeAbstracts": "true"}
        if next_token is not None:
            query["nextToken"] = next_token
        data = _request("GET", path + "/sessions", query)
        items = data.get("items")
        if not isinstance(items, list):
            raise CatalogError("catalog_invalid")
        if isinstance(data.get("totalCount"), int):
            total = data["totalCount"]
        for item in items:
            row = normalize_session(item, event_zone)
            if row["id"] not in seen_ids:
                seen_ids.add(row["id"])
                rows.append(row)
        if "nextToken" not in data or data["nextToken"] is None:
            if total is not None and len(rows) != total:
                raise CatalogError("catalog_incomplete",
                                   message=f"Read {len(rows)} sessions but API reported {total}.")
            return rows
        next_token = data["nextToken"]
        if not isinstance(next_token, str) or next_token in seen_tokens:
            raise CatalogError("catalog_pagination_invalid")
        seen_tokens.add(next_token)
    raise CatalogError("catalog_page_limit")


def load_fixture():
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    rows = []
    for session in data["sessions"]:
        row = dict(session)
        row["source"] = "synthetic_fixture"
        rows.append(row)
    return rows


def load_sessions(source: str = "auto") -> list:
    """"fixture" | "live" | "auto" (live if signed in, else fixture).

    Every returned session carries ``source`` ("official_api" or
    "synthetic_fixture"); ``last_source()`` explains the choice.
    """
    if source not in ("auto", "live", "fixture"):
        raise ValueError("source must be auto, live or fixture")
    if source == "fixture" or (source == "auto" and not official_auth.is_signed_in()):
        _last_source.update(source="synthetic_fixture",
                            reason="requested" if source == "fixture" else "not_signed_in")
        return load_fixture()
    with _cache_lock:
        cached_at = _live_cache["at"]
        if cached_at is not None and time.monotonic() - cached_at < LIVE_CACHE_SECONDS:
            _last_source.update(source="official_api", reason="cache")
            return [dict(s) for s in _live_cache["sessions"]]
    try:
        rows = list_sessions_live()
    except CatalogError as error:
        if source == "live":
            raise
        _last_source.update(source="synthetic_fixture", reason=error.code)
        return load_fixture()
    with _cache_lock:
        _live_cache.update(at=time.monotonic(), sessions=rows)
    _last_source.update(source="official_api", reason="live")
    return [dict(s) for s in rows]


def last_source() -> dict:
    return dict(_last_source)


def clear_cache():
    with _cache_lock:
        _live_cache.update(at=None, sessions=None)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

_DAY_NAMES = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
              "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4, "friday": 4,
              "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}


_STOPWORDS = {"a", "an", "and", "the", "or", "of", "for", "to", "in", "on", "with", "at", "my", "i",
              "no", "not", "is", "are", "about", "session", "sessions", "talk", "talks"}


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _day_matches(session, day):
    start = session.get("start") or ""
    if not start:
        return False
    day = day.strip().lower()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return start[:10] == day
    if day in _DAY_NAMES:
        try:
            return datetime.fromisoformat(start).weekday() == _DAY_NAMES[day]
        except ValueError:
            return False
    return False


def search_sessions(query: str = "", types: list | None = None, levels: list | None = None,
                    topics: list | None = None, day: str | None = None, venue: str | None = None,
                    limit: int = 20, source: str = "auto") -> list:
    """Local keyword + filter search (the official API has no server-side search).

    Keywords match code/title/abstract/topics/speakers (any term; more matching terms rank higher),
    ranked by title hits first, then by start time.
    """
    sessions = load_sessions(source)
    terms = [t for t in _norm(query).split() if t not in _STOPWORDS]
    type_set = {_norm(t) for t in types} if types else None
    level_set = {re.sub(r"\D", "", str(l)) for l in levels} if levels else None
    topic_set = [_norm(t) for t in topics] if topics else None
    venue_key_wanted = (venue_key(venue) or _norm(venue).replace(" ", "_")) if venue else None
    scored = []
    for s in sessions:
        if type_set and _norm(s.get("type", "")) not in type_set:
            continue
        if level_set and str(s.get("level", "")) not in level_set:
            continue
        if topic_set:
            have = [_norm(t) for t in s.get("topics", [])]
            have_words = " ".join(have).split()
            if not any(want in h for want in topic_set for h in have) and not any(
                    w.startswith(t) for want in topic_set for t in want.split()
                    if t not in _STOPWORDS and len(t) > 2 for w in have_words):
                continue
        if day and not _day_matches(s, day):
            continue
        if venue_key_wanted and s.get("venue") != venue_key_wanted:
            continue
        score = 0
        if terms:
            title = _norm(s.get("title", "")) + " " + _norm(s.get("code", ""))
            haystack = " ".join([title, _norm(s.get("abstract", "")),
                                 " ".join(_norm(t) for t in s.get("topics", [])),
                                 " ".join(_norm(p) for p in s.get("speakers", []))])
            words, title_words = haystack.split(), title.split()
            hits = [t for t in terms if any(w.startswith(t) for w in words)]
            if not hits:
                continue
            score = sum(2 if any(w.startswith(t) for w in title_words) else 1 for t in hits)
        scored.append((-score, s.get("start") or "~", s.get("id"), s))
    scored.sort(key=lambda row: row[:3])
    return [row[3] for row in scored[:max(0, int(limit))]]


def get_session(session_id: str, source: str = "auto"):
    for s in load_sessions(source):
        if s.get("id") == session_id or (s.get("code") and s.get("code") == session_id):
            return s
    return None


def get_session_localized(session_id: str, locale: str, event_id: str = EVENT_ID) -> dict:
    """Official GetSession, preserving the actual Content-Language (never assume locale)."""
    headers = {}
    data = _request("GET", "/v1/events/" + quote(event_id, safe="") + "/sessions/"
                    + quote(session_id, safe=""), {"locale": locale}, response_headers=headers)
    session = normalize_session(data.get("session"))
    session["content_language"] = headers.get("content-language") or ""
    return session


# ---------------------------------------------------------------------------
# Personal schedule (live only)
# ---------------------------------------------------------------------------

def _require_live():
    if not official_auth.is_signed_in():
        raise CatalogError("official_sign_in_required",
                           message="Personal schedule needs the official sign-in (live only).")


def get_schedule(event_id: str = EVENT_ID) -> dict:
    """Official GetSchedule: reserved, favorites, personalTime (ids only)."""
    _require_live()
    data = _request("GET", "/v1/events/" + quote(event_id, safe="") + "/schedule")
    schedule = data.get("schedule")
    if not isinstance(schedule, dict):
        raise CatalogError("catalog_invalid")
    return {"reserved": list(schedule.get("reserved") or []),
            "favorites": list(schedule.get("favorites") or []),
            "personalTime": list(schedule.get("personalTime") or []),
            "source": "official_api"}


def reserve_sessions(session_ids: list, event_id: str = EVENT_ID) -> dict:
    """Official ReserveSessions (1-10 distinct ids): per-item result, then GetSchedule read-back.

    HTTP 200 can still mean partial or total failure (result.successful / result.failed), so the
    schedule is read back and each item reports whether it is really in `reserved`.
    Called only from an explicit user click in the web app, never by the model.
    """
    _require_live()
    ids = list(dict.fromkeys(i for i in session_ids if isinstance(i, str) and i))
    if not 1 <= len(ids) <= 10:
        raise ValueError("reserve_sessions takes 1 to 10 distinct session ids")
    data = _request("POST", "/v1/events/" + quote(event_id, safe="") + "/reservations",
                    body={"sessionIds": ids})
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    successful = set(result.get("successful") or [])
    failures = {f.get("sessionId"): f for f in result.get("failed") or [] if isinstance(f, dict)}
    schedule = get_schedule(event_id)
    reserved = set(schedule["reserved"])
    items = []
    for sid in ids:
        entry = {"session_id": sid, "ok": sid in successful, "in_schedule_reserved": sid in reserved}
        if sid not in successful:
            failure = failures.get(sid, {})
            entry["code"] = failure.get("code", "not_reported")
            if failure.get("conflictsWith"):
                entry["conflicts_with"] = list(failure["conflictsWith"])
        items.append(entry)
    return {"results": items, "verified": all(e["in_schedule_reserved"] for e in items if e["ok"])}


def cancel_reservations(session_ids: list, event_id: str = EVENT_ID) -> dict:
    """Official CancelReservation for 1-10 distinct ids: per-item result, then GetSchedule read-back.

    The API cancels one session per call (DELETE /v1/events/{eventId}/reservations/{sessionId}, 204).
    A 404 means there was no reservation for it, which the developer guide says to treat as already done;
    a 409 means cancelling is closed for now. An item is verified when it is no longer in `reserved`.
    Called only from an explicit user click in the web app, never by the model.
    """
    _require_live()
    ids = list(dict.fromkeys(i for i in session_ids if isinstance(i, str) and i))
    if not 1 <= len(ids) <= 10:
        raise ValueError("cancel_reservations takes 1 to 10 distinct session ids")
    items = []
    for sid in ids:
        entry = {"session_id": sid, "ok": True}
        try:
            _request("DELETE", "/v1/events/" + quote(event_id, safe="") + "/reservations/" + quote(sid, safe=""))
        except CatalogError as error:
            if error.code == "official_event_not_found":
                entry["already_gone"] = True
            else:
                entry.update(ok=False, code="operationClosed" if error.code == "official_operation_closed"
                             else error.code)
        items.append(entry)
    reserved = set(get_schedule(event_id)["reserved"])
    for entry in items:
        entry["in_schedule_reserved"] = entry["session_id"] in reserved
    return {"results": items, "verified": all(not e["in_schedule_reserved"] for e in items if e["ok"])}


def add_favorites(session_ids: list, event_id: str = EVENT_ID) -> dict:
    """Official AssociateFavorites (1-10 distinct ids), per-item result, then GetSchedule read-back.

    A favorite is interest only, never a reservation. ReserveSessions is out of scope.
    """
    _require_live()
    ids = list(dict.fromkeys(i for i in session_ids if isinstance(i, str) and i))
    if not 1 <= len(ids) <= 10:
        raise ValueError("add_favorites takes 1 to 10 distinct session ids")
    data = _request("POST", "/v1/events/" + quote(event_id, safe="") + "/favorites",
                    body={"sessionIds": ids})
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    successful = set(result.get("successful") or [])
    failures = {f.get("sessionId"): f for f in result.get("failed") or [] if isinstance(f, dict)}
    items = []
    for sid in ids:
        if sid in successful:
            items.append({"session_id": sid, "ok": True})
        else:
            failure = failures.get(sid, {})
            entry = {"session_id": sid, "ok": False, "code": failure.get("code", "not_reported")}
            if failure.get("conflictsWith"):
                entry["conflicts_with"] = list(failure["conflictsWith"])
            items.append(entry)
    schedule = get_schedule(event_id)
    favorites = set(schedule["favorites"])
    for entry in items:
        entry["in_schedule_favorites"] = entry["session_id"] in favorites
    return {"results": items, "schedule": schedule,
            "verified": all(e["in_schedule_favorites"] for e in items if e["ok"])}
