from dataclasses import dataclass
from bs4 import BeautifulSoup
from html.parser import HTMLParser
from contextlib import contextmanager
from typing import Callable, Dict, List, Optional
import base64
import json
import os
import re
import subprocess
import urllib.parse
import urllib.error
import urllib.request


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str


@dataclass
class FetchedPage:
    title: str
    raw_html: str
    text: str
    final_url: str


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: List[str] = []
        self._skip_depth = 0
        self._title: List[str] = []
        self._in_title = False

    @property
    def title(self) -> str:
        return " ".join(self._title).strip()

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self._title.append(text)
        self._chunks.append(text + " ")

    def to_text(self) -> str:
        text = "".join(self._chunks)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n\n", text)
        return text.strip()


@contextmanager
def _without_proxy_env():
    proxy_keys = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy"]
    original = {key: os.environ.get(key) for key in proxy_keys}
    try:
        for key in proxy_keys:
            os.environ.pop(key, None)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def extract_relevant_passages(text: str, query: str, max_passages: int = 3, max_chars: int = 2200) -> str:
    terms = [token.lower() for token in re.findall(r"\w+", query) if len(token) > 2]
    paragraphs = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
    scored = []
    for paragraph in paragraphs:
        lowered = paragraph.lower()
        score = sum(1 for term in terms if term in lowered)
        if score:
            scored.append((score, paragraph))
    if not scored:
        fallback = text[:max_chars]
        return fallback.strip()
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    selected = []
    current_size = 0
    for _, paragraph in scored:
        if len(selected) >= max_passages:
            break
        if current_size + len(paragraph) > max_chars:
            continue
        selected.append(paragraph)
        current_size += len(paragraph)
    return "\n\n".join(selected).strip() or text[:max_chars].strip()


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


class NetworkModeDecider:
    def __init__(self, proxy_url: str, mode: str, timeout_seconds: int) -> None:
        self.proxy_url = proxy_url
        self.mode = mode if mode in {"auto", "proxy", "direct"} else "auto"
        self.timeout_seconds = timeout_seconds
        self._search_mode: Optional[str] = None
        self._fetch_modes: Dict[str, str] = {}

    def search_attempts(self, probe: Callable[[bool], bool]) -> List[bool]:
        forced = self._forced_mode()
        if forced is not None:
            return [forced == "proxy"]
        selected = None
        if selected is None:
            if self._search_mode is None:
                self._search_mode = self._probe_mode(probe)
            selected = self._search_mode
        return self._attempts_for_mode(selected)

    def fetch_attempts(self, url: str, probe: Callable[[str, bool], bool]) -> List[bool]:
        forced = self._forced_mode()
        if forced is not None:
            return [forced == "proxy"]
        selected = None
        if selected is None:
            host = urllib.parse.urlsplit(url).netloc.lower()
            if host not in self._fetch_modes:
                self._fetch_modes[host] = self._probe_mode(lambda use_proxy: probe(url, use_proxy))
            selected = self._fetch_modes[host]
        return self._attempts_for_mode(selected)

    def _probe_mode(self, probe: Callable[[bool], bool]) -> str:
        if not self.proxy_url:
            return "direct"
        for mode in ("direct", "proxy"):
            if probe(mode == "proxy"):
                return mode
        return "direct"

    def _attempts_for_mode(self, mode: str) -> List[bool]:
        if mode == "proxy" and self.proxy_url:
            return [True, False]
        return [False, True] if self.proxy_url else [False]

    def _forced_mode(self) -> Optional[str]:
        if self.mode == "proxy" and self.proxy_url:
            return "proxy"
        if self.mode == "direct" or not self.proxy_url:
            return "direct"
        return None


