from pathlib import Path
from typing import List, Optional
import argparse
import re
import sys

from .config import AppConfig
from .state import ResearchState
from .workflow import DeepResearcher


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


def _load_question(args: argparse.Namespace) -> Optional[str]:
    if args.question:
        return args.question
    if args.question_file:
        text = Path(args.question_file).read_text(encoding="utf-8").strip()
        queries = load_numbered_queries(text)
        if args.query_index is not None:
            if not queries:
                raise ValueError("No numbered queries found in question file")
            index = args.query_index - 1
            if index < 0 or index >= len(queries):
                raise ValueError("query_index out of range: {0}".format(args.query_index))
            return queries[index]
        if len(queries) > 1:
            raise ValueError("question file contains multiple numbered queries; use --query-index")
        return text
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a debuggable deep research workflow.")
    parser.add_argument("question", nargs="?", help="Research question to investigate.")
    parser.add_argument("--question-file", help="Load the research question from a file.")
    parser.add_argument("--query-index", type=int, help="1-based query index when --question-file contains a numbered query list.")
    parser.add_argument("--list-queries", action="store_true", help="List numbered queries from --question-file and exit.")
    parser.add_argument("--resume", help="Resume from a checkpoint JSON file.")
    parser.add_argument("--mock", action="store_true", help="Use mock LLM and mock tools.")
    parser.add_argument("--mock-llm", action="store_true", help="Use mock LLM only.")
    parser.add_argument("--mock-tools", action="store_true", help="Use mock search and fetch tools only.")
    parser.add_argument("--plan-only", action="store_true", help="Stop after planning and write plan artifacts.")
    parser.add_argument("--run-root", help="Override the output root directory.")
    parser.add_argument("--max-rounds", type=int, help="Override the max research rounds.")
    parser.add_argument("--planner-models", help="Comma-separated planner model candidates.")
    parser.add_argument("--researcher-models", help="Comma-separated researcher model candidates.")
    parser.add_argument("--writer-models", help="Comma-separated writer model candidates.")
    parser.add_argument("--verifier-models", help="Comma-separated verifier model candidates.")
    parser.add_argument("--fast-models", help="Comma-separated fast utility model candidates.")
    return parser


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = AppConfig.from_env()
    if args.run_root:
        config.run_root = Path(args.run_root)
    if args.max_rounds:
        config.max_rounds = args.max_rounds
    if args.mock:
        config.use_mock_llm = True
        config.use_mock_tools = True
    if args.mock_llm:
        config.use_mock_llm = True
    if args.mock_tools:
        config.use_mock_tools = True
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
        queries = load_numbered_queries(Path(args.question_file).read_text(encoding="utf-8"))
        if not queries:
            parser.error("No numbered queries found in question file")
        for index, query in enumerate(queries, start=1):
            preview = query.replace("\n", " ")
            print("{0}. {1}".format(index, preview))
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
