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
class SectionState:
    section_id: str
    title: str
    goal: str
    queries: List[str] = field(default_factory=list)
    status: str = "pending"
    summary: str = ""
    findings: List[Finding] = field(default_factory=list)
    source_ids: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    verification_notes: List[str] = field(default_factory=list)
    draft: str = ""


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


@dataclass
class AuditIssue:
    severity: str
    section_title: str
    reason: str
    suggested_fix: str = ""


@dataclass
class ResearchState:
    run_id: str
    question: str
    created_at: str = field(default_factory=utc_now)
    status: str = "created"
    objective: str = ""
    research_brief: str = ""
    success_criteria: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    current_round: int = 0
    sections: List[SectionState] = field(default_factory=list)
    sources: Dict[str, SourceRecord] = field(default_factory=dict)
    global_gaps: List[str] = field(default_factory=list)
    report_markdown: str = ""
    audit_issues: List[AuditIssue] = field(default_factory=list)
    debug_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ResearchState":
        sections = []
        for item in raw.get("sections", []):
            findings = [Finding(**finding) for finding in item.get("findings", [])]
            sections.append(SectionState(
                section_id=item["section_id"],
                title=item["title"],
                goal=item["goal"],
                queries=item.get("queries", []),
                status=item.get("status", "pending"),
                summary=item.get("summary", ""),
                findings=findings,
                source_ids=item.get("source_ids", []),
                open_questions=item.get("open_questions", []),
                verification_notes=item.get("verification_notes", []),
                draft=item.get("draft", ""),
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
            )
        audit_issues = [AuditIssue(**item) for item in raw.get("audit_issues", [])]
        return cls(
            run_id=raw["run_id"],
            question=raw["question"],
            created_at=raw.get("created_at", utc_now()),
            status=raw.get("status", "created"),
            objective=raw.get("objective", ""),
            research_brief=raw.get("research_brief", ""),
            success_criteria=raw.get("success_criteria", []),
            risks=raw.get("risks", []),
            current_round=raw.get("current_round", 0),
            sections=sections,
            sources=sources,
            global_gaps=raw.get("global_gaps", []),
            report_markdown=raw.get("report_markdown", ""),
            audit_issues=audit_issues,
            debug_notes=raw.get("debug_notes", []),
        )

    @classmethod
    def load(cls, path: str) -> "ResearchState":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))
