from typing import Dict, List
import json

from .state import ResearchState, SectionState


def _json_block(value: Dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_planning_messages(question: str, max_sections: int) -> List[Dict[str, str]]:
    schema = {
        "objective": "string",
        "research_brief": "string",
        "success_criteria": ["string"],
        "risks": ["string"],
        "sections": [
            {
                "id": "string",
                "title": "string",
                "goal": "string",
                "queries": ["string"],
            }
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: planner\n"
                "You design a deep research plan.\n"
                "Return JSON only. No markdown fences. No chain-of-thought."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "MAX_SECTIONS: {1}\n"
                "CONSTRAINTS:\n"
                "- Long-running agent is allowed.\n"
                "- Keep section boundaries clean for context control.\n"
                "- Prefer search queries that can be executed on public web.\n"
                "JSON_SCHEMA:\n{2}"
            ).format(question, max_sections, _json_block(schema)),
        },
    ]


def build_section_research_messages(
    question: str,
    section: SectionState,
    round_index: int,
    evidence_packets: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    schema = {
        "summary": "string",
        "findings": [{"claim": "string", "source_ids": ["S001"]}],
        "open_questions": ["string"],
        "follow_up_queries": ["string"],
        "confidence": "low|medium|high",
        "status": "draft_ready|continue_research|blocked",
    }
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: section_research\n"
                "You are a research analyst for one report section.\n"
                "Use only the provided evidence. Every finding must cite source_ids from the evidence packets.\n"
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SECTION_ID: {1}\n"
                "SECTION_TITLE: {2}\n"
                "SECTION_GOAL: {3}\n"
                "ROUND: {4}\n"
                "KNOWN_QUERIES: {5}\n"
                "EXISTING_FINDINGS: {6}\n"
                "EVIDENCE_PACKETS:\n{7}\n"
                "JSON_SCHEMA:\n{8}"
            ).format(
                question,
                section.section_id,
                section.title,
                section.goal,
                round_index,
                json.dumps(section.queries, ensure_ascii=False),
                json.dumps([finding.claim for finding in section.findings], ensure_ascii=False),
                _json_block({"sources": evidence_packets}),
                _json_block(schema),
            ),
        },
    ]


def build_gap_review_messages(state: ResearchState) -> List[Dict[str, str]]:
    schema = {
        "continue_research": True,
        "global_gaps": ["string"],
        "focus_sections": [
            {"section_id": "string", "reason": "string", "follow_up_queries": ["string"]}
        ],
    }
    sections = []
    for section in state.sections:
        sections.append({
            "section_id": section.section_id,
            "title": section.title,
            "status": section.status,
            "findings": [finding.claim for finding in section.findings],
            "open_questions": section.open_questions,
        })
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: gap_review\n"
                "You are the supervisor deciding whether another research round is needed.\n"
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "CURRENT_ROUND: {1}\n"
                "SECTIONS:\n{2}\n"
                "JSON_SCHEMA:\n{3}"
            ).format(
                state.question,
                state.current_round,
                _json_block({"sections": sections}),
                _json_block(schema),
            ),
        },
    ]


def build_report_messages(state: ResearchState) -> List[Dict[str, str]]:
    section_packets = []
    for section in state.sections:
        section_packets.append({
            "title": section.title,
            "goal": section.goal,
            "summary": section.summary,
            "findings": [
                {"claim": finding.claim, "source_ids": finding.source_ids}
                for finding in section.findings
            ],
        })
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: report_writer\n"
                "Write a concise but decision-useful deep research report in markdown.\n"
                "Only use facts present in the section packets.\n"
                "Add inline citations in the form [source:S001]."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "OBJECTIVE: {1}\n"
                "SUCCESS_CRITERIA: {2}\n"
                "SECTION_PACKETS:\n{3}"
            ).format(
                state.question,
                state.objective,
                json.dumps(state.success_criteria, ensure_ascii=False),
                _json_block({"sections": section_packets}),
            ),
        },
    ]


def build_audit_messages(state: ResearchState) -> List[Dict[str, str]]:
    schema = {
        "status": "pass|needs_revision",
        "issues": [
            {
                "severity": "high|medium|low",
                "section_title": "string",
                "reason": "string",
                "suggested_fix": "string",
            }
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: audit\n"
                "Audit the final report for unsupported claims, weak citations, and missing sections.\n"
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SUCCESS_CRITERIA: {1}\n"
                "REPORT_MARKDOWN:\n{2}\n"
                "JSON_SCHEMA:\n{3}"
            ).format(
                state.question,
                json.dumps(state.success_criteria, ensure_ascii=False),
                state.report_markdown,
                _json_block(schema),
            ),
        },
    ]
