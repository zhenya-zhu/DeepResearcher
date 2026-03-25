from typing import Dict, List
import json

from .state import DepthState, SubProblem


def _json_block(value: Dict) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_depth_decomposition_messages(
    question: str,
    max_sub_problems: int,
) -> List[Dict[str, str]]:
    schema = {
        "problem_analysis": "string",
        "reasoning_approach": "string",
        "sub_problems": [
            {
                "id": "string",
                "description": "string",
                "dependencies": ["id of sub_problem this depends on"],
            }
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: depth_decompose\n"
                "You decompose complex problems into logical sub-problems.\n"
                "Each sub-problem should be a self-contained reasoning task that contributes to answering the overall question.\n"
                "Order sub-problems so that foundational ones come first. Use dependencies to express which sub-problems require the conclusions of earlier ones.\n"
                "Avoid circular dependencies. If the problem is simple enough, return a single sub-problem.\n"
                "Return JSON only. No markdown fences. No chain-of-thought."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "MAX_SUB_PROBLEMS: {1}\n"
                "CONSTRAINTS:\n"
                "- Decompose into at most {1} sub-problems.\n"
                "- Each sub-problem should be answerable through reasoning, analysis, or targeted fact-finding.\n"
                "- problem_analysis should explain the overall structure of the problem.\n"
                "- reasoning_approach should describe the high-level strategy for solving it.\n"
                "- Sub-problem ids should be short, descriptive slugs (e.g., 'define-terms', 'analyze-tradeoffs').\n"
                "- Dependencies must reference ids of other sub-problems in the list.\n"
                "JSON_SCHEMA:\n{2}"
            ).format(
                question,
                max_sub_problems,
                _json_block(schema),
            ),
        },
    ]


def build_depth_thinking_messages(
    question: str,
    sub_problem: SubProblem,
    dependency_context: List[Dict[str, str]],
    evidence: List[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    schema = {
        "steps": [
            {
                "step_id": "string",
                "step_type": "reason",
                "content": "string",
                "confidence": 0.0,
            }
        ],
        "conclusion": "string",
        "confidence": 0.0,
        "needs_search": [
            {
                "query": "string",
                "reason": "string",
            }
        ],
        "needs_computation": [
            {
                "code": "Python code that prints results",
                "description": "string",
            }
        ],
    }
    dep_block = ""
    if dependency_context:
        dep_block = "DEPENDENCY_CONCLUSIONS:\n{0}\n".format(
            _json_block({"dependencies": dependency_context})
        )
    evidence_block = ""
    if evidence:
        evidence_block = "EVIDENCE:\n{0}\n".format(
            _json_block({"sources": evidence})
        )
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: depth_think\n"
                "You are a deep reasoning engine. Think step by step about the sub-problem.\n"
                "Build a chain of reasoning steps, each with a clear content description.\n"
                "If you need an external fact to continue reasoning, include it in needs_search.\n"
                "Each reasoning step should advance the argument. Avoid repetition.\n"
                "Assign a confidence score (0.0-1.0) to each step and to the overall conclusion.\n"
                "If you need to verify a numerical calculation, include it in needs_computation. "
                "Sandboxed Python with math/statistics/decimal/fractions available. Always print() results.\n"
                "Return JSON only. No markdown fences."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SUB_PROBLEM_ID: {1}\n"
                "SUB_PROBLEM: {2}\n"
                "{3}"
                "{4}"
                "JSON_SCHEMA:\n{5}"
            ).format(
                question,
                sub_problem.problem_id,
                sub_problem.description,
                dep_block,
                evidence_block,
                _json_block(schema),
            ),
        },
    ]


def build_depth_verification_messages(
    question: str,
    sub_problem: SubProblem,
    thinking_steps: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    schema = {
        "overall_verdict": "pass|fail|uncertain",
        "step_verdicts": [
            {
                "step_id": "string",
                "verdict": "pass|fail|uncertain",
                "issues": ["string"],
            }
        ],
        "critical_issues": ["string"],
        "suggested_revisions": ["string"],
    }
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: depth_verify\n"
                "You are a rigorous verifier. Check the reasoning chain for:\n"
                "- Logical errors or non-sequiturs\n"
                "- Unsupported assumptions\n"
                "- Circular reasoning\n"
                "- Missing steps in the argument\n"
                "- Conclusions that don't follow from the reasoning\n"
                "Be strict but fair. A reasoning chain passes only if every step logically follows and the conclusion is well-supported.\n"
                "Return JSON only. No markdown fences."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SUB_PROBLEM: {1}\n"
                "REASONING_STEPS:\n{2}\n"
                "JSON_SCHEMA:\n{3}"
            ).format(
                question,
                sub_problem.description,
                _json_block({"steps": thinking_steps}),
                _json_block(schema),
            ),
        },
    ]


