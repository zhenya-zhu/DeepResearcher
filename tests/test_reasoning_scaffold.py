import unittest

from deep_researcher.config import AppConfig
from deep_researcher.state import ReasoningStep, ResearchState, SectionState
from deep_researcher.workflow import DeepResearcher


class ReasoningScaffoldTest(unittest.TestCase):
    def test_state_roundtrip_preserves_reasoning_steps(self) -> None:
        state = ResearchState(
            run_id="reasoning-roundtrip",
            question="研究阳光电源",
            sections=[
                SectionState(
                    section_id="S1",
                    title="成长逻辑",
                    goal="解释成长驱动",
                    thesis="成长来自技术迭代与全球化。",
                    key_drivers=["海外高毛利", "储能放量"],
                    reasoning_steps=[
                        ReasoningStep(
                            observation="海外收入占比提升。",
                            inference="利润结构正在向高毛利区域迁移。",
                            implication="ROE有更强的韧性。",
                            source_ids=["S001"],
                        )
                    ],
                    counterpoints=["海外竞争仍在加剧。"],
                )
            ],
        )

        restored = ResearchState.from_dict(state.to_dict())
        section = restored.sections[0]
        self.assertEqual(section.thesis, "成长来自技术迭代与全球化。")
        self.assertEqual(section.key_drivers, ["海外高毛利", "储能放量"])
        self.assertEqual(section.reasoning_steps[0].inference, "利润结构正在向高毛利区域迁移。")
        self.assertEqual(section.counterpoints, ["海外竞争仍在加剧。"])

    def test_section_draft_includes_reasoning_scaffold(self) -> None:
        config = AppConfig.from_env()
        config.use_mock_llm = True
        config.use_mock_tools = True
        runner = DeepResearcher(config)
        section = SectionState(
            section_id="S1",
            title="成长逻辑",
            goal="解释成长驱动",
            thesis="成长来自技术复用和全球化。",
            summary="证据显示技术底座复用带来跨品类扩张能力。",
            key_drivers=["技术底座复用", "海外高毛利市场"],
            reasoning_steps=[
                ReasoningStep(
                    observation="储能与逆变器共享电力电子能力。",
                    inference="新业务扩张的边际研发成本更低。",
                    implication="利润弹性强于简单卖设备。",
                    source_ids=["S001", "S002"],
                )
            ],
            counterpoints=["储能价格战可能压缩利润。"],
        )

        draft = runner._section_draft(section)
        self.assertIn("**Core Judgment**", draft)
        self.assertIn("**What Drives It**", draft)
        self.assertIn("**Reasoning Chain**", draft)
        self.assertIn("Counterpoints:", draft)

    def test_validate_section_markdown_flags_dangling_tail(self) -> None:
        config = AppConfig.from_env()
        config.use_mock_llm = True
        config.use_mock_tools = True
        runner = DeepResearcher(config)
        section = SectionState(section_id="S1", title="成长逻辑", goal="解释成长驱动")

        issues = runner._validate_section_markdown(
            section,
            "## 成长逻辑\n\n完整内容之后突然停在这里\n\n**政策",
        )

        self.assertTrue(any("does not end cleanly" in issue or "dangling" in issue for issue in issues))

    def test_validate_section_markdown_flags_truncated_bullet_tail(self) -> None:
        config = AppConfig.from_env()
        config.use_mock_llm = True
        config.use_mock_tools = True
        runner = DeepResearcher(config)
        section = SectionState(section_id="S1", title="成长逻辑", goal="解释成长驱动")

        issues = runner._validate_section_markdown(
            section,
            (
                "## 成长逻辑\n\n"
                "- 市场在高景气阶段可能给予过高溢价，一旦增速预期下修，估值收缩会放大回撤，这正是林奇反复警告的\"成长股"
            ),
        )

        self.assertTrue(any("dangling" in issue or "does not end cleanly" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
