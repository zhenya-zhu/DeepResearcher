from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List
import datetime as dt
import json


def utc_now() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class Finding:
    claim: str
    source_ids: List[str] = field(default_factory=list)


@dataclass
class ReasoningStep:
    observation: str
    inference: str
    implication: str = ""
    source_ids: List[str] = field(default_factory=list)


@dataclass
class EvidenceRequirement:
    profile_id: str
    priority: str = "medium"
    must_cover: List[str] = field(default_factory=list)
    preferred_source_packs: List[str] = field(default_factory=list)
    query_hints: List[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class SectionState:
    section_id: str
    title: str
    goal: str
    queries: List[str] = field(default_factory=list)
    must_cover: List[str] = field(default_factory=list)
    evidence_requirements: List[EvidenceRequirement] = field(default_factory=list)
    resolved_profiles: List[str] = field(default_factory=list)
    resolved_source_packs: List[str] = field(default_factory=list)
    status: str = "pending"
    summary: str = ""
    thesis: str = ""
    key_drivers: List[str] = field(default_factory=list)
    reasoning_steps: List[ReasoningStep] = field(default_factory=list)
    counterpoints: List[str] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    verification_notes: List[str] = field(default_factory=list)
    draft: str = ""
    evidence_sufficiency: float = 0.0


@dataclass
class SourceRecord:
    source_id: str
    query: str
    title: str
    url: str
    snippet: str = ""
    excerpt: str = ""
    fetch_status: str = "unfetched"
    raw_artifact: str = ""
    text_artifact: str = ""
    credibility_score: float = 0.5


@dataclass
class SearchResultRecord:
    section_id: str
    raw_query: str
    executed_query: str
    title: str
    url: str
    snippet: str = ""
    selected_for_evidence: bool = False
    source_id: str = ""


@dataclass
class AuditIssue:
    severity: str
    section_title: str
    reason: str
    suggested_fix: str = ""


@dataclass
class GapTask:
    task_id: str
    section_id: str = ""
    gap: str = ""
    category: str = "other"
    action: str = "search"
    priority: str = "medium"
    rationale: str = ""
    follow_up_queries: List[str] = field(default_factory=list)
    must_cover: List[str] = field(default_factory=list)
    preferred_source_packs: List[str] = field(default_factory=list)
    source_hints: List[str] = field(default_factory=list)
    status: str = "open"


@dataclass
class ThinkingStep:
    step_id: str
    step_type: str  # "decompose" | "reason" | "verify" | "revise" | "search_request" | "computation" | "adversarial_verify"
    content: str
    parent_step_id: str = ""
    confidence: float = 0.0
    verification_result: str = ""  # "pass" | "fail" | "uncertain" | ""
    verification_notes: str = ""
    source_ids: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)


@dataclass
class SubProblem:
    problem_id: str
    description: str
    dependencies: List[str] = field(default_factory=list)
    status: str = "pending"  # pending | thinking | verified | failed | revised
    thinking_steps: List[ThinkingStep] = field(default_factory=list)
    conclusion: str = ""
    confidence: float = 0.0
    search_queries_used: List[str] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    revision_count: int = 0
    max_revisions: int = 3


@dataclass
class DepthState:
    run_id: str
    question: str
    mode: str = "depth"
    created_at: str = field(default_factory=utc_now)
    status: str = "created"
    problem_analysis: str = ""
    sub_problems: List[SubProblem] = field(default_factory=list)
    problem_graph: Dict[str, List[str]] = field(default_factory=dict)
    current_iteration: int = 0
    global_reasoning_chain: List[ThinkingStep] = field(default_factory=list)
    verification_summary: str = ""
    failed_paths: List[str] = field(default_factory=list)
    sources: Dict[str, SourceRecord] = field(default_factory=dict)
    searched_results: List[SearchResultRecord] = field(default_factory=list)
    report_markdown: str = ""
    audit_issues: List[AuditIssue] = field(default_factory=list)
    debug_notes: List[str] = field(default_factory=list)
    computation_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "DepthState":
        sub_problems = []
        for item in raw.get("sub_problems", []):
            thinking_steps = [ThinkingStep(**step) for step in item.get("thinking_steps", [])]
            sub_problems.append(SubProblem(
                problem_id=item["problem_id"],
                description=item["description"],
                dependencies=item.get("dependencies", []),
                status=item.get("status", "pending"),
                thinking_steps=thinking_steps,
                conclusion=item.get("conclusion", ""),
                confidence=item.get("confidence", 0.0),
                search_queries_used=item.get("search_queries_used", []),
                source_ids=item.get("source_ids", []),
                revision_count=item.get("revision_count", 0),
                max_revisions=item.get("max_revisions", 3),
            ))
        sources = {}
        for source_id, item in raw.get("sources", {}).items():
            sources[source_id] = SourceRecord(
                source_id=item["source_id"],
                query=item["query"],
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                excerpt=item.get("excerpt", ""),
                fetch_status=item.get("fetch_status", "unfetched"),
                raw_artifact=item.get("raw_artifact", ""),
                text_artifact=item.get("text_artifact", ""),
                credibility_score=item.get("credibility_score", 0.5),
            )
        searched_results = [SearchResultRecord(**item) for item in raw.get("searched_results", [])]
        audit_issues = [AuditIssue(**item) for item in raw.get("audit_issues", [])]
        global_reasoning_chain = [ThinkingStep(**step) for step in raw.get("global_reasoning_chain", [])]
        return cls(
            run_id=raw["run_id"],
            question=raw["question"],
            mode=raw.get("mode", "depth"),
            created_at=raw.get("created_at", utc_now()),
            status=raw.get("status", "created"),
            problem_analysis=raw.get("problem_analysis", ""),
            sub_problems=sub_problems,
            problem_graph=raw.get("problem_graph", {}),
            current_iteration=raw.get("current_iteration", 0),
            global_reasoning_chain=global_reasoning_chain,
            verification_summary=raw.get("verification_summary", ""),
            failed_paths=raw.get("failed_paths", []),
            sources=sources,
            searched_results=searched_results,
            report_markdown=raw.get("report_markdown", ""),
            audit_issues=audit_issues,
            debug_notes=raw.get("debug_notes", []),
            computation_count=raw.get("computation_count", 0),
        )

    @classmethod
    def load(cls, path: str) -> "DepthState":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))


