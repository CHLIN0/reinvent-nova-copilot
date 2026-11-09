#!/usr/bin/env python3
"""Standalone Event Atlas. Official Events catalog, independent in-memory sign-in.

No legacy modules, database or auth/session files are read. Official schedule
writes and automatic RSVP are intentionally unavailable in this stage.
"""
import argparse
import copy
import json
import threading
from datetime import datetime, timezone
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from official_auth import OfficialAuth, OAuthError
from official_catalog import OfficialCatalog, OfficialCatalogUnavailable, TAG_FIELDS

from catalog_topics import CLASSIFICATION_VERSION, TAXONOMY, classify, company_matches


ROOT = Path(__file__).resolve().parent
UPSTREAM_ORIGIN = 'https://api.awsevents.com'
MAX_CATALOG_BYTES = 16 * 1024 * 1024
UPSTREAM_TIMEOUT = 3.0
MIN_REFRESH_SECONDS = 60.0
# Kept independent from the database-backed catalog service intentionally.
PUBLIC_TEXT_FIELDS = (
    'session_id', 'code', 'title', 'abstract', 'date_iso', 'start_local',
    'end_local', 'venue', 'location', 'type', 'level', 'source', 'observed_at',
    'seat_availability',
)
STATIC_FILES = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/app.css': ('app.css', 'text/css; charset=utf-8'),
    '/maplibre-worker.js': ('maplibre-worker.js', 'text/javascript; charset=utf-8'),
    '/geo/campus.json': ('geo/campus.json', 'application/json; charset=utf-8'),
    '/geo/manifest.json': ('geo/manifest.json', 'application/json; charset=utf-8'),
    '/translations.json': ('translations.json', 'application/json; charset=utf-8'),
}
CSP = ("default-src 'self'; script-src 'self'; worker-src 'self'; "
       "style-src 'self'; style-src-elem 'self'; style-src-attr 'unsafe-inline'; "
       "img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; "
       "frame-src 'none'; object-src 'none'; frame-ancestors 'none'; "
       "form-action 'none'; base-uri 'none'")


