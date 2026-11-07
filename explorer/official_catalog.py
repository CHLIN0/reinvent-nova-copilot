"""Read-only AWS Events catalog adapter; never reads or persists credentials.

The default transport uses only GET on api.awsevents.com, with proxies and
redirects disabled. Injected transports are for offline tests: their snapshots
are explicitly unverified and labelled injected_transport, never live evidence.
"""
import copy
import json
import math
import re
import socket
import threading
import time
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ORIGIN = 'https://api.awsevents.com'
SOURCE = 'aws_events_api'
MIN_REFRESH_SECONDS = 60.0
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_CATALOG_BYTES = 16 * 1024 * 1024
MAX_PAGES = 200
MAX_SESSIONS = 20000
SYNC_TIMEOUT = 45.0
REQUEST_TIMEOUT = 10.0
LOCAL_ZONE = ZoneInfo('America/Los_Angeles')
TAG_FIELDS = ('tracks', 'topics', 'industries', 'areasOfInterest', 'roles',
              'services', 'segments', 'features', 'customerPersonas',
              'experiences', 'additionalActivities', 'focusAreas')


class OfficialCatalogUnavailable(Exception):
    """A fixed public code only, never an upstream body or exception message."""

    def __init__(self, code='catalog_unavailable', retry_after=None):
        super().__init__(code)
        self.code = code
        self.retry_after = retry_after


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _text(value):
    return value if isinstance(value, str) else None


def _header(headers, name):
    return next((value for key, value in headers.items()
                 if key.lower() == name.lower()), None)


def _error_for_status(status, headers):
    codes = {401: 'official_sign_in_required', 403: 'official_event_access_required',
             404: 'official_event_not_found', 429: 'official_rate_limited'}
    retry_after = None
    if status == 429:
        try:
            value = float(_header(headers, 'Retry-After'))
            if math.isfinite(value) and value >= 0:
                retry_after = value
        except (TypeError, ValueError):
            pass
    return OfficialCatalogUnavailable(codes.get(status, 'catalog_unavailable'), retry_after)


def _times(value, event_zone):
    """Optional source fields stay unknown; ambiguous DST wall times are not guessed."""
    if not isinstance(value, dict):
        return None, None, None
    raw_date = value.get('date')
    try:
        if not isinstance(raw_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_date):
            return None, None, None
        parsed_date = date.fromisoformat(raw_date)
    except ValueError:
        return None, None, None
    raw_time = value.get('time')
    if not isinstance(raw_time, str) or not re.fullmatch(r'\d{2}:\d{2}', raw_time):
        return raw_date, None, None
    try:
        zone_name = value.get('timezone', event_zone)
        if not isinstance(zone_name, str) or not zone_name:
            return raw_date, None, None
        zone = ZoneInfo(zone_name)
        naive = datetime.combine(parsed_date, datetime.strptime(raw_time, '%H:%M').time())
        candidates = set()
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=fold)
            utc = candidate.astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == naive:
                candidates.add(utc)
        if len(candidates) != 1:
            return raw_date, None, None
        utc_start = candidates.pop()
        start = utc_start.astimezone(LOCAL_ZONE)
    except (ValueError, ZoneInfoNotFoundError, OverflowError):
        return raw_date, None, None
    end = None
    length = value.get('length')
    if isinstance(length, str) and re.fullmatch(r'\d{1,5}', length):
        minutes = int(length)
        if 0 < minutes <= 7 * 24 * 60:
            end = (utc_start + timedelta(minutes=minutes)).astimezone(LOCAL_ZONE).isoformat()
    return start.date().isoformat(), start.isoformat(), end


def normalize_session(item, event_zone, observed_at, verified):
    if (not isinstance(item, dict) or not isinstance(item.get('sessionId'), str)
            or not 1 <= len(item['sessionId']) <= 128
            or not isinstance(item.get('title'), str)):
        raise OfficialCatalogUnavailable('catalog_invalid')
    day, start, end = _times(item.get('sessionTime'), event_zone)
    tags = []
    for field in TAG_FIELDS:
        if isinstance(item.get(field), list):
            tags.extend(f'{field}: {tag}' for tag in item[field]
                        if isinstance(tag, str) and tag)
    speakers = item.get('speakers')
    row = {
        'session_id': item['sessionId'], 'code': _text(item.get('abbreviation')),
        'title': item['title'], 'abstract': _text(item.get('abstract')),
        'date_iso': day, 'start_local': start, 'end_local': end,
        'venue': _text(item.get('venue')), 'location': _text(item.get('room')),
        'type': _text(item.get('type')), 'level': _text(item.get('level')),
        'tags': list(dict.fromkeys(tags)),
        'speakers': [speaker['name'] for speaker in speakers
                     if isinstance(speaker, dict) and isinstance(speaker.get('name'), str)]
                    if isinstance(speakers, list) else [],
        'source': SOURCE, 'observed_at': observed_at, 'api_verified': verified,
        'source_session_id': item['sessionId'],
        'is_reservable': item.get('isReservable') if type(item.get('isReservable')) is bool else None,
        'is_all_day': item.get('isAllDaySession') if type(item.get('isAllDaySession')) is bool else None,
        'seat_availability': item.get('seatAvailability') if item.get('seatAvailability') in
                             ('available', 'limited', 'veryLimited', 'unavailable', 'walkUp') else None,
    }
    # Native dimension names are source provenance. Do not invent RainFocus
    # attribute IDs or flatten different dimensions into one ambiguous label.
    for field in TAG_FIELDS:
        row[field] = list(dict.fromkeys(entry for entry in item.get(field, [])
                                       if isinstance(entry, str) and entry)) \
                     if isinstance(item.get(field), list) else []
    return row


