"""T12: the agenda answers from the last catalog at once and refreshes in the background.

Event Atlas's OfficialCatalog serves its last complete snapshot without waiting (stale-while-revalidate),
the copilot's rows are a view of that same snapshot (one ListSessions read per refresh for the process),
get_session uses an index, and /api/catalog is gzipped when the browser accepts it.
Synthetic catalog and a fake transport only (tests/synthetic_official.py); fake monotonic clock.
"""
import gzip
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "explorer"))

import web  # noqa: E402
from atlas import catalog, official_auth  # noqa: E402
from official_catalog import OfficialCatalog, OfficialCatalogUnavailable  # noqa: E402  explorer/
import server as atlas_server  # noqa: E402  explorer/server.py
from tests.synthetic_official import FakeEventsAPI  # noqa: E402

TOKEN = "test-token-not-real"
PAGES = 11  # 2,516 synthetic sessions at 250 per page, as on BR's account


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeAuth:
    def __init__(self):
        self.invalidated = False

    def status(self):
        return {"connected": not self.invalidated}

    def access_token(self, force_refresh=False):
        if self.invalidated:
            raise official_auth.OAuthError("sign_in_required", terminal=True)
        return TOKEN

    def invalidate(self):
        self.invalidated = True


def wait_until(condition, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.005)


def make_catalog(api, clock, token=lambda: TOKEN):
    return OfficialCatalog(token, transport=api.atlas, clock=clock, views={"copilot": catalog.shared_row})


