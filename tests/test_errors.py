"""Row B2: failures reach the attendee as a short code and one plain sentence, through the real HTTP handler.

Official API failures enter as urllib HTTPError (401/403/429) through the real catalog request path;
Bedrock failures as botocore ClientError codes. No exception class or raw text may reach the response.
"""
import contextlib
import io
import json
import threading
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import tests  # noqa: F401  # temporary cost ledger
import web
from atlas import catalog, official_auth, translate

try:
    from botocore.exceptions import ClientError, NoCredentialsError
except ImportError:  # botocore is installed in CI; a stand-in with the same module and shape keeps this offline
    class ClientError(Exception):
        def __init__(self, error_response, operation_name):
            self.response = error_response
            err = error_response["Error"]
            super().__init__(f"An error occurred ({err['Code']}) when calling the {operation_name} "
                             f"operation: {err.get('Message')}")

    class NoCredentialsError(Exception):
        def __init__(self):
            super().__init__("Unable to locate credentials")

    ClientError.__module__ = NoCredentialsError.__module__ = "botocore.exceptions"

SECRET = "arn:aws:bedrock:us-east-1:123456789012 secret upstream body"
MESSAGES = {code: message for code, (_, message) in web._ERRORS.items()}


def bedrock(code):
    return ClientError({"Error": {"Code": code, "Message": SECRET}}, "Converse")


def http_error(status):
    return HTTPError("https://example.invalid/api", status, SECRET, {}, None)


class ErrorRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = Request(self.base + path, data=data, method="GET" if body is None else "POST",
                      headers={"Content-Type": "application/json"})
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            try:
                with urlopen(req, timeout=10) as r:
                    return r.status, json.loads(r.read()), stderr.getvalue()
            except HTTPError as e:
                with e:
                    return e.code, json.loads(e.read()), stderr.getvalue()

    def assert_failure(self, result, status, code, cls_name):
        got_status, body, log = result
        self.assertEqual(got_status, status)
        self.assertEqual(body.get("error"), code)
        self.assertEqual(body.get("message"), MESSAGES[code])
        text = json.dumps(body)
        for leak in (cls_name, "secret", "123456789012", "Traceback"):
            self.assertNotIn(leak, text)
        self.assertIn(cls_name, log)  # the class is logged for the operator...
        self.assertNotIn("secret", "".join(l for l in log.splitlines() if l.startswith("nova-copilot")))  # never the text
        self.assertIn(code, log)

    def official(self):
        """Signed in with a fake token; the real _request turns the transport's HTTPError into a CatalogError."""
        stack = contextlib.ExitStack()
        stack.enter_context(mock.patch.object(official_auth, "get_access_token", return_value="fake-token"))
        stack.enter_context(mock.patch.object(official_auth, "current_auth", return_value=None))
        stack.enter_context(mock.patch.object(catalog, "_sleep"))
        stack.enter_context(mock.patch.object(catalog, "_require_live"))
        self.addCleanup(stack.close)
        return stack

    def test_official_401_is_signin_expired(self):
        self.official()
        with mock.patch.object(catalog._OPENER, "open", side_effect=http_error(401)):
            result = self.call("/api/rsvp", {"session_ids": ["s-1"]})
        self.assert_failure(result, 401, "signin_expired", "CatalogError")

    def test_expired_token_is_signin_expired(self):
        with mock.patch.object(official_auth, "get_access_token",
                               side_effect=official_auth.OAuthError("sign_in_required")):
            result = self.call("/api/rsvp/cancel", {"session_ids": ["s-1"]})
        self.assert_failure(result, 401, "signin_expired", "CatalogError")

    def test_official_403_is_forbidden(self):
        self.official()
        with mock.patch.object(catalog._OPENER, "open", side_effect=http_error(403)):
            result = self.call("/api/favorite", {"session_ids": ["s-1"]})
        self.assert_failure(result, 403, "forbidden", "CatalogError")

    def test_official_429_is_rate_limited(self):
        self.official()
        with mock.patch.object(catalog._OPENER, "open", side_effect=http_error(429)):
            result = self.call("/api/rsvp", {"session_ids": ["s-1"]})
        self.assert_failure(result, 429, "rate_limited", "CatalogError")

    def test_raw_http_errors_map_by_status(self):
        for status, code in ((401, "signin_expired"), (403, "forbidden"), (429, "rate_limited")):
            with self.subTest(status=status), mock.patch.object(web.catalog, "add_favorites",
                                                                side_effect=http_error(status)):
                self.assert_failure(self.call("/api/favorite", {"session_ids": ["s-1"]}), status, code, "HTTPError")

    def test_bedrock_failures_are_model_unavailable(self):
        for code in ("ThrottlingException", "ServiceUnavailableException", "AccessDeniedException",
                     "ModelErrorException", "ValidationException"):
            with self.subTest(code=code), mock.patch.object(web, "_chat", side_effect=bedrock(code)):
                result = self.call("/api/chat", {"message": "What should I attend?"})
                self.assert_failure(result, 503, "model_unavailable", "ClientError")
                self.assertIn(code, result[2])
        with mock.patch.object(web, "_chat", side_effect=NoCredentialsError()):
            self.assert_failure(self.call("/api/chat", {"message": "hi"}), 503, "model_unavailable",
                                "NoCredentialsError")

    def test_briefing_and_translate_bedrock_failures(self):
        with mock.patch.object(web, "_briefing", side_effect=bedrock("ThrottlingException")):
            self.assert_failure(self.call("/api/briefing", {}), 503, "model_unavailable", "ClientError")
        with mock.patch.object(translate, "translate_session", side_effect=bedrock("ModelErrorException")):
            self.assert_failure(self.call("/api/translate/s-1?lang=zh-Hant"), 503, "model_unavailable",
                                "ClientError")

    def test_bedrock_model_error_message_is_logged_without_tokens(self):
        """T9a round 2: ModelErrorException / ValidationException log Bedrock's message (300 chars, tokens redacted)."""
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
        text = f"Model produced invalid sequence as part of ToolUse. Bearer {token} " + "x " * 300
        for code in ("ModelErrorException", "ValidationException"):
            err = ClientError({"Error": {"Code": code, "Message": text}}, "Converse")
            with self.subTest(code=code), mock.patch.object(web, "_briefing", side_effect=err):
                status, body, log = self.call("/api/briefing", {})
            self.assertEqual((status, body.get("error")), (503, "model_unavailable"))
            line = next(l for l in log.splitlines() if l.startswith("bedrock-message briefing: "))
            self.assertIn("Model produced invalid sequence as part of ToolUse.", line)
            self.assertNotIn(token, log)
            self.assertNotIn("eyJ", log)
            self.assertIn("[redacted]", line)
            self.assertLessEqual(len(line), len("bedrock-message briefing: ") + 300)
            self.assertNotIn("invalid sequence", json.dumps(body))
        with mock.patch.object(web, "_briefing", side_effect=bedrock("ThrottlingException")):
            log = self.call("/api/briefing", {})[2]
        self.assertNotIn("bedrock-message", log)  # other codes: class and code only

    def test_bedrock_message_token_across_the_300_character_cut_is_redacted(self):
        """Codex review r1 (P1): truncating before redacting left the token's first characters in the log."""
        token = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
        for start in (276, 285, 292, 299):
            text = ("ab " * 100)[:start - 1].ljust(start - 1, "a") + " " + token + " tail"  # short words: not token-like
            err = ClientError({"Error": {"Code": "ModelErrorException", "Message": text}}, "Converse")
            with self.subTest(start=start), mock.patch.object(web, "_briefing", side_effect=err):
                log = self.call("/api/briefing", {})[2]
                line = next(l for l in log.splitlines() if l.startswith("bedrock-message briefing: "))
                self.assertNotIn(token[:5], line)
                self.assertLessEqual(len(line), len("bedrock-message briefing: ") + 300)

    def test_unknown_errors_are_server_error(self):
        with mock.patch.object(web, "_chat", side_effect=RuntimeError(SECRET)):
            self.assert_failure(self.call("/api/chat", {"message": "hi"}), 500, "server_error", "RuntimeError")
        with mock.patch.object(web, "_change_plan", side_effect=KeyError(SECRET)):
            self.assert_failure(self.call("/api/plan", {"action": "add", "session_ids": ["s-1"]}), 500,
                                "server_error", "KeyError")
        with mock.patch.object(web, "_plan", side_effect=OSError(SECRET)):
            self.assert_failure(self.call("/api/plan"), 500, "server_error", "OSError")
        with mock.patch.object(web.catalog, "cancel_reservations",
                               side_effect=catalog.CatalogError("catalog_unavailable", message=SECRET)):
            self.assert_failure(self.call("/api/rsvp/cancel", {"session_ids": ["s-1"]}), 500, "server_error",
                                "CatalogError")

    def test_my_schedule_keeps_signed_in_flag(self):
        with mock.patch.object(official_auth, "is_signed_in", return_value=True), \
                mock.patch.object(web, "_my_schedule",
                                  side_effect=catalog.CatalogError("official_sign_in_required", message=SECRET)):
            status, body, _ = self.call("/api/my-schedule")
        self.assertEqual((status, body), (401, {"signed_in": True, "error": "signin_expired",
                                                "message": MESSAGES["signin_expired"]}))

    def test_plan_official_read_error_reports_code_only(self):
        with mock.patch.object(official_auth, "is_signed_in", return_value=True), \
                mock.patch.object(catalog, "get_schedule", side_effect=RuntimeError(SECRET)), \
                contextlib.redirect_stderr(io.StringIO()):
            official = web._plan()["official"]
        self.assertEqual(official, {"status": "error", "error": "server_error"})

    def test_official_not_found_and_closed_keep_their_sentence(self):
        for code, status in (("official_event_not_found", 404), ("official_operation_closed", 409)):
            with self.subTest(code=code), mock.patch.object(web.catalog, "reserve_sessions",
                                                            side_effect=catalog.CatalogError(code, message=catalog._MESSAGES[code])):
                got, body, _ = self.call("/api/rsvp", {"session_ids": ["s-1"]})
            self.assertEqual((got, body), (status, {"error": code, "message": catalog._MESSAGES[code]}))

    def test_existing_specific_errors_unchanged(self):
        status, body, _ = self.call("/api/plan", {"action": "fly", "session_ids": ["s-1"]})
        self.assertEqual((status, body), (400, {"error": "action must be 'add' or 'remove'"}))
        with mock.patch.object(translate, "translate_session", side_effect=RuntimeError(SECRET)):
            status, body, _ = self.call("/api/translate/s-1?lang=zh-Hant")
        self.assertEqual((status, body), (502, {"error": "translation_unavailable"}))


if __name__ == "__main__":
    unittest.main()
