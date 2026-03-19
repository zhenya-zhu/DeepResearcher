from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional
import datetime as dt
import json
import re
from urllib.parse import urlparse

from .config import AppConfig
from .llm import AnthropicCompatibleBackend, MockBackend, ModelRouter, MultiProviderBackend, OpenAICompatibleBackend
from .model_capabilities import load_model_capability_registry
from .prompts import (
    build_audit_messages,
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
from .state import AuditIssue, EvidenceRequirement, Finding, GapTask, ReasoningStep, ResearchState, SearchResultRecord, SectionState, SourceRecord
from .tracing import RunArtifacts
from .workspace_sources import WorkspaceDocument, discover_workspace_documents, select_workspace_evidence


def _run_id() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")


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
    return bool(re.search(r"([。！？.!?；;]|[)\]）】》」』\"”'’`])$", stripped))


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
        ("（", "）"),
        ("[", "]"),
        ("【", "】"),
        ("“", "”"),
        ("‘", "’"),
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


def _clean_query_chunk(chunk: str) -> str:
    if re.fullmatch(r"site:[A-Za-z0-9._/-]+", chunk.strip()):
        return chunk.strip()
    chunk = re.sub(r"[\"'`“”‘’()\[\]{}<>]", " ", chunk)
    chunk = re.sub(r"[:：,，;；|/\\]+", " ", chunk)
    chunk = re.sub(r"\s+", " ", chunk).strip(" .-_")
    return chunk.strip()


def _split_query_chunks(text: str) -> List[str]:
    chunks = []
    for raw in re.split(r"[\s,，、;；|/]+", text):
        chunk = _clean_query_chunk(raw)
        if chunk:
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
    cleaned = re.split(r"[，,。；;：:]", cleaned, maxsplit=1)[0].strip()
    cleaned = re.sub(r"^(一下|一下子)\s*", "", cleaned).strip()
    subject = _clean_query_chunk(cleaned)
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
    for index, chunk in enumerate(raw_chunks):
        if index == 0:
            preferred.append(chunk)
            continue
        if chunk in _GENERIC_QUERY_CHUNKS:
            continue
        if _is_year_chunk(chunk):
            year_chunks.append(chunk)
            continue
        preferred.append(chunk)
    if not preferred:
        preferred = list(raw_chunks[:1])
    selected = preferred[:max_chunks]
    if year_chunks and len(selected) < max_chunks:
        selected.append(year_chunks[-1])
    compact = " ".join(selected).strip()
    while len(compact) > max_chars and len(selected) > 2:
        selected.pop()
        compact = " ".join(selected).strip()
    return compact or " ".join(raw_chunks[:max_chunks]).strip()


def _normalized_queries(question: str, section_title: str, queries: List[str], limit: int) -> List[str]:
    normalized = []
    subject = _extract_subject(question)
    for query in queries:
        compact = _compact_query(query)
        if compact:
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
        self.tracker = RunArtifacts(self.config.run_root, state.run_id)
        self.router = ModelRouter(self.backend, self.rate_limiter, self.tracker, capability_registry=self.capability_registry)
        self.tracker.log("run", "supervisor", "Run started", data={"question": state.question, "semantic_mode": state.semantic_mode})

        if not state.sections:
            self._plan(state)

        next_round = state.current_round + 1
        while not state.report_markdown and next_round <= self.config.max_rounds:
            state.current_round = next_round
            self.tracker.log("research", "supervisor", "Starting research round", data={"round": next_round})
            pending_sections = [section for section in state.sections if section.status != "verified"]
            for section in pending_sections:
                self._research_section(state, section)
            self.tracker.checkpoint("round-{0}".format(next_round), state)
            if not self._review_gaps(state):
                break
            next_round += 1

        if not state.report_markdown:
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
        self.tracker = RunArtifacts(self.config.run_root, state.run_id)
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
        query_budget = min(len(query_queue), self.config.max_queries_per_section + 2)
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
                })
                web_sources_used += 1
                if len(evidence_packets) >= max_total_evidence or web_sources_used >= self.config.max_sources_per_section:
                    break
            if len(evidence_packets) >= max_total_evidence or web_sources_used >= self.config.max_sources_per_section:
                break

        if not evidence_packets:
            section.status = "blocked"
            section.open_questions = _unique(section.open_questions + ["No usable sources found."])
            self.tracker.log("section", section.section_id, "Section blocked due to missing evidence", level="WARN")
            return

        messages = build_section_research_messages(state.question, section, state.current_round, evidence_packets)
        try:
            model, payload = self.router.complete_json(
                "section-{0}-round-{1}".format(section.section_id, state.current_round),
                messages,
                self.config.researcher,
            )
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
                    "global_gap_count": len(state.global_gaps),
                    "task_count": len(tasks),
                    "invalid_profiles": merge_result["invalid_profiles"],
                    "invalid_source_packs": merge_result["invalid_source_packs"],
                },
                artifacts={"gap_tasks": tasks_artifact},
            )
            continue_research = bool(payload.get("continue_research", False))
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
        selection = replace(
            self.config.writer,
            max_output_tokens=min(self.config.writer.max_output_tokens, 4200),
        )
        for attempt in range(1, 3):
            try:
                task_name = "report-section-{0}".format(section.section_id)
                if attempt > 1:
                    task_name += "-retry-{0}".format(attempt)
                result = self.router.complete_text(task_name, messages, selection)
                markdown = self._normalize_section_markdown(section, result.content)
                issues = self._validate_section_markdown(section, markdown)
                if issues:
                    incomplete_artifact = self.tracker.write_text(
                        "artifacts/report-failures/{0}-attempt-{1}.md".format(section.section_id, attempt),
                        markdown,
                    )
                    self.tracker.log(
                        "report-section",
                        section.section_id,
                        "Section report failed completeness validation",
                        level="ERROR",
                        data={"attempt": attempt, "title": section.title, "issues": issues},
                        artifacts={"incomplete_report": incomplete_artifact},
                    )
                    if attempt < 2:
                        messages = self._build_section_report_retry_messages(state, section, markdown, issues)
                        continue
                    raise ReportValidationError("Section report invalid: {0}".format("; ".join(issues)))
                artifact = self.tracker.write_text(
                    "artifacts/report-sections/{0}.md".format(section.section_id),
                    markdown,
                )
                self.tracker.log(
                    "report-section",
                    section.section_id,
                    "Section report generated",
                    data={"model": result.model, "attempt": attempt, "title": section.title},
                    artifacts={"section_report": artifact},
                )
                return markdown
            except Exception as exc:
                self.tracker.log(
                    "report-section",
                    section.section_id,
                    "Section report generation failed, using section draft fallback",
                    level="ERROR",
                    data={"attempt": attempt, "error": str(exc), "title": section.title},
                )
                break
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
        if state.global_gaps:
            lines.extend(["## Remaining Gaps", ""])
            lines.extend("- {0}".format(item) for item in state.global_gaps)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _generate_report_overview(self, state: ResearchState) -> Dict[str, List[str]]:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_report_overview_messages(state)
        selection = replace(
            self.config.writer,
            max_output_tokens=min(self.config.writer.max_output_tokens, 1200),
        )
        try:
            model, payload = self.router.complete_json("report-overview", messages, selection)
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
        if state.global_gaps:
            conclusion.append("当前结论仍受若干证据缺口约束，需结合 Remaining Gaps 一并解读。")
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
        if state.global_gaps:
            lines.extend([
                "## Remaining Gaps",
                "",
                *["- {0}".format(item) for item in state.global_gaps],
                "",
            ])
        return "\n".join(lines).strip() + "\n"
