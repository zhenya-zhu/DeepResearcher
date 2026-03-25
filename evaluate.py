#!/usr/bin/env python3
"""
Evaluate a DeepResearcher report against a Gemini reference report.
Uses an LLM judge to score on multiple dimensions + computes structural metrics.

Usage:
    python evaluate.py <report_path> [--reference <gemini_reference_path>]

Output: prints a TSV-friendly score line and detailed breakdown.
"""
import sys
import os
import re
import json
import argparse
from pathlib import Path

# ---------- Structural metrics (no LLM needed) ----------

def structural_metrics(text: str) -> dict:
    lines = text.split("\n")
    char_count = len(text)
    word_count = len(text.split())
    # Count headings: ## for h2, ### for h3 (but not #### etc counted as h3)
    # Some Gemini reports use ##### instead of ## — normalize by counting any heading depth
    h2_count = sum(1 for l in lines if re.match(r'^#{2,5}\s+\d*\.?\s*\S', l) and not l.startswith("### "))
    h3_count = sum(1 for l in lines if l.startswith("### "))
    # Count markdown tables by looking for separator rows (|---|---| or | \------ |)
    table_separator = re.compile(r'^\|[\s\-:|\\]+\|', re.MULTILINE)
    table_count = len(table_separator.findall(text))
    # Count citation references (multiple formats)
    # [source:S001] format (DeepResearcher)
    source_id_pattern = re.compile(r'\[source:S\d+\]')
    source_id_citations = source_id_pattern.findall(text)
    # [1] or [2] bracket format
    bracket_num_pattern = re.compile(r'\[\d{1,2}\]')
    bracket_citations = bracket_num_pattern.findall(text)
    # Bare superscript numbers before Chinese punctuation (Gemini format)
    # Matches both "系统3。" (no space) and "衍生物 1。" (with space)
    bare_ref_pattern = re.compile(r'(?<=[^\d])\s?\d{1,2}(?=[。，；、\n])')
    bare_citations = bare_ref_pattern.findall(text)
    citation_count = len(source_id_citations) + len(bracket_citations) + len(bare_citations)
    # Count unique sources
    source_pattern = re.compile(r'\[source:(S\d+)\]')
    unique_sources_set = set(source_pattern.findall(text))
    # Also count from endnotes section: "1. text" at line start, excluding image refs
    endnote_pattern = re.compile(r'^\d{1,2}\.\s+(?!\[image)', re.MULTILINE)
    endnote_sources = len(endnote_pattern.findall(text))
    unique_sources = max(len(unique_sources_set), endnote_sources)
    # Paragraph analysis: blocks separated by blank lines, longer than 50 chars
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text) if len(p.strip()) > 50]
    avg_para_len = sum(len(p) for p in paragraphs) / max(len(paragraphs), 1)

    return {
        "char_count": char_count,
        "word_count": word_count,
        "h2_sections": h2_count,
        "h3_subsections": h3_count,
        "tables": table_count,
        "citations": citation_count,
        "unique_sources": unique_sources,
        "paragraphs": len(paragraphs),
        "avg_paragraph_chars": int(avg_para_len),
    }


def compute_structural_score(report_metrics: dict, reference_metrics: dict) -> float:
    """Score 0-100 based on how close the report's structural metrics are to the reference."""
    # "more is better" dimensions: exceeding reference gets full credit
    more_is_better = {
        "char_count", "citations", "unique_sources", "tables",
        "h2_sections", "h3_subsections", "paragraphs",
    }
    # "proximity" dimensions: closer to reference is better, slight tolerance band
    dimensions = {
        "char_count": 15,
        "h2_sections": 8,
        "h3_subsections": 8,
        "tables": 10,
        "citations": 15,
        "unique_sources": 20,
        "paragraphs": 8,
        "avg_paragraph_chars": 16,
    }
    total = 0
    for key, weight in dimensions.items():
        ref_val = max(reference_metrics.get(key, 1), 1)
        rep_val = report_metrics.get(key, 0)
        raw_ratio = rep_val / ref_val
        if key in more_is_better:
            # Reaching or exceeding reference = full credit; below = proportional
            ratio = min(raw_ratio, 1.0)
        else:
            # Proximity scoring: 0.7-1.3x range gets full credit, outside is penalized gently
            if 0.7 <= raw_ratio <= 1.3:
                ratio = 1.0
            else:
                ratio = max(0.5, 1.0 - abs(raw_ratio - 1.0) * 0.5)
        total += ratio * weight
    return round(total, 1)


