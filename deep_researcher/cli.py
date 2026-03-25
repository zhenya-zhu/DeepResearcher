from pathlib import Path
from copy import deepcopy
from dataclasses import dataclass
import datetime as dt
from typing import List, Optional
import argparse
import json
import re
import sys

from .config import AppConfig
from .state import ResearchState
from .workflow import DeepResearcher


@dataclass
class QueryEntry:
    query: str
    reference_plan: str = ""


def _parse_models(raw: Optional[str]) -> Optional[list]:
    if not raw:
        return None
    values = [item.strip() for item in raw.split(",")]
    values = [item for item in values if item]
    return values or None


def load_numbered_queries(text: str) -> List[str]:
    items = []
    current = []
    pattern = re.compile(r"^\s*(\d+)\.\s+(.*\S.*?)\s*$")
    for raw_line in text.splitlines():
        match = pattern.match(raw_line)
        if match:
            if current:
                items.append("\n".join(current).strip())
            current = [match.group(2).strip()]
            continue
        if current:
            stripped = raw_line.strip()
            if stripped:
                current.append(stripped)
    if current:
        items.append("\n".join(current).strip())
    return [item for item in items if item]


def _decode_relaxed_json_string(raw: str) -> str:
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")
    return json.loads('"{0}"'.format(normalized))


def _load_relaxed_json_query_entries(text: str) -> List[QueryEntry]:
    object_pattern = re.compile(r"\{(.*?)\}", re.S)
    field_pattern = re.compile(r'"(?P<key>query|plan)"\s*:\s*"(?P<value>(?:\\.|[^"\\])*)"', re.S)
    entries = []
    for match in object_pattern.finditer(text):
        fields = {}
        for field_match in field_pattern.finditer(match.group(1)):
            fields[field_match.group("key")] = _decode_relaxed_json_string(field_match.group("value")).strip()
        query = fields.get("query", "")
        if query:
            entries.append(QueryEntry(
                query=query,
                reference_plan=fields.get("plan", ""),
            ))
    return entries


def load_query_entries(text: str) -> List[QueryEntry]:
    stripped = text.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            entries = _load_relaxed_json_query_entries(stripped)
            if entries:
                return entries
            raise
        if not isinstance(payload, list):
            raise ValueError("question file JSON must be a list")
        entries = []
        for item in payload:
            if isinstance(item, str):
                query = item.strip()
                if query:
                    entries.append(QueryEntry(query=query))
                continue
            if isinstance(item, dict) and isinstance(item.get("query"), str):
                query = item["query"].strip()
                if query:
                    entries.append(QueryEntry(
                        query=query,
                        reference_plan=str(item.get("plan", "")).strip(),
                    ))
                continue
            raise ValueError("question file JSON list items must be strings or objects with a query field")
        return entries
    numbered_queries = load_numbered_queries(stripped)
    if numbered_queries:
        return [QueryEntry(query=item) for item in numbered_queries]
    return [QueryEntry(query=stripped)]


def _load_question(args: argparse.Namespace) -> Optional[str]:
    if args.question:
        return args.question
    if args.question_file:
        text = Path(args.question_file).read_text(encoding="utf-8").strip()
        entries = load_query_entries(text)
        if args.query_index is not None:
            if not entries:
                raise ValueError("No queries found in question file")
            index = args.query_index - 1
            if index < 0 or index >= len(entries):
                raise ValueError("query_index out of range: {0}".format(args.query_index))
            return entries[index].query
        if len(entries) > 1:
            raise ValueError("question file contains multiple queries; use --query-index")
        return entries[0].query if entries else text
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a debuggable deep research workflow.")
    parser.add_argument("question", nargs="?", help="Research question to investigate.")
    parser.add_argument("--question-file", help="Load the research question from a file.")
    parser.add_argument("--query-index", type=int, help="1-based query index when --question-file contains a numbered query list.")
    parser.add_argument("--list-queries", action="store_true", help="List numbered queries from --question-file and exit.")
    parser.add_argument("--resume", help="Resume from a checkpoint JSON file.")
    parser.add_argument("--mode", choices=["breadth", "depth"], help="Research mode: breadth (survey) or depth (deep reasoning).")
    parser.add_argument("--mock", action="store_true", help="Use mock LLM and mock tools.")
    parser.add_argument("--mock-llm", action="store_true", help="Use mock LLM only.")
    parser.add_argument("--mock-tools", action="store_true", help="Use mock search and fetch tools only.")
    parser.add_argument("--plan-only", action="store_true", help="Stop after planning and write plan artifacts.")
    parser.add_argument("--semantic-mode", choices=["hybrid", "native"], help="Choose how evidence semantics are resolved at runtime.")
    parser.add_argument("--compare-semantic-modes", action="store_true", help="Run both hybrid and native semantic modes and write a comparison artifact.")
    parser.add_argument("--run-root", help="Override the output root directory.")
    parser.add_argument("--max-rounds", type=int, help="Override the max research rounds.")
    parser.add_argument("--workspace-source", action="append", help="Add a local file or directory as a first-party workspace source.")
    parser.add_argument("--planner-models", help="Comma-separated planner model candidates.")
    parser.add_argument("--researcher-models", help="Comma-separated researcher model candidates.")
    parser.add_argument("--writer-models", help="Comma-separated writer model candidates.")
    parser.add_argument("--verifier-models", help="Comma-separated verifier model candidates.")
    parser.add_argument("--fast-models", help="Comma-separated fast utility model candidates.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output on stderr.")
    return parser


