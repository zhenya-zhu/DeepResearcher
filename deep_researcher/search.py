from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List
import json
import os
import re
import subprocess
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


class DDGRSearcher:
    def __init__(self, proxy_url: str, region: str) -> None:
        self.proxy_url = proxy_url
        self.region = region

    def _env(self) -> Dict[str, str]:
        env = dict(os.environ)
        if self.proxy_url:
            env["http_proxy"] = self.proxy_url
            env["https_proxy"] = self.proxy_url
            env["HTTP_PROXY"] = self.proxy_url
            env["HTTPS_PROXY"] = self.proxy_url
            env["NO_PROXY"] = "localhost,127.0.0.1,::1"
        return env

    def search(self, query: str, limit: int) -> List[SearchHit]:
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
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=self._env(),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("ddgr search failed: {0}".format(completed.stderr.strip() or completed.stdout.strip()))
        payload = completed.stdout.strip()
        if not payload:
            return []
        raw = json.loads(payload)
        if isinstance(raw, dict):
            raw = raw.get("results", [])
        results = []
        for item in raw[:limit]:
            results.append(SearchHit(
                title=item.get("title", "").strip(),
                url=item.get("url", "").strip(),
                snippet=item.get("abstract", item.get("body", "")).strip(),
            ))
        return results


class URLFetcher:
    def __init__(self, proxy_url: str, timeout_seconds: int) -> None:
        self.proxy_url = proxy_url
        self.timeout_seconds = timeout_seconds

    def fetch(self, url: str) -> FetchedPage:
        handlers = []
        if self.proxy_url:
            handlers.append(urllib.request.ProxyHandler({
                "http": self.proxy_url,
                "https": self.proxy_url,
            }))
        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DeepResearcher/0.1",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with opener.open(request, timeout=self.timeout_seconds) as response:
            content_type = response.headers.get("Content-Type", "")
            raw_bytes = response.read(1024 * 1024)
        raw_html = raw_bytes.decode("utf-8", errors="ignore")
        if "text/html" not in content_type and not raw_html.lstrip().startswith("<"):
            text = raw_html.strip()
            return FetchedPage(title=url, raw_html=raw_html, text=text)
        parser = _HTMLTextExtractor()
        parser.feed(raw_html)
        return FetchedPage(title=parser.title or url, raw_html=raw_html, text=parser.to_text())


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
        return FetchedPage(title=title, raw_html="<html><title>{0}</title></html>".format(title), text=text)