class CatalogUnavailable(Exception):
    """Public errors are fixed codes; transport details must remain private."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ExclusiveHTTPServer(ThreadingHTTPServer):
    # In particular on BSD/macOS, do not steal loopback from a wildcard bind.
    allow_reuse_address = False


class CallbackHandler(BaseHTTPRequestHandler):
    """Only the registered OAuth callback; request URLs never enter logs."""

    def log_message(self, *_args):
        pass

    def do_GET(self):
        hosts = {f'{name}:{self.server.server_port}' for name in ('127.0.0.1', 'localhost')}
        try:
            parsed = urlsplit(self.path)
            if (len(self.headers.get_all('Host', [])) != 1 or self.headers.get('Host') not in hosts
                    or parsed.scheme or parsed.netloc or parsed.path != '/callback'
                    or parsed.fragment or len(self.path) > 32768):
                raise ValueError()
            self.server.connection.complete(parsed.query)
        except (ValueError, OAuthError):
            body = '登入未完成。請回 Event Atlas 查看狀態並重試。'.encode()
            self.send_response(400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(303)
        self.send_header('Location', self.server.connection.return_origin + '/?signin=complete')
        self.send_header('Content-Length', '0')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.end_headers()


class OfficialConnection:
    """A separate memory-only login, never any legacy session reuse."""

    def __init__(self, frontend_port, auth=None):
        self.frontend_port = frontend_port
        self.auth = auth or OfficialAuth()
        self.catalog = None
        self.callback = None
        self._lock = threading.Lock()
        self._callback_error = False
        self._auth_generation = 0
        self.return_origin = f'http://127.0.0.1:{frontend_port}'

    def status(self):
        return {'provider': 'aws_events_api', **self.auth.status(),
                'callback_available': not self._callback_error,
                'memory_only': True}

    def access_token(self):
        return self.auth.access_token()

    def start(self, origin=None):
        with self._lock:
            allowed = {f'http://{host}:{self.frontend_port}' for host in ('127.0.0.1', 'localhost')}
            if origin is not None and origin not in allowed:
                raise OAuthError('sign_in_required')
            if self.callback is None:
                # Never take8489, the running private monitor. Do not stop an
                # occupied port, and do not create a fresh flow until bound.
                for port in range(8484, 8489):
                    try:
                        candidate = ExclusiveHTTPServer(('127.0.0.1', port), CallbackHandler)
                    except OSError:
                        continue
                    self.callback = candidate
                    self.callback.connection = self
                    self.auth = OfficialAuth(redirect_uri=f'http://127.0.0.1:{port}/callback')
                    threading.Thread(target=candidate.serve_forever, daemon=True).start()
                    break
                if self.callback is None:
                    self._callback_error = True
                    raise OAuthError('sign_in_required')
            self._callback_error = False
            if not self.auth.status()['pending_sign_in']:
                self.return_origin = origin or f'http://127.0.0.1:{self.frontend_port}'
            return self.auth.start()

    def complete(self, query):
        # Publish new auth and reset the old catalog as one identity transition.
        with self._lock:
            result = self.auth.complete(query)
            self._auth_generation += 1
            self.catalog.invalidate(clear=True)
            return result

    def snapshot(self):
        with self._lock:
            generation = self._auth_generation
        try:
            return self.catalog.snapshot()
        except OfficialCatalogUnavailable as error:
            with self._lock:
                if generation != self._auth_generation:
                    raise OfficialCatalogUnavailable('catalog_refresh_superseded') from None
                if error.code == 'official_sign_in_required' and self.auth.status()['connected']:
                    self.auth.invalidate()
                    self._auth_generation += 1
            raise

    def close(self):
        if self.callback is not None:
            self.callback.shutdown()
            self.callback.server_close()


def project_catalog(value):
    """Validate envelope and project public DTO (data transfer object) fields."""
    if (not isinstance(value, dict) or type(value.get('version')) is not int
            or value['version'] != 1 or not isinstance(value.get('sessions'), list)
            or not isinstance(value.get('meta'), dict)):
        raise CatalogUnavailable('catalog_invalid')
    sessions = []
    for item in value['sessions']:
        if not isinstance(item, dict) or not isinstance(item.get('session_id'), str) or not item['session_id']:
            raise CatalogUnavailable('catalog_invalid')
        row = {key: item.get(key) if isinstance(item.get(key), str) else None
               for key in PUBLIC_TEXT_FIELDS}
        for key in ('tags', 'speakers'):
            row[key] = [entry for entry in item.get(key, []) if isinstance(entry, str)] if isinstance(item.get(key), list) else []
        row['api_verified'] = item.get('api_verified') is True
        for key in TAG_FIELDS:
            row[key] = [entry for entry in item.get(key, []) if isinstance(entry, str)] if isinstance(item.get(key), list) else []
        # Derive only from the allowlisted public row, never upstream enrichment.
        reasons = classify(row)
        row['system_topics'] = [reason['id'] for reason in reasons]
        row['classification_reasons'] = reasons
        row['classification_version'] = CLASSIFICATION_VERSION
        row['derived_company_matches'] = company_matches(row)
        sessions.append(row)
    incoming = value['meta']
    meta = {key: incoming.get(key) if isinstance(incoming.get(key), str) else None
            for key in ('generated_at', 'catalog_observed_at', 'source', 'source_kind', 'content_language', 'requested_locale')}
    revision = incoming.get('revision')
    meta.update(revision=revision if type(revision) is int and revision >= 0 else 0,
                count=len(sessions), verified_count=sum(row['api_verified'] for row in sessions),
                stale=incoming.get('stale') is True,
                taxonomy=copy.deepcopy(TAXONOMY), classification_version=CLASSIFICATION_VERSION)
    if meta['stale']:
        meta['error'] = incoming.get('error') if incoming.get('error') in {'official_sign_in_required', 'official_event_access_required', 'official_rate_limited', 'catalog_unavailable'} else 'upstream_stale'
    return {'version': 1, 'meta': meta, 'sessions': sessions}


class SpatialHandler(BaseHTTPRequestHandler):
    server_version = 'EventAtlas/1'

    def __getattr__(self, name):
        if name.startswith('do_'):
            return self._method_not_allowed
        raise AttributeError(name)

    def log_message(self, *_args):
        pass

    def _allowed(self):
        hosts = ('127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port))
        if len(self.headers.get_all('Host', [])) != 1 or self.headers.get('Host') not in hosts:
            return False
        origins = self.headers.get_all('Origin', [])
        return len(origins) <= 1 and (not origins or origins[0] in tuple('http://' + host for host in hosts))

    def _respond(self, status, body=b'', mime='application/json; charset=utf-8', extra_headers=None):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', CSP)
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        if status == 405:
            self.send_header('Allow', 'GET, HEAD')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, status, value, extra_headers=None):
        return self._respond(status, json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode(), extra_headers=extra_headers)

    def do_GET(self):
        if not self._allowed():
            return self._json(403, {'error': 'local_origin_required'})
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            return self._json(400, {'error': 'invalid_path'})
        permitted_signin = parsed.path == '/' and parsed.query == 'signin=complete'
        check_path = parsed.path if permitted_signin else self.path
        if (parsed.scheme or parsed.netloc or any(char in check_path for char in ('%', '\\', '?', '#'))
                or '..' in self.path or any(ord(char) < 32 for char in self.path)):
            return self._json(400, {'error': 'invalid_path'})
        if parsed.path == '/api/auth/status':
            return self._json(200, self.server.connection.status())
        if parsed.path == '/api/health':
            cache = self.server.catalog.health()
            return self._json(200, {'version': 1, 'status': 'degraded' if cache['error'] else 'ok',
                                    'read_only': True, 'upstream': UPSTREAM_ORIGIN, 'public_cache': cache,
                                    'auth': self.server.connection.status(), 'automatic_rsvp': False,
                                    'official_schedule_writes': False})
        if parsed.path == '/api/catalog':
            try:
                return self._json(200, project_catalog(self.server.connection.snapshot()))
            except (OfficialCatalogUnavailable, CatalogUnavailable) as error:
                code = getattr(error, 'code', str(error))
                code = {'official_sign_in_required': 'sign_in_required',
                        'official_event_access_required': 'not_registered',
                        'official_rate_limited': 'rate_limited'}.get(code, code)
                allowed = {'sign_in_required', 'not_registered', 'rate_limited', 'catalog_unavailable', 'catalog_invalid', 'catalog_timeout', 'catalog_sync_in_progress'}
                code = code if code in allowed else 'catalog_unavailable'
                status = {'sign_in_required': 401, 'not_registered': 403, 'rate_limited': 429}.get(code, 503)
                extra = None
                if code == 'rate_limited':
                    seconds = getattr(error, 'retry_after', None)
                    extra = {'Retry-After': str(max(1, min(3600, int(seconds or 60))))}
                return self._json(status, {'version': 1, 'error': code,
                                          'meta': {'stale': True}, 'sessions': []}, extra_headers=extra)
        if parsed.path not in STATIC_FILES:
            return self._json(404, {'error': 'not_found'})
        name, mime = STATIC_FILES[parsed.path]
        try:
            root = self.server.static_root.resolve()
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                return self._json(404, {'error': 'not_found'})
            body = path.read_bytes()
        except OSError:
            return self._json(404, {'error': 'not_found'})
        return self._respond(200, body, mime)

    do_HEAD = do_GET

    def do_POST(self):
        # The sole mutation is explicitly starting this process's own login.
        # No reservations, favorites, personal time or legacy config endpoints.
        if not self._allowed() or len(self.headers.get_all('Origin', [])) != 1:
            return self._json(403, {'error': 'local_origin_required'})
        if self.path != '/api/auth/start':
            return self._method_not_allowed()
        if (self.headers.get('Content-Type') != 'application/json'
                or self.headers.get('Transfer-Encoding')
                or len(self.headers.get_all('Content-Length', [])) != 1):
            return self._json(400, {'error': 'invalid_request'})
        try:
            length = int(self.headers['Content-Length'])
            if not 0 < length <= 64:
                raise ValueError()
            self.connection.settimeout(3)
            body = json.loads(self.rfile.read(length))
            if body != {}:
                raise ValueError()
        except (ValueError, OSError):
            return self._json(400, {'error': 'invalid_request'})
        try:
            return self._json(200, self.server.connection.start(self.headers['Origin']))
        except OAuthError:
            return self._json(503, {'error': 'callback_unavailable'})

    def _method_not_allowed(self):
        if not self._allowed():
            return self._json(403, {'error': 'local_origin_required'})
        return self._json(405, {'error': 'read_only'})


def make_server(port=8492, static_root=None, *, connection=None, catalog=None):
    if port in (8489, 8490, 8491):
        raise ValueError('Existing service ports are reserved')
    server = ExclusiveHTTPServer(('127.0.0.1', port), SpatialHandler)
    server.connection = connection or OfficialConnection(server.server_port)
    server.catalog = catalog or OfficialCatalog(server.connection.access_token)
    server.connection.catalog = server.catalog
    server.static_root = Path(static_root) if static_root is not None else ROOT / 'ui/dist'
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8492)
    parser.add_argument('--static-root', type=Path)
    args = parser.parse_args()
    server = make_server(args.port, args.static_root)
    print(f'Event Atlas: http://127.0.0.1:{server.server_port}/ (official catalog; no auto RSVP)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.connection.close()


if __name__ == '__main__':
    main()
