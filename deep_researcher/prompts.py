from typing import Dict, List
import json

from .state import ResearchState, SectionState


def _json_block(value: Dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_planning_messages(
    question: str,
    max_sections: int,
    available_profiles: List[Dict[str, object]],
    available_source_packs: List[Dict[str, object]],
    semantic_mode: str,
) -> List[Dict[str, str]]:
    schema = {
        "objective": "string",
        "research_brief": "string",
        "input_dependencies": ["string"],
        "source_requirements": ["string"],
        "comparison_axes": ["string"],
        "success_criteria": ["string"],
        "risks": ["string"],
        "sections": [
            {
                "id": "string",
                "title": "string",
                "goal": "string",
                "queries": ["string"],
                "must_cover": ["string"],
                "evidence_requirements": [
                    {
                        "profile_id": "string",
                        "priority": "high|medium|low",
                        "must_cover": ["string"],
                        "preferred_source_packs": ["string"],
                        "query_hints": ["string"],
                        "rationale": "string",
                    }
                ],
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
                "SEMANTIC_MODE: {2}\n"
                "CONSTRAINTS:\n"
                "- Long-running agent is allowed.\n"
                "- Keep section boundaries clean for context control.\n"
                "- Prefer search queries that can be executed on public web.\n"
                "- Keep each search query narrow and retrieval-friendly: usually 3-6 keyword chunks, one intent per query.\n"
                "- If the task depends on user-provided files or private materials, surface that explicitly in input_dependencies.\n"
                "- Use source_requirements to name must-have evidence types, source classes, or documents.\n"
                "- If the task is comparative, list the dimensions in comparison_axes.\n"
                "- Use must_cover to capture concrete analytical checkpoints or subtopics that should not be missed inside each section.\n"
                "- When primary sources exist, explicitly require them in source_requirements; examples include official docs, blogs, papers, code repos, standards, manuals, reports, filings, and investor-relations materials.\n"
                "- Use evidence_requirements to declare what kind of evidence each section needs. Only use profile_id and preferred_source_packs from the provided registries.\n"
                "- Do not only group by vendor or chronology when mechanism-level comparison is important.\n"
                "- Keep the plan concise and execution-oriented. Prefer 3-5 queries per section and 5-8 must_cover bullets per section.\n"
                "- Keep source_requirements, comparison_axes, success_criteria, and risks focused; do not enumerate everything you know.\n"
                "- Keep entity names consistent with the user question. Do not invent alternate company or product names.\n"
                "- The full response must remain a single complete JSON object.\n"
                "- In `hybrid` mode, use evidence_requirements and preferred_source_packs as structured intent; runtime may render additional retrieval queries from the registries.\n"
                "- In `native` mode, your section queries must already encode the retrieval plan directly. If you select a source pack, reflect it inside queries yourself with source names, domains, site operators, or other executable hints; runtime will validate ids but will not expand registry templates except for safety fallback.\n"
                "AVAILABLE_EVIDENCE_PROFILES:\n{3}\n"
                "AVAILABLE_SOURCE_PACKS:\n{4}\n"
                "JSON_SCHEMA:\n{5}"
            ).format(
                question,
                max_sections,
                semantic_mode,
                _json_block({"profiles": available_profiles}),
                _json_block({"source_packs": available_source_packs}),
                _json_block(schema),
            ),
        },
    ]


def build_section_research_messages(
    question: str,
    section: SectionState,
    round_index: int,
    evidence_packets: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    schema = {
        "thesis": "string",
        "key_drivers": ["string"],
        "reasoning_steps": [
            {
                "observation": "string",
                "inference": "string",
                "implication": "string",
                "source_ids": ["S001"],
            }
        ],
        "counterpoints": ["string"],
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
                "Return explicit analyst-facing reasoning, not hidden chain-of-thought.\n"
                "Use reasoning_steps to capture observation -> inference -> implication links that can appear in the final report.\n"
                "Use counterpoints for tensions, alternative explanations, or places where evidence is still thin.\n"
                "Keep the JSON compact and decision-useful.\n"
                "Prefer at most 6 key_drivers, 5 reasoning_steps, 5 counterpoints, 8 open_questions, and 6 follow_up_queries.\n"
                "IMPORTANT: Generate follow_up_queries aggressively. Think about what specific details, comparisons, data points, or mechanism explanations are still missing. Each follow_up_query should target a specific gap that would make the analysis deeper and more authoritative.\n"
                "If evidence is thin, reduce breadth instead of returning a long exhaustive list.\n"
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
                "SECTION_MUST_COVER: {6}\n"
                "EXISTING_THESIS: {7}\n"
                "EXISTING_FINDINGS: {8}\n"
                "EXISTING_KEY_DRIVERS: {9}\n"
                "EXISTING_OPEN_QUESTIONS: {10}\n"
                "EVIDENCE_PACKETS:\n{11}\n"
                "JSON_SCHEMA:\n{12}"
            ).format(
                question,
                section.section_id,
                section.title,
                section.goal,
                round_index,
                json.dumps(section.queries, ensure_ascii=False),
                json.dumps(section.must_cover, ensure_ascii=False),
                json.dumps(section.thesis, ensure_ascii=False),
                json.dumps([finding.claim for finding in section.findings], ensure_ascii=False),
                json.dumps(section.key_drivers, ensure_ascii=False),
                json.dumps(section.open_questions, ensure_ascii=False),
                _json_block({"sources": evidence_packets}),
                _json_block(schema),
            ),
        },
    ]


