"""Offline status projection, token refresh, and real Copilot banner checks."""
import json
import io
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import web
from atlas import official_auth


class StubAuth:
    def __init__(self, **status):
        self.state = {"connected": True, "auth_status": "connected",
                      "expires_at": 1180, **status}

    def status(self):
        return dict(self.state)

    def access_token(self, force_refresh=False):
        raise AssertionError("Status must never request or refresh credentials")


class StatusTests(unittest.TestCase):
    def setUp(self):
        self.auth = mock.patch.object(official_auth, "_AUTH", None)
        self.auth.start()
        self.addCleanup(self.auth.stop)
        for patch in (mock.patch.dict(web._state, {"signed_in_once": False}),
                      mock.patch.object(web.time, "time", return_value=1000),
                      mock.patch.object(web.profile, "load_profile", return_value={"profile": "test"})):
            patch.start()
            self.addCleanup(patch.stop)

    def endpoint(self):
        # Exercise GET routing and serialization without binding a socket.
        handler = web.Handler.__new__(web.Handler)
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 8510))
        handler.headers = {"Host": "127.0.0.1:8510"}
        handler.path = "/api/status"
        handler._json = mock.Mock()
        handler.do_GET()
        code, body = handler._json.call_args.args
        self.assertEqual(code, 200)
        return json.loads(json.dumps(body))

    def test_three_minutes_left_and_safe_metadata(self):
        official_auth.set_auth(StubAuth(access_token="test-secret", refresh_token="test-secret"))
        status = self.endpoint()
        self.assertTrue(status["signed_in"])
        self.assertEqual(status["expires_at"], 1180)
        self.assertEqual(status["seconds_left"], 180)
        self.assertEqual(status["restarted_at"], web.RESTARTED_AT)
        self.assertIsNone(status["reason"])
        self.assertNotIn("test-secret", json.dumps(status))

    def test_startup_reports_restart_and_stable_timestamp(self):
        status = self.endpoint()
        self.assertFalse(status["signed_in"])
        self.assertEqual(status["reason"], "restarted")
        self.assertIsNone(status["expires_at"])
        self.assertIsNone(status["seconds_left"])
        self.assertFalse(status["refreshable"])
        self.assertEqual(status["restarted_at"], self.endpoint()["restarted_at"])

    def test_expiry_without_refresh_is_not_a_restart(self):
        official_auth.set_auth(StubAuth())
        self.endpoint()
        official_auth.set_auth(StubAuth(expires_at=999))
        status = self.endpoint()
        self.assertFalse(status["signed_in"])
        self.assertEqual(status["seconds_left"], 0)
        self.assertEqual(status["reason"], "expired")
        official_auth.set_auth(None)
        self.assertEqual(self.endpoint()["reason"], "sign_in_required")

    def test_last_fraction_of_second_is_still_signed_in(self):
        official_auth.set_auth(StubAuth(expires_at=1000.5))
        self.assertTrue(self.endpoint()["signed_in"])

    def test_real_memory_only_refresh_and_terminal_failure(self):
        clock = [1000]
        transport = mock.Mock(return_value=official_auth.TokenResponse(200, {}, json.dumps({
            "access_token": "test-access", "refresh_token": "test-refresh",
            "expires_in": 180, "refresh_expires_in": 1000,
        }).encode()))
        auth = official_auth.OfficialAuth(transport=transport, clock=lambda: clock[0])
        state = parse_qs(urlsplit(auth.start()["authorization_url"]).query)["state"][0]
        auth.complete(f"code=test&state={state}")
        official_auth.set_auth(auth)
        self.assertTrue(self.endpoint()["refreshable"])
        clock[0] = 1181
        with mock.patch.object(web.time, "time", return_value=clock[0]):
            status = self.endpoint()
            self.assertTrue(status["signed_in"])
            self.assertEqual(status["seconds_left"], 0)
            self.assertEqual(status["auth_status"], "refresh_required")
            self.assertEqual(transport.call_count, 1)  # Status never refreshes.
            auth.access_token()
            self.assertEqual(self.endpoint()["seconds_left"], 180)
            self.assertEqual(parse_qs(transport.call_args.args[3].decode())["grant_type"], ["refresh_token"])
            transport.return_value = official_auth.TokenResponse(400, {}, b'{"error":"invalid_grant"}')
            with self.assertRaises(official_auth.OAuthError):
                auth.access_token(force_refresh=True)
            status = self.endpoint()
            self.assertFalse(status["signed_in"])
            self.assertFalse(status["refreshable"])
            self.assertEqual(status["auth_status"], "reauth_required")
            self.assertEqual(status["reason"], "sign_in_required")

    def test_refresh_deadline_requires_sign_in(self):
        clock = [1000]
        auth = official_auth.OfficialAuth(clock=lambda: clock[0], transport=lambda *_: official_auth.TokenResponse(
            200, {}, b'{"access_token":"test-access","refresh_token":"test-refresh","expires_in":180,"refresh_expires_in":200}'))
        state = parse_qs(urlsplit(auth.start()["authorization_url"]).query)["state"][0]
        auth.complete(f"code=test&state={state}")
        official_auth.set_auth(auth)
        self.endpoint()
        clock[0] = 1200
        status = self.endpoint()
        self.assertFalse(status["refreshable"])
        self.assertFalse(status["signed_in"])
        self.assertEqual(status["reason"], "sign_in_required")

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for the actual banner function")
    def test_real_banner_with_three_minute_api_status(self):
        official_auth.set_auth(StubAuth())
        # Take the real POST route's response rather than inventing its wire shape.
        handler = web.Handler.__new__(web.Handler)
        handler.server = SimpleNamespace(server_address=("127.0.0.1", 8510))
        handler.headers = {"Host": "127.0.0.1:8510", "Content-Type": "application/json", "Content-Length": "2"}
        handler.path = "/api/auth/start"
        handler.rfile = io.BytesIO(b"{}")
        handler._json = mock.Mock()
        with mock.patch.object(web, "_start_sign_in", return_value={
                "sign_in": {"url": "https://example.invalid/signin", "running": True}}):
            handler.do_POST()
        code, sign_in = handler._json.call_args.args
        self.assertEqual(code, 200)
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(
            ["node", str(root / "tests" / "copilot_status.mjs"), str(root / "web" / "copilot.js")],
            input=json.dumps({"status": self.endpoint(), "sign_in": sign_in}),
            text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("banner status checks passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