def _render_semantic_comparison(results: List[dict], question: str, plan_only: bool) -> str:
    lines = [
        "# Semantic Mode Comparison",
        "",
        "Question: {0}".format(question),
        "",
        "Mode comparison: `hybrid` vs `native`",
        "",
        "## Overview",
        "",
    ]
    for result in results:
        state = result["state"]
        lines.append("### {0}".format(result["mode"]))
        lines.append("")
        lines.append("- run_id: `{0}`".format(state.run_id))
        lines.append("- run_dir: `{0}`".format(result["run_dir"]))
        lines.append("- section_count: `{0}`".format(len(state.sections)))
        lines.append("- source_count: `{0}`".format(len(state.sources)))
        if plan_only:
            lines.append("- status: `{0}`".format(state.status))
        else:
            lines.append("- report_chars: `{0}`".format(len(state.report_markdown)))
            lines.append("- audit_issue_count: `{0}`".format(len(state.audit_issues)))
        lines.append("")
    lines.append("## Section Comparison")
    lines.append("")
    section_count = max((len(item["state"].sections) for item in results), default=0)
    for index in range(section_count):
        lines.append("### Section {0}".format(index + 1))
        lines.append("")
        for result in results:
            state = result["state"]
            if index >= len(state.sections):
                continue
            section = state.sections[index]
            lines.append("#### {0}: {1}".format(result["mode"], section.title))
            lines.append("")
            lines.append("- goal: {0}".format(section.goal))
            lines.append("- resolved_profiles: `{0}`".format(", ".join(section.resolved_profiles) or "none"))
            lines.append("- resolved_source_packs: `{0}`".format(", ".join(section.resolved_source_packs) or "none"))
            lines.append("- queries:")
            for query in section.queries[:6]:
                lines.append("  - `{0}`".format(query))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _comparison_payload(results: List[dict], question: str, plan_only: bool) -> dict:
    payload = {
        "question": question,
        "plan_only": plan_only,
        "results": [],
    }
    for result in results:
        state = result["state"]
        payload["results"].append({
            "mode": result["mode"],
            "run_id": state.run_id,
            "run_dir": result["run_dir"],
            "status": state.status,
            "source_count": len(state.sources),
            "audit_issue_count": len(state.audit_issues),
            "report_chars": len(state.report_markdown),
            "sections": [
                {
                    "section_id": section.section_id,
                    "title": section.title,
                    "goal": section.goal,
                    "queries": section.queries,
                    "resolved_profiles": section.resolved_profiles,
                    "resolved_source_packs": section.resolved_source_packs,
                }
                for section in state.sections
            ],
        })
    return payload


