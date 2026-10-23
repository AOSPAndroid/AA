"""Firecrawl transport, fallback, cached evidence and private key setup; no live API."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import start
import web_tools as web

TEST_KEY = "fc-test-only-key-for-offline-tests"


def client_with(data):
    client = web.FirecrawlClient(TEST_KEY)
    response = MagicMock()
    response.read.return_value = json.dumps({"success": True, "data": data}).encode()
    client.http = MagicMock()
    client.http.open.return_value.__enter__.return_value = response
    return client, response


class FirecrawlTests(unittest.TestCase):
    def test_search_uses_v2_authentication_and_filters_results(self):
        client, _ = client_with({"web": [
            {"url": "https://example.com/help", "title": "Help", "description": "A source"},
            {"url": "https://example.com/help", "title": "Duplicate"},
            {"url": "http://127.0.0.1/private"},
            {"url": "https://example.org", "title": "Another source"}]})
        result = client.search("vendor docs", 2)
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["snippet"], "A source")
        self.assertEqual(result["provider"], "Firecrawl")
        self.assertTrue(result["untrusted_content"])
        request = client.http.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.firecrawl.dev/v2/search")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + TEST_KEY)
        payload = json.loads(request.data)
        self.assertEqual(payload["query"], "vendor docs")
        self.assertEqual(payload["limit"], 2)
        self.assertNotIn("scrapeOptions", payload)
        self.assertNotIn(TEST_KEY, request.full_url + request.data.decode() + json.dumps(result))

    def test_rendered_text_and_pdf_use_one_request_for_cached_pagination(self):
        for url in ("https://example.com/dynamic", "https://example.com/manual.pdf"):
            with self.subTest(url=url):
                client, _ = client_with({"markdown": "Useful text. " * 300,
                                         "metadata": {"sourceURL": url, "title": "Manual", "statusCode": 200},
                                         "links": ["/help", "/help", "http://127.0.0.1", "javascript:bad()"]})
                fallback = MagicMock()
                browser = web.WebTools(fetcher=fallback, firecrawl=client)
                with patch.object(web, "_lookup", return_value=["93.184.216.34"]):
                    first = browser.read(url, limit=200)
                    second = browser.read(url, offset=first["next_offset"], limit=200)
                self.assertTrue(second["cached"])
                self.assertEqual(first["provider"], "Firecrawl")
                self.assertEqual(first["content_type"], "text/markdown")
                self.assertEqual(first["total_links"], 1)
                self.assertEqual(first["links"][0]["url"], "https://example.com/help")
                self.assertTrue(second["untrusted_content"])
                client.http.open.assert_called_once()
                fallback.assert_not_called()
                payload = json.loads(client.http.open.call_args.args[0].data)
                self.assertFalse(payload["skipTlsVerification"])
                self.assertNotIn("actions", payload)
                self.assertNotIn("headers", payload)

    def test_private_destinations_are_rejected_before_cloud_request(self):
        client, _ = client_with({})
        for url in ("http://127.0.0.1/", "http://workstation/", "file:///secret", "https://user:password@example.com"):
            with self.subTest(url=url), self.assertRaises(web.WebError):
                client.read(url)
        with patch.object(web.socket, "getaddrinfo", return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]):
            with self.assertRaises(web.WebError):
                client.read("https://private.example.com")
        client.http.open.assert_not_called()

    def test_api_errors_never_echo_credentials_or_response_bodies(self):
        client, _ = client_with({})
        for status in (401, 402, 403, 429, 500):
            body = io.BytesIO(("secret response " + TEST_KEY).encode())
            failure = urllib.error.HTTPError(client.BASE + "search", status, TEST_KEY, {}, body)
            client.http.open.side_effect = failure
            with self.subTest(status=status), self.assertRaises(web.WebError) as caught:
                client.search("docs", 1)
            self.assertNotIn(TEST_KEY, str(caught.exception))
            self.assertNotIn("secret response", str(caught.exception))
            self.assertTrue(body.closed)

    def test_invalid_and_oversized_responses_are_bounded(self):
        client, response = client_with({})
        for raw in (b"not json", b"[]", b'{"success":false,"error":"private"}', b"x" * (web.MAX_BYTES + 1)):
            response.read.return_value = raw
            with self.subTest(size=len(raw)), self.assertRaises(web.WebError) as caught:
                client.search("docs", 1)
            self.assertNotIn("private", str(caught.exception))
            response.read.assert_called_with(web.MAX_BYTES + 1)

    def test_api_redirect_is_refused_instead_of_forwarding_the_key(self):
        request = urllib.request.Request("https://api.firecrawl.dev/v2/search", data=b"{}",
                                         headers={"Authorization": "Bearer " + TEST_KEY})
        with self.assertRaises(web.WebError):
            web._NoAPIRedirect().redirect_request(request, io.BytesIO(), 307, "Redirect", {}, "https://other.example.com")

    def test_auth_failure_uses_basic_reader_then_retries_after_cooldown(self):
        client = MagicMock()
        client.search.side_effect = web.WebError("Firecrawl rejected the API key")
        rss = b'<rss><channel><item><title>Guide</title><link>https://example.com/guide</link></item></channel></rss>'
        fetch = MagicMock(return_value={"url": "https://www.bing.com/search", "body": rss,
                                        "headers": {"content-type": "text/xml"}})
        browser = web.WebTools(fetcher=fetch, firecrawl=client)
        first = browser.search("docs")
        second = browser.search("more docs")
        self.assertEqual(first["provider"], "Bing RSS")
        self.assertIn("rejected", second["provider_notice"])
        self.assertIn("Basic", browser.status)
        client.search.assert_called_once()
        browser.retry_after = 0
        client.search.side_effect = None
        client.search.return_value = {"provider": "Firecrawl", "results": []}
        self.assertEqual(browser.search("docs")["provider"], "Firecrawl")
        self.assertIsNone(browser.provider_notice)
        self.assertIn("Firecrawl", browser.status)

    def test_scrape_failure_falls_back_and_preserves_notice_in_cache(self):
        client = MagicMock()
        client.read.side_effect = web.WebError("Firecrawl connection failed or timed out")
        fetch = MagicMock(return_value={"url": "https://example.com/", "body": b"plain text " * 100,
                                        "headers": {"content-type": "text/plain"}})
        browser = web.WebTools(fetcher=fetch, firecrawl=client)
        first = browser.read("https://example.com", limit=200)
        second = browser.read("https://example.com", offset=200, limit=200)
        self.assertEqual(second["provider"], "Basic reader")
        self.assertEqual(first["provider_notice"], second["provider_notice"])
        fetch.assert_called_once()
        client.read.assert_called_once()

    def test_malformed_search_or_scrape_results_report_failure(self):
        for data in (None, {}, {"web": "not a list"}, {"web": [{"url": "file:///secret"}]}):
            with self.subTest(data=data), self.assertRaises(web.WebError):
                client_with(data)[0].search("docs", 1)
        for data in (None, {}, {"markdown": ""}, {"markdown": "Error", "metadata": {"statusCode": 403}},
                     {"markdown": "Text", "metadata": {"sourceURL": "http://127.0.0.1/"}}):
            with self.subTest(data=data), patch.object(web, "_lookup", return_value=["93.184.216.34"]), self.assertRaises(web.WebError):
                client_with(data)[0].read("https://example.com")


class FirecrawlConfigurationTests(unittest.TestCase):
    def test_setup_saves_in_user_profile_without_echoing_key_and_can_reload(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True), \
             patch.object(web, "firecrawl_key_path", return_value=Path(folder) / "Axis" / "firecrawl.key"), \
             patch.object(web.getpass, "getpass", return_value=TEST_KEY), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(web.configure_firecrawl(), 0)
            self.assertEqual(web.load_firecrawl_key(), TEST_KEY)
            self.assertNotIn(TEST_KEY, output.getvalue())
            browser = web.WebTools()
            self.assertIsInstance(browser.firecrawl, web.FirecrawlClient)
            if os.name != "nt":
                self.assertEqual(web.firecrawl_key_path().stat().st_mode & 0o777, 0o600)

    def test_environment_overrides_file_and_empty_value_disables_firecrawl(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web, "firecrawl_key_path", return_value=Path(folder) / "key"):
            web.firecrawl_key_path().write_text(TEST_KEY, encoding="utf-8")
            with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "fc-another-offline-test-key"}):
                self.assertEqual(web.load_firecrawl_key(), "fc-another-offline-test-key")
            with patch.dict(os.environ, {"FIRECRAWL_API_KEY": ""}):
                self.assertIsNone(web.WebTools().firecrawl)

    def test_invalid_configuration_keeps_basic_browsing_available(self):
        with patch.dict(os.environ, {"FIRECRAWL_API_KEY": "bad-secret-value"}):
            browser = web.WebTools()
            self.assertIsNone(browser.firecrawl)
            self.assertIn("Invalid Firecrawl key", browser.status)
            self.assertNotIn("bad-secret-value", browser.status)

    def test_setup_can_cancel_without_overwriting_existing_key(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web, "firecrawl_key_path", return_value=Path(folder) / "key"), \
             patch.object(web.getpass, "getpass", return_value=""), redirect_stdout(io.StringIO()):
            web.firecrawl_key_path().write_text(TEST_KEY, encoding="utf-8")
            self.assertEqual(web.configure_firecrawl(), 0)
            self.assertEqual(web.firecrawl_key_path().read_text(), TEST_KEY)

    def test_setup_does_not_load_a_model_or_start_a_server(self):
        with patch.object(web, "configure_firecrawl", return_value=0) as setup, \
             patch.object(start, "prepare_model") as prepare, patch.object(start, "start_server") as server:
            self.assertEqual(start.main(["--setup-firecrawl"]), 0)
        setup.assert_called_once()
        prepare.assert_not_called()
        server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