class AtlasStaleWhileRevalidateTests(unittest.TestCase):
    def setUp(self):
        self.api, self.clock = FakeEventsAPI(), Clock()
        self.cat = make_catalog(self.api, self.clock)

    def idle(self):
        wait_until(lambda: self.cat._refreshing is None)

    def test_first_load_waits_for_one_full_read(self):
        snap = self.cat.snapshot()
        self.assertEqual(len(snap["sessions"]), 2516)
        self.assertEqual(self.api.list_calls, PAGES)
        meta = snap["meta"]
        self.assertFalse(meta["refreshing"])
        self.assertIsInstance(meta["received_at"], str)
        self.assertEqual(meta["sync"], {"phase": "ready", "pages": PAGES, "collected": 2516})

    def test_concurrent_first_loads_share_one_read(self):
        self.api.block()
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.cat.snapshot())) for _ in range(4)]
        for t in threads:
            t.start()
        self.api.entered.wait(5)
        time.sleep(0.05)  # the other callers are now waiting, not reading
        self.api.gate.set()
        for t in threads:
            t.join(5)
        self.assertEqual(len(results), 4)
        self.assertEqual(self.api.list_calls, PAGES)
        self.assertEqual(self.cat.health()["refreshes"], 1)
        self.assertTrue(all(r["sessions"] is results[0]["sessions"] for r in results))

    def test_fresh_snapshot_starts_no_refresh(self):
        first = self.cat.snapshot()
        self.clock.now += 59
        again = self.cat.snapshot()
        self.assertIs(again["sessions"], first["sessions"])  # no copy per request
        self.assertFalse(again["meta"]["refreshing"])
        self.assertEqual(self.api.list_calls, PAGES)

    def test_stale_snapshot_is_returned_at_once_and_one_refresh_starts(self):
        first = self.cat.snapshot()
        self.clock.now += 61
        self.api.block()  # the refresh cannot finish until released
        started = time.perf_counter()
        stale = self.cat.snapshot()
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertIs(stale["sessions"], first["sessions"])
        self.assertTrue(stale["meta"]["refreshing"])
        self.assertFalse(stale["meta"].get("stale"))
        self.api.entered.wait(5)
        self.assertEqual(self.cat.health()["refreshes"], 2)
        self.api.gate.set()
        self.idle()
        fresh = self.cat.snapshot()
        self.assertIsNot(fresh["sessions"], first["sessions"])
        self.assertEqual(fresh["meta"]["revision"], 2)
        self.assertFalse(fresh["meta"]["refreshing"])
        self.assertEqual(self.api.list_calls, 2 * PAGES)

    def test_concurrent_stale_requests_start_exactly_one_refresh(self):
        first = self.cat.snapshot()
        self.clock.now += 61
        self.api.block()
        results, barrier = [], threading.Barrier(8)

        def request():
            barrier.wait(5)
            results.append(self.cat.snapshot())

        threads = [threading.Thread(target=request) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        self.assertEqual(len(results), 8)  # all answered while the refresh is still blocked
        self.assertTrue(all(r["sessions"] is first["sessions"] for r in results))
        self.assertEqual(self.cat.health()["refreshes"], 2)
        self.api.gate.set()
        self.idle()
        self.assertEqual(self.api.list_calls, 2 * PAGES)

    def test_refresh_started_before_sign_in_change_is_discarded(self):
        self.cat.snapshot()
        self.clock.now += 61
        self.api.block()
        self.cat.snapshot()  # starts the background refresh under the old sign-in
        self.api.entered.wait(5)
        self.cat.invalidate(clear=True)  # sign-in completed meanwhile
        self.api.gate.set()
        self.idle()
        self.assertFalse(self.cat.health()["available"])
        self.assertEqual(self.api.list_calls, PAGES + 1)  # the old read stopped after its page in flight
        self.api.gate = None
        snap = self.cat.snapshot()  # first load for the new sign-in waits for its own read
        self.assertEqual(snap["meta"]["revision"], 2)
        self.assertEqual(self.api.list_calls, 2 * PAGES + 1)

    def test_first_load_superseded_by_sign_in_never_fills_the_cache(self):
        self.api.block()
        errors = []

        def load():
            try:
                self.cat.snapshot()
            except OfficialCatalogUnavailable as error:
                errors.append(error.code)

        t = threading.Thread(target=load)
        t.start()
        self.api.entered.wait(5)
        self.cat.invalidate(clear=True)
        self.api.gate.set()
        t.join(5)
        self.assertEqual(errors, ["catalog_refresh_superseded"])
        self.assertFalse(self.cat.health()["available"])

    def test_failed_background_refresh_keeps_the_last_snapshot(self):
        first = self.cat.snapshot()
        self.clock.now += 61
        def failing(path, query, token, timeout):
            return 500, {}, b""

        self.cat._transport = failing
        self.cat.snapshot()
        self.idle()
        after = self.cat.snapshot()
        self.assertIs(after["sessions"], first["sessions"])
        self.assertTrue(after["meta"]["stale"])
        self.assertEqual(after["meta"]["error"], "catalog_unavailable")

    def test_revoked_sign_in_is_never_served_from_the_cache(self):
        auth = FakeAuth()
        cat = make_catalog(self.api, self.clock, token=auth.access_token)
        cat.snapshot()
        auth.invalidate()
        with self.assertRaises(OfficialCatalogUnavailable) as raised:
            cat.snapshot()
        self.assertEqual(raised.exception.code, "official_sign_in_required")


class CopilotSharedCatalogTests(unittest.TestCase):
    def setUp(self):
        self.api, self.clock = FakeEventsAPI(), Clock()
        self.cat = make_catalog(self.api, self.clock)
        self.own_reads = []
        self._transport = catalog._transport
        catalog._transport = lambda *args: self.own_reads.append(args) or self.api.copilot(*args)
        self.auth = FakeAuth()
        official_auth.set_auth(self.auth)
        catalog.clear_cache()
        catalog.use_shared(self.cat)

    def tearDown(self):
        catalog.use_shared(None)
        catalog.clear_cache()
        catalog._transport = self._transport
        official_auth.set_auth(None)

    def test_load_sessions_makes_no_list_sessions_call_while_atlas_has_a_snapshot(self):
        self.cat.snapshot()  # Event Atlas loaded the agenda
        calls = self.api.list_calls
        rows = catalog.load_sessions()
        self.assertEqual(self.api.list_calls, calls)
        self.assertEqual(self.own_reads, [])
        self.assertEqual(catalog.last_source()["source"], "official_api")
        # Row content is exactly what the copilot's own read would have built (T6's live check relies on it).
        self.assertEqual(rows, [catalog.normalize_session(item, "America/Los_Angeles") for item in self.api.items])
        self.assertTrue(all(s["source"] == "official_api" for s in rows))

    def test_one_read_serves_both_sides_on_a_cold_start(self):
        rows = catalog.load_sessions()  # the copilot asks first; Event Atlas then answers from the same read
        snap = self.cat.snapshot()
        self.assertEqual(len(rows), len(snap["sessions"]))
        self.assertEqual(self.api.list_calls, PAGES)
        self.assertEqual(self.own_reads, [])

    def test_stale_rows_are_served_at_once_with_one_background_refresh(self):
        catalog.load_sessions()
        self.clock.now += 400  # older than both the old 60 s and 5-minute limits
        self.api.block()
        started = time.perf_counter()
        rows = [catalog.load_sessions() for _ in range(3)]
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertTrue(all(len(r) == 2516 for r in rows))
        self.assertEqual(self.cat.health()["refreshes"], 2)
        self.api.gate.set()
        wait_until(lambda: self.cat._refreshing is None)
        self.assertEqual(self.api.list_calls, 2 * PAGES)
        self.assertEqual(self.own_reads, [])

    def test_sign_in_clears_the_shared_snapshot(self):
        catalog.load_sessions()
        catalog.clear_cache()  # what web.py does after a completed sign-in
        self.assertFalse(self.cat.health()["available"])

    def test_signed_out_shared_catalog_maps_to_the_copilot_error(self):
        catalog.load_sessions()
        self.cat._token_provider = lambda: (_ for _ in ()).throw(official_auth.OAuthError("sign_in_required", terminal=True))
        with self.assertRaises(catalog.CatalogError) as raised:
            catalog.load_sessions("live")
        self.assertEqual(raised.exception.code, "official_sign_in_required")
        self.assertTrue(self.auth.invalidated)  # as after a 401 on the copilot's own read
        self.assertEqual(catalog.load_sessions("auto")[0]["source"], "synthetic_fixture")

    def test_read_superseded_by_a_sign_in_is_asked_once_more(self):
        real = self.cat.snapshot
        superseded = OfficialCatalogUnavailable("catalog_refresh_superseded")
        with mock.patch.object(self.cat, "snapshot", side_effect=[superseded, real("copilot")]):
            rows = catalog.load_sessions("live")
        self.assertEqual(rows[0]["source"], "official_api")
        with mock.patch.object(self.cat, "snapshot", side_effect=[superseded, superseded]):
            with self.assertRaises(catalog.CatalogError) as raised:
                catalog.load_sessions("live")
        self.assertEqual(raised.exception.code, "catalog_refresh_superseded")

    def test_get_session_uses_an_index_and_copies_only_the_row(self):
        with mock.patch.object(catalog, "load_sessions", side_effect=AssertionError("list copy")):
            first = catalog.get_session("syn-00007")
            index = catalog._index["by_id"]
            by_code = catalog.get_session("SYN0012")
            self.assertIs(catalog._index["by_id"], index)  # built once per snapshot
        self.assertEqual(first["title"], self.api.items[7]["title"])
        self.assertEqual(by_code["id"], "syn-00012")
        self.assertIsNone(catalog.get_session("nope"))
        first["title"] = "changed by a caller"
        self.assertNotEqual(catalog.get_session("syn-00007")["title"], "changed by a caller")
        self.assertEqual(self.api.list_calls, PAGES)


class GzipTests(unittest.TestCase):
    def test_accepts_gzip(self):
        for header, expected in (("gzip, deflate, br", True), ("GZIP;q=0.5", True), ("br", False),
                                 ("gzip;q=0", False), ("deflate, gzip; q=0.0", False), (None, False), ("", False)):
            self.assertIs(atlas_server.accepts_gzip(header), expected, header)


class OneProcessEndToEndTests(unittest.TestCase):
    """web.start_explorer wiring: Event Atlas and the copilot share one read; gzip through the proxy."""

    def setUp(self):
        self.api = FakeEventsAPI()
        official_auth.set_auth(FakeAuth())
        catalog.clear_cache()
        api = self.api
        with mock.patch.object(OfficialCatalog, "_http_get",
                               lambda self, path, query, token, timeout: api.atlas(path, query, token, timeout)):
            self.explorer = web.start_explorer(0)
        self._state = dict(web._state)
        web._state["explorer_port"] = self.explorer.server_port
        self.web = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.web.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.web.server_address[1]}"
        self._transport = catalog._transport
        catalog._transport = lambda *args: self.fail("the copilot made its own catalog read")

    def tearDown(self):
        for srv in (self.web, self.explorer):
            srv.shutdown()
            srv.server_close()
        web._state.clear()
        web._state.update(self._state)
        catalog.use_shared(None)
        catalog.clear_cache()
        catalog._transport = self._transport
        official_auth.set_auth(None)

    def get(self, path, accept_encoding=None):
        headers = {"Accept-Encoding": accept_encoding} if accept_encoding else {}
        with urlopen(Request(self.base + path, headers=headers), timeout=30) as r:
            return r.headers, r.read()

    def test_gzip_only_when_accepted_and_one_read_for_the_process(self):
        zipped_headers, zipped = self.get("/api/catalog", "gzip, deflate, br")
        plain_headers, plain = self.get("/api/catalog")
        self.assertEqual(zipped_headers.get("Content-Encoding"), "gzip")
        self.assertIsNone(plain_headers.get("Content-Encoding"))
        self.assertEqual(plain_headers.get("Vary"), "Accept-Encoding")
        self.assertEqual(gzip.decompress(zipped), plain)
        self.assertLess(len(zipped), len(plain) / 3)
        body = json.loads(plain)
        self.assertEqual(body["meta"]["count"], 2516)
        self.assertEqual(body["meta"]["sync"], {"phase": "ready", "pages": PAGES, "collected": 2516})
        self.assertFalse(body["meta"]["refreshing"])
        self.assertIsInstance(body["meta"]["received_at"], str)
        rows = catalog.load_sessions()
        self.assertEqual(len(rows), 2516)
        self.assertTrue(catalog.get_session("SYN0003"))
        _, health = self.get("/api/health")
        self.assertEqual(json.loads(health)["public_cache"]["refreshes"], 1)
        self.assertEqual(self.api.list_calls, PAGES)


if __name__ == "__main__":
    unittest.main()
