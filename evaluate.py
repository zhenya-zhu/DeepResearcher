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
    h2_count = sum(1 for l in lines if l.startswith("## "))
    h3_count = sum(1 for l in lines if l.startswith("### "))
    table_count = text.count("| --- |") + text.count("|---|")
    # Count citation references (multiple formats)
    # [source:S001] format (DeepResearcher)
    source_id_pattern = re.compile(r'\[source:S\d+\]')
    source_id_citations = source_id_pattern.findall(text)
    # [1] or [2] bracket format
    bracket_num_pattern = re.compile(r'\[\d{1,2}\]')
    bracket_citations = bracket_num_pattern.findall(text)
    # Bare superscript numbers before Chinese punctuation (Gemini format: 系统3。)
    bare_ref_pattern = re.compile(r'(?<=[^\d\s])\d{1,2}(?=[。，；、\n])')
    bare_citations = bare_ref_pattern.findall(text)
    citation_count = len(source_id_citations) + len(bracket_citations) + len(bare_citations)
    # Count unique sources
    source_pattern = re.compile(r'\[source:(S\d+)\]')
    unique_sources_set = set(source_pattern.findall(text))
    # Also count from endnotes section
    endnote_pattern = re.compile(r'^\d{1,2}\.\s', re.MULTILINE)
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
    dimensions = {
        "char_count": 20,       # length matters a lot
        "h2_sections": 10,
        "h3_subsections": 10,
        "tables": 10,
        "citations": 15,
        "unique_sources": 15,
        "paragraphs": 10,
        "avg_paragraph_chars": 10,
    }
    total = 0
    for key, weight in dimensions.items():
        ref_val = max(reference_metrics.get(key, 1), 1)
        rep_val = report_metrics.get(key, 0)
        # ratio capped at 1.0 (exceeding reference is fine, counts as 1.0)
        ratio = min(rep_val / ref_val, 1.5) / 1.5  # allow up to 1.5x, normalize
        # For very close match (0.8-1.2x), give full credit
        if 0.8 <= rep_val / ref_val <= 1.2:
            ratio = 1.0
        elif rep_val / ref_val > 1.2:
            ratio = max(0.8, 1.0 - abs(rep_val / ref_val - 1.0) * 0.3)  # slight penalty for far over
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

    # Truncate texts to fit context
    max_chars = 30000
    report_trunc = report_text[:max_chars]
    reference_trunc = reference_text[:max_chars]

    try:
        response = client.chat.completions.create(
            model="anthropic--claude-4.6-sonnet",
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


def compute_composite_score(structural_score: float, llm_scores: dict) -> float:
    """Weighted composite score. Returns 0-100."""
    if llm_scores is None:
        return structural_score  # fallback to structural only

    # LLM dimensions weighted equally, total weight = 70
    llm_keys = ["structure", "depth", "evidence", "coherence", "tables",
                 "paragraph_quality", "summary_conclusion", "completeness"]
    llm_total = sum(llm_scores.get(k, 0) for k in llm_keys)
    llm_normalized = (llm_total / (len(llm_keys) * 10)) * 70  # 0-70

    # Structural = 30
    structural_normalized = structural_score * 0.3

    return round(llm_normalized + structural_normalized, 1)


def main():
    parser = argparse.ArgumentParser(description="Evaluate a DeepResearcher report")
    parser.add_argument("report", help="Path to the report to evaluate")
    parser.add_argument("--reference", default="sample_result/Deep Research 技术探索与实现.md",
                       help="Path to the Gemini reference report")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM judge, structural only")
    args = parser.parse_args()

    report_text = Path(args.report).read_text(encoding="utf-8")
    reference_text = Path(args.reference).read_text(encoding="utf-8")

    # Structural metrics
    rep_metrics = structural_metrics(report_text)
    ref_metrics = structural_metrics(reference_text)
    structural_score = compute_structural_score(rep_metrics, ref_metrics)

    print("=== Structural Metrics ===")
    print(f"{'Metric':<25} {'Report':>10} {'Reference':>10}")
    for key in rep_metrics:
        print(f"{key:<25} {rep_metrics[key]:>10} {ref_metrics[key]:>10}")
    print(f"\nStructural Score: {structural_score}/100")

    # LLM judge
    llm_scores = None
    if not args.no_llm:
        print("\n=== LLM Judge ===")
        llm_scores = llm_judge_score(report_text, reference_text)
        if llm_scores:
            for k, v in llm_scores.items():
                if k != "overall_notes":
                    print(f"  {k}: {v}/10")
            if "overall_notes" in llm_scores:
                print(f"  notes: {llm_scores['overall_notes']}")
        else:
            print("  (LLM judge unavailable, using structural score only)")

    # Composite
    composite = compute_composite_score(structural_score, llm_scores)
    print(f"\n=== COMPOSITE SCORE: {composite}/100 ===")

    # Print machine-readable line
    print(f"\nMETRIC:{composite}")


if __name__ == "__main__":
    main()