@dataclass
class ResearchState:
    run_id: str
    question: str
    created_at: str = field(default_factory=utc_now)
    status: str = "created"
    semantic_mode: str = "hybrid"
    objective: str = ""
    research_brief: str = ""
    input_dependencies: List[str] = field(default_factory=list)
    source_requirements: List[str] = field(default_factory=list)
    comparison_axes: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    current_round: int = 0
    sections: List[SectionState] = field(default_factory=list)
    sources: Dict[str, SourceRecord] = field(default_factory=dict)
    searched_results: List[SearchResultRecord] = field(default_factory=list)
    global_gaps: List[str] = field(default_factory=list)
    gap_tasks: List[GapTask] = field(default_factory=list)
    report_markdown: str = ""
    audit_issues: List[AuditIssue] = field(default_factory=list)
    debug_notes: List[str] = field(default_factory=list)
    cross_section_synthesis: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ResearchState":
        sections = []
        for item in raw.get("sections", []):
            findings = [Finding(**finding) for finding in item.get("findings", [])]
            reasoning_steps = [ReasoningStep(**step) for step in item.get("reasoning_steps", [])]
            sections.append(SectionState(
                section_id=item["section_id"],
                title=item["title"],
                goal=item["goal"],
                queries=item.get("queries", []),
                must_cover=item.get("must_cover", []),
                evidence_requirements=[EvidenceRequirement(**req) for req in item.get("evidence_requirements", [])],
                resolved_profiles=item.get("resolved_profiles", []),
                resolved_source_packs=item.get("resolved_source_packs", []),
                status=item.get("status", "pending"),
                summary=item.get("summary", ""),
                thesis=item.get("thesis", ""),
                key_drivers=item.get("key_drivers", []),
                reasoning_steps=reasoning_steps,
                counterpoints=item.get("counterpoints", []),
                findings=findings,
                source_ids=item.get("source_ids", []),
                open_questions=item.get("open_questions", []),
                verification_notes=item.get("verification_notes", []),
                draft=item.get("draft", ""),
                evidence_sufficiency=item.get("evidence_sufficiency", 0.0),
            ))
        sources = {}
        for source_id, item in raw.get("sources", {}).items():
            sources[source_id] = SourceRecord(
                source_id=item["source_id"],
                query=item["query"],
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                excerpt=item.get("excerpt", ""),
                fetch_status=item.get("fetch_status", "unfetched"),
                raw_artifact=item.get("raw_artifact", ""),
                text_artifact=item.get("text_artifact", ""),
                credibility_score=item.get("credibility_score", 0.5),
            )
        searched_results = [SearchResultRecord(**item) for item in raw.get("searched_results", [])]
        audit_issues = [AuditIssue(**item) for item in raw.get("audit_issues", [])]
        gap_tasks = [GapTask(**item) for item in raw.get("gap_tasks", [])]
        return cls(
            run_id=raw["run_id"],
            question=raw["question"],
            created_at=raw.get("created_at", utc_now()),
            status=raw.get("status", "created"),
            semantic_mode=raw.get("semantic_mode", "hybrid"),
            objective=raw.get("objective", ""),
            research_brief=raw.get("research_brief", ""),
            input_dependencies=raw.get("input_dependencies", []),
            source_requirements=raw.get("source_requirements", []),
            comparison_axes=raw.get("comparison_axes", []),
            success_criteria=raw.get("success_criteria", []),
            risks=raw.get("risks", []),
            current_round=raw.get("current_round", 0),
            sections=sections,
            sources=sources,
            searched_results=searched_results,
            global_gaps=raw.get("global_gaps", []),
            gap_tasks=gap_tasks,
            report_markdown=raw.get("report_markdown", ""),
            audit_issues=audit_issues,
            debug_notes=raw.get("debug_notes", []),
            cross_section_synthesis=raw.get("cross_section_synthesis", {}),
        )

    @classmethod
    def load(cls, path: str) -> "ResearchState":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))