class DDGRSearcher:
    def __init__(self, proxy_url: str, region: str, network_mode: str = "auto") -> None:
        self.proxy_url = proxy_url
        self.region = region
        self.network_mode = network_mode
        self.decider = NetworkModeDecider(proxy_url=proxy_url, mode=network_mode, timeout_seconds=10)
        self.last_mode = "unknown"

    def _env(self, use_proxy: bool) -> Dict[str, str]:
        env = dict(os.environ)
        if use_proxy and self.proxy_url:
            env["http_proxy"] = self.proxy_url
            env["https_proxy"] = self.proxy_url
            env["HTTP_PROXY"] = self.proxy_url
            env["HTTPS_PROXY"] = self.proxy_url
            env["NO_PROXY"] = "localhost,127.0.0.1,::1"
        else:
            for key in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "no_proxy"]:
                env.pop(key, None)
        return env

    def _run_ddgr(self, query: str, limit: int, use_proxy: bool) -> subprocess.CompletedProcess:
        command = [
            "ddgr",
            "--json",
            "--noprompt",
            "--unsafe",
            "--num",
            str(limit),
            "--reg",
            self.region,
            query,
        ]
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=self._env(use_proxy=use_proxy),
            check=False,
        )

    def _build_opener(self, use_proxy: bool):
        handlers = []
        if use_proxy and self.proxy_url:
            handlers.append(urllib.request.ProxyHandler({
                "http": self.proxy_url,
                "https": self.proxy_url,
            }))
        else:
            handlers.append(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener(*handlers)

    def _fetch_html(self, url: str, use_proxy: bool) -> str:
        opener = self._build_opener(use_proxy=use_proxy)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DeepResearcher/0.1",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if use_proxy:
            with opener.open(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="ignore")
        with _without_proxy_env():
            with opener.open(request, timeout=20) as response:
                return response.read().decode("utf-8", errors="ignore")

    def _search_html_fallback(self, query: str, limit: int, use_proxy: bool) -> List[SearchHit]:
        providers = ["bing", "sogou"]
        errors = []
        for provider in providers:
            try:
                hits = self._search_provider(query, limit, provider, use_proxy=use_proxy)
            except Exception as exc:
                errors.append("{0}: {1}".format(provider, exc))
                continue
            if hits:
                return hits[:limit]
        if errors:
            raise RuntimeError("; ".join(errors))
        return []

    def _search_provider(self, query: str, limit: int, provider: str, use_proxy: bool) -> List[SearchHit]:
        if provider == "bing":
            url = "https://www.bing.com/search?q={0}&mkt=en-US&setlang=en".format(
                urllib.parse.quote(query)
            )
            html = self._fetch_html(url, use_proxy=use_proxy)
            return self._parse_bing_results(html, limit)
        if provider == "sogou":
            url = "https://www.sogou.com/web?query={0}".format(urllib.parse.quote(query))
            html = self._fetch_html(url, use_proxy=use_proxy)
            return self._parse_sogou_results(html, limit)
        raise ValueError("Unsupported provider: {0}".format(provider))

    def _parse_bing_results(self, html: str, limit: int) -> List[SearchHit]:
        soup = BeautifulSoup(html, "html.parser")
        hits = []
        for item in soup.select("li.b_algo"):
            anchor = item.select_one("h2 a") or item.select_one("a")
            if anchor is None:
                continue
            href = (anchor.get("href") or "").strip()
            title = anchor.get_text(" ", strip=True)
            snippet_node = item.select_one("p")
            snippet = snippet_node.get_text(" ", strip=True) if snippet_node else item.get_text(" ", strip=True)
            hit = self._build_search_hit(title, href, snippet, provider="bing")
            if hit is None:
                continue
            hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    def _parse_sogou_results(self, html: str, limit: int) -> List[SearchHit]:
        soup = BeautifulSoup(html, "html.parser")
        hits = []
        for item in soup.select("div.results > div.reactResult, div.results > div.vrwrap"):
            hit = self._extract_sogou_hit(item)
            if hit is None:
                continue
            hits.append(hit)
            if len(hits) >= limit:
                break
        return hits

    def _extract_sogou_hit(self, node) -> Optional[SearchHit]:
        best_anchor = None
        best_score = -1
        for anchor in node.select("a[href]"):
            href = (anchor.get("href") or "").strip()
            title = anchor.get_text(" ", strip=True)
            score = self._score_sogou_anchor(title, href)
            if score > best_score:
                best_anchor = anchor
                best_score = score
        if best_anchor is None or best_score < 1:
            return None
        href = urllib.parse.urljoin("https://www.sogou.com", (best_anchor.get("href") or "").strip())
        title = best_anchor.get_text(" ", strip=True)
        snippet = node.get_text(" ", strip=True)
        return self._build_search_hit(title, href, snippet, provider="sogou")

    def _score_sogou_anchor(self, title: str, href: str) -> int:
        if not href or href.startswith("javascript:") or href == "#":
            return -1
        score = len(title)
        bad_fragments = [
            "yuanbao.tencent.com",
            "ima.qq.com",
            "pic.sogou.com",
            "weixin.sogou.com",
            "fanyi.sogou.com",
        ]
        bad_titles = ["详情", "去试试", "看看", "搜狗图片", "推荐您搜索"]
        if any(fragment in href for fragment in bad_fragments):
            score -= 10
        if any(marker in title for marker in bad_titles):
            score -= 8
        if href.startswith("/link?"):
            score += 4
        if _contains_cjk(title):
            score += 2
        return score

    def _build_search_hit(self, title: str, href: str, snippet: str, provider: str) -> Optional[SearchHit]:
        title = re.sub(r"\s+", " ", title).strip()
        href = href.strip()
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if not title or not href:
            return None
        if provider == "bing" and href.startswith("https://www.bing.com/ck/a?"):
            href = self._decode_bing_redirect(href) or ""
            if not href:
                return None
        return SearchHit(title=title, url=href, snippet=snippet[:400])

    def _decode_bing_redirect(self, href: str) -> Optional[str]:
        parsed = urllib.parse.urlsplit(href)
        query = urllib.parse.parse_qs(parsed.query)
        candidates = query.get("u", [])
        for value in candidates:
            target = value.strip()
            if not target:
                continue
            if target.startswith(("http://", "https://")):
                return target
            if len(target) > 2 and target[:2] in {"a1", "u1"}:
                target = target[2:]
            padding = "=" * (-len(target) % 4)
            for decoder in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    decoded = decoder(target + padding).decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue
                if decoded.startswith(("http://", "https://")):
                    return decoded
        return None

    def _probe(self, use_proxy: bool) -> bool:
        completed = self._run_ddgr("openai", 1, use_proxy=use_proxy)
        payload = completed.stdout.strip()
        if completed.returncode != 0 or not payload:
            return False
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError:
            return False
        if isinstance(raw, dict):
            raw = raw.get("results", [])
        return isinstance(raw, list)

    def search(self, query: str, limit: int) -> List[SearchHit]:
        attempts = self.decider.search_attempts(self._probe)
        last_error = ""
        raw = []
        for use_proxy in attempts:
            completed = self._run_ddgr(query, limit, use_proxy=use_proxy)
            self.last_mode = "proxy" if use_proxy else "direct"
            payload = completed.stdout.strip()
            stderr = completed.stderr.strip()
            if completed.returncode != 0:
                last_error = stderr or payload or "ddgr returned non-zero exit status"
                continue
            if not payload:
                last_error = stderr or "ddgr returned empty output"
                continue
            try:
                raw = json.loads(payload)
            except json.JSONDecodeError as exc:
                last_error = "ddgr returned invalid JSON: {0}".format(exc)
                continue
            if isinstance(raw, dict):
                raw = raw.get("results", [])
            if raw:
                break
        results = []
        for item in raw[:limit]:
            hit = self._build_search_hit(
                item.get("title", "").strip(),
                item.get("url", "").strip(),
                item.get("abstract", item.get("body", "")).strip(),
                provider="ddgr",
            )
            if hit is not None:
                results.append(hit)
        if results:
            return results
        html_errors = []
        for use_proxy in attempts:
            self.last_mode = "proxy" if use_proxy else "direct"
            try:
                html_results = self._search_html_fallback(query, limit, use_proxy=use_proxy)
            except Exception as exc:
                html_errors.append(str(exc))
                continue
            if html_results:
                return html_results
        if last_error and html_errors:
            raise RuntimeError("ddgr search failed: {0}; html fallback failed: {1}".format(last_error, "; ".join(html_errors)))
        if last_error:
            raise RuntimeError("ddgr search failed: {0}".format(last_error))
        return []


class URLFetcher:
    def __init__(self, proxy_url: str, timeout_seconds: int, network_mode: str = "auto") -> None:
        self.proxy_url = proxy_url
        self.timeout_seconds = timeout_seconds
        self.network_mode = network_mode
        self.decider = NetworkModeDecider(proxy_url=proxy_url, mode=network_mode, timeout_seconds=timeout_seconds)
        self.last_mode = "unknown"

    def _build_opener(self, use_proxy: bool):
        handlers = []
        if use_proxy and self.proxy_url:
            handlers.append(urllib.request.ProxyHandler({
                "http": self.proxy_url,
                "https": self.proxy_url,
            }))
        else:
            handlers.append(urllib.request.ProxyHandler({}))
        return urllib.request.build_opener(*handlers)

    def _open(self, opener, request, timeout: int, use_proxy: bool):
        if use_proxy:
            return opener.open(request, timeout=timeout)
        with _without_proxy_env():
            return opener.open(request, timeout=timeout)

    def _probe(self, url: str, use_proxy: bool) -> bool:
        opener = self._build_opener(use_proxy=use_proxy)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DeepResearcher/0.1",
                "Accept": "text/html,application/xhtml+xml,*/*",
            },
            method="HEAD",
        )
        timeout = max(5, min(self.timeout_seconds, 12))
        try:
            with self._open(opener, request, timeout=timeout, use_proxy=use_proxy):
                return True
        except urllib.error.HTTPError as exc:
            return exc.code in {200, 204, 301, 302, 303, 307, 308, 401, 403, 405}
        except Exception:
            return False

    def _extract_html_redirect(self, raw_html: str, base_url: str) -> Optional[str]:
        patterns = [
            r"""window\.location(?:\.replace)?\(\s*['"]([^'"]+)['"]\s*\)""",
            r"""window\.location\.href\s*=\s*['"]([^'"]+)['"]""",
            r"""location\.href\s*=\s*['"]([^'"]+)['"]""",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw_html, flags=re.IGNORECASE)
            if match:
                target = urllib.parse.urljoin(base_url, match.group(1).strip())
                if target and target != base_url:
                    return target
        meta_match = re.search(
            r"""<meta[^>]+http-equiv=["']refresh["'][^>]+content=["'][^"']*url=([^"'>]+)""",
            raw_html,
            flags=re.IGNORECASE,
        )
        if meta_match:
            target = urllib.parse.urljoin(base_url, meta_match.group(1).strip(" '\""))
            if target and target != base_url:
                return target
        return None

    def fetch(self, url: str, _visited: Optional[set] = None) -> FetchedPage:
        visited = set(_visited or set())
        if url in visited:
            raise RuntimeError("redirect loop detected for {0}".format(url))
        visited.add(url)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DeepResearcher/0.1",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        last_error = None
        attempts = self.decider.fetch_attempts(url, self._probe)
        for use_proxy in attempts:
            opener = self._build_opener(use_proxy=use_proxy)
            try:
                with self._open(opener, request, timeout=self.timeout_seconds, use_proxy=use_proxy) as response:
                    content_type = response.headers.get("Content-Type", "")
                    raw_bytes = response.read(1024 * 1024)
                    response_url = response.geturl()
                self.last_mode = "proxy" if use_proxy else "direct"
                break
            except Exception as exc:
                last_error = exc
        else:
            raise last_error or RuntimeError("fetch failed")
        raw_html = raw_bytes.decode("utf-8", errors="ignore")
        redirect_target = self._extract_html_redirect(raw_html, response_url)
        if redirect_target:
            return self.fetch(redirect_target, _visited=visited)
        if "text/html" not in content_type and not raw_html.lstrip().startswith("<"):
            text = raw_html.strip()
            return FetchedPage(title=response_url, raw_html=raw_html, text=text, final_url=response_url)
        parser = _HTMLTextExtractor()
        parser.feed(raw_html)
        return FetchedPage(title=parser.title or response_url, raw_html=raw_html, text=parser.to_text(), final_url=response_url)


class MockSearcher:
    def search(self, query: str, limit: int) -> List[SearchHit]:
        hits = []
        for index in range(limit):
            hits.append(SearchHit(
                title="Mock result {0} for {1}".format(index + 1, query),
                url="https://example.com/{0}/{1}".format(re.sub(r"[^a-z0-9]+", "-", query.lower()), index + 1),
                snippet="Mock evidence about {0}. This is placeholder source {1}.".format(query, index + 1),
            ))
        return hits


class MockFetcher:
    def fetch(self, url: str) -> FetchedPage:
        title = url.rsplit("/", 1)[-1] or "mock-source"
        text = (
            "This is a mock page for {0}. It includes background, market signals, "
            "risks, implementation details, and recommended next steps."
        ).format(url)
        return FetchedPage(title=title, raw_html="<html><title>{0}</title></html>".format(title), text=text, final_url=url)