# ---------- LLM-based quality score ----------

JUDGE_PROMPT = """You are evaluating a research report against a reference report produced by Gemini Deep Research.

Score each dimension from 0-10, where 10 = reference quality or better.

## Dimensions

1. **Structure & Organization** (0-10): Does the report have clear hierarchical sections, subsections, logical flow from introduction to conclusion? Compare heading structure and section organization.
2. **Depth & Reasoning** (0-10): Does each section provide deep analysis with mechanism-level explanations, not just surface-level facts? Are there observation→inference→implication chains?
3. **Evidence & Citations** (0-10): Are claims supported by specific data, sources, and citations? Is the evidence diverse and from authoritative sources?
4. **Narrative Coherence** (0-10): Do sections build on each other? Is there a coherent throughline? Or do sections feel like independent summaries?
5. **Tables & Comparisons** (0-10): Does the report use comparison tables, data tables, and structured breakdowns where appropriate?
6. **Paragraph Quality** (0-10): Are paragraphs substantial (3-5 sentences each), well-developed, with clear topic sentences? Or are they thin/bullet-like?
7. **Executive Summary & Conclusion** (0-10): Is there a rich executive summary and conclusion that synthesizes across sections?
8. **Completeness** (0-10): Does the report address all aspects of the question? Are there obvious gaps?
9. **Intellectual Honesty** (0-10): Does confidence match evidence? Are well-sourced claims stated confidently? Are inferences distinguished from direct evidence? Does the report avoid both false confidence (strong claims without citations, speculation presented as fact) AND excessive hedging (epistemic disclaimers, research-process narration)?

## Output Format

Return JSON only:
{
  "structure": <int>,
  "depth": <int>,
  "evidence": <int>,
  "coherence": <int>,
  "tables": <int>,
  "paragraph_quality": <int>,
  "summary_conclusion": <int>,
  "completeness": <int>,
  "honesty": <int>,
  "overall_notes": "<brief explanation of biggest gaps vs reference>"
}
"""


def llm_judge_score(report_text: str, reference_text: str) -> dict:
    """Call the LLM to judge report quality. Returns scores dict or None if unavailable."""
    try:
        import openai
    except ImportError:
        return None

    api_key = os.getenv("DEEP_RESEARCHER_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("DEEP_RESEARCHER_BASE_URL", "http://localhost:6655/litellm/v1")

    if not api_key:
        return None

    client = openai.OpenAI(api_key=api_key, base_url=base_url)

    # Truncate texts to fit context (Opus 4.6 supports 1M tokens)
    max_chars = 120000
    report_trunc = report_text[:max_chars]
    reference_trunc = reference_text[:max_chars]

    try:
        response = client.chat.completions.create(
            model="anthropic--claude-4.6-opus",
            messages=[
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": (
                    f"## REFERENCE REPORT (Gemini Deep Research)\n\n{reference_trunc}\n\n"
                    f"---\n\n## REPORT TO EVALUATE\n\n{report_trunc}"
                )},
            ],
            temperature=0.0,
            max_tokens=1000,
        )
        content = response.choices[0].message.content
        # Extract JSON
        json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        print(f"LLM judge error: {e}", file=sys.stderr)

    return None