def build_depth_revision_messages(
    question: str,
    sub_problem: SubProblem,
    original_steps: List[Dict[str, str]],
    verification_feedback: Dict,
    urgency: str = "",
) -> List[Dict[str, str]]:
    schema = {
        "steps": [
            {
                "step_id": "string",
                "step_type": "revise",
                "content": "string",
                "confidence": 0.0,
            }
        ],
        "conclusion": "string",
        "confidence": 0.0,
        "needs_search": [
            {
                "query": "string",
                "reason": "string",
            }
        ],
        "needs_computation": [
            {
                "code": "Python code that prints results",
                "description": "string",
            }
        ],
    }
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: depth_revise\n"
                "You are revising a reasoning chain based on verification feedback.\n"
                "Address each critical issue identified by the verifier.\n"
                "You may:\n"
                "- Fix specific steps that had logical errors\n"
                "- Add missing steps to fill gaps\n"
                "- Propose an entirely different approach if the original was fundamentally flawed\n"
                "- Request additional evidence via needs_search if needed\n"
                "Return JSON only. No markdown fences."
                + ("\n" + urgency if urgency else "")
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SUB_PROBLEM: {1}\n"
                "ORIGINAL_REASONING:\n{2}\n"
                "VERIFICATION_FEEDBACK:\n{3}\n"
                "JSON_SCHEMA:\n{4}"
            ).format(
                question,
                sub_problem.description,
                _json_block({"steps": original_steps}),
                _json_block(verification_feedback),
                _json_block(schema),
            ),
        },
    ]


def build_depth_report_messages(state: DepthState) -> List[Dict[str, str]]:
    sub_problem_packets = []
    for sp in state.sub_problems:
        steps_summary = []
        for step in sp.thinking_steps:
            steps_summary.append({
                "step_id": step.step_id,
                "step_type": step.step_type,
                "content": step.content,
                "confidence": step.confidence,
                "verification_result": step.verification_result,
            })
        sub_problem_packets.append({
            "problem_id": sp.problem_id,
            "description": sp.description,
            "status": sp.status,
            "conclusion": sp.conclusion,
            "confidence": sp.confidence,
            "thinking_steps": steps_summary,
            "source_ids": sp.source_ids,
        })
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: depth_report\n"
                "Write a deep analysis report in markdown.\n"
                "This is a depth-first reasoning report, not a survey. Emphasize:\n"
                "- The logical chain of reasoning from problem decomposition to conclusion\n"
                "- How each sub-problem was solved and how solutions connect\n"
                "- Where verification confirmed or challenged the reasoning\n"
                "- Failed approaches and why they were rejected\n"
                "Add inline citations in the form [source:S001] where evidence was used.\n"
                "CITATION RULES:\n"
                "- Only cite source IDs that appear in the sub-problems' source_ids lists.\n"
                "- If a claim is derived from reasoning rather than external sources, do NOT add a citation.\n"
                "- NEVER fabricate source IDs. It is better to have no citations than fake ones.\n"
                "Structure: Problem Analysis → Sub-Problem Solutions → Synthesis → Conclusion.\n"
                "Include a section on 'Approaches Considered and Rejected' if any sub-problems failed.\n"
                "Do not write first-person narration. Be analytical and precise."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "PROBLEM_ANALYSIS: {1}\n"
                "VERIFICATION_SUMMARY: {2}\n"
                "FAILED_PATHS: {3}\n"
                "SUB_PROBLEMS:\n{4}"
            ).format(
                state.question,
                state.problem_analysis,
                state.verification_summary,
                json.dumps(state.failed_paths, ensure_ascii=False),
                _json_block({"sub_problems": sub_problem_packets}),
            ),
        },
    ]


