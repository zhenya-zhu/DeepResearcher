from pathlib import Path
from typing import Dict, List, Optional
import datetime as dt
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import urlparse, urlsplit

from .config import AppConfig, ModelSelection
from .llm import AnthropicCompatibleBackend, MockBackend, ModelRouter, MultiProviderBackend, OpenAICompatibleBackend
from .model_capabilities import load_model_capability_registry
from .prompts import (
    build_audit_messages,
    build_cross_section_synthesis_messages,
    build_gap_review_messages,
    build_planning_messages,
    build_report_overview_messages,
    build_section_report_messages,
    build_section_research_messages,
)
from .rate_limit import IntervalRateLimiter
from .search import (
    DDGRSearcher,
    MockFetcher,
    MockSearcher,
    URLFetcher,
    extract_relevant_passages,
)
from .semantic_registry import load_semantic_registry
from .sonar_adapter import adapt_sonar_response, is_sonar_model
from .state import AuditIssue, EvidenceRequirement, Finding, GapTask, ReasoningStep, ResearchState, SearchResultRecord, SectionState, SourceRecord
from .tracing import RunArtifacts
from .workspace_sources import WorkspaceDocument, discover_workspace_documents, select_workspace_evidence


def _run_id() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")


def _extract_outbound_links(raw_html: str, base_url: str, max_links: int = 10) -> List[str]:
    """Extract outbound HTTP(S) links from raw HTML, deduplicating and filtering."""
    try:
        from html.parser import HTMLParser

        class _LinkExtractor(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.links: List[str] = []

            def handle_starttag(self, tag: str, attrs: List) -> None:
                if tag == "a":
                    for name, value in attrs:
                        if name == "href" and value and value.startswith("http"):
                            self.links.append(value)

        parser = _LinkExtractor()
        parser.feed(raw_html[:200000])  # limit parsing to first 200K chars
        parsed_base = urlparse(base_url)
        seen = set()
        result = []
        for link in parser.links:
            parsed = urlparse(link)
            # Skip same-domain links, fragments, and common non-content URLs
            if parsed.netloc == parsed_base.netloc:
                continue
            if any(skip in link.lower() for skip in [
                "javascript:", "mailto:", "tel:", "#", "login", "signup",
                "privacy", "terms", "cookie", ".pdf", ".zip", ".png", ".jpg",
            ]):
                continue
            normalized = "{0}://{1}{2}".format(parsed.scheme, parsed.netloc, parsed.path.rstrip("/"))
            if normalized in seen:
                continue
            seen.add(normalized)
            result.append(link)
            if len(result) >= max_links:
                break
        return result
    except Exception:
        return []


# --- Source credibility heuristic ---

_HIGH_CREDIBILITY_DOMAINS = {
    "openai.com": 0.95, "anthropic.com": 0.95, "deepmind.google": 0.95,
    "ai.google": 0.95, "blog.google": 0.90, "cloud.google.com": 0.90,
    "arxiv.org": 0.90, "nature.com": 0.90, "science.org": 0.90,
    "ieee.org": 0.85, "acm.org": 0.85, "proceedings.mlr.press": 0.85,
    "github.com": 0.80, "huggingface.co": 0.80,
    "docs.python.org": 0.85, "pytorch.org": 0.85, "tensorflow.org": 0.85,
    "microsoft.com": 0.85, "research.google": 0.90,
    "en.wikipedia.org": 0.70, "zh.wikipedia.org": 0.70,
    "reuters.com": 0.85, "bloomberg.com": 0.85, "ft.com": 0.85,
    "techcrunch.com": 0.70, "theverge.com": 0.65,
    "medium.com": 0.55, "substack.com": 0.55,
    "reddit.com": 0.40, "quora.com": 0.40,
}

_DOMAIN_TIER_PATTERNS = [
    (re.compile(r"\.gov$|\.gov\.\w+$"), 0.85),   # government
    (re.compile(r"\.edu$|\.edu\.\w+$|\.ac\.\w+$"), 0.80),  # academic
    (re.compile(r"\.org$"), 0.65),                 # organizations
]


def _score_source_credibility(url: str, title: str) -> float:
    """Heuristic credibility score 0-1 based on domain reputation and content signals."""
    try:
        host = urlsplit(url).netloc.lower()
    except Exception:
        return 0.5
    # Strip www prefix
    if host.startswith("www."):
        host = host[4:]
    # Exact domain match
    if host in _HIGH_CREDIBILITY_DOMAINS:
        return _HIGH_CREDIBILITY_DOMAINS[host]
    # Check parent domain (e.g., blog.openai.com → openai.com)
    parts = host.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[-2:])
        if parent in _HIGH_CREDIBILITY_DOMAINS:
            return _HIGH_CREDIBILITY_DOMAINS[parent]
    # Pattern-based tier
    for pattern, score in _DOMAIN_TIER_PATTERNS:
        if pattern.search(host):
            return score
    # Default for unknown domains
    return 0.5


