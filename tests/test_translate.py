"""Offline translation tests: no AWS credentials, network, or real model calls."""
import copy
import json
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import web
from atlas import catalog, costs, translate


def response(title="AWS Lambda 入門", abstract="使用 AWS Lambda 建立應用程式。"):
    return {"output": {"message": {"content": [{"text": json.dumps({
        "title": title, "abstract": abstract}, ensure_ascii=False)}]}},
        "stopReason": "end_turn", "usage": {"inputTokens": 100, "outputTokens": 40}}


class TranslateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache_dir = Path(self.tmp.name) / "translations"
        self.ledger = Path(self.tmp.name) / "costs.jsonl"
        self.session = {"id": "test-session", "code": "TST101", "title": "AWS Lambda intro",
                        "abstract": "Build applications with AWS Lambda.", "content_language": "en-US"}
        self.client = mock.Mock()
        self.client.converse.return_value = response()
        for patch in [mock.patch.object(translate, "TRANSLATION_DIR", self.cache_dir),
                      mock.patch.object(costs, "LEDGER_PATH", self.ledger),
                      mock.patch.object(translate, "make_client", return_value=self.client),
                      mock.patch.object(catalog.official_auth, "is_signed_in", return_value=False),
                      mock.patch.object(catalog, "get_session", side_effect=lambda *a, **kw: copy.deepcopy(self.session)),
                      mock.patch.dict(os.environ, {"TRANSLATE_MODEL_ID": ""})]:
            patch.start()
            self.addCleanup(patch.stop)

    def run_translation(self, lang="zh-Hant"):
        return translate.translate_session(self.session["id"], lang)

    def test_official_locale_sends_query_and_uses_actual_header(self):
        item = {"sessionId": self.session["id"], "title": "官方標題", "abstract": "官方摘要"}
        with mock.patch.object(catalog.official_auth, "is_signed_in", return_value=True), \
                mock.patch.object(catalog.official_auth, "get_access_token", return_value="offline-token"), \
                mock.patch.object(catalog, "_transport", return_value=(
                    200, {"cOnTeNt-LaNgUaGe": "zh-Hant"}, json.dumps({"session": item}).encode())) as http:
            result = self.run_translation()
        self.assertEqual(http.call_args.args[2], {"locale": "zh-Hant"})
        self.assertTrue(http.call_args.args[1].endswith("/sessions/" + self.session["id"]))
        self.assertEqual(result, {"title": "官方標題", "abstract": "官方摘要", "lang": "zh-Hant",
                                  "source": "official", "model": None, "cached": False})
        self.client.converse.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_missing_or_english_header_falls_back_to_nova(self):
        for language in ("", "en-US"):
            with self.subTest(language=language), \
                    mock.patch.object(catalog.official_auth, "is_signed_in", return_value=True), \
                    mock.patch.object(catalog, "get_session_localized", return_value={
                        **self.session, "id": language or "missing", "content_language": language}) as official:
                result = self.run_translation()
                self.assertEqual(result["source"], "nova")
                official.assert_called_once_with(self.session["id"], "zh-Hant")

    def test_cache_miss_one_model_call_and_cost_ledger_line(self):
        result = self.run_translation()
        self.assertEqual((result["source"], result["cached"], result["lang"]), ("nova", False, "zh-Hant"))
        self.assertEqual(result["model"], translate.DEFAULT_MODEL_ID)
        self.client.converse.assert_called_once()
        request = self.client.converse.call_args.kwargs
        self.assertNotIn("toolConfig", request)
        self.assertEqual(request["system"], [{"text": translate.PROMPT}])
        sent = json.loads(request["messages"][0]["content"][0]["text"])
        self.assertEqual(sent["code"], self.session["code"])
        self.assertEqual(sent["abstract"], self.session["abstract"])
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["feature"], rows[0]["total_tokens"], rows[0]["rounds"]), ("translate", 140, 0))
        self.assertGreater(rows[0]["usd"], 0)
        self.assertIn("| translate | 1 |", costs.render_report(costs.summarize(self.ledger)))
        self.assertNotIn("abstract", rows[0])

    def test_cache_hit_calls_no_model_and_preserves_model(self):
        first = self.run_translation()
        self.client.converse.reset_mock()
        second = self.run_translation()
        self.assertEqual((second["source"], second["cached"]), ("cache", True))
        self.assertEqual((second["title"], second["model"]), (first["title"], first["model"]))
        self.client.converse.assert_not_called()
        self.assertEqual(len(self.ledger.read_text().splitlines()), 1)

    def test_private_cache_and_exact_key(self):
        self.run_translation()
        path = self.cache_dir / "zh-Hant.jsonl"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        row = json.loads(path.read_text())
        self.assertEqual(row["key"][0:2], [catalog.EVENT_ID, self.session["id"]])
        self.assertEqual(len(row["key"][2]), 64)
        self.assertEqual(row["key"][3:], ["zh-Hant", translate.TRANSLATOR_VERSION])
        path.chmod(0o644)
        self.run_translation()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_title_and_abstract_hash_invalidation(self):
        self.run_translation()
        for field in ("title", "abstract"):
            self.session[field] += " Updated."
            self.assertEqual(self.run_translation()["source"], "nova")
        self.assertEqual(self.client.converse.call_count, 3)

    def test_version_language_event_and_session_are_separate(self):
        self.run_translation()
        with mock.patch.object(translate, "TRANSLATOR_VERSION", "next"):
            self.assertEqual(self.run_translation()["source"], "nova")
        self.assertEqual(self.run_translation("ja")["source"], "nova")
        with mock.patch.object(catalog, "EVENT_ID", "other-event"):
            self.assertEqual(self.run_translation()["source"], "nova")
        self.session["id"] = "other-session"
        self.assertEqual(self.run_translation()["source"], "nova")
        self.assertEqual(self.client.converse.call_count, 5)

    def test_override_model(self):
        with mock.patch.dict(os.environ, {"TRANSLATE_MODEL_ID": "us.amazon.nova-lite-v1:0"}):
            self.assertEqual(self.run_translation()["model"], "us.amazon.nova-lite-v1:0")
        self.assertEqual(self.client.converse.call_args.kwargs["modelId"], "us.amazon.nova-lite-v1:0")

    def test_bad_or_truncated_response_is_billed_but_not_cached(self):
        for reason, text in [("max_tokens", '{"title":'), ("end_turn", 'not json'),
                             ("end_turn", '{"title":"ok","abstract":""}')]:
            self.client.converse.return_value = {
                "stopReason": reason, "usage": {"inputTokens": 10, "outputTokens": 5},
                "output": {"message": {"content": [{"text": text}]}}}
            with self.assertRaises(translate.TranslationError):
                self.run_translation()
        self.assertFalse(self.cache_dir.exists())
        self.assertEqual(len(self.ledger.read_text().splitlines()), 3)

    def test_language_validation_before_any_call(self):
        for language in ("../en", "", "zh/Hant", "x" * 100, None):
            with self.assertRaises(ValueError):
                self.run_translation(language)
        self.client.converse.assert_not_called()
        self.assertEqual(translate.normalize_language("繁體中文"), "zh-Hant")
        self.assertEqual(translate.normalize_language("ZH-hant"), "zh-Hant")

    def test_unknown_session_and_official_errors_do_not_call_model(self):
        with mock.patch.object(catalog, "get_session", return_value=None):
            with self.assertRaises(translate.TranslationError) as ctx:
                self.run_translation()
            self.assertEqual(ctx.exception.code, "session_not_found")
        with mock.patch.object(catalog.official_auth, "is_signed_in", return_value=True), \
                mock.patch.object(catalog, "get_session_localized", side_effect=catalog.CatalogError("catalog_unavailable")):
            with self.assertRaises(catalog.CatalogError):
                self.run_translation()
        self.client.converse.assert_not_called()

    def test_concurrent_clicks_share_one_model_call(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.run_translation(), range(4)))
        self.client.converse.assert_called_once()
        self.assertEqual(sum(r["cached"] for r in results), 3)


