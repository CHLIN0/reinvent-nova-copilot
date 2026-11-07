"""Offline tests for the official data layer: fixture, search, mocked HTTP."""
import json
import unittest

from atlas import catalog, official_auth, official_mcp

TOKEN = "test-token-not-real"


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


def _item(n):
    return {"sessionId": f"s{n:03d}", "title": f"Session {n}", "abbreviation": f"TST{n:03d}",
            "type": "Breakout", "level": "300 - Advanced", "topics": ["Agents"],
            "venue": "Caesars Forum", "room": "Room 1",
            "sessionTime": {"date": "2026-12-01", "time": "10:00", "length": "60",
                            "timezone": "America/Los_Angeles"}}


class Recorder:
    """Scripted transport: list of (status, headers, body-dict) per call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, path, query, body, token):
        self.calls.append({"method": method, "path": path, "query": dict(query or {}),
                           "body": body, "token": token})
        status, headers, payload = self.responses.pop(0)
        return status, headers, json.dumps(payload).encode() if payload is not None else b""


class Base(unittest.TestCase):
    def setUp(self):
        self._transport, self._sleep = catalog._transport, catalog._sleep
        self.sleeps = []
        catalog._sleep = self.sleeps.append
        catalog.clear_cache()
        official_auth.set_auth(None)

    def tearDown(self):
        catalog._transport, catalog._sleep = self._transport, self._sleep
        catalog.clear_cache()
        official_auth.set_auth(None)


class FixtureTests(Base):
    def test_fixture_is_synthetic_and_well_formed(self):
        raw = json.loads(catalog.FIXTURE_PATH.read_text())
        self.assertTrue(raw["synthetic"])
        self.assertIn("SYNTHETIC", raw["note"])
        sessions = raw["sessions"]
        self.assertGreaterEqual(len(sessions), 55)
        self.assertEqual(len({s["id"] for s in sessions}), len(sessions))
        venues = {"venetian", "wynn", "encore", "caesars_forum", "mgm_grand", "mandalay_bay"}
        for s in sessions:
            self.assertIn(s["venue"], venues)
            self.assertTrue(s["start"].endswith("-08:00") and s["end"].endswith("-08:00"))
            self.assertIn(s["start"][:10], {"2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03"})
            self.assertLess(s["start"], s["end"])
            self.assertIn(s["level"], {"100", "200", "300", "400"})
        self.assertEqual({s["venue"] for s in sessions}, venues)

    def test_auto_without_sign_in_uses_fixture_with_visible_source(self):
        sessions = catalog.load_sessions("auto")
        self.assertTrue(sessions)
        self.assertTrue(all(s["source"] == "synthetic_fixture" for s in sessions))
        self.assertEqual(catalog.last_source(), {"source": "synthetic_fixture", "reason": "not_signed_in"})

    def test_search_keyword_and_filters(self):
        hits = catalog.search_sessions("agents", day="tue", source="fixture", limit=50)
        self.assertTrue(hits)
        for s in hits:
            self.assertTrue(s["start"].startswith("2026-12-01"))
        security = catalog.search_sessions(topics=["security"], levels=["300", "400"], source="fixture", limit=50)
        self.assertTrue(security)
        for s in security:
            self.assertIn(s["level"], {"300", "400"})
            self.assertTrue(any("security" in t.lower() for t in s["topics"]))
        workshops = catalog.search_sessions(types=["Workshop"], venue="Wynn Las Vegas", source="fixture", limit=50)
        for s in workshops:
            self.assertEqual((s["type"], s["venue"]), ("Workshop", "wynn"))
        self.assertEqual(catalog.search_sessions("zzz-no-match", source="fixture"), [])
        self.assertEqual(len(catalog.search_sessions(source="fixture", limit=3)), 3)

    def test_title_hits_rank_first(self):
        hits = catalog.search_sessions("mcp", source="fixture")
        self.assertIn("MCP", hits[0]["title"])

    def test_get_session_by_id_and_code(self):
        first = catalog.load_sessions("fixture")[0]
        self.assertEqual(catalog.get_session(first["id"], source="fixture")["title"], first["title"])
        self.assertEqual(catalog.get_session(first["code"], source="fixture")["id"], first["id"])
        self.assertIsNone(catalog.get_session("nope", source="fixture"))

    def test_live_only_calls_refuse_without_sign_in(self):
        with self.assertRaises(catalog.CatalogError) as ctx:
            catalog.get_schedule()
        self.assertEqual(ctx.exception.code, "official_sign_in_required")
        with self.assertRaises(catalog.CatalogError):
            catalog.add_favorites(["syn-0001"])


class LiveHttpTests(Base):
    def setUp(self):
        super().setUp()
        self.auth = FakeAuth()
        official_auth.set_auth(self.auth)

    def _event(self):
        return (200, {}, {"event": {"eventId": "reinvent2026", "timezone": "America/Los_Angeles"}})

    def test_pagination_runs_until_next_token_absent(self):
        rec = Recorder([self._event(),
                        (200, {}, {"items": [_item(1), _item(2)], "totalCount": 5, "nextToken": "p2"}),
                        (200, {}, {"items": [_item(3), _item(4)], "totalCount": 5, "nextToken": "p3"}),
                        (200, {}, {"items": [_item(5)], "totalCount": 5})])
        catalog._transport = rec
        sessions = catalog.load_sessions("live")
        self.assertEqual([s["id"] for s in sessions], ["s001", "s002", "s003", "s004", "s005"])
        page_tokens = [c["query"].get("nextToken") for c in rec.calls[1:]]
        self.assertEqual(page_tokens, [None, "p2", "p3"])
        self.assertIsNone(rec.calls[0]["token"])  # GetEvent is public
        self.assertTrue(all(c["token"] == TOKEN for c in rec.calls[1:]))
        s = sessions[0]
        self.assertEqual((s["source"], s["venue"], s["level"]), ("official_api", "caesars_forum", "300"))
        self.assertEqual((s["start"], s["end"]), ("2026-12-01T10:00:00-08:00", "2026-12-01T11:00:00-08:00"))
        self.assertEqual(catalog.last_source()["source"], "official_api")

    def test_incomplete_read_is_an_error(self):
        catalog._transport = Recorder([self._event(), (200, {}, {"items": [_item(1)], "totalCount": 2})])
        with self.assertRaises(catalog.CatalogError) as ctx:
            catalog.load_sessions("live")
        self.assertEqual(ctx.exception.code, "catalog_incomplete")

    def test_repeated_next_token_is_rejected(self):
        catalog._transport = Recorder([self._event(),
                                       (200, {}, {"items": [_item(1)], "totalCount": 3, "nextToken": "x"}),
                                       (200, {}, {"items": [_item(2)], "totalCount": 3, "nextToken": "x"})])
        with self.assertRaises(catalog.CatalogError) as ctx:
            catalog.load_sessions("live")
        self.assertEqual(ctx.exception.code, "catalog_pagination_invalid")

    def test_401_invalidates_and_reports_clearly_without_token(self):
        catalog._transport = Recorder([self._event(), (401, {}, None)])
        with self.assertRaises(catalog.CatalogError) as ctx:
            catalog.load_sessions("live")
        self.assertEqual(ctx.exception.code, "official_sign_in_required")
        self.assertIn("401", str(ctx.exception))
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertTrue(self.auth.invalidated)

    def test_401_in_auto_mode_falls_back_to_fixture(self):
        catalog._transport = Recorder([self._event(), (401, {}, None)])
        sessions = catalog.load_sessions("auto")
        self.assertTrue(all(s["source"] == "synthetic_fixture" for s in sessions))
        self.assertEqual(catalog.last_source()["reason"], "official_sign_in_required")

    def test_403_reports_event_access(self):
        catalog._transport = Recorder([self._event(), (403, {}, None)])
        with self.assertRaises(catalog.CatalogError) as ctx:
            catalog.load_sessions("live")
        self.assertEqual(ctx.exception.code, "official_event_access_required")

    def test_429_respects_retry_after_then_succeeds(self):
        catalog._transport = Recorder([self._event(),
                                       (429, {"Retry-After": "2"}, None),
                                       (429, {"retry-after": "1.5"}, None),
                                       (200, {}, {"items": [_item(1)], "totalCount": 1})])
        sessions = catalog.load_sessions("live")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(self.sleeps, [2.0, 1.5])

    def test_429_gives_up_after_retries(self):
        catalog._transport = Recorder([self._event()] + [(429, {"Retry-After": "1"}, None)] * 4)
        with self.assertRaises(catalog.CatalogError) as ctx:
            catalog.load_sessions("live")
        self.assertEqual(ctx.exception.code, "official_rate_limited")
        self.assertEqual(self.sleeps, [1.0, 1.0, 1.0])

    def test_429_with_huge_retry_after_does_not_sleep(self):
        catalog._transport = Recorder([self._event(), (429, {"Retry-After": "3600"}, None)])
        with self.assertRaises(catalog.CatalogError) as ctx:
            catalog.load_sessions("live")
        self.assertEqual((ctx.exception.code, ctx.exception.retry_after), ("official_rate_limited", 3600.0))
        self.assertEqual(self.sleeps, [])

    def test_add_favorites_reports_per_item_then_reads_back_schedule(self):
        rec = Recorder([
            (200, {}, {"result": {"successful": ["a1"],
                                  "failed": [{"sessionId": "b2", "code": "alreadyFavorited"}]}}),
            (200, {}, {"schedule": {"reserved": [], "favorites": ["a1", "b2"], "personalTime": []}}),
        ])
        catalog._transport = rec
        out = catalog.add_favorites(["a1", "b2", "a1"])
        self.assertEqual(rec.calls[0]["method"], "POST")
        self.assertEqual(rec.calls[0]["path"], "/v1/events/reinvent2026/favorites")
        self.assertEqual(rec.calls[0]["body"], {"sessionIds": ["a1", "b2"]})
        self.assertEqual(rec.calls[1]["path"], "/v1/events/reinvent2026/schedule")
        self.assertEqual(out["results"][0], {"session_id": "a1", "ok": True, "in_schedule_favorites": True})
        self.assertEqual(out["results"][1]["code"], "alreadyFavorited")
        self.assertTrue(out["verified"])
        self.assertEqual(out["schedule"]["favorites"], ["a1", "b2"])

    def test_add_favorites_rejects_bad_counts(self):
        with self.assertRaises(ValueError):
            catalog.add_favorites([])
        with self.assertRaises(ValueError):
            catalog.add_favorites([f"x{i}" for i in range(11)])


class AuthTests(unittest.TestCase):
    def test_callback_port_8489_is_refused(self):
        with self.assertRaises(ValueError):
            official_auth.OfficialAuth(redirect_uri="http://127.0.0.1:8489/callback")
        with self.assertRaises(ValueError):
            official_auth.OfficialAuth(redirect_uri="http://127.0.0.1:8492/callback")
        self.assertNotIn(8489, official_auth.CALLBACK_PORTS)

    def test_pkce_start_and_memory_only_status(self):
        auth = official_auth.OfficialAuth(redirect_uri="http://127.0.0.1:8485/callback")
        url = auth.start()["authorization_url"]
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A8485%2Fcallback", url)
        status = auth.status()
        self.assertEqual((status["connected"], status["memory_only"]), (False, True))
        self.assertNotIn("access_token", json.dumps(status))

    def test_token_exchange_keeps_token_out_of_status(self):
        from urllib.parse import parse_qs, urlsplit

        def transport(method, url, headers, body):
            return official_auth.TokenResponse(200, {}, json.dumps(
                {"access_token": "AT-secret", "refresh_token": "RT-secret",
                 "expires_in": 3600, "token_type": "Bearer"}).encode())
        auth = official_auth.OfficialAuth(transport=transport)
        state = parse_qs(urlsplit(auth.start()["authorization_url"]).query)["state"][0]
        status = auth.complete(f"code=abc&state={state}")
        self.assertTrue(status["connected"])
        self.assertNotIn("secret", json.dumps(status))
        self.assertEqual(auth.access_token(), "AT-secret")


class MCPTests(unittest.TestCase):
    def setUp(self):
        self._transport = official_mcp._transport
        official_mcp.reset()
        official_auth.set_auth(FakeAuth())

    def tearDown(self):
        official_mcp._transport = self._transport
        official_mcp.reset()
        official_auth.set_auth(None)

    def test_initialize_list_and_call_over_sse_and_json(self):
        seen = []

        def transport(url, headers, body):
            msg = json.loads(body)
            seen.append((msg["method"], dict(headers)))
            if msg["method"] == "initialize":
                return 200, {"Content-Type": "application/json", "Mcp-Session-Id": "sess-1"}, json.dumps(
                    {"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-06-18"}}).encode()
            if msg["method"] == "notifications/initialized":
                return 202, {}, b""
            if msg["method"] == "tools/list":
                payload = {"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": [{"name": "ListEvents"}]}}
                return 200, {"Content-Type": "text/event-stream"}, (
                    "event: message\ndata: " + json.dumps(payload) + "\n\n").encode()
            return 200, {"Content-Type": "application/json"}, json.dumps(
                {"jsonrpc": "2.0", "id": msg["id"],
                 "result": {"content": [{"type": "text", "text": "ok"}], "args": msg["params"]}}).encode()

        official_mcp._transport = transport
        self.assertEqual(official_mcp.list_tools(), [{"name": "ListEvents"}])
        result = official_mcp.call_tool("GetEvent", {"eventId": "reinvent2026"})
        self.assertEqual(result["args"], {"name": "GetEvent", "arguments": {"eventId": "reinvent2026"}})
        self.assertEqual([m for m, _ in seen], ["initialize", "notifications/initialized", "tools/list", "tools/call"])
        self.assertEqual(seen[0][1]["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(seen[2][1]["Mcp-Session-Id"], "sess-1")

    def test_401_raises_sign_in_required(self):
        official_mcp._transport = lambda url, headers, body: (401, {}, b"")
        with self.assertRaises(official_mcp.MCPError) as ctx:
            official_mcp.list_tools()
        self.assertEqual(ctx.exception.code, "official_sign_in_required")

    def test_requires_sign_in(self):
        official_auth.set_auth(None)
        with self.assertRaises(official_mcp.MCPError) as ctx:
            official_mcp.call_tool("ListEvents")
        self.assertEqual(ctx.exception.code, "official_sign_in_required")


if __name__ == "__main__":
    unittest.main()
