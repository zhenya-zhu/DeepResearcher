from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from deep_researcher.config import AppConfig
from deep_researcher.llm import MockBackend
from deep_researcher.state import ResearchState, SectionState
from deep_researcher.workflow import DeepResearcher


class SemanticResolutionTest(unittest.TestCase):
    def _config(self, temp_dir: str) -> AppConfig:
        config = AppConfig.from_env()
        config.run_root = Path(temp_dir)
        config.use_mock_llm = True
        config.use_mock_tools = True
        config.max_rounds = 2
        return config

    def _semantic_resolution(self, runner: DeepResearcher, section_id: str, stage: str = "planning") -> dict:
        run_dir = Path(runner.run_dir or "")
        path = run_dir / "state" / "semantic-resolution-{0}-{1}.json".format(section_id, stage)
        return json.loads(path.read_text(encoding="utf-8"))

    def _event_payloads(self, runner: DeepResearcher, stage: str) -> list:
        run_dir = Path(runner.run_dir or "")
        events_path = run_dir / "events.jsonl"
        payloads = []
        for line in events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("stage") == stage:
                payloads.append(event.get("data", {}))
        return payloads

    def test_planner_resolves_deep_research_semantics_without_market_data_pack(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runner = DeepResearcher(self._config(temp_dir), backend=MockBackend())
            state = runner.plan(question="研究一下 Deep Research 的进展和原理，重点关注 OpenAI、Gemini、Claude 的 blog、代码、实现")

            resolved_profiles = {item for section in state.sections for item in section.resolved_profiles}
            resolved_packs = {item for section in state.sections for item in section.resolved_source_packs}

            self.assertTrue({"primary_source", "implementation_detail", "comparative_benchmark"}.issubset(resolved_profiles))
            self.assertNotIn("market_data_pack", resolved_packs)
            landscape_resolution = self._semantic_resolution(runner, "landscape")
            self.assertEqual(landscape_resolution["fallback_used"], [])

    def test_planner_resolves_sunshine_semantics_with_market_data_pack_via_requirement(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runner = DeepResearcher(self._config(temp_dir), backend=MockBackend())
            state = runner.plan(question="给我研究下阳光电源这家公司，分析其 ROE 和成长潜力，并用格雷厄姆和彼得林奇方法分析")

            resolved_profiles = {item for section in state.sections for item in section.resolved_profiles}
            resolved_packs = {item for section in state.sections for item in section.resolved_source_packs}
            section_queries = [query for section in state.sections for query in section.queries]

            self.assertTrue({"primary_source", "quantitative_metric", "derivation", "comparative_benchmark"}.issubset(resolved_profiles))
            self.assertIn("market_data_pack", resolved_packs)
            self.assertTrue(any("site:futunn.com" in item for item in section_queries))
            self.assertTrue(any("site:cn.tradingview.com" in item for item in section_queries))

    def test_planner_resolves_tpu_supply_chain_semantics(self) -> None:
        with TemporaryDirectory() as temp_dir:
            runner = DeepResearcher(self._config(temp_dir), backend=MockBackend())
            state = runner.plan(question="Google 的新 TPU 采用了一种新模式，涉及光模块，调研详细信息，并调研上游供应链")

            resolved_profiles = {item for section in state.sections for item in section.resolved_profiles}
            resolved_packs = {item for section in state.sections for item in section.resolved_source_packs}

            self.assertTrue({"implementation_detail", "structural_breakdown", "ecosystem_supply_chain"}.issubset(resolved_profiles))
            self.assertIn("supply_chain_pack", resolved_packs)

    def test_native_mode_keeps_planner_queries_and_skips_registry_expansion(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = self._config(temp_dir)
            config.semantic_mode = "native"
            runner = DeepResearcher(config, backend=MockBackend())
            state = runner.plan(question="给我研究下阳光电源这家公司，分析其 ROE 和成长潜力，并用格雷厄姆和彼得林奇方法分析")

            financials = next(section for section in state.sections if section.section_id == "financials")
            resolution = self._semantic_resolution(runner, "financials")

            self.assertIn("site:cn.tradingview.com", financials.queries[0])
            self.assertEqual(resolution["query_generation_mode"], "planner_native")
            self.assertEqual(resolution["generated_queries"], [])

    def test_unknown_planner_profile_is_dropped_and_minimal_fallback_is_logged(self) -> None:
        class InvalidPlannerBackend(MockBackend):
            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: planner" in joined:
                    return json.dumps({
                        "objective": "Inspect docs and metrics",
                        "research_brief": "Test fallback behavior.",
                        "input_dependencies": [],
                        "source_requirements": ["Official docs", "Metrics"],
                        "comparison_axes": [],
                        "success_criteria": [],
                        "risks": [],
                        "sections": [
                            {
                                "id": "S1",
                                "title": "Docs and Metrics",
                                "goal": "Validate fallback semantics.",
                                "queries": ["example official docs metrics"],
                                "must_cover": ["official docs", "metrics"],
                                "evidence_requirements": [
                                    {
                                        "profile_id": "unknown_profile",
                                        "priority": "high",
                                        "must_cover": ["official docs", "metrics"],
                                        "preferred_source_packs": ["market_data_pack"],
                                        "query_hints": ["official docs", "benchmark metrics"],
                                        "rationale": "Invalid on purpose.",
                                    }
                                ],
                            }
                        ],
                    }, ensure_ascii=False)
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            runner = DeepResearcher(self._config(temp_dir), backend=InvalidPlannerBackend())
            state = runner.plan(question="Compare official docs and benchmark metrics for the platform")

            section = state.sections[0]
            resolution = self._semantic_resolution(runner, "S1")

            self.assertEqual(section.resolved_profiles, ["primary_source", "quantitative_metric"])
            self.assertEqual(section.resolved_source_packs, [])
            self.assertEqual(resolution["invalid_profiles"], ["unknown_profile"])
            self.assertEqual(resolution["fallback_used"], ["primary_source", "quantitative_metric"])

    def test_no_valid_requirements_use_only_minimal_generic_fallback(self) -> None:
        class EmptyRequirementPlanner(MockBackend):
            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: planner" in joined:
                    return json.dumps({
                        "objective": "Inspect docs and metrics",
                        "research_brief": "Test empty requirement fallback behavior.",
                        "input_dependencies": [],
                        "source_requirements": ["Official docs", "Metrics"],
                        "comparison_axes": [],
                        "success_criteria": [],
                        "risks": [],
                        "sections": [
                            {
                                "id": "S1",
                                "title": "Docs and Metrics",
                                "goal": "Validate fallback semantics.",
                                "queries": ["example official docs metrics"],
                                "must_cover": ["official docs", "metrics"],
                                "evidence_requirements": [],
                            }
                        ],
                    }, ensure_ascii=False)
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            runner = DeepResearcher(self._config(temp_dir), backend=EmptyRequirementPlanner())
            state = runner.plan(question="Analyze official docs and benchmark metrics for the platform")

            section = state.sections[0]
            self.assertEqual(section.resolved_profiles, ["primary_source", "quantitative_metric"])
            self.assertEqual(section.resolved_source_packs, [])

    def test_gap_review_drops_unknown_ids_and_applies_only_valid_tasks(self) -> None:
        class GapReviewBackend(MockBackend):
            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: gap_review" in joined:
                    return json.dumps({
                        "continue_research": True,
                        "global_gaps": ["Need a stronger primary source anchor."],
                        "focus_sections": [],
                        "gap_tasks": [
                            {
                                "task_id": "bad-task",
                                "section_id": "context",
                                "gap": "Bad semantic id",
                                "category": "not_real",
                                "action": "search",
                                "priority": "high",
                                "rationale": "Should be dropped.",
                                "follow_up_queries": ["bad task query"],
                                "must_cover": ["bad"],
                                "source_hints": [],
                                "preferred_source_packs": ["market_data_pack"],
                            },
                            {
                                "task_id": "good-task",
                                "section_id": "context",
                                "gap": "Need first-party docs",
                                "category": "primary_source",
                                "action": "search",
                                "priority": "high",
                                "rationale": "Anchor section with primary docs.",
                                "follow_up_queries": ["deep research official docs"],
                                "must_cover": ["official docs"],
                                "source_hints": ["Official docs"],
                                "preferred_source_packs": ["official_docs_pack", "unknown_pack"],
                            },
                        ],
                    }, ensure_ascii=False)
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            config = self._config(temp_dir)
            runner = DeepResearcher(config, backend=GapReviewBackend())
            state = runner.plan(question="研究一下 Deep Research 的进展和原理，重点关注 OpenAI、Gemini、Claude 的 blog、代码、实现")
            state.current_round = 1

            continue_research = runner._review_gaps(state)
            context_section = next(section for section in state.sections if section.section_id == "context")
            events = self._event_payloads(runner, "review")

            self.assertTrue(continue_research)
            self.assertEqual(len(state.gap_tasks), 1)
            self.assertEqual(state.gap_tasks[0].category, "primary_source")
            self.assertEqual(state.gap_tasks[0].preferred_source_packs, ["official_docs_pack"])
            self.assertIn("official_docs_pack", context_section.resolved_source_packs)
            self.assertTrue(events)
            self.assertEqual(events[-1]["invalid_profiles"], ["not_real"])
            self.assertEqual(events[-1]["invalid_source_packs"], ["unknown_pack"])


if __name__ == "__main__":
    unittest.main()