def build_gap_review_messages(
    state: ResearchState,
    available_profiles: List[Dict[str, object]],
    available_source_packs: List[Dict[str, object]],
    semantic_mode: str,
) -> List[Dict[str, str]]:
    schema = {
        "continue_research": True,
        "global_gaps": ["string"],
        "focus_sections": [
            {"section_id": "string", "reason": "string", "follow_up_queries": ["string"]}
        ],
        "gap_tasks": [
            {
                "task_id": "string",
                "section_id": "string",
                "gap": "string",
                "category": "string (must be a valid evidence profile id)",
                "action": "workspace|search|derive",
                "priority": "high|medium|low",
                "rationale": "string",
                "follow_up_queries": ["string"],
                "must_cover": ["string"],
                "source_hints": ["string"],
                "preferred_source_packs": ["string"],
            }
        ],
    }
    sections = []
    for section in state.sections:
        sections.append({
            "section_id": section.section_id,
            "title": section.title,
            "status": section.status,
            "thesis": section.thesis,
            "key_drivers": section.key_drivers,
            "counterpoints": section.counterpoints,
            "findings": [finding.claim for finding in section.findings],
            "open_questions": section.open_questions,
            "must_cover": section.must_cover,
        })
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: gap_review\n"
                "You are the supervisor deciding whether another research round is needed.\n"
                "Convert missing evidence into explicit remediation tasks whenever possible.\n"
                "Use action=workspace when first-party local files or curated workspace materials should resolve the gap.\n"
                "Use action=derive when the missing point can be computed, decomposed, or bridged from evidence already in hand.\n"
                "Use action=search when targeted external retrieval is still required.\n"
                "Only use category values from the provided evidence profile registry.\n"
                "Only use preferred_source_packs from the provided source pack registry.\n"
                "In native mode, follow_up_queries must already be directly executable and reflect any chosen source pack.\n"
                "In hybrid mode, follow_up_queries can be lighter because runtime may expand selected profiles and packs into more retrieval queries.\n"
                "Prefer concrete, solvable tasks over vague statements.\n"
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "CURRENT_ROUND: {1}\n"
                "SEMANTIC_MODE: {2}\n"
                "OBJECTIVE: {3}\n"
                "SOURCE_REQUIREMENTS: {4}\n"
                "GLOBAL_GAPS: {5}\n"
                "AVAILABLE_EVIDENCE_PROFILES:\n{6}\n"
                "AVAILABLE_SOURCE_PACKS:\n{7}\n"
                "SECTIONS:\n{8}\n"
                "JSON_SCHEMA:\n{9}"
            ).format(
                state.question,
                state.current_round,
                state.semantic_mode,
                state.objective,
                json.dumps(state.source_requirements, ensure_ascii=False),
                json.dumps(state.global_gaps, ensure_ascii=False),
                _json_block({"profiles": available_profiles}),
                _json_block({"source_packs": available_source_packs}),
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
            "thesis": section.thesis,
            "key_drivers": section.key_drivers,
            "reasoning_steps": [
                {
                    "observation": step.observation,
                    "inference": step.inference,
                    "implication": step.implication,
                    "source_ids": step.source_ids,
                }
                for step in section.reasoning_steps
            ],
            "counterpoints": section.counterpoints,
            "open_questions": section.open_questions,
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
                "Add inline citations in the form [source:S001].\n"
                "Write the full report in one response.\n"
                "Do not stop early, do not leave placeholder sections, and do not end mid-sentence or mid-list.\n"
                "Do not only enumerate facts. For each section, turn evidence into explicit analytical judgment.\n"
                "Use an observation -> inference -> implication structure wherever possible.\n"
                "When evidence is incomplete, state the uncertainty or counterpoint directly instead of pretending certainty.\n"
                "Do not write first-person diary-style narration."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "OBJECTIVE: {1}\n"
                "SUCCESS_CRITERIA: {2}\n"
                "REQUIRED_SECTIONS: {3}\n"
                "CONSTRAINTS:\n"
                "- Include a real body section for every required section title, not just a table of contents.\n"
                "- Ensure the report reaches a clear ending before any source appendix is added later by the workflow.\n"
                "- Each section should surface a core judgment, explain why it follows from the evidence, and state what it implies.\n"
                "- Prefer mechanism-level reasoning over flat description.\n"
                "- If a driver is inferred rather than directly observed, make that clear.\n"
                "SECTION_PACKETS:\n{4}"
            ).format(
                state.question,
                state.objective,
                json.dumps(state.success_criteria, ensure_ascii=False),
                json.dumps([section.title for section in state.sections], ensure_ascii=False),
                _json_block({"sections": section_packets}),
            ),
        },
    ]