def build_depth_section_report_messages(
    state: DepthState,
    sub_problem: SubProblem,
) -> List[Dict[str, str]]:
    steps_summary = []
    for step in sub_problem.thinking_steps:
        steps_summary.append({
            "step_id": step.step_id,
            "step_type": step.step_type,
            "content": step.content,
            "confidence": step.confidence,
            "verification_result": step.verification_result,
        })

    # Build available sources list for this sub-problem
    available_sources = []
    for sid in sub_problem.source_ids:
        src = state.sources.get(sid)
        if src and src.excerpt:
            available_sources.append({
                "source_id": sid,
                "title": src.title,
                "url": src.url,
            })

    source_instruction = ""
    if available_sources:
        source_instruction = (
            "AVAILABLE_SOURCES for citation (only cite these if the source content actually supports your claim):\n"
            "{0}\n".format(_json_block(available_sources))
        )
    else:
        source_instruction = (
            "No external sources were found for this sub-problem. "
            "Do NOT fabricate citations. If all reasoning is from domain knowledge, "
            "do not add [source:...] markers.\n"
        )

    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: depth_section_report\n"
                "Write exactly one markdown section for the deep analysis report.\n"
                "Focus on the reasoning chain: how this sub-problem was approached, what was concluded, and why.\n"
                "CITATION RULES:\n"
                "- Only add [source:SXXX] citations for claims directly supported by the listed AVAILABLE_SOURCES.\n"
                "- If a factual claim comes from your domain knowledge and not from an available source, do NOT add a citation.\n"
                "- NEVER fabricate or invent source IDs. Only use source IDs from AVAILABLE_SOURCES.\n"
                "- It is perfectly acceptable to write paragraphs with no citations if no sources support them.\n"
                "Start with a ## heading. Write 3-6 analytical paragraphs.\n"
                "If the sub-problem failed, explain what was attempted and why it didn't work.\n"
                "Do not write executive summary, conclusion, or source lists."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SUB_PROBLEM_ID: {1}\n"
                "SUB_PROBLEM: {2}\n"
                "STATUS: {3}\n"
                "CONCLUSION: {4}\n"
                "CONFIDENCE: {5}\n"
                "{6}"
                "THINKING_STEPS:\n{7}"
            ).format(
                state.question,
                sub_problem.problem_id,
                sub_problem.description,
                sub_problem.status,
                sub_problem.conclusion,
                sub_problem.confidence,
                source_instruction,
                _json_block({"steps": steps_summary}),
            ),
        },
    ]


def build_depth_audit_messages(state: DepthState) -> List[Dict[str, str]]:
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
    sub_problem_titles = [
        "{0}: {1}".format(sp.problem_id, sp.description[:80])
        for sp in state.sub_problems
    ]
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: audit\n"
                "Audit the deep analysis report for logical errors, unsupported conclusions, and completeness.\n"
                "Check that the reasoning chain is coherent and that all sub-problems are addressed.\n"
                "Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SUB_PROBLEMS: {1}\n"
                "REPORT_MARKDOWN:\n{2}\n"
                "JSON_SCHEMA:\n{3}"
            ).format(
                state.question,
                json.dumps(sub_problem_titles, ensure_ascii=False),
                state.report_markdown,
                _json_block(schema),
            ),
        },
    ]


def build_depth_adversarial_verification_messages(
    question: str,
    sub_problem: SubProblem,
) -> List[Dict[str, str]]:
    schema = {
        "independent_reasoning": "string",
        "agrees_with_conclusion": True,
        "disagreement_reason": "string (empty if agrees)",
        "confidence": 0.0,
    }
    return [
        {
            "role": "system",
            "content": (
                "TASK_KIND: depth_adversarial_verify\n"
                "You are an independent verifier. You receive ONLY a conclusion (not the reasoning chain).\n"
                "Independently derive whether the conclusion is correct for the given sub-problem.\n"
                "Do NOT assume the original reasoning was correct. Work from first principles.\n"
                "If you disagree, explain specifically why in disagreement_reason.\n"
                "Return JSON only. No markdown fences."
            ),
        },
        {
            "role": "user",
            "content": (
                "QUESTION: {0}\n"
                "SUB_PROBLEM: {1}\n"
                "CONCLUSION_TO_VERIFY: {2}\n"
                "JSON_SCHEMA:\n{3}"
            ).format(
                question,
                sub_problem.description,
                sub_problem.conclusion,
                _json_block(schema),
            ),
        },
    ]