def _run_semantic_comparison(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    config: AppConfig,
    question: Optional[str],
) -> int:
    if args.resume:
        parser.error("--compare-semantic-modes does not support --resume")
    if not question:
        parser.error("question or --question-file is required for semantic comparison")
    base_root = config.run_root
    compare_root = base_root / "semantic-compare-{0}".format(dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f"))
    results = []
    for mode in ["hybrid", "native"]:
        mode_config = deepcopy(config)
        mode_config.semantic_mode = mode
        mode_config.run_root = compare_root / mode
        runner = DeepResearcher(mode_config)
        state = runner.plan(question=question) if args.plan_only else runner.run(question=question)
        results.append({
            "mode": mode,
            "state": state,
            "run_dir": runner.run_dir or "",
        })
    compare_root.mkdir(parents=True, exist_ok=True)
    comparison_md = compare_root / "comparison.md"
    comparison_json = compare_root / "comparison.json"
    comparison_md.write_text(_render_semantic_comparison(results, question, args.plan_only), encoding="utf-8")
    comparison_json.write_text(json.dumps(_comparison_payload(results, question, args.plan_only), ensure_ascii=False, indent=2), encoding="utf-8")
    print("Comparison directory: {0}".format(compare_root))
    print("Comparison report: {0}".format(comparison_md))
    print("Comparison JSON: {0}".format(comparison_json))
    for result in results:
        print("- {0}: {1}".format(result["mode"], result["run_dir"]))
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = AppConfig.from_env()
    if args.run_root:
        config.run_root = Path(args.run_root)
    if args.max_rounds:
        config.max_rounds = args.max_rounds
    if args.workspace_source:
        config.workspace_sources = [Path(item) for item in args.workspace_source]
    if args.mock:
        config.use_mock_llm = True
        config.use_mock_tools = True
    if args.mock_llm:
        config.use_mock_llm = True
    if args.mock_tools:
        config.use_mock_tools = True
    if args.quiet:
        config.verbose = False
    if args.semantic_mode:
        config.semantic_mode = args.semantic_mode
    if args.mode:
        config.mode = args.mode
    planner_models = _parse_models(args.planner_models)
    researcher_models = _parse_models(args.researcher_models)
    writer_models = _parse_models(args.writer_models)
    verifier_models = _parse_models(args.verifier_models)
    fast_models = _parse_models(args.fast_models)
    if planner_models:
        config.planner.candidates = planner_models
    if researcher_models:
        config.researcher.candidates = researcher_models
    if writer_models:
        config.writer.candidates = writer_models
    if verifier_models:
        config.verifier.candidates = verifier_models
    if fast_models:
        config.fast.candidates = fast_models

    if args.list_queries:
        if not args.question_file:
            parser.error("--list-queries requires --question-file")
        entries = load_query_entries(Path(args.question_file).read_text(encoding="utf-8"))
        if not entries:
            parser.error("No queries found in question file")
        for index, entry in enumerate(entries, start=1):
            preview = entry.query.replace("\n", " ")
            suffix = " [has-reference-plan]" if entry.reference_plan else ""
            print("{0}. {1}{2}".format(index, preview, suffix))
        return 0

    try:
        question = _load_question(args)
    except ValueError as exc:
        parser.error(str(exc))
    state = None
    if args.resume:
        state = ResearchState.load(args.resume)
        if question and question != state.question:
            parser.error("--resume cannot be combined with a different question")
    elif not question:
        parser.error("question or --question-file is required unless --resume is used")

    if args.compare_semantic_modes:
        return _run_semantic_comparison(parser, args, config, question)

    if config.mode == "depth":
        from .depth_workflow import DeepThinker
        runner = DeepThinker(config)
    else:
        runner = DeepResearcher(config)
    final_state = runner.plan(question=question, state=state) if args.plan_only else runner.run(question=question, state=state)
    run_dir = runner.run_dir or ""
    print("Run ID: {0}".format(final_state.run_id))
    print("Run directory: {0}".format(run_dir))
    if args.plan_only:
        print("Plan: {0}".format(Path(run_dir) / "plan.md"))
        print("Plan JSON: {0}".format(Path(run_dir) / "plan.json"))
    else:
        print("Report: {0}".format(Path(run_dir) / "report.md"))
    print("Trace: {0}".format(Path(run_dir) / "trace.html"))
    if not args.plan_only and final_state.audit_issues:
        print("Audit issues: {0}".format(len(final_state.audit_issues)))
        for issue in final_state.audit_issues:
            print("- [{0}] {1}: {2}".format(issue.severity, issue.section_title, issue.reason))
    return 0


if __name__ == "__main__":
    sys.exit(main())