def compute_semantic_coverage(report_text: str, reference_text: str) -> float:
    """Keyword-based topic coverage score (0-100). No LLM needed."""
    # Extract key topics from reference by finding repeated meaningful phrases
    ref_words = set(re.findall(r'[\w\u4e00-\u9fff]{2,}', reference_text.lower()))
    rep_words = set(re.findall(r'[\w\u4e00-\u9fff]{2,}', report_text.lower()))
    # Filter to words that appear multiple times in reference (likely topics)
    from collections import Counter
    ref_counter = Counter(re.findall(r'[\w\u4e00-\u9fff]{2,}', reference_text.lower()))
    topic_words = {word for word, count in ref_counter.items() if count >= 3 and len(word) >= 3}
    if not topic_words:
        return 100.0  # no topics to check
    covered = topic_words & rep_words
    return round(len(covered) / len(topic_words) * 100, 1)


def compute_composite_score(structural_score: float, llm_scores: dict, semantic_score: float = None) -> float:
    """Weighted composite score. Returns 0-100."""
    if llm_scores is None:
        # Structural 70% + Semantic 30% when no LLM
        if semantic_score is not None:
            return round(structural_score * 0.7 + semantic_score * 0.3, 1)
        return structural_score  # fallback to structural only

    # LLM dimensions weighted equally, total weight = 60
    # Dynamic denominator: supports both 8-dim (legacy) and 9-dim (with honesty) results
    llm_keys = ["structure", "depth", "evidence", "coherence", "tables",
                 "paragraph_quality", "summary_conclusion", "completeness", "honesty"]
    present_keys = [k for k in llm_keys if k in llm_scores]
    if not present_keys:
        present_keys = llm_keys[:8]  # fallback to 8-dim
    llm_total = sum(llm_scores.get(k, 0) for k in present_keys)
    llm_normalized = (llm_total / (len(present_keys) * 10)) * 60  # 0-60

    # Structural = 25
    structural_normalized = structural_score * 0.25

    # Semantic = 15
    semantic_normalized = (semantic_score or structural_score) * 0.15

    return round(llm_normalized + structural_normalized + semantic_normalized, 1)