def build_section_report_messages(state: ResearchState, section: SectionState) -> List[Dict[str, str]]:
    section_packet = {
        "title": section.title,
        "goal": section.goal,
        "summary": section.summary,
        "thesis": section.thesis,
        "key_drivers": section.key_drivers,
        "reasoning_steps": [
            {
                "observation": step.observation,
                "inference": step.inference,
                "implication": step.implication,
                "source_ids": step.source_ids,
            }
            for step in section.reasoning_steps
        ],
        "counterpoints": section.counterpoints,
        "open_questions": section.open_questions,
        "findings": [
            {"claim": finding.claim, "source_ids": finding.source_ids}
            for finding in section.findings
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: report_section_writer\n"
                "Write exactly one markdown section for the final report.\n"
                "Only use facts present in the section packet.\n"
                "Add inline citations in the form [source:S001] after every factual claim.\n"
                "Start with a ## heading, then use ### subheadings to organize the section into 2-4 logical subsections.\n"
                "WRITING QUALITY REQUIREMENTS:\n"
                "- Write 8-15 substantial paragraphs total across all subsections.\n"
                "- Each paragraph MUST be 4-8 sentences with clear topic sentences and deep analytical content. Short 1-2 sentence paragraphs are NOT acceptable.\n"
                "- Go beyond surface description: explain mechanisms, causes, implications, and trade-offs.\n"
                "- Use observation → inference → implication chains to build analytical arguments.\n"
                "- You MUST include at least one comparison table (markdown table with | header | format) per section when comparing systems, approaches, metrics, or features. Tables should have 3+ columns and 3+ rows.\n"
                "- When evidence supports it, include specific numbers, dates, percentages, and concrete examples.\n"
                "- Connect this section's analysis to the broader research question — explain why this matters.\n"
                "- State counterpoints and limitations directly rather than pretending certainty.\n"
                "End every paragraph cleanly with punctuation or a citation bracket.\n"
                "Do not write any executive summary, conclusion, appendix, or sources list."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "OBJECTIVE: {1}\n"
                "SECTION_TITLE: {2}\n"
                "SECTION_PACKET:\n{3}"
            ).format(
                state.question,
                state.objective,
                section.title,
                _json_block(section_packet),
            ),
        },
    ]


def build_report_overview_messages(state: ResearchState) -> List[Dict[str, str]]:
    schema = {
        "title": "string",
        "executive_summary": ["string"],
        "conclusion": ["string"],
    }
    overview_packets = []
    for section in state.sections:
        overview_packets.append({
            "title": section.title,
            "thesis": section.thesis,
            "key_drivers": section.key_drivers,
            "counterpoints": section.counterpoints,
            "open_questions": section.open_questions,
        })
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: report_overview\n"
                "Draft a title, executive summary, and conclusion for the final report.\n"
                "The executive_summary should be 2-3 substantial paragraphs (not just bullets) that synthesize key findings across all sections, highlight the most important insights, and frame the overall narrative.\n"
                "The conclusion should be 2-3 paragraphs that bring together cross-cutting themes, state the overall assessment, and note remaining open questions.\n"
                "Write in a professional analytical tone. Be specific and cite concrete findings from the sections.\n"
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "OBJECTIVE: {1}\n"
                "SECTION_OVERVIEW:\n{2}\n"
                "JSON_SCHEMA:\n{3}"
            ).format(
                state.question,
                state.objective,
                _json_block({"sections": overview_packets}),
                _json_block(schema),
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
                "Audit the final report for unsupported claims, weak citations, missing sections, and truncation.\n"
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SUCCESS_CRITERIA: {1}\n"
                "REQUIRED_SECTIONS: {2}\n"
                "REPORT_MARKDOWN:\n{3}\n"
                "JSON_SCHEMA:\n{4}"
            ).format(
                state.question,
                json.dumps(state.success_criteria, ensure_ascii=False),
                json.dumps([section.title for section in state.sections], ensure_ascii=False),
                state.report_markdown,
                _json_block(schema),
            ),
        },
    ]
