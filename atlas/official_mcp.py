"""Minimal client for the official AWS Events remote MCP server (streamable HTTP).

Plain JSON-RPC 2.0 over HTTPS to https://api.awsevents.com/mcp, using the same
in-memory bearer token as the REST client (``official_auth``). Handles both
``application/json`` and ``text/event-stream`` responses and the
``Mcp-Session-Id`` header. The token is never logged or returned.
"""
from __future__ import annotations

import itertools
import json
import threading
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from . import official_auth

MCP_URL = "https://api.awsevents.com/mcp"
PROTOCOL_VERSION = "2025-06-18"
TIMEOUT = 30.0
MAX_BYTES = 4 * 1024 * 1024


class MCPError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def _http_post(url, headers, body):
    """-> (status, headers, bytes). Tests replace ``_transport``."""
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with _OPENER.open(request, timeout=TIMEOUT) as response:
            return response.status, {k: v for k, v in response.headers.items()}, response.read(MAX_BYTES)
    except HTTPError as error:
        try:
            return error.code, {}, b""
        finally:
            error.close()
    except (URLError, OSError, ValueError):
        raise MCPError("mcp_unavailable") from None


_transport = _http_post
_ids = itertools.count(1)
_lock = threading.Lock()
_session = {"id": None, "initialized": False}


def _header(headers, name):
    return next((v for k, v in (headers or {}).items() if k.lower() == name.lower()), None)


def _parse(headers, raw, request_id):
    content_type = (_header(headers, "Content-Type") or "").lower()
    text = raw.decode("utf-8", "replace")
    messages = []
    if "text/event-stream" in content_type:
        for block in text.split("\n\n"):
            data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
            if data:
                messages.append(json.loads(data))
    elif text.strip():
        payload = json.loads(text)
        messages.extend(payload if isinstance(payload, list) else [payload])
    for message in messages:
        if isinstance(message, dict) and message.get("id") == request_id:
            if "error" in message:
                err = message["error"] or {}
                raise MCPError("mcp_rpc_error", f"MCP error {err.get('code')}: {err.get('message')}")
            return message.get("result")
    if request_id is None:
        return None
    raise MCPError("mcp_no_response")


def _post(method, params=None, notify=False):
    try:
        token = official_auth.get_access_token()
    except official_auth.OAuthError:
        raise MCPError("official_sign_in_required", "Sign in first (official_auth.sign_in()).") from None
    request_id = None if notify else next(_ids)
    message = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        message["params"] = params
    if request_id is not None:
        message["id"] = request_id
    headers = {"Content-Type": "application/json",
               "Accept": "application/json, text/event-stream",
               "MCP-Protocol-Version": PROTOCOL_VERSION,
               "Authorization": "Bearer " + token}
    token = None
    if _session["id"]:
        headers["Mcp-Session-Id"] = _session["id"]
    try:
        status, resp_headers, raw = _transport(MCP_URL, headers, json.dumps(message).encode("utf-8"))
    finally:
        headers.pop("Authorization", None)
    if status == 401:
        auth = official_auth.current_auth()
        if auth is not None:
            auth.invalidate()
        raise MCPError("official_sign_in_required", "MCP server rejected the token (401).")
    if status == 403:
        raise MCPError("official_event_access_required", "MCP server refused access (403).")
    if status == 404 and _session["id"]:
        _session.update(id=None, initialized=False)  # session expired; caller may retry
        raise MCPError("mcp_session_expired")
    if status == 429:
        raise MCPError("official_rate_limited", "MCP server rate limited the call (429).")
    if status not in (200, 202):
        raise MCPError("mcp_unavailable", f"MCP server returned HTTP {status}.")
    session_id = _header(resp_headers, "Mcp-Session-Id")
    if session_id:
        _session["id"] = session_id
    if notify:
        return None
    return _parse(resp_headers, raw, request_id)


def _ensure_initialized():
    if _session["initialized"]:
        return
    _post("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                         "clientInfo": {"name": "reinvent-nova-copilot", "version": "0.1"}})
    _post("notifications/initialized", notify=True)
    _session["initialized"] = True


def _call(method, params=None):
    with _lock:
        for attempt in range(2):
            _ensure_initialized()
            try:
                return _post(method, params)
            except MCPError as error:
                if error.code != "mcp_session_expired" or attempt:
                    raise
    raise MCPError("mcp_unavailable")


def list_tools() -> list:
    """Tool definitions exposed by the official MCP server (follows nextCursor)."""
    tools, cursor = [], None
    for _ in range(20):
        result = _call("tools/list", {"cursor": cursor} if cursor else {}) or {}
        tools.extend(result.get("tools") or [])
        cursor = result.get("nextCursor")
        if not cursor:
            break
    return tools


def call_tool(name: str, arguments: dict | None = None) -> dict:
    """Proxy one tool call; returns the MCP result (content / structuredContent / isError)."""
    result = _call("tools/call", {"name": name, "arguments": arguments or {}}) or {}
    return result


def reset():
    with _lock:
        _session.update(id=None, initialized=False)