def evaluate_single(report_path: str, reference_path: str, use_llm: bool = True) -> dict:
    """Evaluate a single report against a reference. Returns scores dict."""
    report_text = Path(report_path).read_text(encoding="utf-8")
    reference_text = Path(reference_path).read_text(encoding="utf-8")

    rep_metrics = structural_metrics(report_text)
    ref_metrics = structural_metrics(reference_text)
    struct_score = compute_structural_score(rep_metrics, ref_metrics)
    semantic_score = compute_semantic_coverage(report_text, reference_text)

    llm_scores = None
    if use_llm:
        llm_scores = llm_judge_score(report_text, reference_text)

    composite = compute_composite_score(struct_score, llm_scores, semantic_score)
    return {
        "report_path": report_path,
        "reference_path": reference_path,
        "report_metrics": rep_metrics,
        "reference_metrics": ref_metrics,
        "structural_score": struct_score,
        "semantic_score": semantic_score,
        "llm_scores": llm_scores,
        "composite": composite,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate a DeepResearcher report")
    parser.add_argument("report", nargs="?", help="Path to the report to evaluate")
    parser.add_argument("--reference", default=None,
                       help="Path to the Gemini reference report")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM judge, structural only")
    parser.add_argument("--multi-query", default=None,
                       help="Path to queries.json for multi-query evaluation. "
                            "Evaluates each query's latest run against its gemini_report reference.")
    parser.add_argument("--runs-dir", default="runs",
                       help="Directory containing run outputs (default: runs)")
    args = parser.parse_args()

    if args.multi_query:
        # Multi-query evaluation mode
        with open(args.multi_query, "r", encoding="utf-8") as f:
            queries = json.load(f)
        runs_dir = Path(args.runs_dir)
        all_run_dirs = sorted(runs_dir.glob("202*"), reverse=True) if runs_dir.exists() else []

        # Build index: map each run dir to its query (from plan.json)
        def _run_query(run_dir: Path) -> str:
            plan_path = run_dir / "plan.json"
            if plan_path.exists():
                try:
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                    return plan.get("question", "")
                except (json.JSONDecodeError, KeyError):
                    pass
            return ""

        def _query_match(run_q: str, entry_q: str) -> bool:
            """Check if a run's question matches a query entry (prefix match, 60 chars)."""
            return run_q[:60] == entry_q[:60] if run_q and entry_q else False

        scores = []
        for i, query_entry in enumerate(queries):
            ref_path = query_entry.get("gemini_report")
            if not ref_path or not Path(ref_path).exists():
                print(f"\nQuery {i+1}: skipped (no reference report)")
                continue
            # Find the latest run directory matching this query
            report_found = None
            matched_run = None
            for run_dir in all_run_dirs:
                report_path = run_dir / "report.md"
                if not report_path.exists():
                    continue
                run_q = _run_query(run_dir)
                if _query_match(run_q, query_entry["query"]):
                    report_found = str(report_path)
                    matched_run = run_dir.name
                    break
            if not report_found:
                print(f"\nQuery {i+1}: skipped (no matching run found)")
                continue
            print(f"\n{'='*60}")
            print(f"Query {i+1}: {query_entry['query'][:80]}...")
            print(f"  Run: {matched_run}")
            result = evaluate_single(report_found, ref_path, use_llm=not args.no_llm)
            scores.append(result["composite"])
            print(f"  Structural: {result['structural_score']}/100")
            print(f"  Semantic:   {result['semantic_score']}/100")
            print(f"  Composite:  {result['composite']}/100")
            # Show key metric gaps
            rep_m = result["report_metrics"]
            ref_m = result["reference_metrics"]
            gaps = []
            for key in ["unique_sources", "citations", "tables", "h2_sections"]:
                if rep_m.get(key, 0) < ref_m.get(key, 1):
                    gaps.append(f"{key}: {rep_m[key]} vs {ref_m[key]}")
            if gaps:
                print(f"  Gaps: {', '.join(gaps)}")
        if scores:
            avg = round(sum(scores) / len(scores), 1)
            print(f"\n{'='*60}")
            print(f"AGGREGATE SCORE ({len(scores)} queries): {avg}/100")
            print(f"\nMETRIC:{avg}")
        else:
            print("\nNo matching runs found for any query.")
        return

    # Single report evaluation (original mode)
    if not args.report:
        parser.error("report path is required (or use --multi-query)")

    reference = args.reference or "sample_result/Deep Research 技术探索与实现.md"
    result = evaluate_single(args.report, reference, use_llm=not args.no_llm)

    rep_metrics = result["report_metrics"]
    ref_metrics = result["reference_metrics"]

    print("=== Structural Metrics ===")
    print(f"{'Metric':<25} {'Report':>10} {'Reference':>10}")
    for key in rep_metrics:
        print(f"{key:<25} {rep_metrics[key]:>10} {ref_metrics[key]:>10}")
    print(f"\nStructural Score: {result['structural_score']}/100")
    print(f"Semantic Coverage: {result['semantic_score']}/100")

    if result["llm_scores"]:
        print("\n=== LLM Judge ===")
        for k, v in result["llm_scores"].items():
            if k != "overall_notes":
                print(f"  {k}: {v}/10")
            if "overall_notes" in result["llm_scores"]:
                print(f"  notes: {result['llm_scores']['overall_notes']}")
    elif not args.no_llm:
        print("\n  (LLM judge unavailable, using structural + semantic only)")

    print(f"\n=== COMPOSITE SCORE: {result['composite']}/100 ===")
    print(f"\nMETRIC:{result['composite']}")


if __name__ == "__main__":
    main()