class OfficialCatalog:
    """Atomic paginated catalog cache with a minimum 60-second attempt cooldown.

    token_provider() supplies the current bearer string or raises. Its exceptions
    are sanitized, and the token exists only for the lifetime of each request.
    transport(path, query, token, timeout) may return (status, headers, bytes)
    for offline tests. No injected response is accepted as official evidence.
    """

    def __init__(self, token_provider, event_id='reinvent2026', *, locale='en-US',
                 refresh_seconds=MIN_REFRESH_SECONDS, transport=None,
                 clock=time.monotonic, now=None):
        if (not isinstance(event_id, str) or not 1 <= len(event_id) <= 128
                or any(ord(char) < 33 for char in event_id)):
            raise ValueError('invalid_event_id')
        if not isinstance(locale, str) or not re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', locale):
            raise ValueError('invalid_locale')
        self.event_id = event_id
        self.locale = locale
        self.refresh_seconds = max(MIN_REFRESH_SECONDS, float(refresh_seconds))
        if not math.isfinite(self.refresh_seconds):
            raise ValueError('invalid_refresh_seconds')
        self._token_provider = token_provider
        self._transport = transport or self._http_get
        self._verified_transport = transport is None
        self._clock = clock
        self._now = now or (lambda: datetime.now(timezone.utc).isoformat())
        self._path = '/v1/events/' + quote(event_id, safe='')
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self._lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._cached = None
        self._attempted = float('-inf')
        self._retry_seconds = self.refresh_seconds
        self._received_at = None
        self._error = None
        self._revision = 0
        self._last_query = None
        self._progress = {'phase': 'idle', 'pages': 0, 'collected': 0}
        self._generation = 0

    def _http_get(self, path, query, token, timeout):
        if path not in (self._path, self._path + '/sessions'):
            raise OfficialCatalogUnavailable('catalog_invalid')
        url = ORIGIN + path + ('?' + urlencode(query) if query else '')
        headers = {'Accept': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(url, headers=headers, method='GET')
        deadline = self._clock() + timeout
        try:
            with self._opener.open(request, timeout=timeout) as response:
                if response.status != 200:
                    return response.status, {}, b''
                length = response.headers.get('Content-Length')
                if length is not None:
                    try:
                        declared = int(length)
                    except (TypeError, ValueError):
                        raise OfficialCatalogUnavailable('catalog_invalid') from None
                    if not 0 <= declared <= MAX_PAGE_BYTES:
                        raise OfficialCatalogUnavailable('catalog_too_large')
                chunks, size = [], 0
                while True:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        raise OfficialCatalogUnavailable('catalog_timeout')
                    raw = getattr(getattr(response, 'fp', None), 'raw', None)
                    sock = getattr(raw, '_sock', None)
                    if sock is not None:
                        sock.settimeout(remaining)
                    chunk = getattr(response, 'read1', response.read)(min(65536, MAX_PAGE_BYTES + 1 - size))
                    if self._clock() > deadline:
                        raise OfficialCatalogUnavailable('catalog_timeout')
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_PAGE_BYTES:
                        raise OfficialCatalogUnavailable('catalog_too_large')
                    chunks.append(chunk)
                safe_headers = {name: response.headers.get(name) for name in
                                ('Content-Language', 'Content-Type') if response.headers.get(name)}
                return response.status, safe_headers, b''.join(chunks)
        except HTTPError as error:
            # No error body, full response, request headers or redirect URL leaves this layer.
            try:
                headers = {'Retry-After': error.headers.get('Retry-After')}
                return error.code, headers, b''
            finally:
                error.close()
        except (TimeoutError, socket.timeout):
            raise OfficialCatalogUnavailable('catalog_timeout') from None
        except (URLError, OSError, HTTPException, ValueError):
            raise OfficialCatalogUnavailable('catalog_unavailable') from None

    def _token(self):
        try:
            token = self._token_provider()
        except Exception as error:
            # A transient refresh outage must not revoke a still recoverable
            # OAuth connection. Only explicit terminal/auth-required outcomes
            # request a new sign-in; provider text never leaves this adapter.
            if getattr(error, 'terminal', False) is True or getattr(error, 'code', None) == 'sign_in_required':
                raise OfficialCatalogUnavailable('official_sign_in_required') from None
            retry_after = getattr(error, 'retry_after', None)
            if (type(retry_after) not in (int, float) or not math.isfinite(retry_after)
                    or retry_after < 0):
                retry_after = None
            raise OfficialCatalogUnavailable('catalog_unavailable', retry_after) from None
        if (not isinstance(token, str) or not token or len(token) > 32768
                or any(ord(char) < 33 or ord(char) > 126 for char in token)):
            raise OfficialCatalogUnavailable('official_sign_in_required')
        return token

    def _get(self, operation, path, query, deadline, authenticated, generation):
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise OfficialCatalogUnavailable('catalog_timeout')
        token = self._token() if authenticated else None
        started = self._clock()
        try:
            status, headers, body = self._transport(path, query, token, min(REQUEST_TIMEOUT, remaining))
        except OfficialCatalogUnavailable:
            raise
        except Exception:
            raise OfficialCatalogUnavailable('catalog_unavailable') from None
        finally:
            token = None
        if type(status) is not int or not isinstance(headers, dict) or not isinstance(body, bytes):
            raise OfficialCatalogUnavailable('catalog_invalid')
        with self._lock:
            if generation != self._generation:
                raise OfficialCatalogUnavailable('catalog_refresh_superseded')
            self._last_query = {'operation': operation, 'status': status,
                                'response_at': self._now(),
                                'duration_seconds': round(self._clock() - started, 3),
                                'source': SOURCE,
                                'scope': 'official_http' if self._verified_transport else 'injected_transport'}
        if self._clock() > deadline:
            raise OfficialCatalogUnavailable('catalog_timeout')
        if status != 200:
            raise _error_for_status(status, headers)
        if len(body) > MAX_PAGE_BYTES:
            raise OfficialCatalogUnavailable('catalog_too_large')
        try:
            data = json.loads(body)
        except (ValueError, UnicodeError, RecursionError):
            raise OfficialCatalogUnavailable('catalog_invalid') from None
        if not isinstance(data, dict):
            raise OfficialCatalogUnavailable('catalog_invalid')
        return data, headers, len(body)

    def _read(self, generation):
        deadline = self._clock() + SYNC_TIMEOUT
        # snapshot() already checked auth without retaining its bearer. Each
        # authenticated page obtains the current token separately after refresh.
        event_data, _, consumed = self._get('GetEvent', self._path, {}, deadline, False, generation)
        event = event_data.get('event')
        if not isinstance(event, dict) or event.get('eventId') != self.event_id:
            raise OfficialCatalogUnavailable('catalog_invalid')
        event_zone = event.get('timezone', 'America/Los_Angeles')
        rows, seen_ids, seen_tokens = [], set(), set()
        page_token, total, language = None, None, None
        pages = 0
        observed_at = self._now()
        while True:
            pages += 1
            if pages > MAX_PAGES:
                raise OfficialCatalogUnavailable('catalog_page_limit')
            query = {'includeAbstracts': 'true', 'locale': self.locale}
            if page_token is not None:
                query['nextToken'] = page_token
            data, headers, size = self._get('ListSessions', self._path + '/sessions', query, deadline, True, generation)
            consumed += size
            if consumed > MAX_CATALOG_BYTES:
                raise OfficialCatalogUnavailable('catalog_too_large')
            page_language = _header(headers, 'Content-Language')
            if (not isinstance(page_language, str) or not re.fullmatch(
                    r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*', page_language)):
                raise OfficialCatalogUnavailable('catalog_language_unknown')
            if language is not None and language.lower() != page_language.lower():
                raise OfficialCatalogUnavailable('catalog_language_changed')
            language = page_language
            count = data.get('totalCount')
            if (type(count) not in (int, float) or not 0 <= count <= MAX_SESSIONS
                    or not math.isfinite(count) or count != int(count)):
                raise OfficialCatalogUnavailable('catalog_invalid')
            if total is not None and count != total:
                raise OfficialCatalogUnavailable('catalog_changed_during_sync')
            total = int(count)
            items = data.get('items')
            if not isinstance(items, list) or len(items) > 250:
                raise OfficialCatalogUnavailable('catalog_invalid')
            for item in items:
                row = normalize_session(item, event_zone, observed_at, self._verified_transport)
                if row['session_id'] in seen_ids:
                    raise OfficialCatalogUnavailable('catalog_duplicate_session')
                seen_ids.add(row['session_id'])
                rows.append(row)
            with self._lock:
                if generation != self._generation:
                    raise OfficialCatalogUnavailable('catalog_refresh_superseded')
                self._progress = {'phase': 'syncing', 'pages': pages, 'collected': len(rows)}
            if len(rows) > total or len(rows) > MAX_SESSIONS:
                raise OfficialCatalogUnavailable('catalog_invalid')
            if 'nextToken' not in data:
                break
            page_token = data['nextToken']
            if (not isinstance(page_token, str) or not 1 <= len(page_token) <= 512
                    or page_token in seen_tokens):
                raise OfficialCatalogUnavailable('catalog_pagination_invalid')
            seen_tokens.add(page_token)
        if len(rows) != total:
            raise OfficialCatalogUnavailable('catalog_incomplete')
        completed_at = self._now()
        return {'version': 1, 'sessions': rows, 'meta': {
            'source': SOURCE, 'source_kind': 'official_http' if self._verified_transport else 'injected_transport',
            'event_id': self.event_id, 'generated_at': completed_at,
            'catalog_observed_at': completed_at, 'stale': False,
            'revision': self._revision + 1, 'count': len(rows),
            'verified_count': len(rows) if self._verified_transport else 0,
            'requested_language': self.locale, 'content_language': language,
            'supported_languages': [entry for entry in event.get('supportedLanguageCodes', [])
                                    if isinstance(entry, str)]
                                    if isinstance(event.get('supportedLanguageCodes'), list) else [],
            'pages': pages, 'complete': True,
        }}

    def snapshot(self):
        with self._sync_lock:
            # Cached event content remains protected. Check the current auth
            # provider even inside the refresh cooldown and never serve a prior
            # catalog after a revoked/expired connection.
            try:
                self._token()
            except OfficialCatalogUnavailable as error:
                with self._lock:
                    self._error = error.code
                    self._attempted = self._clock()
                    self._retry_seconds = max(self.refresh_seconds, error.retry_after or 0)
                    self._progress['phase'] = 'error'
                raise
            with self._lock:
                due = self._clock() - self._attempted >= self._retry_seconds
                generation = self._generation
                if due:
                    self._progress = {'phase': 'syncing', 'pages': 0, 'collected': 0}
            if due:
                try:
                    snapshot = self._read(generation)
                    with self._lock:
                        if generation == self._generation:
                            self._cached = snapshot
                            self._revision += 1
                            self._received_at = self._now()
                            self._error = None
                            self._retry_seconds = self.refresh_seconds
                            self._progress['phase'] = 'ready'
                except OfficialCatalogUnavailable as error:
                    with self._lock:
                        if generation == self._generation:
                            self._error = str(error)
                            self._retry_seconds = max(self.refresh_seconds, error.retry_after or 0)
                            self._progress['phase'] = 'error'
                finally:
                    with self._lock:
                        if generation == self._generation:
                            self._attempted = self._clock()
            with self._lock:
                if generation != self._generation:
                    raise OfficialCatalogUnavailable('catalog_refresh_superseded')
                if self._error in ('official_sign_in_required', 'official_event_access_required'):
                    raise OfficialCatalogUnavailable(self._error)
                if self._cached is None:
                    raise OfficialCatalogUnavailable(
                        self._error or 'catalog_unavailable',
                        retry_after=max(0, self._retry_seconds - (self._clock() - self._attempted)))
                result = copy.deepcopy(self._cached)
                if self._error:
                    result['meta'].update(stale=True, error=self._error)
                return result

    def invalidate(self, clear=False):
        """Refresh immediately; completed sign-in must use clear=True for identity changes.

        A generation change prevents an old in-flight request from repopulating
        a cleared cache, even if that old response arrives after the new login.
        """
        with self._lock:
            self._attempted = float('-inf')
            self._generation += 1
            self._retry_seconds = self.refresh_seconds
            if clear:
                self._cached = None
                self._received_at = None
                self._error = None
                self._last_query = None
                self._progress = {'phase': 'idle', 'pages': 0, 'collected': 0}

    def health(self):
        with self._lock:
            return {'available': self._cached is not None, 'stale': bool(self._error),
                    'received_at': self._received_at, 'refresh_seconds': self.refresh_seconds,
                    'retry_seconds': self._retry_seconds, 'error': self._error,
                    'source': SOURCE,
                    'source_kind': 'official_http' if self._verified_transport else 'injected_transport',
                    'last_query': copy.deepcopy(self._last_query),
                    'sync': copy.deepcopy(self._progress)}
