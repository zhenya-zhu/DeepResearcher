from typing import Dict, List, Optional
import datetime as dt
import json

from .config import AppConfig
from .llm import AnthropicCompatibleBackend, MockBackend, ModelRouter, MultiProviderBackend, OpenAICompatibleBackend
from .model_capabilities import load_model_capability_registry
from .prompts import (
    build_audit_messages,
    build_gap_review_messages,
    build_planning_messages,
    build_report_messages,
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
from .state import AuditIssue, Finding, ResearchState, SectionState, SourceRecord
from .tracing import RunArtifacts


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
            searcher = MockSearcher() if config.use_mock_tools else DDGRSearcher(config.proxy_url, config.search_region)
        if fetcher is None:
            fetcher = MockFetcher() if config.use_mock_tools else URLFetcher(config.proxy_url, config.timeout_seconds)
        self.backend = backend
        self.searcher = searcher
        self.fetcher = fetcher
        effective_rpm = 600 if config.use_mock_llm else config.rpm_limit
        self.rate_limiter = IntervalRateLimiter(effective_rpm)
        self.capability_registry = load_model_capability_registry(config.model_capabilities_file)
        self.tracker: Optional[RunArtifacts] = None
        self.router: Optional[ModelRouter] = None

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
        self.tracker = RunArtifacts(self.config.run_root, state.run_id)
        self.router = ModelRouter(self.backend, self.rate_limiter, self.tracker, capability_registry=self.capability_registry)
        self.tracker.log("run", "supervisor", "Run started", data={"question": state.question})

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
        self.tracker = RunArtifacts(self.config.run_root, state.run_id)
        self.router = ModelRouter(self.backend, self.rate_limiter, self.tracker, capability_registry=self.capability_registry)
        self.tracker.log("run", "supervisor", "Plan-only run started", data={"question": state.question, "mode": "plan_only"})
        if not state.sections:
            self._plan(state)
        self.tracker.log("run", "supervisor", "Plan-only run completed", data={"run_dir": str(self.tracker.run_dir), "mode": "plan_only"})
        self.tracker.finalize(state)
        return state

    def _plan(self, state: ResearchState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_planning_messages(state.question, self.config.max_sections)
        try:
            model, payload = self.router.complete_json("planning", messages, self.config.planner)
            self.tracker.log("planning", "planner", "Research plan created", data={"model": model})
            sections = []
            for item in payload.get("sections", [])[:self.config.max_sections]:
                queries = _unique(item.get("queries", [])[:self.config.max_queries_per_section])
                if not queries:
                    queries = [state.question, "{0} {1}".format(state.question, item.get("title", ""))]
                sections.append(SectionState(
                    section_id=item.get("id") or "section-{0}".format(len(sections) + 1),
                    title=item.get("title", "Untitled section"),
                    goal=item.get("goal", ""),
                    queries=queries,
                ))
            state.objective = payload.get("objective", state.question)
            state.research_brief = payload.get("research_brief", "")
            state.success_criteria = payload.get("success_criteria", [])
            state.risks = payload.get("risks", [])
            state.sections = sections or self._fallback_sections(state.question)
        except Exception as exc:
            state.debug_notes.append("Planning fallback used: {0}".format(exc))
            self.tracker.log("planning", "planner", "Planning failed, using fallback", level="ERROR", data={"error": str(exc)})
            state.objective = "Deliver a structured answer for: {0}".format(state.question)
            state.sections = self._fallback_sections(state.question)
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
                queries=["{0} {1}".format(question, title), question],
            ))
        return sections

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
        evidence_packets = []
        for query in section.queries[:self.config.max_queries_per_section]:
            try:
                hits = self.searcher.search(query, self.config.max_results_per_query)
            except Exception as exc:
                self.tracker.log(
                    "search",
                    section.section_id,
                    "Search failed",
                    level="ERROR",
                    data={"query": query, "error": str(exc)},
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
                data={"query": query, "results": len(hits)},
                artifacts={"results": results_artifact},
            )
            for hit in hits[:self.config.max_sources_per_section]:
                source = self._register_source(state, query, hit.title, hit.url, hit.snippet)
                if source.fetch_status == "unfetched":
                    try:
                        page = self.fetcher.fetch(hit.url)
                        source.raw_artifact = self.tracker.write_text(
                            "sources/{0}.raw.html".format(source.source_id), page.raw_html
                        )
                        source.excerpt = extract_relevant_passages(
                            page.text or hit.snippet,
                            query,
                            max_chars=self.config.max_chars_per_source,
                        )
                        source.fetch_status = "fetched"
                        source.text_artifact = self.tracker.write_text(
                            "sources/{0}.txt".format(source.source_id), page.text
                        )
                        if page.title and source.title == hit.title:
                            source.title = page.title
                    except Exception as exc:
                        source.fetch_status = "failed"
                        source.excerpt = hit.snippet
                        self.tracker.log(
                            "fetch",
                            section.section_id,
                            "Fetch failed, falling back to snippet",
                            level="ERROR",
                            data={"source_id": source.source_id, "url": hit.url, "error": str(exc)},
                        )
                if source.source_id not in section.source_ids:
                    section.source_ids.append(source.source_id)
                evidence_packets.append({
                    "source_id": source.source_id,
                    "title": source.title,
                    "url": source.url,
                    "excerpt": source.excerpt or source.snippet,
                })
                if len(evidence_packets) >= self.config.max_sources_per_section:
                    break
            if len(evidence_packets) >= self.config.max_sources_per_section:
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
            self.tracker.log(
                "section",
                section.section_id,
                "Section synthesis completed",
                data={"model": model, "source_count": len(evidence_packets)},
            )
            section.summary = payload.get("summary", section.summary)
            section.findings = self._merge_findings(section.findings, payload.get("findings", []))
            section.open_questions = _unique(payload.get("open_questions", []))
            section.queries = _unique(section.queries + payload.get("follow_up_queries", []))
            status = payload.get("status", "draft_ready")
            section.status = "pending" if status == "continue_research" else status
            section.draft = self._section_draft(section)
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
        messages = build_gap_review_messages(state)
        try:
            model, payload = self.router.complete_json(
                "gap-review-round-{0}".format(state.current_round),
                messages,
                self.config.verifier,
            )
            state.global_gaps = payload.get("global_gaps", [])
            focus_sections = payload.get("focus_sections", [])
            self.tracker.log(
                "review",
                "verifier",
                "Gap review completed",
                data={"model": model, "continue_research": payload.get("continue_research", False)},
            )
            if not payload.get("continue_research", False):
                return False
            by_id = {section.section_id: section for section in state.sections}
            for item in focus_sections:
                section = by_id.get(item.get("section_id", ""))
                if section is None:
                    continue
                section.status = "pending"
                section.open_questions = _unique(section.open_questions + [item.get("reason", "")])
                section.queries = _unique(section.queries + item.get("follow_up_queries", []))
            return True
        except Exception as exc:
            self.tracker.log("review", "verifier", "Gap review failed, stopping rounds", level="ERROR", data={"error": str(exc)})
            return False

    def _write_report(self, state: ResearchState) -> None:
        assert self.router is not None
        assert self.tracker is not None
        messages = build_report_messages(state)
        try:
            result = self.router.complete_text("report-writer", messages, self.config.writer)
            state.report_markdown = result.content.strip()
            self.tracker.log("report", "writer", "Report generated", data={"model": result.model})
        except Exception as exc:
            self.tracker.log("report", "writer", "Report generation failed, using fallback", level="ERROR", data={"error": str(exc)})
            state.report_markdown = self._fallback_report(state)
        self.tracker.write_text("report.md", state.report_markdown)
        self.tracker.checkpoint("report-generated", state)

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
        lines = ["## {0}".format(section.title), "", section.summary or section.goal, ""]
        for finding in section.findings:
            citations = " ".join("[source:{0}]".format(source_id) for source_id in finding.source_ids)
            lines.append("- {0} {1}".format(finding.claim, citations).strip())
        if section.open_questions:
            lines.append("")
            lines.append("Open questions: {0}".format("; ".join(section.open_questions)))
        return "\n".join(lines).strip() + "\n"

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
