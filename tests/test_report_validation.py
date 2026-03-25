import unittest

from deep_researcher.config import AppConfig
from deep_researcher.state import Finding, ResearchState, SectionState
from deep_researcher.workflow import DeepResearcher


class ReportValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        config = AppConfig.from_env()
        config.use_mock_llm = True
        config.use_mock_tools = True
        self.runner = DeepResearcher(config)
        self.state = ResearchState(
            run_id="test-report-validation",
            question="研究阳光电源这家公司",
            objective="输出完整深度研究报告",
            sections=[
                SectionState(
                    section_id="S1",
                    title="发展历程与战略演进",
                    goal="梳理发展历程",
                    findings=[Finding(claim="公司经历了多个发展阶段。", source_ids=["S001"])],
                ),
                SectionState(
                    section_id="S2",
                    title="产品线全景与各业务成长分析",
                    goal="梳理产品线",
                    findings=[Finding(claim="产品线覆盖逆变器和储能。", source_ids=["S002"])],
                ),
                SectionState(
                    section_id="S3",
                    title="综合投资结论",
                    goal="形成结论",
                    findings=[Finding(claim="结论需要覆盖增长和风险。", source_ids=["S003"])],
                ),
            ],
        )

    def test_validate_report_accepts_complete_report(self) -> None:
        report = (
            "# 阳光电源深度研究报告\n\n"
            "## 发展历程与战略演进\n\n"
            "公司在多个阶段完成了从技术创业到全球化扩张的跃迁，这一过程构成当前竞争力的基础。"
            " 报告在这一部分只使用现有 section packet 中的事实，不额外扩展未验证的信息。 [source:S001]\n\n"
            "## 产品线全景与各业务成长分析\n\n"
            "核心业务围绕逆变器、储能及相关电力电子能力展开，其中逆变器仍是经营基本盘，储能承担更高增速。"
            " 这一节的目标是把产品矩阵、盈利弹性和业务边界讲清楚。 [source:S002]\n\n"
            "## 综合投资结论\n\n"
            "综合来看，公司具备较强的全球竞争力，但增长质量仍受行业景气、海外政策和供应链价格波动影响。"
            " 因此结论必须同时覆盖成长逻辑、盈利持续性和主要风险，而不是只给单边判断。 [source:S003]\n"
        )
        issues = self.runner._validate_report_completeness(self.state, report)
        self.assertEqual(issues, [])

    def test_validate_report_flags_missing_sections_and_dangling_tail(self) -> None:
        report = (
            "# 阳光电源深度研究报告\n\n"
            "## 发展历程与战略演进\n\n"
            "公司完成了早期创业和上市扩张。 [source:S001]\n\n"
            "## 产品线全景与各业务成长分析\n\n"
            "**亚太市场（含中国）**：\n"
            "- 2024"
        )
        issues = self.runner._validate_report_completeness(self.state, report)
        self.assertTrue(any("Missing body sections" in issue for issue in issues))
        self.assertTrue(any("dangling" in issue or "does not end cleanly" in issue for issue in issues))

    def test_validate_report_allows_bullet_list_ending(self) -> None:
        report = (
            "# 阳光电源深度研究报告\n\n"
            "## 发展历程与战略演进\n\n"
            "公司在多个阶段完成成长。 [source:S001]\n\n"
            "## 产品线全景与各业务成长分析\n\n"
            "产品结构已经从单一逆变器扩展到储能。 [source:S002]\n\n"
            "## 综合投资结论\n\n"
            "综合来看，公司具备较强的全球竞争力，增长逻辑清晰但风险需要关注。 [source:S003]\n\n"
            "- 增长逻辑清晰\n"
            "- 风险可控但需关注海外政策\n"
        )
        issues = self.runner._validate_report_completeness(self.state, report)
        self.assertEqual(issues, [])

    def test_report_has_no_remaining_gaps_section(self) -> None:
        """Regression: generated reports must not contain a Remaining Gaps section."""
        self.state.global_gaps = ["Gap A", "Gap B"]
        report = self.runner._fallback_report(self.state)
        self.assertNotIn("## Remaining Gaps", report)
        self.assertNotIn("Remaining Gaps", report)


if __name__ == "__main__":
    unittest.main()
