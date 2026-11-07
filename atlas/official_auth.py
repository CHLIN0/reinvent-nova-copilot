"""Memory-only AWS Events OAuth PKCE (Builder ID); never persists or logs credentials.

Adapted from the verified event-atlas client. ``sign_in()`` runs one loopback
callback on 127.0.0.1 ports 8484-8488 (/callback) and keeps tokens in process
memory only. ``status()`` is safe to show; ``access_token()`` is for API clients.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import secrets
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CLIENT_ID = "7vmom55m1qstvq8i71ph127bfq"
AUTHORIZE_URL = "https://oauth.awsevents.com/oauth2/authorize"
TOKEN_URL = "https://oauth.awsevents.com/oauth2/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8484/callback"
MAX_RESPONSE_BYTES = 128 * 1024
MAX_QUERY_BYTES = 32768
PENDING_SECONDS = 300
ACCESS_SECONDS = 3600
REFRESH_SECONDS = 30 * 24 * 60 * 60
RETRY_SECONDS = 60
CALLBACK_PORTS = range(8484, 8489)  # registered loopback ports; 8489 excluded on purpose


class OAuthError(Exception):
    """Fixed public code only; provider text and exception details are discarded."""

    def __init__(self, code, *, terminal=False, retry_after=None):
        self.code = code
        self.terminal = terminal
        self.retry_after = retry_after
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class TokenResponse:
    status: int
    headers: dict
    body: bytes


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _http_transport(method, url, headers, body):
    # Do not inherit proxy credentials or forward codes/tokens through redirects.
    request = Request(url, data=body, headers=headers, method=method)
    deadline = time.monotonic() + 10
    try:
        response = build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        # read1 returns after at most one socket read. A plain read(n) could keep
        # accepting trickled bytes indefinitely despite the socket-idle timeout.
        chunks, size = [], 0
        read_chunk = response.read1
        while True:
            if time.monotonic() >= deadline:
                raise OAuthError("token_endpoint_unavailable")
            chunk = read_chunk(min(8192, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise OAuthError("invalid_token_response")
        if time.monotonic() >= deadline:
            raise OAuthError("token_endpoint_unavailable")
        return TokenResponse(response.status, dict(response.headers.items()), b"".join(chunks))


def _positive(value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise OAuthError("invalid_token_response")
    return float(value)


def _secret(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 16384
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
        raise OAuthError("invalid_token_response")
    return value


def _json_object(payload):
    # Reject ambiguous duplicate fields rather than choosing a credential value.
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    data = json.loads(payload, object_pairs_hook=unique)
    if not isinstance(data, dict):
        raise ValueError("object required")
    return data


class OfficialAuth:
    def __init__(self, redirect_uri=DEFAULT_REDIRECT_URI, transport=None, clock=None):
        # 8489 belongs to another local service. Never claim its callback.
        if redirect_uri not in {f"http://127.0.0.1:{port}/callback" for port in CALLBACK_PORTS}:
            raise ValueError("Use an isolated registered loopback callback on ports 8484–8488")
        self.redirect_uri = redirect_uri
        self._transport = transport or _http_transport
        self._clock = clock or time.time
        self._lock = threading.RLock()
        self._tokens = None
        self._pending = None
        self._error = None
        self._blocked = False
        self._retry_at = 0

    def _expire(self):
        now = self._clock()
        if self._pending and now >= self._pending["expires_at"]:
            self._pending = None
        if self._tokens and now >= self._tokens["refresh_expires_at"]:
            self._tokens = None
            self._blocked, self._error = True, "sign_in_required"
        return now

    def status(self):
        """Safe projection; this never refreshes credentials or starts sign-in."""
        with self._lock:
            now = self._expire()
            connected = bool(self._tokens and not self._blocked)
            phase = ("awaiting_sign_in" if self._pending else
                     "refresh_required" if connected and now >= self._tokens["expires_at"] else
                     "connected" if connected else
                     "reauth_required" if self._blocked else "unauthenticated")
            return {"connected": connected, "auth_status": phase,
                    "pending_sign_in": bool(self._pending), "error": self._error,
                    "expires_at": self._tokens["expires_at"] if connected else None,
                    "memory_only": True}

    def start(self):
        """Explicit user sign-in only; duplicate clicks preserve the active flow."""
        with self._lock:
            now = self._expire()
            if self._pending:
                return {"authorization_url": self._pending["authorization_url"]}
            verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
            challenge = base64.urlsafe_b64encode(
                hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
            fields = {"response_type": "code", "client_id": CLIENT_ID,
                      "redirect_uri": self.redirect_uri, "scope": "openid email events/access",
                      "identity_provider": "AWSBuilderID", "code_challenge": challenge,
                      "code_challenge_method": "S256", "state": state}
            url = AUTHORIZE_URL + "?" + urlencode(fields)
            self._pending = {"state": state, "verifier": verifier,
                             "expires_at": now + PENDING_SECONDS, "authorization_url": url}
            return {"authorization_url": url}

    def _exchange(self, fields):
        try:
            response = self._transport(
                "POST", TOKEN_URL,
                {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                urlencode({"client_id": CLIENT_ID, **fields}).encode("ascii"))
            if not isinstance(response.body, bytes) or len(response.body) > MAX_RESPONSE_BYTES:
                raise OAuthError("invalid_token_response")
            if response.status != 200:
                try:
                    provider_error = _json_object(response.body).get("error")
                except (ValueError, TypeError, UnicodeError, RecursionError):
                    provider_error = None
                if response.status in (400, 401) and provider_error == "invalid_grant":
                    raise OAuthError("invalid_grant", terminal=True)
                retry_after = RETRY_SECONDS
                for key, value in (response.headers or {}).items():
                    if key.lower() == "retry-after":
                        try:
                            seconds = float(value)
                            if math.isfinite(seconds) and seconds > 0:
                                retry_after = max(RETRY_SECONDS, min(seconds, 86400))
                        except (ValueError, TypeError):
                            pass
                raise OAuthError("token_exchange_failed", retry_after=retry_after)
            data = _json_object(response.body)
            if str(data.get("token_type", "bearer")).lower() != "bearer":
                raise OAuthError("invalid_token_response")
            refresh_lifetime = None
            for name in ("refresh_expires_in", "refresh_token_expires_in"):
                if name in data:
                    candidate = min(_positive(data[name]), REFRESH_SECONDS)
                    refresh_lifetime = (candidate if refresh_lifetime is None
                                        else min(refresh_lifetime, candidate))
            return {"access_token": _secret(data.get("access_token")),
                    "refresh_token": _secret(data["refresh_token"]) if "refresh_token" in data else None,
                    "lifetime": min(_positive(data.get("expires_in")), ACCESS_SECONDS),
                    "refresh_lifetime": refresh_lifetime}
        except OAuthError:
            raise
        except (ValueError, TypeError, AttributeError, UnicodeError, RecursionError):
            raise OAuthError("invalid_token_response") from None
        except Exception:
            raise OAuthError("token_endpoint_unavailable") from None

    def complete(self, querystring):
        """Consume one matching callback before sending its code to the provider."""
        with self._lock:
            try:
                if (not isinstance(querystring, str)
                        or len(querystring.encode("utf-8")) > MAX_QUERY_BYTES):
                    raise OAuthError("invalid_callback")
                query = parse_qs(querystring, keep_blank_values=True, max_num_fields=12,
                                 encoding="utf-8", errors="strict")
                if any(len(values) != 1 for values in query.values()):
                    raise OAuthError("invalid_callback")
                for name in ("state", "code", "error"):
                    value = query.get(name, [None])[0]
                    if value is not None and (not value or len(value) > 16384
                            or any(ord(c) <= 32 or ord(c) == 127 for c in value)):
                        raise OAuthError("invalid_callback")
                self._expire()
                pending = self._pending
                if not pending:
                    raise OAuthError("expired_callback")
                state = query.get("state", [""])[0]
                if not hmac.compare_digest(state.encode("utf-8"), pending["state"].encode("ascii")):
                    raise OAuthError("invalid_state")
                self._pending = None  # Failed/uncertain exchanges must never replay this code.
                if "error" in query or "code" not in query:
                    raise OAuthError("sign_in_denied")
                result = self._exchange({"grant_type": "authorization_code",
                                         "redirect_uri": self.redirect_uri,
                                         "code": query["code"][0],
                                         "code_verifier": pending["verifier"]})
                if result["refresh_token"] is None:
                    raise OAuthError("invalid_token_response")
                now, lifetime = self._clock(), result["lifetime"]
                self._tokens = {"access_token": result["access_token"],
                                "refresh_token": result["refresh_token"],
                                "expires_at": now + lifetime,
                                "refresh_at": now + lifetime - min(30, lifetime / 10),
                                "refresh_expires_at": now + (result["refresh_lifetime"] or REFRESH_SECONDS)}
                self._blocked, self._error, self._retry_at = False, None, 0
                return self.status()
            except OAuthError as error:
                if error.code not in {"invalid_state", "invalid_callback", "expired_callback"}:
                    self._error = error.code
                raise
            except (ValueError, TypeError, UnicodeError):
                raise OAuthError("invalid_callback") from None

    def access_token(self, force_refresh=False):
        """Server-only token access with serialized refresh and bounded retry rate."""
        with self._lock:
            now = self._expire()
            if not self._tokens or self._blocked:
                raise OAuthError("sign_in_required", terminal=True)
            tokens = self._tokens
            if self._retry_at > now:
                if not force_refresh and now < tokens["expires_at"]:
                    return tokens["access_token"]
                raise OAuthError("token_retry_wait", retry_after=self._retry_at - now)
            if not force_refresh and now < tokens["refresh_at"]:
                return tokens["access_token"]
            try:
                result = self._exchange({"grant_type": "refresh_token",
                                         "refresh_token": tokens["refresh_token"]})
                now, lifetime = self._clock(), result["lifetime"]
                deadline = tokens["refresh_expires_at"]
                if result["refresh_lifetime"] is not None:
                    deadline = min(deadline, now + result["refresh_lifetime"])
                self._tokens = {"access_token": result["access_token"],
                                "refresh_token": result["refresh_token"] or tokens["refresh_token"],
                                "expires_at": now + lifetime,
                                "refresh_at": now + lifetime - min(30, lifetime / 10),
                                "refresh_expires_at": deadline}
                self._error, self._retry_at = None, 0
                return result["access_token"]
            except OAuthError as error:
                if error.terminal:
                    self._tokens = None
                    self._blocked, self._error = True, "sign_in_required"
                    self._retry_at = 0
                else:
                    self._error = error.code
                    self._retry_at = self._clock() + (error.retry_after or RETRY_SECONDS)
                    # Early renewal may fail while the prior token is still
                    # valid. Keep this read available, but never use an expired
                    # token or hide a forced refresh failure after API rejection.
                    if not force_refresh and self._clock() < tokens['expires_at']:
                        return tokens['access_token']
                raise

    def invalidate(self):
        """Locally stop use after a verified API 401; no logout/revoke request."""
        with self._lock:
            self._tokens = None
            self._blocked, self._error, self._retry_at = True, "sign_in_required", 0
            return self.status()


# ---------------------------------------------------------------------------
# Process-wide connection and loopback sign-in
# ---------------------------------------------------------------------------

_AUTH = None
_AUTH_LOCK = threading.Lock()


def current_auth():
    """The signed-in OfficialAuth for this process, or None."""
    return _AUTH


def set_auth(auth):
    """Install an auth object (tests inject fakes here)."""
    global _AUTH
    with _AUTH_LOCK:
        _AUTH = auth


def is_signed_in():
    auth = _AUTH
    return bool(auth and auth.status().get("connected"))


def get_access_token():
    """Bearer for API clients only. Raises OAuthError('sign_in_required') if absent."""
    auth = _AUTH
    if auth is None:
        raise OAuthError("sign_in_required", terminal=True)
    return auth.access_token()


def sign_in(open_browser=True, timeout=300, ports=CALLBACK_PORTS, announce=print, return_url=None):
    """Interactive Builder ID sign-in via OAuth PKCE and a one-shot loopback callback.

    Binds the first free port in 8484-8488 on 127.0.0.1 only, opens the authorize
    URL, waits for /callback, exchanges the code and keeps tokens in memory.
    Returns the safe status() dict; never returns or prints a token.
    """
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import urlsplit
    import webbrowser

    result = {}

    class _Server(HTTPServer):
        allow_reuse_address = False

    class _Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):  # request URLs carry the code; never log them
            pass

        def do_GET(self):
            port = self.server.server_port
            parsed = urlsplit(self.path)
            ok = False
            if (self.headers.get("Host") == f"127.0.0.1:{port}" and parsed.path == "/callback"
                    and not parsed.fragment and len(self.path) <= MAX_QUERY_BYTES):
                try:
                    result["status"] = self.server.auth.complete(parsed.query)
                    ok = True
                except OAuthError as error:
                    result["error"] = error.code
            if ok and return_url:
                self.send_response(303)
                self.send_header("Location", return_url)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                if parsed.path == "/callback":
                    result["done"] = True
                return
            body = (b"Signed in. You can close this tab and return to the terminal." if ok
                    else b"Sign-in did not complete. Return to the terminal and retry.")
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)
            if parsed.path == "/callback":
                result["done"] = True

    server = None
    for port in ports:
        if port not in CALLBACK_PORTS:
            continue
        try:
            server = _Server(("127.0.0.1", port), _Handler)
            break
        except OSError:
            continue
    if server is None:
        raise OAuthError("callback_ports_busy")
    try:
        auth = OfficialAuth(redirect_uri=f"http://127.0.0.1:{server.server_port}/callback")
        server.auth = auth
        url = auth.start()["authorization_url"]
        announce("Open this URL to sign in with AWS Builder ID:\n" + url)
        if open_browser:
            webbrowser.open(url)
        server.timeout = 1
        deadline = time.monotonic() + timeout
        while not result.get("done") and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if "status" not in result:
        raise OAuthError(result.get("error") or "sign_in_timeout")
    set_auth(auth)
    return result["status"]
