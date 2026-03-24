import unittest

from deep_researcher.state import SectionState
from deep_researcher.workflow import _compact_query, _extract_subject, _normalized_queries, _search_query_variants


class QueryRewriteTest(unittest.TestCase):
    def test_compact_query_trims_long_keyword_stack(self) -> None:
        query = "阳光电源 光伏逆变器 组串式 集中式 微型逆变器 技术参数 市场份额 2023 2024"

        compact = _compact_query(query)

        self.assertIn("阳光电源", compact)
        self.assertLessEqual(len(compact), 48)
        self.assertLessEqual(len(compact.split()), 6)

    def test_normalized_queries_keep_subject_and_dedupe(self) -> None:
        question = "给我研究下阳光电源这家公司，分析它的产品线和竞争力"
        queries = [
            "阳光电源 光伏逆变器 组串式 集中式 微型逆变器 技术参数 市场份额",
            "阳光电源 光伏逆变器 组串式 集中式 微型逆变器 技术参数 市场份额",
        ]

        normalized = _normalized_queries(question, "产品线分析", queries, 2)

        self.assertEqual(len(normalized), 1)
        self.assertTrue(normalized[0].startswith("阳光电源"))

    def test_search_query_variants_generate_shorter_fallbacks(self) -> None:
        question = "给我研究下阳光电源这家公司，分析它的产品线和竞争力"
        section = SectionState(section_id="S2", title="产品线分析", goal="拆解产品结构")
        raw_query = "阳光电源 光伏逆变器 组串式 集中式 微型逆变器 技术参数 市场份额 2023 2024"

        variants = _search_query_variants(question, section, raw_query)

        self.assertGreaterEqual(len(variants), 2)
        self.assertTrue(all(len(item) <= 48 for item in variants))
        self.assertTrue(all(item.startswith("阳光电源") for item in variants))

    def test_normalized_queries_preserve_site_operator(self) -> None:
        question = "研究阳光电源估值"
        queries = [
            "阳光电源 site:futunn.com PE PEG BPS EPS",
            "阳光电源 site:cn.tradingview.com 财务 ROE",
        ]

        normalized = _normalized_queries(question, "估值分析", queries, 4)

        self.assertTrue(any("site:futunn.com" in item for item in normalized))
        self.assertTrue(any("site:cn.tradingview.com" in item for item in normalized))

    def test_extract_subject_strips_request_prefixes(self) -> None:
        subject = _extract_subject("给我研究一下 Deep Research 的进展和原理，重点关注 OpenAI、Gemini、Claude")

        self.assertEqual(subject, "Deep Research 进展和原理")

    def test_compact_query_drops_chinese_filler_in_mixed_query(self) -> None:
        compact = _compact_query("Deep Research的进展和原理 launch blog product")
        self.assertIn("Deep Research", compact)
        self.assertIn("launch", compact)
        self.assertNotIn("进展", compact)
        self.assertNotIn("原理", compact)

    def test_compact_query_keeps_short_cjk_proper_nouns(self) -> None:
        compact = _compact_query("FICC宏观框架 fixed income currency commodity")
        self.assertIn("FICC", compact)
        self.assertIn("fixed", compact)

    def test_compact_query_pure_english_unchanged(self) -> None:
        compact = _compact_query("coal chemical petroleum alternative production cost")
        self.assertIn("coal", compact)
        self.assertIn("petroleum", compact)

    def test_compact_query_filters_generic_chinese_chunks(self) -> None:
        compact = _compact_query("Deep Research 技术 分析 原理 architecture design")
        self.assertNotIn("技术", compact)
        self.assertNotIn("分析", compact)
        self.assertNotIn("原理", compact)
        self.assertIn("architecture", compact)


if __name__ == "__main__":
    unittest.main()
