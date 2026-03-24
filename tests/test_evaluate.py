import unittest

from evaluate import structural_metrics, compute_structural_score, compute_semantic_coverage, compute_composite_score


class StructuralMetricsTest(unittest.TestCase):
    def test_counts_headings_and_tables(self):
        text = "## Section 1\nSome text.\n### Sub\nMore text.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
        m = structural_metrics(text)
        self.assertEqual(m["h2_sections"], 1)
        self.assertEqual(m["h3_subsections"], 1)
        self.assertEqual(m["tables"], 1)

    def test_counts_source_citations(self):
        text = "Claim one [source:S001]. Claim two [source:S002]. Claim three [source:S001].\n"
        m = structural_metrics(text)
        self.assertEqual(m["citations"], 3)
        self.assertEqual(m["unique_sources"], 2)

    def test_counts_bracket_citations(self):
        text = "Fact [1]. Another fact [2]. Third [1].\n"
        m = structural_metrics(text)
        self.assertEqual(m["citations"], 3)


class StructuralScoreTest(unittest.TestCase):
    def test_no_penalty_for_exceeding_reference_length(self):
        """Reports longer than reference should NOT be penalized for char_count, citations, unique_sources, tables."""
        ref = {"char_count": 10000, "h2_sections": 5, "h3_subsections": 10,
               "tables": 3, "citations": 50, "unique_sources": 20,
               "paragraphs": 30, "avg_paragraph_chars": 300}
        # Report is 2x longer with more citations
        rep = {"char_count": 20000, "h2_sections": 5, "h3_subsections": 10,
               "tables": 6, "citations": 100, "unique_sources": 40,
               "paragraphs": 30, "avg_paragraph_chars": 300}
        score = compute_structural_score(rep, ref)
        # All "more is better" dimensions should get full credit
        # All "proximity" dimensions match exactly → full credit
        self.assertEqual(score, 100.0)

    def test_old_penalty_removed(self):
        """Specifically test that char_count 2x reference gets full credit, not 0.8 penalty."""
        ref = {"char_count": 10000, "h2_sections": 5, "h3_subsections": 10,
               "tables": 3, "citations": 50, "unique_sources": 20,
               "paragraphs": 30, "avg_paragraph_chars": 300}
        rep_double = dict(ref)
        rep_double["char_count"] = 20000
        score = compute_structural_score(rep_double, ref)
        # char_count weight=20, should get full credit. Everything else matches.
        self.assertEqual(score, 100.0)

    def test_below_reference_gets_proportional_score(self):
        ref = {"char_count": 10000, "h2_sections": 5, "h3_subsections": 10,
               "tables": 3, "citations": 50, "unique_sources": 20,
               "paragraphs": 30, "avg_paragraph_chars": 300}
        rep_half = dict(ref)
        rep_half["char_count"] = 5000  # 50% of reference
        score = compute_structural_score(rep_half, ref)
        # char_count gets 0.5 ratio * 15 weight = 7.5 instead of 15
        # Everything else matches = 85
        self.assertEqual(score, 92.5)

    def test_proximity_dimensions_tolerate_range(self):
        ref = {"char_count": 10000, "h2_sections": 5, "h3_subsections": 10,
               "tables": 3, "citations": 50, "unique_sources": 20,
               "paragraphs": 30, "avg_paragraph_chars": 300}
        rep = dict(ref)
        rep["h2_sections"] = 6  # 1.2x — within more_is_better, gets full credit
        score = compute_structural_score(rep, ref)
        self.assertEqual(score, 100.0)

    def test_more_sections_not_penalized(self):
        """Reports with more sections/paragraphs than reference should NOT lose points."""
        ref = {"char_count": 10000, "h2_sections": 5, "h3_subsections": 10,
               "tables": 3, "citations": 50, "unique_sources": 20,
               "paragraphs": 30, "avg_paragraph_chars": 300}
        rep = dict(ref)
        rep["h2_sections"] = 10  # 2x sections
        rep["h3_subsections"] = 20  # 2x subsections
        rep["paragraphs"] = 90  # 3x paragraphs
        score = compute_structural_score(rep, ref)
        # All now "more is better" — full credit
        self.assertEqual(score, 100.0)

    def test_unique_sources_most_important(self):
        """unique_sources has highest weight (20) — low coverage hurts most."""
        ref = {"char_count": 10000, "h2_sections": 5, "h3_subsections": 10,
               "tables": 3, "citations": 50, "unique_sources": 50,
               "paragraphs": 30, "avg_paragraph_chars": 300}
        rep = dict(ref)
        rep["unique_sources"] = 3  # Only 3 unique sources vs 50 reference
        score = compute_structural_score(rep, ref)
        # unique_sources: 3/50 = 0.06 * 20 = 1.2 instead of 20
        # Loss = 18.8 points
        self.assertLess(score, 82.0)


class SemanticCoverageTest(unittest.TestCase):
    def test_full_coverage(self):
        reference = "Deep Research 技术 Deep Research 技术 Deep Research 技术"
        report = "This report covers Deep Research 技术 and more."
        score = compute_semantic_coverage(report, reference)
        self.assertEqual(score, 100.0)

    def test_zero_coverage(self):
        reference = "quantum computing quantum computing quantum computing"
        report = "This is about something completely different."
        score = compute_semantic_coverage(report, reference)
        self.assertLess(score, 50.0)


class CompositeScoreTest(unittest.TestCase):
    def test_structural_only_with_semantic(self):
        score = compute_composite_score(80.0, None, 60.0)
        # 80*0.7 + 60*0.3 = 56 + 18 = 74
        self.assertEqual(score, 74.0)

    def test_structural_only_no_semantic(self):
        score = compute_composite_score(80.0, None, None)
        self.assertEqual(score, 80.0)

    def test_with_llm_scores(self):
        llm = {"structure": 8, "depth": 7, "evidence": 9, "coherence": 8,
               "tables": 6, "paragraph_quality": 7, "summary_conclusion": 8, "completeness": 7}
        score = compute_composite_score(90.0, llm, 80.0)
        # llm_total = 60/80 = 0.75 * 60 = 45
        # structural = 90 * 0.25 = 22.5
        # semantic = 80 * 0.15 = 12
        # total = 79.5
        self.assertEqual(score, 79.5)


if __name__ == "__main__":
    unittest.main()
