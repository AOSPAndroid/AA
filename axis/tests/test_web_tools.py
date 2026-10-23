"""Public browsing boundaries, extraction and pagination; no live network."""
import io
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import web_tools as web


def page(body, url="https://example.com/", content_type="text/html; charset=utf-8"):
    return {"url": url, "body": body.encode("utf-8"), "headers": {"content-type": content_type}}


class ParsingTests(unittest.TestCase):
    def test_extracts_visible_text_title_links_and_ignores_hidden_void(self):
        content = '''<title>Useful &amp; current</title><nav>noise</nav><script>evil()</script>
        <input hidden><img aria-hidden="true"><main><h1>Guide</h1>
        <p>Read <a href="/help?a=1&amp;b=2"><b>the help</b></a>.</p>
        <div hidden>secret <b>noise</b></div><p>Visible end</p>
        <a href="javascript:evil()">bad link</a><a href="http://127.0.0.1/">local</a></main>'''
        browser = web.WebTools(fetcher=lambda _: page(content))
        result = json.loads(browser.call("web_read", {"url": "https://example.com"}))
        self.assertEqual(result["title"], "Useful & current")
        self.assertIn("Visible end", result["text"])
        self.assertNotIn("secret", result["text"])
        self.assertNotIn("evil()", result["text"])
        self.assertNotIn("noise", result["text"])
        self.assertEqual(result["links"], [{"id": 1, "text": "the help", "url": "https://example.com/help?a=1&b=2"}])
        self.assertTrue(result["untrusted_content"])

    def test_cached_text_and_links_paginate_without_refetch_including_redirect_alias(self):
        html = "<p>" + "x" * 900 + "</p>" + "".join('<a href="/p%d">P%d</a>' % (i, i) for i in range(13))
        fetch = MagicMock(return_value=page(html, "https://example.com/final"))
        browser = web.WebTools(fetcher=fetch)
        first = browser.read("https://example.com/start", limit=200)
        second = browser.read(first["url"], offset=first["next_offset"], limit=200, link_offset=8)
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(second["offset"], 200)
        self.assertEqual(first["total_links"], 13)
        self.assertEqual(len(first["links"]), 8)
        self.assertEqual(second["links"][0]["id"], 9)
        self.assertIsNone(second["next_link_offset"])
        self.assertIn("fetched_at", second)

    def test_invalid_arguments_and_unsupported_types_are_clear(self):
        browser = web.WebTools(fetcher=lambda _: page("%PDF", content_type="application/pdf"))
        for arguments in ({"url": "https://example.com", "limit": True},
                          {"url": "https://example.com", "offset": -1},
                          {"url": "https://example.com", "extra": 1},
                          {"url": "https://example.com", "offset": 200}, {}):
            self.assertIn("error", json.loads(browser.call("web_read", arguments)))
        self.assertIn("no PDFs", json.loads(browser.call("web_read", {"url": "https://example.com"}))["error"])
        self.assertIn("error", json.loads(browser.call("unknown", {})))

    def test_plain_text_cache_expires_and_is_bounded(self):
        fetch = MagicMock(side_effect=lambda url: page("Text", url, "text/plain"))
        browser = web.WebTools(fetcher=fetch)
        for i in range(web.CACHE_PAGES + 2):
            browser.read("https://example.com/%d" % i)
        self.assertEqual(len(browser.cache), web.CACHE_PAGES)
        key = next(iter(browser.cache))
        browser.cache[key]["stored_at"] -= web.CACHE_SECONDS + 1
        with self.assertRaises(web.WebError):
            browser.read(key, offset=1)
        self.assertLessEqual(len(browser.aliases), web.CACHE_PAGES)


class SearchTests(unittest.TestCase):
    def test_rss_search_encodes_query_deduplicates_and_retains_sources(self):
        rss = '''<rss><channel><item><title>A &amp; B</title><link>https://example.com/help</link>
        <description>Useful &lt;b&gt;answer&lt;/b&gt;</description></item>
        <item><title>duplicate</title><link>https://example.com/help</link></item>
        <item><title>bad</title><link>file:///secret</link></item></channel></rss>'''
        fetch = MagicMock(return_value=page(rss, "https://www.bing.com/search", "text/xml"))
        result = web.WebTools(fetcher=fetch).search("A & B?", max_results=3)
        self.assertIn("q=A+%26+B%3F", fetch.call_args[0][0])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["snippet"], "Useful answer")
        self.assertEqual(result["provider"], "Bing RSS")
        self.assertTrue(result["untrusted_content"])

    def test_search_falls_back_decodes_ddg_links_and_reports_challenges(self):
        html = '''<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fhelp">Guide <b>here</b></a>
        <div class="result__snippet">An <b>actual</b> snippet.</div>'''
        def fetch(url, **kwargs):
            return page("<html>blocked</html>" if "bing.com" in url else html, url)
        result = web.WebTools(fetcher=fetch).search("help")
        self.assertEqual(result["provider"], "DuckDuckGo HTML")
        self.assertEqual(result["results"][0]["url"], "https://example.com/help")
        self.assertEqual(result["results"][0]["snippet"], "An actual snippet.")
        browser = web.WebTools(fetcher=lambda url, **kwargs: page("<html>captcha</html>", url))
        failure = json.loads(browser.call("web_search", {"query": "help"}))
        self.assertIn("unavailable", failure["error"])
        self.assertIn("web_read", failure["error"])