def _unique(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _trim_list(values: List[str], limit: int) -> List[str]:
    return _unique(values)[:limit]


def _line_ends_cleanly(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return False
    if re.search(r"\[source:S\d+\]$", stripped):
        return True
    return bool(re.search("([。！？.!?；;]|[)\\]）】》」』\u201c\u201d\u2018\u2019`])$", stripped))


def _line_has_unbalanced_tail(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return False
    paired_markers = ("**", "__", "`")
    for marker in paired_markers:
        if stripped.count(marker) % 2 == 1:
            return True
    asymmetric_pairs = (
        ("(", ")"),
        ("\uff08", "\uff09"),
        ("[", "]"),
        ("\u3010", "\u3011"),
        ("\u201c", "\u201d"),
        ("\u2018", "\u2019"),
    )
    for opening, closing in asymmetric_pairs:
        if stripped.count(opening) > stripped.count(closing):
            return True
    if stripped.count("\"") % 2 == 1:
        return True
    return False


_GENERIC_QUERY_CHUNKS = {
    "分析",
    "报告",
    "研究",
    "评估",
    "公司",
    "企业",
    "情况",
    "布局",
    "优势",
    "劣势",
    "多少",
    "为什么",
    "如何",
    "怎么",
    "技术",
    "原理",
    "进展",
    "发展",
    "探索",
    "实现",
    "综述",
    "概述",
    "介绍",
    "背景",
    "现状",
    "趋势",
    "前景",
    "方向",
    "方案",
    "特点",
    "比较",
    "对比",
    "总结",
    "梳理",
    "解读",
    "详解",
    "深度",
    "全面",
    "最新",
    "主要",
    "核心",
    "关键",
    "重要",
}

_GENERIC_FOCUS_STOPWORDS = {
    "研究", "分析", "调研", "报告", "详细", "信息", "情况", "问题", "重点", "相关", "需要", "包括", "形成", "进行",
    "about", "overview", "details", "detail", "research", "analysis", "report", "current", "latest",
}
_MINIMAL_PRIMARY_SOURCE_TERMS = {
    "official", "docs", "documentation", "paper", "repo", "repository", "report", "filing", "blog", "release notes",
    "disclosure", "official documentation", "official report", "github", "api", "官网", "官方", "文档", "论文", "技术报告",
    "白皮书", "报告", "公告", "披露", "投资者关系", "博客", "代码", "仓库", "源码", "年报", "半年报", "季报", "财报",
}
_MINIMAL_QUANTITATIVE_TERMS = {
    "metric", "metrics", "benchmark", "kpi", "revenue", "profit", "margin", "growth", "latency", "bandwidth", "capacity",
    "power", "roe", "roa", "pe", "pb", "eps", "peg", "yield", "指标", "数据", "数值", "营收", "收入", "净利润", "毛利率",
    "增速", "份额", "带宽", "延迟", "功耗", "估值", "市值", "基准",
}
_LEADING_REQUEST_PREFIXES = (
    "请你帮我",
    "请帮我",
    "帮我",
    "给我",
    "麻烦你",
    "请你",
    "请",
    "我想",
    "我需要",
    "想",
    "需要",
    "can you",
    "please",
)
_LEADING_REQUEST_VERBS = (
    "研究一下",
    "研究下",
    "研究",
    "调研一下",
    "调研下",
    "调研",
    "分析一下",
    "分析下",
    "分析",
    "评估一下",
    "评估下",
    "评估",
    "梳理一下",
    "梳理下",
    "梳理",
    "总结一下",
    "总结下",
    "总结",
    "对比一下",
    "对比下",
    "对比",
    "了解一下",
    "了解下",
    "了解",
    "看看",
    "看下",
    "evaluate",
    "analyze",
    "research",
    "study",
    "compare",
    "review",
)


def _is_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _strip_chinese_particles(text: str) -> str:
    text = re.sub(r"[的地得](?=[\u4e00-\u9fffa-zA-Z])", "", text)
    text = re.sub(r"^[和与及在从对把被让给向往]+", "", text)
    text = re.sub(r"[和与及]+$", "", text)
    return text.strip()


def _clean_query_chunk(chunk: str) -> str:
    if re.fullmatch(r"site:[A-Za-z0-9._/-]+", chunk.strip()):
        return chunk.strip()
    chunk = re.sub("[\"\u2018\u2019\u201c\u201d'`()\u005b\u005d{}<>]", " ", chunk)
    chunk = re.sub(r"[:：,，;；|/\\]+", " ", chunk)
    chunk = _strip_chinese_particles(chunk)
    chunk = re.sub(r"\s+", " ", chunk).strip(" .-_")
    return chunk.strip()


def _split_query_chunks(text: str) -> List[str]:
    chunks = []
    for raw in re.split(r"[\s,，、;；|/]+", text):
        chunk = _clean_query_chunk(raw)
        if not chunk:
            continue
        # Split mixed CJK+Latin tokens into separate chunks
        # e.g. "Research进展和原理" -> ["Research", "进展和原理"]
        if re.search(r"[a-zA-Z]", chunk) and _is_cjk(chunk):
            parts = re.split(r"(?<=[a-zA-Z])(?=[\u4e00-\u9fff])|(?<=[\u4e00-\u9fff])(?=[a-zA-Z])", chunk)
            for part in parts:
                part = part.strip()
                if part:
                    chunks.append(part)
        else:
            chunks.append(chunk)
    return chunks


def _is_year_chunk(chunk: str) -> bool:
    return bool(re.fullmatch(r"(19|20)\d{2}([\-~](19|20)\d{2})?", chunk))


def _extract_subject(question: str) -> str:
    patterns = [
        r"研究下(.+?)(?:这家公司|这家企业|公司|企业)",
        r"研究(.+?)(?:这家公司|这家企业|公司|企业)",
        r"分析(.+?)(?:这家公司|这家企业|公司|企业)",
        r"评估(.+?)(?:这家公司|这家企业|公司|企业)",
    ]
    for pattern in patterns:
        match = re.search(pattern, question)
        if not match:
            continue
        subject = _clean_query_chunk(match.group(1))
        if subject:
            return subject
    cleaned = question.strip()
    lowered = cleaned.lower()
    changed = True
    while changed and cleaned:
        changed = False
        lowered = cleaned.lower()
        for prefix in _LEADING_REQUEST_PREFIXES:
            if lowered.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip(" ，,。.;:：")
                changed = True
                break
        if changed:
            continue
        lowered = cleaned.lower()
        for verb in _LEADING_REQUEST_VERBS:
            if lowered.startswith(verb):
                cleaned = cleaned[len(verb):].strip(" ，,。.;:：")
                changed = True
                break
    cleaned = re.sub(r"^下面的?内容\s*", "", cleaned).strip(" ，,。.;:：")
    # Strip filler request phrases that describe HOW to research, not WHAT
    cleaned = re.sub(r"^(浅显易懂地?|详细地?|深入地?|全面地?|系统地?)(阐述|分析|研究|介绍|解读|说明|梳理)(一下)?\s*", "", cleaned).strip(" ，,。.;:：")
    # If after stripping we have something generic (e.g. "整个体系") but the
    # original question has a newline with substantial content after it, prefer
    # extracting the subject from the content block after the first newline.
    if "\n" in question:
        after_newline = question.split("\n", 1)[1].strip()
        if len(after_newline) > 20:
            # The post-newline block likely has the real subject; extract leading term
            first_line = re.split(r"[，,。；;：:\n]", after_newline, maxsplit=1)[0].strip()
            # Use _split_query_chunks to get the first meaningful token
            chunks = _split_query_chunks(first_line)
            candidate = chunks[0] if chunks else ""
            if candidate and len(candidate) >= 2:
                cleaned = candidate
    # Split on punctuation or newline to isolate the first meaningful fragment
    cleaned = re.split(r"[，,。；;：:\n]", cleaned, maxsplit=1)[0].strip()
    cleaned = re.sub(r"^(一下|一下子)\s*", "", cleaned).strip()
    subject = _clean_query_chunk(cleaned)
    # If the subject is still too long (e.g. a full sentence), compact it
    # to extract the key noun phrases only
    if subject and len(subject) > 20:
        compacted = _compact_query(subject, max_chunks=3, max_chars=30)
        # If compact didn't help (single long CJK chunk), extract key nouns
        if len(compacted) > 30:
            # Split CJK text on question marks, common function words
            fragments = re.split(r"[？?！!]|能够|是否|哪些|哪一些|什么|如何|怎么", subject)
            nouns = []
            for frag in fragments:
                frag = frag.strip()
                if frag and len(frag) >= 2:
                    nouns.append(frag)
                if sum(len(n) for n in nouns) > 20:
                    break
            if nouns:
                compacted = " ".join(nouns[:2])
        subject = compacted
    if subject:
        return subject
    chunks = _split_query_chunks(question)
    return chunks[0] if chunks else ""


def _compact_query(text: str, max_chunks: int = 5, max_chars: int = 48) -> str:
    raw_chunks = _unique(_split_query_chunks(text))
    if not raw_chunks:
        return ""
    preferred = []
    year_chunks = []
    for chunk in raw_chunks:
        if chunk in _GENERIC_QUERY_CHUNKS:
            continue
        if _is_year_chunk(chunk):
            year_chunks.append(chunk)
            continue
        preferred.append(chunk)
    if not preferred:
        preferred = list(raw_chunks[:1])
    # For mixed CJK+Latin queries, keep proper nouns (short CJK, e.g. product names)
    # but drop long generic Chinese phrases that confuse English-region search engines.
    has_latin = any(re.search(r"[a-zA-Z]{2,}", c) for c in preferred)
    has_cjk = any(_is_cjk(c) for c in preferred)
    if has_latin and has_cjk and len(preferred) > 1:
        filtered = []
        for chunk in preferred:
            if _is_cjk(chunk):
                # Keep short CJK chunks (likely proper nouns like 煤化工, FICC)
                # Drop long CJK chunks (likely descriptions like 进展原理)
                cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", chunk))
                if cjk_chars <= 4:
                    filtered.append(chunk)
            else:
                filtered.append(chunk)
        if filtered:
            preferred = filtered
    selected = preferred[:max_chunks]
    if year_chunks and len(selected) < max_chunks:
        selected.append(year_chunks[-1])
    compact = " ".join(selected).strip()
    while len(compact) > max_chars and len(selected) > 2:
        selected.pop()
        compact = " ".join(selected).strip()
    return compact or " ".join(raw_chunks[:max_chunks]).strip()


_GENERIC_SINGLE_WORD_QUERIES = {
    "metrics", "comparison", "drivers", "breakdown", "regional", "timeline",
    "implementation", "supply chain", "official docs", "official blog",
    "official report", "paper", "technical report", "github repo",
    "source code",
}


def _is_low_quality_query(query: str) -> bool:
    """Reject queries that are single generic words or lack a meaningful subject."""
    stripped = query.strip().lower()
    if stripped in _GENERIC_SINGLE_WORD_QUERIES:
        return True
    # A single word with no spaces and fewer than 6 chars is too vague
    if " " not in stripped and len(stripped) < 6:
        return True
    return False


def _normalized_queries(question: str, section_title: str, queries: List[str], limit: int) -> List[str]:
    normalized = []
    subject = _extract_subject(question)
    for query in queries:
        compact = _compact_query(query)
        if compact and not _is_low_quality_query(compact):
            normalized.append(compact)
    if not normalized and subject:
        normalized.append(_compact_query("{0} {1}".format(subject, section_title)))
    if not normalized:
        normalized.append(_compact_query(section_title))
    return _unique(normalized)[:limit]


def _search_query_variants(question: str, section: SectionState, raw_query: str) -> List[str]:
    variants = []
    subject = _extract_subject(question)
    compact = _compact_query(raw_query)
    if compact:
        variants.append(compact)
    without_years = _compact_query(
        " ".join(chunk for chunk in _split_query_chunks(raw_query) if not _is_year_chunk(chunk)),
        max_chunks=4,
        max_chars=40,
    )
    if without_years:
        variants.append(without_years)
    if subject:
        variants.append(_compact_query("{0} {1}".format(subject, section.title), max_chunks=4, max_chars=36))
        focus_chunks = [chunk for chunk in _split_query_chunks(raw_query) if chunk != subject and not _is_year_chunk(chunk)]
        if focus_chunks:
            variants.append(_compact_query("{0} {1}".format(subject, " ".join(focus_chunks[:3])), max_chunks=4, max_chars=36))
    return _unique([item for item in variants if item])[:3]


# --- Multi-strategy search ---

_STRATEGY_SITE_PREFIXES = {
    "academic": ["site:arxiv.org", "site:scholar.google.com", "site:semanticscholar.org"],
    "official_docs": ["site:openai.com", "site:anthropic.com", "site:ai.google", "site:cloud.google.com"],
    "code": ["site:github.com", "site:huggingface.co"],
    "news": ["site:reuters.com", "site:bloomberg.com", "site:techcrunch.com"],
    "technical_blog": ["site:blog.google", "site:openai.com/blog", "site:engineering."],
}


def _strategy_queries(base_query: str, section: "SectionState") -> List[str]:
    """Generate additional strategy-specific queries based on section evidence requirements."""
    augmented = []
    # Check evidence requirements for source pack hints
    source_packs = set()
    for req in section.evidence_requirements:
        for pack in req.preferred_source_packs:
            source_packs.add(pack.lower())
    # Check must_cover for domain hints
    goal_lower = (section.goal or "").lower()
    # Map source packs and goal keywords to strategies
    strategies = set()
    if any(kw in goal_lower for kw in ("paper", "academic", "research", "论文", "学术")):
        strategies.add("academic")
    if any(kw in goal_lower for kw in ("official", "documentation", "docs", "官方", "文档")):
        strategies.add("official_docs")
    if any(kw in goal_lower for kw in ("code", "implementation", "github", "open source", "代码", "开源")):
        strategies.add("code")
    if any(kw in goal_lower for kw in ("market", "industry", "news", "市场", "行业")):
        strategies.add("news")
    if any(kw in goal_lower for kw in ("blog", "technical", "engineering", "技术", "博客")):
        strategies.add("technical_blog")
    # Also map source pack names
    for pack in source_packs:
        if "academic" in pack or "paper" in pack:
            strategies.add("academic")
        elif "official" in pack or "doc" in pack:
            strategies.add("official_docs")
        elif "code" in pack or "github" in pack:
            strategies.add("code")
    # Generate one site-prefixed query per strategy (pick first prefix)
    compact = _compact_query(base_query, max_chunks=4, max_chars=40)
    if not compact:
        return []
    for strategy in list(strategies)[:3]:  # limit to 3 strategy queries
        prefixes = _STRATEGY_SITE_PREFIXES.get(strategy, [])
        if prefixes:
            augmented.append("{0} {1}".format(prefixes[0], compact))
    return augmented


def _normalize_url(url: str) -> str:
    stripped = url.strip()
    if not stripped:
        return ""
    if stripped.startswith("/"):
        return stripped.rstrip("/") or stripped
    parsed = urlparse(stripped)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query = parsed.query
    normalized = "{0}://{1}{2}".format(scheme, netloc, path)
    if query:
        normalized += "?{0}".format(query)
    return normalized


def _text_blob(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part).strip().lower()


def _contains_keywords(text: str, keywords: set) -> bool:
    lowered = text.lower()
    for keyword in keywords:
        normalized = str(keyword).strip().lower()
        if not normalized:
            continue
        if re.fullmatch(r"[a-z0-9._-]{1,4}", normalized):
            if re.search(r"(?<![a-z0-9]){0}(?![a-z0-9])".format(re.escape(normalized)), lowered):
                return True
            continue
        if normalized in lowered:
            return True
    return False


def _priority_rank(value: str) -> int:
    order = {"high": 0, "medium": 1, "low": 2}
    return order.get((value or "").lower(), 1)


class ReportValidationError(RuntimeError):
    pass


class DeepResearcher:
    def __init__(
        self,
        config: AppConfig,
        backend: Optional[object] = None,
        searcher: Optional[object] = None,
        fetcher: Optional[object] = None,
    ) -> None:
        self.config = config
        if backend is None:
            if config.use_mock_llm:
                backend = MockBackend()
            else:
                backend = MultiProviderBackend(
                    openai_backend=OpenAICompatibleBackend(
                        base_url=config.base_url,
                        api_key=config.api_key,
                        timeout_seconds=config.timeout_seconds,
                    ),
                    anthropic_backend=AnthropicCompatibleBackend(
                        base_url=config.anthropic_base_url,
                        api_key=config.api_key,
                        anthropic_version=config.anthropic_version,
                        timeout_seconds=config.timeout_seconds,
                    ),
                )
        if searcher is None:
            searcher = (
                MockSearcher()
                if config.use_mock_tools
                else DDGRSearcher(config.proxy_url, config.search_region, network_mode=config.network_mode)
            )
        if fetcher is None:
            fetcher = (
                MockFetcher()
                if config.use_mock_tools
                else URLFetcher(config.proxy_url, config.timeout_seconds, network_mode=config.network_mode)
            )
        self.backend = backend
        self.searcher = searcher
        self.fetcher = fetcher
        effective_rpm = 600 if config.use_mock_llm else config.rpm_limit
        self.rate_limiter = IntervalRateLimiter(effective_rpm)
        self.capability_registry = load_model_capability_registry(config.model_capabilities_file)
        self.semantic_registry = load_semantic_registry(
            config.evidence_profiles_file,
            config.source_packs_file,
        )
        self.tracker: Optional[RunArtifacts] = None
        self.router: Optional[ModelRouter] = None
        self.workspace_documents: Optional[List[WorkspaceDocument]] = None
        self._state_lock = Lock()

    @property
    def run_dir(self) -> Optional[str]:
        if self.tracker is None:
            return None
        return str(self.tracker.run_dir)

    def run(self, question: Optional[str] = None, state: Optional[ResearchState] = None) -> ResearchState:
        if state is None and not question:
            raise ValueError("question is required when no checkpoint state is provided")
        if state is None:
            state = ResearchState(run_id=_run_id(), question=question or "")
        state.semantic_mode = self.config.semantic_mode
        self.tracker = RunArtifacts(self.config.run_root, state.run_id, verbose=self.config.verbose)
        self.router = ModelRouter(self.backend, self.rate_limiter, self.tracker, capability_registry=self.capability_registry)
        self.tracker.log("run", "supervisor", "Run started", data={"question": state.question, "semantic_mode": state.semantic_mode})

        if not state.sections:
            self._plan(state)

        next_round = state.current_round + 1
        while not state.report_markdown and next_round <= self.config.max_rounds:
            state.current_round = next_round
            self.tracker.log("research", "supervisor", "Starting research round", data={"round": next_round})
            pending_sections = [section for section in state.sections if section.status != "verified"]
            max_workers = min(len(pending_sections), 3) if not self.config.use_mock_tools else 1
            if max_workers > 1:
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(self._research_section, state, section): section
                        for section in pending_sections
                    }
                    for future in as_completed(futures):
                        section = futures[future]
                        try:
                            future.result()
                        except Exception as exc:
                            self.tracker.log(
                                "section",
                                section.section_id,
                                "Parallel section research failed",
                                level="ERROR",
                                data={"error": str(exc), "title": section.title},
                            )
            else:
                for section in pending_sections:
                    self._research_section(state, section)
            self.tracker.checkpoint("round-{0}".format(next_round), state)
            if not self._review_gaps(state):
                break
            next_round += 1

        if not state.report_markdown:
            self._cross_section_synthesis(state)
            self._write_report(state)

        self._audit_report(state)
        state.status = "completed"
        self.tracker.write_text("report.md", state.report_markdown)
        self.tracker.checkpoint("final", state)
        self.tracker.log("run", "supervisor", "Run completed", data={"run_dir": str(self.tracker.run_dir)})
        self.tracker.finalize(state)
        return state

    def plan(self, question: Optional[str] = None, state: Optional[ResearchState] = None) -> ResearchState:
        if state is None and not question:
            raise ValueError("question is required when no checkpoint state is provided")
        if state is None:
            state = ResearchState(run_id=_run_id(), question=question or "")
        state.semantic_mode = self.config.semantic_mode
        self.tracker = RunArtifacts(self.config.run_root, state.run_id, verbose=self.config.verbose)
        self.router = ModelRouter(self.backend, self.rate_limiter, self.tracker, capability_registry=self.capability_registry)
        self.tracker.log("run", "supervisor", "Plan-only run started", data={"question": state.question, "mode": "plan_only", "semantic_mode": state.semantic_mode})
        if not state.sections:
            self._plan(state)
        self.tracker.log("run", "supervisor", "Plan-only run completed", data={"run_dir": str(self.tracker.run_dir), "mode": "plan_only"})
        self.tracker.finalize(state)
        return state

    def _plan(self, state: ResearchState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_planning_messages(
            state.question,
            self.config.max_sections,
            self.semantic_registry.profile_prompt_payload(),
            self.semantic_registry.source_pack_prompt_payload(),
            self.config.semantic_mode,
        )
        try:
            model, payload = self.router.complete_json("planning", messages, self.config.planner)
            self.tracker.log("planning", "planner", "Research plan created", data={"model": model})
            sections = []
            for item in payload.get("sections", [])[:self.config.max_sections]:
                queries = _normalized_queries(
                    state.question,
                    item.get("title", ""),
                    item.get("queries", [])[:self.config.max_queries_per_section],
                    self.config.max_queries_per_section,
                )
                if not queries:
                    queries = _normalized_queries(
                        state.question,
                        item.get("title", ""),
                        [state.question, "{0} {1}".format(state.question, item.get("title", ""))],
                        self.config.max_queries_per_section,
                    )
                must_cover = _trim_list(item.get("must_cover", []), 6)
                sections.append(SectionState(
                    section_id=item.get("id") or "section-{0}".format(len(sections) + 1),
                    title=item.get("title", "Untitled section"),
                    goal=item.get("goal", ""),
                    queries=queries,
                    must_cover=must_cover,
                    evidence_requirements=self._parse_evidence_requirements(item.get("evidence_requirements", [])),
                ))
            state.objective = payload.get("objective", state.question)
            state.research_brief = payload.get("research_brief", "")
            state.input_dependencies = _trim_list(payload.get("input_dependencies", []), 6)
            state.source_requirements = _trim_list(payload.get("source_requirements", []), 8)
            state.comparison_axes = _trim_list(payload.get("comparison_axes", []), 8)
            state.success_criteria = _trim_list(payload.get("success_criteria", []), 8)
            state.risks = _trim_list(payload.get("risks", []), 8)
            state.sections = sections or self._fallback_sections(state.question)
            raw_requirements_artifact = self.tracker.write_json(
                "state/planner-evidence-requirements.json",
                [
                    {
                        "section_id": section.section_id,
                        "evidence_requirements": [item.__dict__ for item in section.evidence_requirements],
                    }
                    for section in state.sections
                ],
            )
            for section in state.sections:
                self._resolve_section_semantics(state, section, stage="planning")
            self.tracker.log(
                "planning",
                "planner",
                "Planner evidence requirements recorded",
                artifacts={"raw_evidence_requirements": raw_requirements_artifact},
            )
        except Exception as exc:
            state.debug_notes.append("Planning fallback used: {0}".format(exc))
            self.tracker.log("planning", "planner", "Planning failed, using fallback", level="ERROR", data={"error": str(exc)})
            state.objective = "Deliver a structured answer for: {0}".format(state.question)
            state.sections = self._fallback_sections(state.question)
        for section in state.sections:
            if not section.resolved_profiles and not section.resolved_source_packs:
                self._resolve_section_semantics(state, section, stage="planning-fallback")
        state.status = "planned"
        self.tracker.checkpoint("planned", state)
        plan_md = self.tracker.render_plan(state)
        plan_json = self.tracker.write_plan_json(state)
        self.tracker.log(
            "planning",
            "planner",
            "Plan artifacts generated",
            artifacts={"plan_md": plan_md, "plan_json": plan_json},
        )

    def _fallback_sections(self, question: str) -> List[SectionState]:
        base = [
            ("context", "Context and Scope", "Define the question and boundaries."),
            ("landscape", "Landscape", "Map the current ecosystem and options."),
            ("risks", "Risks and Constraints", "Surface main risks and limitations."),
            ("recommendation", "Recommendation", "Summarize a practical recommendation."),
        ]
        sections = []
        for section_id, title, goal in base:
            sections.append(SectionState(
                section_id=section_id,
                title=title,
                goal=goal,
                queries=_normalized_queries(question, title, ["{0} {1}".format(question, title), question], 2),
            ))
        return sections

    def _collect_semantic_texts(self, state: ResearchState, section: Optional[SectionState] = None) -> List[str]:
        values = [
            state.question,
            state.objective,
            state.research_brief,
            *state.input_dependencies,
            *state.source_requirements,
            *state.comparison_axes,
            *state.success_criteria,
            *state.global_gaps,
        ]
        if section is not None:
            values.extend([
                section.title,
                section.goal,
                *section.queries,
                *section.must_cover,
                *section.open_questions,
                *section.verification_notes,
            ])
            for requirement in section.evidence_requirements:
                values.extend(requirement.must_cover)
                values.extend(requirement.query_hints)
                values.extend(requirement.preferred_source_packs)
                if requirement.rationale:
                    values.append(requirement.rationale)
        return [value for value in values if value]

    def _extract_focus_terms(self, values: List[str], limit: int = 8) -> List[str]:
        terms = []
        for value in values:
            for raw in re.split(r"[\n,，、;；|/]+", value):
                chunk = _clean_query_chunk(raw)
                if not chunk:
                    continue
                lowered = chunk.lower()
                if lowered in _GENERIC_FOCUS_STOPWORDS:
                    continue
                if len(chunk) < 2 or len(chunk) > 60:
                    continue
                terms.append(chunk)
        return _trim_list(terms, limit)

    def _mentions_terms(self, values: List[str], terms: set) -> bool:
        return _contains_keywords(_text_blob(*values), terms)

    def _minimal_fallback_requirements(self, state: ResearchState, section: SectionState) -> List[EvidenceRequirement]:
        values = self._collect_semantic_texts(state, section)
        fallback: List[EvidenceRequirement] = []
        if self._mentions_terms(values, _MINIMAL_PRIMARY_SOURCE_TERMS):
            fallback.append(EvidenceRequirement(
                profile_id="primary_source",
                priority="high",
                must_cover=_trim_list(section.must_cover, 4),
                query_hints=self._extract_focus_terms(values, 4),
                rationale="Minimal fallback: the task explicitly mentions official or first-party sources.",
            ))
        if self._mentions_terms(values, _MINIMAL_QUANTITATIVE_TERMS):
            fallback.append(EvidenceRequirement(
                profile_id="quantitative_metric",
                priority="medium",
                must_cover=_trim_list(section.must_cover, 4),
                query_hints=self._extract_focus_terms(values, 4),
                rationale="Minimal fallback: the task explicitly requests metrics, benchmarks, or numeric evidence.",
            ))
        return fallback

    def _parse_evidence_requirements(self, raw_requirements: List[Dict[str, object]]) -> List[EvidenceRequirement]:
        requirements = []
        for item in raw_requirements:
            profile_id = str(item.get("profile_id", "")).strip()
            if not profile_id:
                continue
            requirements.append(EvidenceRequirement(
                profile_id=profile_id,
                priority=str(item.get("priority", "medium")).strip() or "medium",
                must_cover=_trim_list([str(value) for value in item.get("must_cover", [])], 6),
                preferred_source_packs=_trim_list([str(value) for value in item.get("preferred_source_packs", [])], 6),
                query_hints=_trim_list([str(value) for value in item.get("query_hints", [])], 6),
                rationale=str(item.get("rationale", "")).strip(),
            ))
        return requirements

    def _render_query_templates(self, templates: List[str], context: Dict[str, str]) -> List[str]:
        queries = []
        for template in templates:
            try:
                rendered = template.format_map(context)
            except Exception:
                rendered = template
            rendered = re.sub(r"\s+", " ", rendered).strip()
            if rendered:
                queries.append(rendered)
        return queries

    def _resolve_source_packs(self, profile_id: str, preferred_source_packs: List[str]) -> Dict[str, List[str]]:
        valid = []
        invalid = []
        for pack_id in preferred_source_packs:
            source_pack = self.semantic_registry.source_packs.get(pack_id)
            if source_pack is None:
                invalid.append(pack_id)
                continue
            if profile_id not in source_pack.applies_to_profiles:
                invalid.append(pack_id)
                continue
            if pack_id not in valid:
                valid.append(pack_id)
        return {"valid": valid, "invalid": invalid}

    def _resolve_section_semantics(self, state: ResearchState, section: SectionState, stage: str) -> Dict[str, object]:
        assert self.tracker is not None
        raw_requirements = list(section.evidence_requirements)
        valid_requirements: List[EvidenceRequirement] = []
        invalid_profiles: List[str] = []
        invalid_source_packs: List[str] = []
        for requirement in raw_requirements:
            if requirement.profile_id not in self.semantic_registry.profiles:
                invalid_profiles.append(requirement.profile_id)
                continue
            valid_packs = self._resolve_source_packs(requirement.profile_id, requirement.preferred_source_packs)
            invalid_source_packs.extend(valid_packs["invalid"])
            valid_requirements.append(EvidenceRequirement(
                profile_id=requirement.profile_id,
                priority=requirement.priority,
                must_cover=_trim_list(requirement.must_cover, 6),
                preferred_source_packs=valid_packs["valid"],
                query_hints=_trim_list(requirement.query_hints, 6),
                rationale=requirement.rationale,
            ))

        fallback_used = []
        if not valid_requirements:
            fallback_requirements = [
                item
                for item in self._minimal_fallback_requirements(state, section)
                if item.profile_id in self.semantic_registry.profiles
                and self.semantic_registry.profiles[item.profile_id].fallback_enabled
            ]
            valid_requirements = fallback_requirements
            fallback_used = [item.profile_id for item in fallback_requirements]

        subject = _extract_subject(state.question) or _compact_query(state.question, max_chunks=3, max_chars=32)
        resolved_profiles = []
        resolved_source_packs = []
        generated_queries = []
        source_hints = []
        query_generation_mode = "planner_native"
        should_expand_registry_templates = (
            self.config.semantic_mode == "hybrid"
            or not raw_requirements
            or bool(fallback_used)
        )
        for requirement in valid_requirements:
            profile = self.semantic_registry.profiles[requirement.profile_id]
            resolved_profiles.append(profile.profile_id)
            focus_terms = _trim_list(
                requirement.query_hints + requirement.must_cover + self._extract_focus_terms([section.title, section.goal], 4),
                6,
            )
            document_terms = " ".join(self._extract_focus_terms(state.source_requirements + requirement.query_hints, 3)) or "official docs"
            context = {
                "subject": subject,
                "section_title": section.title,
                "must_cover": " ".join(requirement.must_cover or section.must_cover[:4]),
                "query_hints": " ".join(focus_terms),
                "document_terms": (
                    " ".join(self._extract_focus_terms(requirement.query_hints + requirement.must_cover, 3))
                    or document_terms
                ),
            }
            if should_expand_registry_templates:
                source_hints.extend(profile.default_source_hints)
                generated_queries.extend(self._render_query_templates(profile.default_query_templates, context))
                query_generation_mode = "registry_templates"
            for pack_id in requirement.preferred_source_packs:
                source_pack = self.semantic_registry.source_packs.get(pack_id)
                if source_pack is None:
                    continue
                resolved_source_packs.append(pack_id)
                if should_expand_registry_templates:
                    source_hints.extend(source_pack.source_hints)
                    generated_queries.extend(self._render_query_templates(source_pack.query_templates, context))

        section.evidence_requirements = valid_requirements
        section.resolved_profiles = _unique(resolved_profiles)
        section.resolved_source_packs = _unique(resolved_source_packs)
        section.queries = _normalized_queries(
            state.question,
            section.title,
            generated_queries + section.queries,
            max(len(_unique(generated_queries + section.queries)), self.config.max_queries_per_section + 2),
        )
        if source_hints:
            state.source_requirements = _trim_list(state.source_requirements + source_hints, 12)
        resolution = {
            "section_id": section.section_id,
            "stage": stage,
            "semantic_mode": self.config.semantic_mode,
            "raw_requirements": [item.__dict__ for item in raw_requirements],
            "resolved_requirements": [item.__dict__ for item in valid_requirements],
            "resolved_profiles": section.resolved_profiles,
            "resolved_source_packs": section.resolved_source_packs,
            "query_generation_mode": query_generation_mode,
            "generated_queries": generated_queries,
            "effective_queries": section.queries,
            "invalid_profiles": _unique(invalid_profiles),
            "invalid_source_packs": _unique(invalid_source_packs),
            "fallback_used": fallback_used,
        }
        artifact = self.tracker.write_json(
            "state/semantic-resolution-{0}-{1}.json".format(section.section_id, stage),
            resolution,
        )
        self.tracker.log(
            "semantics",
            section.section_id,
            "Resolved section semantics",
            data={
                "stage": stage,
                "semantic_mode": self.config.semantic_mode,
                "resolved_profiles": section.resolved_profiles,
                "resolved_source_packs": section.resolved_source_packs,
                "query_generation_mode": query_generation_mode,
                "invalid_profiles": _unique(invalid_profiles),
                "invalid_source_packs": _unique(invalid_source_packs),
                "fallback_used": fallback_used,
            },
            artifacts={"resolution": artifact},
        )
        return resolution

    def _merge_gap_tasks(self, raw_tasks: List[Dict[str, object]]) -> Dict[str, object]:
        merged: Dict[str, GapTask] = {}
        invalid_profiles: List[str] = []
        invalid_source_packs: List[str] = []
        for item in raw_tasks:
            category = str(item.get("category", "")).strip()
            if category not in self.semantic_registry.profiles:
                if category:
                    invalid_profiles.append(category)
                continue
            preferred_source_packs = []
            for pack_id in [str(value) for value in item.get("preferred_source_packs", [])]:
                if pack_id not in self.semantic_registry.source_packs:
                    invalid_source_packs.append(pack_id)
                    continue
                preferred_source_packs.append(pack_id)
            task = GapTask(
                task_id=str(item.get("task_id", "")).strip() or "gap-{0}".format(category),
                section_id=str(item.get("section_id", "")).strip(),
                gap=str(item.get("gap", "")).strip(),
                category=category,
                action=str(item.get("action", "search")).strip() or "search",
                priority=str(item.get("priority", "medium")).strip() or "medium",
                rationale=str(item.get("rationale", "")).strip(),
                follow_up_queries=_trim_list([str(value) for value in item.get("follow_up_queries", [])], 6),
                must_cover=_trim_list([str(value) for value in item.get("must_cover", [])], 6),
                preferred_source_packs=_trim_list(preferred_source_packs, 6),
                source_hints=_trim_list([str(value) for value in item.get("source_hints", [])], 6),
                status=str(item.get("status", "open")).strip() or "open",
            )
            key = "{0}:{1}:{2}".format(task.section_id or "unassigned", task.category, task.gap or task.task_id)
            existing = merged.get(key)
            if existing is None:
                merged[key] = task
                continue
            existing.follow_up_queries = _trim_list(existing.follow_up_queries + task.follow_up_queries, 6)
            existing.must_cover = _trim_list(existing.must_cover + task.must_cover, 8)
            existing.preferred_source_packs = _trim_list(existing.preferred_source_packs + task.preferred_source_packs, 6)
            existing.source_hints = _trim_list(existing.source_hints + task.source_hints, 8)
            if _priority_rank(task.priority) < _priority_rank(existing.priority):
                existing.priority = task.priority
            if not existing.rationale and task.rationale:
                existing.rationale = task.rationale
        tasks = sorted(merged.values(), key=lambda item: (_priority_rank(item.priority), item.section_id, item.category))
        return {
            "tasks": tasks,
            "invalid_profiles": _unique(invalid_profiles),
            "invalid_source_packs": _unique(invalid_source_packs),
        }

    def _apply_gap_tasks(self, state: ResearchState, tasks: List[GapTask]) -> None:
        by_id = {section.section_id: section for section in state.sections}
        touched_sections = set()
        for task in tasks:
            section = by_id.get(task.section_id)
            if section is None:
                continue
            section.must_cover = _trim_list(section.must_cover + task.must_cover, 10)
            section.open_questions = _unique(section.open_questions + [task.gap or task.rationale])
            if task.rationale:
                section.verification_notes = _trim_list(section.verification_notes + [task.rationale], 8)
            section.evidence_requirements.append(EvidenceRequirement(
                profile_id=task.category,
                priority=task.priority,
                must_cover=task.must_cover,
                preferred_source_packs=task.preferred_source_packs,
                query_hints=self._extract_focus_terms(task.follow_up_queries + [task.gap, task.rationale], 6),
                rationale=task.rationale,
            ))
            section.queries = _normalized_queries(
                state.question,
                section.title,
                task.follow_up_queries + section.queries,
                max(len(section.queries) + 3, self.config.max_queries_per_section + 2),
            )
            if section.status == "verified" or task.priority in {"high", "medium"}:
                section.status = "pending"
            task.status = "applied"
            touched_sections.add(section.section_id)
        for section_id in touched_sections:
            section = by_id[section_id]
            self._resolve_section_semantics(state, section, stage="gap-review")

    def _research_section(self, state: ResearchState, section: SectionState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        section.status = "researching"
        self.tracker.log(
            "section",
            section.section_id,
            "Researching section",
            data={"title": section.title, "queries": section.queries},
        )
        evidence_packets = self._collect_workspace_evidence(state, section)
        max_total_evidence = self.config.max_workspace_sources_per_section + self.config.max_sources_per_section
        web_sources_used = 0
        query_queue = _normalized_queries(
            state.question,
            section.title,
            section.queries,
            max(len(section.queries), self.config.max_queries_per_section + 2),
        )
        # Inject strategy-specific queries (site: prefixed) based on section evidence needs
        if query_queue:
            strategy_extras = _strategy_queries(query_queue[0], section)
            if strategy_extras:
                query_queue = query_queue + strategy_extras
        query_budget = min(len(query_queue), self.config.max_queries_per_section + 4)
        for raw_query in query_queue[:query_budget]:
            hits = []
            search_variants = _search_query_variants(state.question, section, raw_query)
            for attempt_index, query in enumerate(search_variants, start=1):
                try:
                    hits = self.searcher.search(query, self.config.max_results_per_query)
                except Exception as exc:
                    self.tracker.log(
                        "search",
                        section.section_id,
                        "Search failed",
                        level="ERROR",
                        data={"raw_query": raw_query, "query": query, "attempt": attempt_index, "error": str(exc)},
                    )
                    continue
                results_artifact = self.tracker.write_text(
                    "sources/{0}-{1}.json".format(section.section_id, len(evidence_packets) + 1),
                    json.dumps([hit.__dict__ for hit in hits], ensure_ascii=False, indent=2),
                )
                self.tracker.log(
                    "search",
                    section.section_id,
                    "Search completed",
                    data={
                        "raw_query": raw_query,
                        "query": query,
                        "attempt": attempt_index,
                        "results": len(hits),
                        "network_mode": getattr(self.searcher, "last_mode", "unknown"),
                    },
                    artifacts={"results": results_artifact},
                )
                self._record_search_results(state, section.section_id, raw_query, query, hits)
                if hits:
                    break
            if not hits:
                continue
            for hit in hits[:self.config.max_sources_per_section]:
                source = self._register_source(state, raw_query, hit.title, hit.url, hit.snippet)
                if any(packet["source_id"] == source.source_id for packet in evidence_packets):
                    continue
                self._mark_search_result_used(state, section.section_id, raw_query, query, source)
                if source.fetch_status == "unfetched":
                    try:
                        page = self.fetcher.fetch(hit.url)
                        if page.final_url:
                            source.url = page.final_url
                        source.raw_artifact = self.tracker.write_text(
                            "sources/{0}.raw.html".format(source.source_id), page.raw_html
                        )
                        source.excerpt = extract_relevant_passages(
                            page.text or hit.snippet,
                            raw_query,
                            max_chars=self.config.max_chars_per_source,
                        )
                        source.fetch_status = "fetched"
                        source.text_artifact = self.tracker.write_text(
                            "sources/{0}.txt".format(source.source_id), page.text
                        )
                        if page.title and page.title != page.final_url and source.title == hit.title:
                            source.title = page.title
                    except Exception as exc:
                        source.fetch_status = "failed"
                        source.excerpt = hit.snippet
                        self.tracker.log(
                            "fetch",
                            section.section_id,
                            "Fetch failed, falling back to snippet",
                            level="ERROR",
                            data={
                                "source_id": source.source_id,
                                "url": hit.url,
                                "network_mode": getattr(self.fetcher, "last_mode", "unknown"),
                                "error": str(exc),
                            },
                        )
                if source.source_id not in section.source_ids:
                    section.source_ids.append(source.source_id)
                evidence_packets.append({
                    "source_id": source.source_id,
                    "title": source.title,
                    "url": source.url,
                    "excerpt": source.excerpt or source.snippet,
                    "source_type": "web",
                })
                web_sources_used += 1
                if len(evidence_packets) >= max_total_evidence or web_sources_used >= self.config.max_sources_per_section:
                    break
            if len(evidence_packets) >= max_total_evidence or web_sources_used >= self.config.max_sources_per_section:
                break

        # Link following: extract outbound links from high-credibility sources
        if evidence_packets and len(evidence_packets) < max_total_evidence:
            known_urls = {source.url for source in state.sources.values()}
            links_followed = 0
            max_follow = 3
            for packet in list(evidence_packets):
                if links_followed >= max_follow:
                    break
                source = state.sources.get(packet["source_id"])
                if not source or source.credibility_score < 0.8 or not source.raw_artifact:
                    continue
                raw_path = self.tracker.run_dir / source.raw_artifact if self.tracker else None
                if not raw_path or not raw_path.exists():
                    continue
                try:
                    raw_html = raw_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                outbound = _extract_outbound_links(raw_html, source.url, max_links=5)
                for link_url in outbound:
                    if links_followed >= max_follow:
                        break
                    if link_url in known_urls:
                        continue
                    known_urls.add(link_url)
                    try:
                        page = self.fetcher.fetch(link_url)
                        if not page.text or len(page.text.strip()) < 100:
                            continue
                        final_url = page.final_url or link_url
                        linked_source = self._register_source(
                            state, "link-follow:{0}".format(source.source_id),
                            page.title or link_url, final_url, "",
                        )
                        if linked_source.fetch_status != "unfetched":
                            continue
                        linked_source.raw_artifact = self.tracker.write_text(
                            "sources/{0}.raw.html".format(linked_source.source_id), page.raw_html,
                        )
                        linked_source.excerpt = extract_relevant_passages(
                            page.text, section.queries[0] if section.queries else state.question,
                            max_chars=self.config.max_chars_per_source,
                        )
                        linked_source.fetch_status = "fetched"
                        linked_source.text_artifact = self.tracker.write_text(
                            "sources/{0}.txt".format(linked_source.source_id), page.text,
                        )
                        if linked_source.source_id not in section.source_ids:
                            section.source_ids.append(linked_source.source_id)
                        evidence_packets.append({
                            "source_id": linked_source.source_id,
                            "title": linked_source.title,
                            "url": final_url,
                            "excerpt": linked_source.excerpt,
                            "source_type": "web",
                        })
                        links_followed += 1
                        self.tracker.log(
                            "link-follow",
                            section.section_id,
                            "Followed outbound link",
                            data={
                                "from_source": source.source_id,
                                "to_url": final_url,
                                "new_source": linked_source.source_id,
                            },
                        )
                    except Exception:
                        continue

        if not evidence_packets:
            section.status = "blocked"
            section.open_questions = _unique(section.open_questions + ["No usable sources found."])
            self.tracker.log("section", section.section_id, "Section blocked due to missing evidence", level="WARN")
            return

        messages = build_section_research_messages(state.question, section, state.current_round, evidence_packets)
        try:
            task_label = "section-{0}-round-{1}".format(section.section_id, state.current_round)
            try:
                model, payload = self.router.complete_json(
                    task_label,
                    messages,
                    self.config.researcher,
                )
            except RuntimeError as json_exc:
                # Only retry with Sonar models — non-Sonar models should produce valid JSON
                sonar_candidates = [c for c in self.config.researcher.candidates if is_sonar_model(c)]
                if not sonar_candidates:
                    raise json_exc
                sonar_selection = ModelSelection(
                    candidates=sonar_candidates,
                    temperature=self.config.researcher.temperature,
                    max_output_tokens=self.config.researcher.max_output_tokens,
                )
                result = self.router.complete_text(task_label + "-sonar-retry", messages, sonar_selection)
                payload = adapt_sonar_response(result.content)
                model = result.model
                # Register Sonar URLs as real sources and remap sonar-ref-N to S-IDs
                sonar_urls = payload.pop("_sonar_urls", [])
                ref_to_sid: Dict[str, str] = {}
                for url in sonar_urls:
                    source = self._register_source(state, "sonar:" + section.section_id, url.split("/")[-1][:80], url, "")
                    # Map by order: sonar-ref-1 → first URL, sonar-ref-2 → second, etc.
                    ref_key = "sonar-ref-{0}".format(len(ref_to_sid) + 1)
                    ref_to_sid[ref_key] = source.source_id
                if ref_to_sid:
                    for finding in payload.get("findings", []):
                        finding["source_ids"] = [ref_to_sid.get(sid, sid) for sid in finding.get("source_ids", [])]
                self.tracker.log("section", section.section_id, "Used sonar adapter for non-JSON response", data={"model": model, "urls_registered": len(sonar_urls)})
            section.thesis = str(payload.get("thesis", section.thesis or section.summary)).strip()
            section.key_drivers = _trim_list([str(item) for item in payload.get("key_drivers", [])], 6)
            section.reasoning_steps = self._merge_reasoning_steps(
                section.reasoning_steps,
                payload.get("reasoning_steps", []),
            )
            section.counterpoints = _trim_list([str(item) for item in payload.get("counterpoints", [])], 6)
            section.summary = payload.get("summary", section.summary)
            section.findings = self._merge_findings(section.findings, payload.get("findings", []))
            section.open_questions = _unique(payload.get("open_questions", []))
            section.queries = _normalized_queries(
                state.question,
                section.title,
                section.queries + payload.get("follow_up_queries", []),
                6,
            )
            status = payload.get("status", "draft_ready")
            section.status = "pending" if status == "continue_research" else status
            section.draft = self._section_draft(section)
            reasoning_artifact = self.tracker.write_text(
                "analysis/{0}-round-{1}.md".format(section.section_id, state.current_round),
                self._section_reasoning_note(section),
            )
            self.tracker.log(
                "section",
                section.section_id,
                "Section synthesis completed",
                data={
                    "model": model,
                    "source_count": len(evidence_packets),
                    "thesis": section.thesis,
                    "driver_count": len(section.key_drivers),
                    "reasoning_step_count": len(section.reasoning_steps),
                },
                artifacts={"analysis": reasoning_artifact},
            )
        except Exception as exc:
            self.tracker.log(
                "section",
                section.section_id,
                "Section synthesis failed, using heuristic fallback",
                level="ERROR",
                data={"error": str(exc)},
            )
            section.summary = "Collected {0} sources for {1}.".format(len(evidence_packets), section.title)
            if not section.findings:
                section.findings = [
                    Finding(
                        claim="Evidence was collected for {0}, but LLM synthesis failed. Review source artifacts.".format(section.title),
                        source_ids=[packet["source_id"] for packet in evidence_packets[:2]],
                    )
                ]
            if not section.thesis:
                section.thesis = "Current evidence for {0} is partial and requires manual review.".format(section.title)
            section.status = "draft_ready"
            section.draft = self._section_draft(section)
        self.tracker.checkpoint(
            "section-{0}-round-{1}".format(section.section_id, state.current_round),
            state,
        )

    def _review_gaps(self, state: ResearchState) -> bool:
        assert self.router is not None
        assert self.tracker is not None
        if state.current_round >= self.config.max_rounds:
            self.tracker.log("review", "supervisor", "Reached max rounds", data={"round": state.current_round})
            return False
        messages = build_gap_review_messages(
            state,
            self.semantic_registry.profile_prompt_payload(),
            self.semantic_registry.source_pack_prompt_payload(),
            self.config.semantic_mode,
        )
        try:
            model, payload = self.router.complete_json(
                "gap-review-round-{0}".format(state.current_round),
                messages,
                self.config.verifier,
            )
            state.global_gaps = _trim_list([str(item) for item in payload.get("global_gaps", [])], 12)
            # Parse and store section sufficiency scores
            by_id = {section.section_id: section for section in state.sections}
            for suf in payload.get("section_sufficiency", []):
                sid = suf.get("section_id", "")
                section = by_id.get(sid)
                if section is not None:
                    score = suf.get("score", 0)
                    section.evidence_sufficiency = float(min(max(score, 0), 5))
            avg_sufficiency = (
                sum(s.evidence_sufficiency for s in state.sections) / max(len(state.sections), 1)
            )
            focus_sections = payload.get("focus_sections", [])
            merge_result = self._merge_gap_tasks(payload.get("gap_tasks", []))
            tasks = merge_result["tasks"]
            state.gap_tasks = tasks
            tasks_artifact = self.tracker.write_json(
                "state/gap-tasks-round-{0}.json".format(state.current_round),
                {
                    "tasks": [item.__dict__ for item in tasks],
                    "invalid_profiles": merge_result["invalid_profiles"],
                    "invalid_source_packs": merge_result["invalid_source_packs"],
                },
            )
            self.tracker.log(
                "review",
                "verifier",
                "Gap review completed",
                data={
                    "model": model,
                    "continue_research": payload.get("continue_research", False),
                    "avg_sufficiency": round(avg_sufficiency, 2),
                    "global_gap_count": len(state.global_gaps),
                    "task_count": len(tasks),
                    "invalid_profiles": merge_result["invalid_profiles"],
                    "invalid_source_packs": merge_result["invalid_source_packs"],
                },
                artifacts={"gap_tasks": tasks_artifact},
            )
            continue_research = bool(payload.get("continue_research", False))
            # Adaptive: also continue if average sufficiency is low
            if avg_sufficiency < 3.5 and state.current_round < self.config.max_rounds:
                continue_research = True
            if tasks and state.current_round < self.config.max_rounds:
                continue_research = True
            if not continue_research:
                return False
            by_id = {section.section_id: section for section in state.sections}
            for item in focus_sections:
                section = by_id.get(item.get("section_id", ""))
                if section is None:
                    continue
                section.status = "pending"
                section.open_questions = _unique(section.open_questions + [item.get("reason", "")])
                section.queries = _normalized_queries(
                    state.question,
                    section.title,
                    section.queries + item.get("follow_up_queries", []),
                    6,
                )
                self._resolve_section_semantics(state, section, stage="gap-focus")
            self._apply_gap_tasks(state, tasks)
            return True
        except Exception as exc:
            self.tracker.log("review", "verifier", "Gap review failed, stopping rounds", level="ERROR", data={"error": str(exc)})
            return False

    def _cross_section_synthesis(self, state: ResearchState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        if len(state.sections) < 2:
            return
        messages = build_cross_section_synthesis_messages(state)
        try:
            _, payload = self.router.complete_json(
                "cross-section-synthesis", messages, self.config.verifier,
            )
            state.cross_section_synthesis = payload
            contradictions = payload.get("contradictions", [])
            overlaps = payload.get("overlaps", [])
            themes = payload.get("cross_cutting_themes", [])
            self.tracker.log(
                "synthesis",
                "supervisor",
                "Cross-section synthesis completed",
                data={
                    "contradictions": len(contradictions),
                    "overlaps": len(overlaps),
                    "themes": len(themes),
                },
            )
            artifact = self.tracker.write_text(
                "artifacts/cross-section-synthesis.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            self.tracker.log(
                "synthesis",
                "supervisor",
                "Synthesis artifact written",
                artifacts={"synthesis": artifact},
            )
        except Exception as exc:
            self.tracker.log(
                "synthesis",
                "supervisor",
                "Cross-section synthesis failed, proceeding without",
                level="WARNING",
                data={"error": str(exc)},
            )

    def _write_report(self, state: ResearchState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        last_issues: List[str] = []
        try:
            section_markdowns = [self._write_report_section(state, section) for section in state.sections]
            candidate_report = self._assemble_report(state, section_markdowns)
            issues = self._validate_report_completeness(state, candidate_report)
            if issues:
                last_issues = issues
                incomplete_artifact = self.tracker.write_text(
                    "artifacts/report-failures/report-assembled.md",
                    candidate_report,
                )
                self.tracker.log(
                    "report",
                    "writer",
                    "Assembled report failed completeness validation",
                    level="ERROR",
                    data={"issues": issues},
                    artifacts={"incomplete_report": incomplete_artifact},
                )
                raise ReportValidationError("; ".join(issues))
            state.report_markdown = self._append_source_appendices(state, candidate_report)
            self.tracker.log(
                "report",
                "writer",
                "Report generated",
                data={"section_count": len(section_markdowns)},
            )
            self.tracker.write_text("report.md", state.report_markdown)
            self.tracker.checkpoint("report-generated", state)
            return
        except Exception as exc:
            self.tracker.log(
                "report",
                "writer",
                "Hierarchical report generation failed, using fallback",
                level="ERROR",
                data={"error": str(exc)},
            )
            fallback_report = self._fallback_report(state)
            issues = self._validate_report_completeness(state, fallback_report)
            if issues:
                last_issues = issues
                fallback_artifact = self.tracker.write_text(
                    "artifacts/report-failures/fallback-report.md",
                    fallback_report,
                )
                self.tracker.log(
                    "report",
                    "writer",
                    "Fallback report also failed completeness validation",
                    level="ERROR",
                    data={"issues": issues},
                    artifacts={"incomplete_report": fallback_artifact},
                )
                state.status = "failed"
                state.debug_notes.append("Report generation incomplete: {0}".format("; ".join(last_issues) or str(exc)))
                self.tracker.checkpoint("report-failed", state)
                raise ReportValidationError("Report generation incomplete: {0}".format("; ".join(last_issues) or str(exc)))
            state.report_markdown = self._append_source_appendices(state, fallback_report)
            self.tracker.write_text("report.md", state.report_markdown)
            self.tracker.checkpoint("report-generated", state)
            return

    def _audit_report(self, state: ResearchState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_audit_messages(state)
        try:
            model, payload = self.router.complete_json("report-audit", messages, self.config.verifier)
            issues = []
            for item in payload.get("issues", []):
                issues.append(AuditIssue(
                    severity=item.get("severity", "low"),
                    section_title=item.get("section_title", "General"),
                    reason=item.get("reason", ""),
                    suggested_fix=item.get("suggested_fix", ""),
                ))
            state.audit_issues = issues
            self.tracker.log(
                "audit",
                "verifier",
                "Audit completed",
                data={"model": model, "status": payload.get("status", "pass"), "issue_count": len(issues)},
            )
        except Exception as exc:
            state.audit_issues = [AuditIssue(
                severity="medium",
                section_title="General",
                reason="Audit step failed: {0}".format(exc),
            )]
            self.tracker.log("audit", "verifier", "Audit failed", level="ERROR", data={"error": str(exc)})

    def _write_report_section(self, state: ResearchState, section: SectionState) -> str:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_section_report_messages(state, section)
        try:
            # Step 1: Write initial draft
            task_name = "report-section-{0}".format(section.section_id)
            result = self.router.complete_text(task_name, messages, self.config.writer)
            markdown = self._normalize_section_markdown(section, result.content)
            issues = self._validate_section_markdown(section, markdown)
            if issues:
                incomplete_artifact = self.tracker.write_text(
                    "artifacts/report-failures/{0}-initial.md".format(section.section_id),
                    markdown,
                )
                self.tracker.log(
                    "report-section",
                    section.section_id,
                    "Initial draft failed validation, attempting retry",
                    level="WARNING",
                    data={"title": section.title, "issues": issues},
                    artifacts={"incomplete_report": incomplete_artifact},
                )
                retry_messages = self._build_section_report_retry_messages(state, section, markdown, issues)
                result = self.router.complete_text(task_name + "-retry", retry_messages, self.config.writer)
                markdown = self._normalize_section_markdown(section, result.content)
                retry_issues = self._validate_section_markdown(section, markdown)
                if retry_issues:
                    raise ValueError("Section still invalid after retry: {0}".format("; ".join(retry_issues)))

            # Step 2: Critique the draft
            try:
                from .prompts import build_section_critique_messages, build_section_revise_messages
                critique_messages = build_section_critique_messages(state, section, markdown)
                _, critique_payload = self.router.complete_json(
                    "critique-section-{0}".format(section.section_id),
                    critique_messages,
                    self.config.verifier,
                )
                critique_issues = critique_payload.get("issues", [])
                quality_score = critique_payload.get("overall_quality", 10)
                self.tracker.log(
                    "critique",
                    section.section_id,
                    "Section critique completed",
                    data={"quality_score": quality_score, "issue_count": len(critique_issues)},
                )

                # Step 3: Revise if quality is below threshold
                if quality_score < 8 and critique_issues:
                    revise_messages = build_section_revise_messages(state, section, markdown, critique_payload)
                    revise_result = self.router.complete_text(
                        "revise-section-{0}".format(section.section_id),
                        revise_messages,
                        self.config.writer,
                    )
                    revised = self._normalize_section_markdown(section, revise_result.content)
                    revised_issues = self._validate_section_markdown(section, revised)
                    if not revised_issues:
                        markdown = revised
                        self.tracker.log(
                            "revise",
                            section.section_id,
                            "Section revised after critique",
                            data={"quality_before": quality_score, "critique_issues": len(critique_issues)},
                        )
                    else:
                        self.tracker.log(
                            "revise",
                            section.section_id,
                            "Revised section failed validation, keeping original",
                            level="WARNING",
                            data={"issues": revised_issues},
                        )
            except Exception as critique_exc:
                self.tracker.log(
                    "critique",
                    section.section_id,
                    "Critique/revise cycle failed, keeping initial draft",
                    level="WARNING",
                    data={"error": str(critique_exc)},
                )

            # Save final result
            artifact = self.tracker.write_text(
                "artifacts/report-sections/{0}.md".format(section.section_id),
                markdown,
            )
            self.tracker.log(
                "report-section",
                section.section_id,
                "Section report generated",
                data={"model": result.model, "title": section.title},
                artifacts={"section_report": artifact},
            )
            return markdown
        except Exception as exc:
            self.tracker.log(
                "report-section",
                section.section_id,
                "Section report generation failed, using section draft fallback",
                level="ERROR",
                data={"error": str(exc), "title": section.title},
            )
        markdown = self._normalize_section_markdown(section, section.draft or self._section_draft(section))
        artifact = self.tracker.write_text(
            "artifacts/report-sections/{0}-fallback.md".format(section.section_id),
            markdown,
        )
        self.tracker.log(
            "report-section",
            section.section_id,
            "Section report fallback used",
            level="WARN",
            data={"title": section.title},
            artifacts={"section_report": artifact},
        )
        return markdown

    def _assemble_report(self, state: ResearchState, section_markdowns: List[str]) -> str:
        overview = self._generate_report_overview(state)
        lines = [
            overview.get("title", "") or "# Deep Research Report",
            "",
        ]
        executive_summary = overview.get("executive_summary", [])
        if executive_summary:
            lines.extend(["## Executive Summary", ""])
            lines.extend("- {0}".format(item) for item in executive_summary)
            lines.append("")
        for section_markdown in section_markdowns:
            lines.append(section_markdown.strip())
            lines.append("")
        conclusion = overview.get("conclusion", [])
        if conclusion:
            lines.extend(["## Conclusion", ""])
            lines.extend("- {0}".format(item) for item in conclusion)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _generate_report_overview(self, state: ResearchState) -> Dict[str, List[str]]:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_report_overview_messages(state)
        try:
            model, payload = self.router.complete_json("report-overview", messages, self.config.verifier)
            self.tracker.log(
                "report",
                "writer",
                "Report overview generated",
                data={"model": model},
            )
            return {
                "title": str(payload.get("title", "")).strip() or "# Deep Research Report",
                "executive_summary": _trim_list([str(item) for item in payload.get("executive_summary", [])], 5),
                "conclusion": _trim_list([str(item) for item in payload.get("conclusion", [])], 4),
            }
        except Exception as exc:
            self.tracker.log(
                "report",
                "writer",
                "Report overview generation failed, using deterministic fallback",
                level="ERROR",
                data={"error": str(exc)},
            )
            return self._fallback_report_overview(state)

    def _fallback_report_overview(self, state: ResearchState) -> Dict[str, List[str]]:
        title = "# Deep Research Report"
        if state.question:
            subject = _extract_subject(state.question)
            if subject:
                title = "# {0}深度研究报告".format(subject)
        executive_summary = []
        for section in state.sections[:4]:
            summary = section.thesis or section.summary or section.goal
            if summary:
                executive_summary.append(summary)
        conclusion = []
        if state.sections:
            final_thesis = state.sections[-1].thesis or state.sections[-1].summary
            if final_thesis:
                conclusion.append(final_thesis)
        return {
            "title": title,
            "executive_summary": _trim_list(executive_summary, 5),
            "conclusion": _trim_list(conclusion, 4),
        }

    def _normalize_section_markdown(self, section: SectionState, markdown: str) -> str:
        cleaned = markdown.strip()
        if not cleaned:
            return ""
        heading = "## {0}".format(section.title)
        if not cleaned.startswith(heading):
            cleaned = "{0}\n\n{1}".format(heading, cleaned)
        return cleaned.rstrip() + "\n"

    def _build_section_report_retry_messages(
        self,
        state: ResearchState,
        section: SectionState,
        partial_markdown: str,
        issues: List[str],
    ) -> List[Dict[str, str]]:
        return build_section_report_messages(state, section) + [{
            "role": "user",
            "content": (
                "PREVIOUS_SECTION_ATTEMPT_WAS_INCOMPLETE.\n"
                "Rewrite the entire section from scratch.\n"
                "Make it shorter so it fits comfortably in one response.\n"
                "Use at most 3 subsections and 8 bullets total.\n"
                "End the final line with punctuation or a citation bracket.\n"
                "VALIDATION_ISSUES: {0}\n"
                "PARTIAL_SECTION:\n{1}"
            ).format(
                json.dumps(issues, ensure_ascii=False),
                partial_markdown,
            ),
        }]

    def _validate_section_markdown(self, section: SectionState, markdown: str) -> List[str]:
        issues = []
        cleaned = markdown.strip()
        if not cleaned:
            return ["Section markdown is empty"]
        heading = "## {0}".format(section.title)
        if not cleaned.startswith(heading):
            issues.append("Section heading missing: {0}".format(section.title))
        last_nonempty_line = ""
        for line in reversed(cleaned.splitlines()):
            if line.strip():
                last_nonempty_line = line.strip()
                break
        if not last_nonempty_line:
            issues.append("Section has no non-empty trailing line")
        elif re.search(r"[:：\-—/（(\[]\s*$", last_nonempty_line) or re.fullmatch(r"-?\s*\d{4}", last_nonempty_line):
            issues.append("Section ends with a dangling trailing line: {0}".format(last_nonempty_line))
        elif last_nonempty_line.startswith("- "):
            bullet_text = last_nonempty_line[2:].strip()
            if (
                len(bullet_text) < 12
                or re.fullmatch(r"\d{4}(\D.*)?", bullet_text)
                or (_line_has_unbalanced_tail(last_nonempty_line) and not _line_ends_cleanly(last_nonempty_line))
            ):
                issues.append("Section ends with a dangling trailing line: {0}".format(last_nonempty_line))
        elif not _line_ends_cleanly(last_nonempty_line):
            issues.append("Section does not end cleanly: {0}".format(last_nonempty_line))
        return issues

    def _validate_report_completeness(self, state: ResearchState, report_markdown: str) -> List[str]:
        issues = []
        body = report_markdown.split("\n## Sources Used As Citations", 1)[0].rstrip()
        if not body:
            return ["Report body is empty"]

        heading_lines = [line.strip() for line in body.splitlines() if line.strip().startswith("#")]
        missing_sections = [
            section.title
            for section in state.sections
            if section.title and not any(section.title in heading for heading in heading_lines)
        ]
        if missing_sections:
            issues.append("Missing body sections: {0}".format(", ".join(missing_sections)))

        last_nonempty_line = ""
        for line in reversed(body.splitlines()):
            if line.strip():
                last_nonempty_line = line.strip()
                break
        if not last_nonempty_line:
            issues.append("Report body has no non-empty trailing line")
        elif re.search(r"[:：\-—/（(\[]\s*$", last_nonempty_line) or re.fullmatch(r"-?\s*\d{4}", last_nonempty_line):
            issues.append("Report ends with a dangling trailing line: {0}".format(last_nonempty_line))
        elif last_nonempty_line.startswith("- "):
            bullet_text = last_nonempty_line[2:].strip()
            if (
                len(bullet_text) < 12
                or re.fullmatch(r"\d{4}(\D.*)?", bullet_text)
                or (_line_has_unbalanced_tail(last_nonempty_line) and not _line_ends_cleanly(last_nonempty_line))
            ):
                issues.append("Report ends with a dangling trailing line: {0}".format(last_nonempty_line))
        elif not _line_ends_cleanly(last_nonempty_line):
            issues.append("Report does not end cleanly: {0}".format(last_nonempty_line))

        final_section_title = state.sections[-1].title if state.sections else ""
        if final_section_title:
            final_heading_index = body.find(final_section_title)
            if final_heading_index < 0:
                issues.append("Final required section is missing: {0}".format(final_section_title))
            else:
                tail = body[final_heading_index:]
                if len(tail.strip()) < 60:
                    issues.append("Final required section appears too short: {0}".format(final_section_title))
        return issues

    def _register_source(self, state: ResearchState, query: str, title: str, url: str, snippet: str) -> SourceRecord:
        with self._state_lock:
            for source in state.sources.values():
                if source.url == url:
                    return source
            source_id = "S{0:03d}".format(len(state.sources) + 1)
            source = SourceRecord(
                source_id=source_id,
                query=query,
                title=title,
                url=url,
                snippet=snippet,
                credibility_score=_score_source_credibility(url, title),
            )
            state.sources[source_id] = source
            return source

    def _load_workspace_documents(self, state: ResearchState) -> List[WorkspaceDocument]:
        assert self.tracker is not None
        if self.workspace_documents is not None:
            return self.workspace_documents
        self.workspace_documents = discover_workspace_documents(
            project_root=Path.cwd(),
            configured_paths=self.config.workspace_sources,
            question=state.question,
            max_documents=self.config.max_workspace_documents,
            max_chars_per_document=self.config.max_chars_per_workspace_document,
        )
        if self.workspace_documents:
            catalog_artifact = self.tracker.write_json(
                "state/workspace-documents.json",
                [
                    {
                        "path": str(item.path),
                        "title": item.title,
                        "source_type": item.source_type,
                        "char_count": len(item.text),
                    }
                    for item in self.workspace_documents
                ],
            )
            self.tracker.log(
                "workspace",
                "catalog",
                "Workspace documents discovered",
                data={"count": len(self.workspace_documents)},
                artifacts={"catalog": catalog_artifact},
            )
        return self.workspace_documents

    def _collect_workspace_evidence(self, state: ResearchState, section: SectionState) -> List[Dict[str, str]]:
        assert self.tracker is not None
        documents = self._load_workspace_documents(state)
        if not documents:
            return []
        selected = select_workspace_evidence(
            documents=documents,
            question=state.question,
            section_title=section.title,
            section_queries=section.queries,
            must_cover=section.must_cover,
            max_documents=self.config.max_workspace_sources_per_section,
            max_chars_per_excerpt=self.config.max_chars_per_workspace_excerpt,
        )
        evidence_packets = []
        for item in selected:
            source = self._register_source(
                state,
                "workspace:{0}".format(section.title),
                item.title,
                str(item.path),
                item.snippet,
            )
            if source.fetch_status == "unfetched":
                source.fetch_status = "workspace"
                source.excerpt = item.excerpt
                source.raw_artifact = self.tracker.write_json(
                    "sources/{0}.workspace.json".format(source.source_id),
                    {
                        "path": str(item.path),
                        "title": item.title,
                        "source_type": item.source_type,
                        "score": item.score,
                    },
                )
                source.text_artifact = self.tracker.write_text(
                    "sources/{0}.txt".format(source.source_id),
                    item.excerpt,
                )
            if source.source_id not in section.source_ids:
                section.source_ids.append(source.source_id)
            evidence_packets.append({
                "source_id": source.source_id,
                "title": source.title,
                "url": source.url,
                "excerpt": source.excerpt or source.snippet,
                "source_type": "workspace",
            })
            self.tracker.log(
                "workspace",
                section.section_id,
                "Workspace source selected",
                data={
                    "title": item.title,
                    "path": str(item.path),
                    "score": item.score,
                    "source_type": item.source_type,
                },
                artifacts={"excerpt": source.text_artifact},
            )
        return evidence_packets

    def _record_search_results(
        self,
        state: ResearchState,
        section_id: str,
        raw_query: str,
        executed_query: str,
        hits: List[object],
    ) -> None:
        with self._state_lock:
            existing = {
                (item.section_id, item.raw_query, _normalize_url(item.url)): item
                for item in state.searched_results
            }
            for hit in hits:
                key = (section_id, raw_query, _normalize_url(hit.url))
                if key in existing:
                    record = existing[key]
                    record.executed_query = executed_query
                    record.title = hit.title
                    record.snippet = hit.snippet
                    continue
                state.searched_results.append(SearchResultRecord(
                    section_id=section_id,
                    raw_query=raw_query,
                    executed_query=executed_query,
                    title=hit.title,
                    url=hit.url,
                    snippet=hit.snippet,
                ))

    def _mark_search_result_used(
        self,
        state: ResearchState,
        section_id: str,
        raw_query: str,
        executed_query: str,
        source: SourceRecord,
    ) -> None:
        with self._state_lock:
            normalized_url = _normalize_url(source.url)
            for item in state.searched_results:
                if item.section_id != section_id or item.raw_query != raw_query:
                    continue
                if _normalize_url(item.url) != normalized_url:
                    continue
                item.selected_for_evidence = True
                item.source_id = source.source_id
                item.executed_query = executed_query
                if not item.title:
                    item.title = source.title
                if not item.snippet:
                    item.snippet = source.snippet
            return

    def _append_source_appendices(self, state: ResearchState, report_markdown: str) -> str:
        report_markdown = report_markdown.rstrip()
        cited_source_ids = re.findall(r"\[source:(S\d+)\]", report_markdown)
        if not cited_source_ids:
            for section in state.sections:
                for finding in section.findings:
                    cited_source_ids.extend(finding.source_ids)
        cited_source_ids = _unique(cited_source_ids)
        cited_urls = {
            _normalize_url(state.sources[source_id].url)
            for source_id in cited_source_ids
            if source_id in state.sources
        }

        lines = [report_markdown, "", "## Sources Used As Citations", ""]
        if cited_source_ids:
            for source_id in cited_source_ids:
                source = state.sources.get(source_id)
                if source is None:
                    continue
                lines.append(
                    "- `{0}` [{1}]({2})".format(
                        source_id,
                        source.title or source.url,
                        source.url,
                    )
                )
        else:
            lines.append("- None")

        lines.extend(["", "## Queried But Not Used As Citations", ""])
        unused_records = []
        seen_urls = set()
        for item in state.searched_results:
            normalized_url = _normalize_url(item.url)
            if normalized_url in cited_urls or normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)
            unused_records.append(item)

        if unused_records:
            for item in unused_records:
                title = item.title or item.url
                lines.append(
                    "- [{0}]({1})"
                    " | section=`{2}` | raw_query=`{3}` | executed_query=`{4}`".format(
                        title,
                        item.url,
                        item.section_id,
                        item.raw_query,
                        item.executed_query,
                    )
                )
        else:
            lines.append("- None")
        return "\n".join(lines).rstrip() + "\n"

    def _merge_reasoning_steps(
        self,
        current: List[ReasoningStep],
        incoming: List[Dict[str, object]],
    ) -> List[ReasoningStep]:
        merged: Dict[str, ReasoningStep] = {}
        for item in current:
            key = "{0}|{1}".format(item.observation.strip(), item.inference.strip())
            merged[key] = item
        for item in incoming:
            observation = str(item.get("observation", "")).strip()
            inference = str(item.get("inference", "")).strip()
            implication = str(item.get("implication", "")).strip()
            if not observation or not inference:
                continue
            source_ids = _unique([str(value) for value in item.get("source_ids", []) if str(value).strip()])
            key = "{0}|{1}".format(observation, inference)
            merged[key] = ReasoningStep(
                observation=observation,
                inference=inference,
                implication=implication,
                source_ids=source_ids,
            )
        return list(merged.values())

    def _merge_findings(self, current: List[Finding], incoming: List[Dict[str, object]]) -> List[Finding]:
        merged: Dict[str, Finding] = {item.claim: item for item in current}
        for item in incoming:
            claim = str(item.get("claim", "")).strip()
            if not claim:
                continue
            source_ids = [str(value) for value in item.get("source_ids", []) if str(value).strip()]
            if claim in merged:
                merged[claim].source_ids = _unique(merged[claim].source_ids + source_ids)
            else:
                merged[claim] = Finding(claim=claim, source_ids=_unique(source_ids))
        return list(merged.values())

    def _section_draft(self, section: SectionState) -> str:
        lines = ["## {0}".format(section.title), ""]
        if section.thesis:
            lines.extend(["**Core Judgment**", "", section.thesis, ""])
        if section.summary:
            lines.extend([section.summary, ""])
        elif section.goal:
            lines.extend([section.goal, ""])
        if section.key_drivers:
            lines.extend(["**What Drives It**", ""])
            lines.extend("- {0}".format(item) for item in section.key_drivers)
            lines.append("")
        if section.reasoning_steps:
            lines.extend(["**Reasoning Chain**", ""])
            for step in section.reasoning_steps:
                citations = " ".join("[source:{0}]".format(source_id) for source_id in step.source_ids)
                line = "- Observation: {0} | Inference: {1}".format(step.observation, step.inference)
                if step.implication:
                    line += " | Implication: {0}".format(step.implication)
                if citations:
                    line += " {0}".format(citations)
                lines.append(line)
            lines.append("")
        for finding in section.findings:
            citations = " ".join("[source:{0}]".format(source_id) for source_id in finding.source_ids)
            lines.append("- {0} {1}".format(finding.claim, citations).strip())
        if section.counterpoints:
            lines.append("")
            lines.append("Counterpoints:")
            lines.extend("- {0}".format(item) for item in section.counterpoints)
        if section.open_questions:
            lines.append("")
            lines.append("Open questions: {0}".format("; ".join(section.open_questions)))
        return "\n".join(lines).strip() + "\n"

    def _section_reasoning_note(self, section: SectionState) -> str:
        lines = [
            "# Section Analysis",
            "",
            "Section: {0}".format(section.title),
            "",
        ]
        if section.thesis:
            lines.extend(["## Thesis", "", section.thesis, ""])
        if section.key_drivers:
            lines.extend(["## Key Drivers", ""])
            lines.extend("- {0}".format(item) for item in section.key_drivers)
            lines.append("")
        if section.reasoning_steps:
            lines.extend(["## Reasoning Steps", ""])
            for step in section.reasoning_steps:
                citations = ", ".join(step.source_ids) or "none"
                lines.append("- Observation: {0}".format(step.observation))
                lines.append("  Inference: {0}".format(step.inference))
                if step.implication:
                    lines.append("  Implication: {0}".format(step.implication))
                lines.append("  Sources: {0}".format(citations))
            lines.append("")
        if section.counterpoints:
            lines.extend(["## Counterpoints", ""])
            lines.extend("- {0}".format(item) for item in section.counterpoints)
            lines.append("")
        if section.open_questions:
            lines.extend(["## Open Questions", ""])
            lines.extend("- {0}".format(item) for item in section.open_questions)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _fallback_report(self, state: ResearchState) -> str:
        lines = [
            "# Deep Research Report",
            "",
            "## Objective",
            "",
            state.objective or state.question,
            "",
        ]
        for section in state.sections:
            lines.append(section.draft or self._section_draft(section))
            lines.append("")
        return "\n".join(lines).strip() + "\n"