class TranslateRouteTests(unittest.TestCase):
    def handler(self, path):
        handler = web.Handler.__new__(web.Handler)
        handler.path = path
        handler._host_ok = mock.Mock(return_value=True)
        handler._json = mock.Mock()
        return handler

    def test_get_translation_and_profile_language_default(self):
        for suffix, language in [("?lang=ja", "ja"), ("", "zh-Hant")]:
            handler = self.handler("/api/translate/test%20session" + suffix)
            with mock.patch.object(web.profile, "load_profile", return_value={"fields": {}}), \
                    mock.patch.object(translate, "translate_session", return_value={"source": "cache"}) as fn:
                handler.do_GET()
                fn.assert_called_once_with("test session", language)
                handler._json.assert_called_once_with(200, {"source": "cache"})

    def test_profile_language_used_without_explicit_query(self):
        handler = self.handler("/api/translate/test-session")
        with mock.patch.object(web.profile, "load_profile", return_value={"fields": {"language": "ja"}}), \
                mock.patch.object(translate, "translate_session", return_value={}) as fn:
            handler.do_GET()
        fn.assert_called_once_with("test-session", "ja")

    def test_errors_are_safe_and_have_status(self):
        for exc, status, code in [(ValueError("invalid_language"), 400, "invalid_language"),
                                  (translate.TranslationError("session_not_found"), 404, "session_not_found"),
                                  (RuntimeError("secret upstream body"), 502, "translation_unavailable")]:
            handler = self.handler("/api/translate/test-session?lang=zh-Hant")
            with mock.patch.object(web.profile, "load_profile", return_value={"fields": {}}), \
                    mock.patch.object(translate, "translate_session", side_effect=exc):
                handler.do_GET()
            handler._json.assert_called_once_with(status, {"error": code})

    def test_host_guard_before_translation(self):
        handler = self.handler("/api/translate/test-session")
        handler._host_ok.return_value = False
        with mock.patch.object(translate, "translate_session") as fn:
            handler.do_GET()
        fn.assert_not_called()
        handler._json.assert_called_once_with(403, {"error": "forbidden host"})


if __name__ == "__main__":
    unittest.main()