class Response:
    def __init__(self, status=200, body=b"Hello", headers=None):
        self.status = status
        self.headers = headers or {"content-type": "text/plain", "content-length": str(len(body))}
        self.stream = io.BytesIO(body)
        self.length = len(body)

    def close(self):
        self.stream.close()

    def getheaders(self):
        return list(self.headers.items())

    def read1(self, count):
        data = self.stream.read(count)
        self.length -= len(data)
        return data


class Connection:
    instances = []
    responses = []

    def __init__(self, target, address, deadline, proxy):
        self.target, self.address = target, address
        self.sock = MagicMock()
        self.transport = self.sock
        self.closed = False
        self.instances.append(self)

    def request(self, method, path, headers):
        self.requested = (method, path, headers)

    def getresponse(self):
        self.sock = None  # HTTPConnection does this for Connection:close.
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class NetworkTests(unittest.TestCase):
    def setUp(self):
        Connection.instances = []
        Connection.responses = []

    def test_rejects_private_special_credentials_controls_and_malformed_urls(self):
        invalid = ["file:///etc/passwd", "http://localhost/", "http://127.0.0.1/", "http://169.254.169.254/",
                   "http://[::1]/", "http://[fe80::1%25eth0]/", "https://user:password@example.com/",
                   "http://example.com:0/", "http://example.com:99999/", "http://example.com/\nnext", "http://example.com\\@localhost/"]
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(web.WebError):
                web._url(url)
        for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "ff02::1", "::ffff:127.0.0.1"):
            self.assertFalse(web._public(address))

    def test_dns_mixed_public_private_answers_rejected(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ("93.184.216.34", "10.0.0.1")]
        with patch("web_tools.socket.getaddrinfo", return_value=answers), self.assertRaises(web.WebError):
            web._lookup("example.com", 443, time.monotonic() + 5)

    def test_redirect_revalidates_target_and_pins_public_dns_once_per_hop(self):
        redirect, final = Response(302, headers={"location": "/final"}), Response()
        Connection.responses = [redirect, final]
        with patch("web_tools._lookup", return_value=["93.184.216.34"]) as lookup, patch("web_tools._proxy", return_value=None), patch("web_tools._Connection", Connection):
            result = web.fetch_url("https://example.com/start")
        self.assertEqual(result["url"], "https://example.com/final")
        self.assertEqual(lookup.call_count, 2)
        self.assertTrue(redirect.stream.closed)
        self.assertTrue(final.stream.closed)
        self.assertTrue(all(c.address == "93.184.216.34" and c.closed for c in Connection.instances))
        self.assertGreaterEqual(Connection.instances[-1].transport.settimeout.call_count, 2)
        Connection.responses = [Response(302, headers={"location": "http://127.0.0.1/secret"})]
        with patch("web_tools._lookup", return_value=["93.184.216.34"]), patch("web_tools._proxy", return_value=None), patch("web_tools._Connection", Connection), self.assertRaises(web.WebError):
            web.fetch_url("https://example.com/start")

    def test_size_limits_and_incomplete_responses_are_rejected(self):
        for response in (Response(headers={"content-length": str(web.MAX_BYTES + 1)}), Response(body=b"abcdef", headers={"content-type": "text/plain"})):
            Connection.responses = [response]
            with patch("web_tools._lookup", return_value=["93.184.216.34"]), patch("web_tools._proxy", return_value=None), patch("web_tools._Connection", Connection), patch("web_tools.MAX_BYTES", 5), self.assertRaises(web.WebError):
                web.fetch_url("https://example.com/")
            self.assertTrue(response.stream.closed)
        response = Response()
        response.length = 20
        Connection.responses = [response]
        with patch("web_tools._lookup", return_value=["93.184.216.34"]), patch("web_tools._proxy", return_value=None), patch("web_tools._Connection", Connection), self.assertRaises(web.WebError):
            web.fetch_url("https://example.com/")

    def test_exact_content_length_closes_actual_httpresponse_without_reusing_socket(self):
        class BodyFile(io.BytesIO):
            def close(self):
                transport.closed = True
                super().close()
        class Transport:
            closed = False
            def makefile(self, *args):
                return BodyFile(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\nContent-Type: text/plain\r\n\r\nHello")
            def settimeout(self, value):
                if self.closed:
                    raise OSError("closed socket")
            def shutdown(self, how):
                pass
        transport = Transport()
        class RealResponseConnection(Connection):
            def __init__(self, *args):
                super().__init__(*args)
                self.sock = self.transport = transport
            def getresponse(self):
                response = web.http.client.HTTPResponse(self.transport)
                response.begin()
                self.sock = None
                return response
        with patch("web_tools._lookup", return_value=["93.184.216.34"]), patch("web_tools._proxy", return_value=None), patch("web_tools._Connection", RealResponseConnection):
            result = web.fetch_url("https://example.com/")
        self.assertEqual(result["body"], b"Hello")
        self.assertTrue(transport.closed)

    def test_deadline_is_enforced_when_http_client_has_cleared_connection_socket(self):
        response = Response()
        response.read1 = MagicMock(return_value=b"unexpected")
        Connection.responses = [response]
        with patch("web_tools._lookup", return_value=["93.184.216.34"]), patch("web_tools._proxy", return_value=None), patch("web_tools._Connection", Connection), patch("web_tools.threading.Timer") as timer, patch("web_tools.time.monotonic", side_effect=[50, 50, 101]), self.assertRaises(web.WebError):
            web.fetch_url("https://example.com/", deadline=100)
        response.read1.assert_not_called()
        timer.return_value.cancel.assert_called_once()
        self.assertTrue(Connection.instances[0].closed)

    def test_dns_wait_is_bounded_even_if_platform_resolver_stalls(self):
        release = threading.Event()
        def resolver(*args, **kwargs):
            release.wait(1)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        try:
            with patch("web_tools.socket.getaddrinfo", side_effect=resolver), self.assertRaises(web.WebError):
                web._lookup("example.com", 443, time.monotonic() + 0.01)
        finally:
            release.set()

    def test_direct_tls_and_proxy_tunnel_preserve_hostname_without_auth_leak(self):
        target = web._url("https://example.com:8443/path")
        proxy = {"address": "10.1.1.2", "port": 8080, "authorization": "Basic secret"}
        sock = MagicMock()
        context = MagicMock()
        with patch("web_tools._socket", return_value=sock) as connect, patch("web_tools.ssl.create_default_context", return_value=context), patch.object(web._Connection, "_tunnel") as tunnel:
            connection = web._Connection(target, "93.184.216.34", time.monotonic() + 5, proxy)
            connection.connect()
            self.assertEqual(connect.call_args[0][:2], ("10.1.1.2", 8080))
            self.assertEqual(connection._tunnel_host, "93.184.216.34")
            self.assertEqual(connection._tunnel_headers["Host"], "example.com:8443")
            self.assertEqual(connection._tunnel_headers["Proxy-Authorization"], "Basic secret")
            self.assertEqual(context.wrap_socket.call_args[1]["server_hostname"], "example.com")
            tunnel.assert_called_once()

    def test_ipv6_proxy_connect_uses_bracketed_pinned_address(self):
        target = web._url("https://example.com/")
        proxy = {"address": "10.1.1.2", "port": 8080, "authorization": None}
        sock = MagicMock()
        sock.makefile.return_value = io.BytesIO(b"HTTP/1.1 200 Connection established\r\n\r\n")
        connection = web._Connection(target, "2606:4700:4700::1111", time.monotonic() + 5, proxy)
        connection.sock = sock
        connection._tunnel()
        sent = b"".join(call[0][0] for call in sock.sendall.call_args_list)
        self.assertIn(b"CONNECT [2606:4700:4700::1111]:443 HTTP/", sent)
        self.assertEqual(connection._tunnel_host, "2606:4700:4700::1111")

    def test_http_proxy_absolute_target_is_pinned_but_host_is_original(self):
        proxy = {"address": "10.1.1.2", "port": 8080, "authorization": "Basic token"}
        Connection.responses = [Response()]
        with patch("web_tools._lookup", return_value=["93.184.216.34"]), patch("web_tools._proxy", return_value=proxy), patch("web_tools._Connection", Connection):
            web.fetch_url("http://example.com/path")
        _, path, headers = Connection.instances[0].requested
        self.assertEqual(path, "http://93.184.216.34/path")
        self.assertEqual(headers["Host"], "example.com")
        self.assertEqual(headers["Proxy-Authorization"], "Basic token")
        Connection.responses = [Response()]
        with patch("web_tools._lookup", return_value=["93.184.216.34"]), patch("web_tools._proxy", return_value=proxy), patch("web_tools._Connection", Connection):
            web.fetch_url("https://example.com/path")
        self.assertNotIn("Proxy-Authorization", Connection.instances[-1].requested[2])

    def test_configured_unsupported_proxy_is_not_silently_bypassed(self):
        with patch("web_tools.urllib.request.getproxies", return_value={"https": "socks5://proxy.example:1080"}), patch("web_tools.urllib.request.proxy_bypass", return_value=False), self.assertRaises(web.WebError):
            web._proxy(web._url("https://example.com"), time.monotonic() + 5)


if __name__ == "__main__":
    unittest.main()
