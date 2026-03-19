from unittest.mock import patch
import subprocess
import unittest

from deep_researcher.search import DDGRSearcher, NetworkModeDecider, URLFetcher


class NetworkModeDeciderTest(unittest.TestCase):
    def test_auto_prefers_direct_when_probe_succeeds(self) -> None:
        decider = NetworkModeDecider(proxy_url="http://proxy.example:8080", mode="auto", timeout_seconds=10)

        attempts = decider.search_attempts(lambda use_proxy: not use_proxy)

        self.assertEqual(attempts, [False, True])

    def test_auto_caches_fetch_mode_by_host(self) -> None:
        decider = NetworkModeDecider(proxy_url="http://proxy.example:8080", mode="auto", timeout_seconds=10)
        calls = []

        def probe(url: str, use_proxy: bool) -> bool:
            calls.append((url, use_proxy))
            return use_proxy

        first_attempts = decider.fetch_attempts("https://example.com/a", probe)
        second_attempts = decider.fetch_attempts("https://example.com/b", probe)

        self.assertEqual(first_attempts, [True, False])
        self.assertEqual(second_attempts, [True, False])
        self.assertEqual(calls, [
            ("https://example.com/a", False),
            ("https://example.com/a", True),
        ])


class SearcherTest(unittest.TestCase):
    def test_ddgr_auto_probes_direct_first(self) -> None:
        calls = []

        def fake_run(command, capture_output, text, env, check):
            query = command[-1]
            calls.append((query, env.copy()))
            if query == "openai":
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout='[{"title":"probe","url":"https://example.com","abstract":"probe"}]',
                    stderr="",
                )
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout='[{"title":"ok","url":"https://example.com","abstract":"snippet"}]',
                stderr="",
            )

        with patch("deep_researcher.search.subprocess.run", side_effect=fake_run):
            searcher = DDGRSearcher(proxy_url="http://proxy.example:8080", region="us-en", network_mode="auto")
            results = searcher.search("test query", 3)

        self.assertEqual(len(results), 1)
        self.assertEqual(searcher.last_mode, "direct")
        self.assertNotIn("http_proxy", calls[0][1])
        self.assertNotIn("http_proxy", calls[1][1])

    def test_ddgr_retries_without_proxy_when_proxy_returns_empty(self) -> None:
        calls = []

        def fake_run(command, capture_output, text, env, check):
            calls.append(env.copy())
            if len(calls) == 1:
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="[]",
                    stderr="[ERROR] <urlopen error Tunnel connection failed: 503 Service Unavailable>",
                )
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout='[{"title":"ok","url":"https://example.com","abstract":"snippet"}]',
                stderr="",
            )

        with patch("deep_researcher.search.subprocess.run", side_effect=fake_run):
            searcher = DDGRSearcher(proxy_url="http://proxy.example:8080", region="us-en", network_mode="auto")
            searcher.decider._search_mode = "proxy"
            results = searcher.search("test query", 3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "ok")
        self.assertEqual(calls[0].get("http_proxy"), "http://proxy.example:8080")
        self.assertNotIn("http_proxy", calls[1])
        self.assertEqual(searcher.last_mode, "direct")

    def test_ddgr_forced_direct_skips_proxy(self) -> None:
        calls = []

        def fake_run(command, capture_output, text, env, check):
            calls.append(env.copy())
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout='[{"title":"ok","url":"https://example.com","abstract":"snippet"}]',
                stderr="",
            )

        with patch("deep_researcher.search.subprocess.run", side_effect=fake_run):
            searcher = DDGRSearcher(proxy_url="http://proxy.example:8080", region="us-en", network_mode="direct")
            results = searcher.search("test query", 3)

        self.assertEqual(len(results), 1)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("http_proxy", calls[0])

    def test_ddgr_records_last_mode_on_zero_results(self) -> None:
        def fake_run(command, capture_output, text, env, check):
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="[]",
                stderr="",
            )

        with patch("deep_researcher.search.subprocess.run", side_effect=fake_run):
            searcher = DDGRSearcher(proxy_url="http://proxy.example:8080", region="us-en", network_mode="direct")
            with patch.object(searcher, "_search_html_fallback", return_value=[]):
                results = searcher.search("test query", 3)

        self.assertEqual(results, [])
        self.assertEqual(searcher.last_mode, "direct")

    def test_ddgr_falls_back_to_html_search(self) -> None:
        def fake_run(command, capture_output, text, env, check):
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout="[]",
                stderr="ddgr empty",
            )

        with patch("deep_researcher.search.subprocess.run", side_effect=fake_run):
            searcher = DDGRSearcher(proxy_url="", region="us-en", network_mode="direct")
            with patch.object(
                searcher,
                "_search_html_fallback",
                return_value=[searcher._build_search_hit("阳光电源官网", "https://example.com", "snippet", provider="sogou")],
            ):
                results = searcher.search("阳光电源", 3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "阳光电源官网")

    def test_html_fallback_prefers_bing_before_sogou(self) -> None:
        searcher = DDGRSearcher(proxy_url="", region="us-en", network_mode="direct")
        calls = []

        def fake_provider(query, limit, provider, use_proxy):
            calls.append(provider)
            if provider == "bing":
                return [searcher._build_search_hit("bing hit", "https://example.com", "snippet", provider="bing")]
            return [searcher._build_search_hit("sogou hit", "https://www.sogou.com/link?url=good", "snippet", provider="sogou")]

        with patch.object(searcher, "_search_provider", side_effect=fake_provider):
            results = searcher._search_html_fallback("阳光电源", 3, use_proxy=False)

        self.assertEqual(calls, ["bing"])
        self.assertEqual(results[0].title, "bing hit")

    def test_parse_sogou_results_skips_low_quality_links(self) -> None:
        html = """
<html><body>
  <div class="results">
    <div class="reactResult">
      <a href="https://pic.sogou.com/pics">阳光电源 - 搜狗图片</a>
      <a href="https://yuanbao.tencent.com/test">阳光电源 - 看看元宝怎么说</a>
      <a href="/link?url=good">阳光电源股份有限公司官网</a>
      <p>公司官网与业务介绍</p>
    </div>
  </div>
</body></html>
"""
        searcher = DDGRSearcher(proxy_url="", region="us-en", network_mode="direct")

        results = searcher._parse_sogou_results(html, 3)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "阳光电源股份有限公司官网")
        self.assertTrue(results[0].url.startswith("https://www.sogou.com/link?url=good"))

    def test_build_search_hit_decodes_bing_redirect_url(self) -> None:
        searcher = DDGRSearcher(proxy_url="", region="us-en", network_mode="direct")

        hit = searcher._build_search_hit(
            "OpenAI - Reddit",
            "https://www.bing.com/ck/a?!&&p=f9250abdccee82cb2714b20b694fcd36fc7cc31e7d01d391c6172a9fede4d4bcJmltdHM9MTc3MzEwMDgwMA&ptn=3&ver=2&hsh=4&fclid=1a8fd16c-03c5-61b4-2487-c675021460b8&u=a1aHR0cHM6Ly93d3cucmVkZGl0LmNvbS9yL09wZW5BSS8&ntb=1",
            "snippet",
            provider="bing",
        )

        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.url, "https://www.reddit.com/r/OpenAI/")

    def test_build_search_hit_keeps_ddgr_direct_url(self) -> None:
        searcher = DDGRSearcher(proxy_url="", region="us-en", network_mode="direct")

        hit = searcher._build_search_hit(
            "Official site",
            "https://openai.com/",
            "snippet",
            provider="ddgr",
        )

        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.url, "https://openai.com/")

    def test_fetcher_retries_without_proxy(self) -> None:
        class _Response:
            def __init__(self, body: bytes) -> None:
                self._body = body
                self.headers = {"Content-Type": "text/html; charset=utf-8"}

            def read(self, size=-1):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def geturl(self):
                return "https://example.com"

        class _Opener:
            def __init__(self, should_fail: bool) -> None:
                self.should_fail = should_fail

            def open(self, request, timeout):
                if request.get_method() == "HEAD":
                    return _Response(b"")
                if self.should_fail:
                    raise RuntimeError("proxy failed")
                return _Response(b"<html><title>ok</title><body>Hello</body></html>")

        openers = [_Opener(True), _Opener(False)]

        def fake_build_opener(*handlers):
            return openers.pop(0)

        with patch("deep_researcher.search.urllib.request.build_opener", side_effect=fake_build_opener):
            fetcher = URLFetcher(proxy_url="http://proxy.example:8080", timeout_seconds=10, network_mode="auto")
            fetcher.decider._fetch_modes["example.com"] = "proxy"
            page = fetcher.fetch("https://example.com")

        self.assertEqual(page.title, "ok")
        self.assertIn("Hello", page.text)
        self.assertEqual(fetcher.last_mode, "direct")

    def test_fetcher_auto_uses_cached_direct_mode(self) -> None:
        build_calls = []

        class _Response:
            def __init__(self, body: bytes) -> None:
                self._body = body
                self.headers = {"Content-Type": "text/html; charset=utf-8"}

            def read(self, size=-1):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def geturl(self):
                return "https://example.com/test"

        class _Opener:
            def __init__(self, should_fail: bool) -> None:
                self.should_fail = should_fail

            def open(self, request, timeout):
                build_calls.append(request.get_method())
                if request.get_method() == "HEAD":
                    if self.should_fail:
                        raise RuntimeError("proxy probe failed")
                    return _Response(b"")
                if self.should_fail:
                    raise RuntimeError("proxy fetch failed")
                return _Response(b"<html><title>ok</title><body>Hello</body></html>")

        openers = [_Opener(False), _Opener(False), _Opener(False)]

        def fake_build_opener(*handlers):
            return openers.pop(0)

        with patch("deep_researcher.search.urllib.request.build_opener", side_effect=fake_build_opener):
            fetcher = URLFetcher(proxy_url="http://proxy.example:8080", timeout_seconds=10, network_mode="auto")
            page = fetcher.fetch("https://example.com/test")

        self.assertEqual(page.title, "ok")
        self.assertEqual(fetcher.last_mode, "direct")
        self.assertEqual(build_calls, ["HEAD", "GET"])

    def test_fetcher_follows_html_redirect_stub(self) -> None:
        class _Response:
            def __init__(self, body: bytes, url: str) -> None:
                self._body = body
                self._url = url
                self.headers = {"Content-Type": "text/html; charset=utf-8"}

            def read(self, size=-1):
                return self._body

            def geturl(self):
                return self._url

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class _Opener:
            def __init__(self) -> None:
                self.calls = []

            def open(self, request, timeout):
                url = request.full_url
                self.calls.append((request.get_method(), url))
                if "www.sogou.com/link?url=stub" in url:
                    return _Response(
                        b'<meta content="always" name="referrer"><script>window.location.replace("https://target.example.com/article")</script>',
                        url,
                    )
                return _Response(
                    b"<html><title>Target Title</title><body>Target body text</body></html>",
                    "https://target.example.com/article",
                )

        opener = _Opener()

        with patch("deep_researcher.search.urllib.request.build_opener", return_value=opener):
            fetcher = URLFetcher(proxy_url="", timeout_seconds=10, network_mode="direct")
            page = fetcher.fetch("https://www.sogou.com/link?url=stub")

        self.assertEqual(page.final_url, "https://target.example.com/article")
        self.assertEqual(page.title, "Target Title")
        self.assertIn("Target body text", page.text)
        self.assertEqual(
            opener.calls,
            [
                ("GET", "https://www.sogou.com/link?url=stub"),
                ("GET", "https://target.example.com/article"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
