from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deep_researcher.config import AppConfig
from deep_researcher.llm import MockBackend
from deep_researcher.search import FetchedPage, MockFetcher, SearchHit
from deep_researcher.state import ResearchState, SectionState
from deep_researcher.workflow import DeepResearcher


class MockWorkflowTest(unittest.TestCase):
    class EmptySearcher:
        last_mode = "direct"

        def search(self, query, limit):  # type: ignore[no-untyped-def]
            return []

    def test_mock_run_generates_report_and_trace(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True
            config.max_rounds = 1

            runner = DeepResearcher(config)
            state = runner.run(question="Evaluate enterprise deep research agent architectures")

            self.assertEqual(state.status, "completed")
            self.assertTrue(state.report_markdown.startswith("# Mock Deep Research Report"))
            self.assertIn("**Core Judgment**", state.report_markdown)
            self.assertIn("## Sources Used As Citations", state.report_markdown)
            self.assertIn("## Queried But Not Used As Citations", state.report_markdown)
            self.assertIn("`S001` [", state.report_markdown)
            self.assertIn("https://example.com/", state.report_markdown)
            run_dir = Path(runner.run_dir or "")
            self.assertTrue((run_dir / "report.md").exists())
            self.assertTrue((run_dir / "trace.html").exists())
            self.assertTrue((run_dir / "events.jsonl").exists())
            self.assertTrue(any((run_dir / "analysis").glob("*.md")))

    def test_mock_run_falls_back_when_section_writer_times_out(self) -> None:
        class FailingReportBackend(MockBackend):
            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: report_section_writer" in joined or "TASK_KIND: report_overview" in joined:
                    raise RuntimeError("timed out")
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True
            config.max_rounds = 1

            runner = DeepResearcher(config, backend=FailingReportBackend())
            state = runner.run(question="Evaluate enterprise deep research agent architectures")

            self.assertEqual(state.status, "completed")
            self.assertIn("## Executive Summary", state.report_markdown)
            self.assertIn("## Context and Scope", state.report_markdown)
            self.assertIn("**Reasoning Chain**", state.report_markdown)
            run_dir = Path(runner.run_dir or "")
            self.assertTrue((run_dir / "artifacts" / "report-sections" / "context-fallback.md").exists())

    def test_mock_run_falls_back_when_section_writer_returns_truncated_section(self) -> None:
        class TruncatedSectionBackend(MockBackend):
            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: report_section_writer" in joined:
                    return "## Context and Scope\n\n**政策"
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True
            config.max_rounds = 1

            runner = DeepResearcher(config, backend=TruncatedSectionBackend())
            state = runner.run(question="Evaluate enterprise deep research agent architectures")

            self.assertEqual(state.status, "completed")
            self.assertIn("## Context and Scope", state.report_markdown)
            self.assertIn("**Reasoning Chain**", state.report_markdown)
            run_dir = Path(runner.run_dir or "")
            self.assertTrue((run_dir / "artifacts" / "report-sections" / "context-fallback.md").exists())

    def test_mock_run_can_use_workspace_documents_without_web_results(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workspace_dir = temp_root / "workspace_sources"
            workspace_dir.mkdir()
            annual_report = workspace_dir / "阳光电源2024年报.txt"
            annual_report.write_text(
                "阳光电源2024年营业收入722亿元。\n净利润94.4亿元。\n储能业务收入占比41%。\n海外收入占比提升。\n",
                encoding="utf-8",
            )
            config = AppConfig.from_env()
            config.run_root = temp_root / "runs"
            config.use_mock_llm = True
            config.use_mock_tools = False
            config.max_rounds = 1
            config.workspace_sources = [workspace_dir]

            state = ResearchState(
                run_id="workspace-local-docs",
                question="研究阳光电源的财务质量与产品结构",
                objective="基于本地财报和公开信息完成研究",
                sections=[
                    SectionState(
                        section_id="S1",
                        title="财务质量与产品结构",
                        goal="解释营收、净利润和储能业务占比",
                        queries=["阳光电源 财务质量 产品结构"],
                        must_cover=["营业收入", "净利润", "储能业务收入占比"],
                    )
                ],
            )

            runner = DeepResearcher(
                config,
                backend=MockBackend(),
                searcher=self.EmptySearcher(),
                fetcher=MockFetcher(),
            )
            final_state = runner.run(state=state)

            self.assertEqual(final_state.status, "completed")
            resolved_report = str(annual_report.resolve())
            self.assertIn("## 财务质量与产品结构", final_state.report_markdown)
            self.assertIn(resolved_report, final_state.report_markdown)
            self.assertTrue(any(source.url == resolved_report for source in final_state.sources.values()))

    def test_mock_run_falls_back_when_section_writer_returns_truncated_quoted_bullet(self) -> None:
        class TruncatedQuotedBulletBackend(MockBackend):
            def chat(self, model, messages, temperature, max_output_tokens):  # type: ignore[override]
                joined = "\n".join(message["content"] for message in messages)
                if "TASK_KIND: report_section_writer" in joined:
                    return "## Context and Scope\n\n- 市场在高景气阶段可能给予过高溢价，这正是林奇反复警告的\"成长股"
                return super().chat(model, messages, temperature, max_output_tokens)

        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True
            config.max_rounds = 1

            runner = DeepResearcher(config, backend=TruncatedQuotedBulletBackend())
            state = runner.run(question="Evaluate enterprise deep research agent architectures")

            self.assertEqual(state.status, "completed")
            self.assertIn("## Context and Scope", state.report_markdown)
            self.assertIn("**Reasoning Chain**", state.report_markdown)
            run_dir = Path(runner.run_dir or "")
            self.assertTrue((run_dir / "artifacts" / "report-sections" / "context-fallback.md").exists())

    def test_citations_use_resolved_target_url_not_search_engine_redirect(self) -> None:
        class RedirectOnlySearcher:
            last_mode = "direct"

            def search(self, query, limit):  # type: ignore[no-untyped-def]
                return [
                    SearchHit(
                        title="目标文章",
                        url="https://www.sogou.com/link?url=stub",
                        snippet="来自目标页面的摘要",
                    )
                ]

        class RedirectResolvingFetcher:
            last_mode = "direct"

            def fetch(self, url):  # type: ignore[no-untyped-def]
                return FetchedPage(
                    title="目标文章",
                    raw_html="<html><title>目标文章</title><body>目标正文</body></html>",
                    text="目标正文，包含可以引用的内容。",
                    final_url="https://target.example.com/article",
                )

        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = False
            config.max_rounds = 1
            config.max_sections = 1
            config.max_queries_per_section = 1
            config.max_sources_per_section = 1

            state = ResearchState(
                run_id="resolved-target-url",
                question="研究目标页面的核心观点",
                objective="验证 citation 使用最终 URL",
                sections=[
                    SectionState(
                        section_id="S1",
                        title="目标页面分析",
                        goal="总结目标页面观点",
                        queries=["目标页面 核心观点"],
                    )
                ],
            )

            runner = DeepResearcher(
                config,
                backend=MockBackend(),
                searcher=RedirectOnlySearcher(),
                fetcher=RedirectResolvingFetcher(),
            )
            final_state = runner.run(state=state)

            self.assertEqual(final_state.status, "completed")
            self.assertIn("https://target.example.com/article", final_state.report_markdown)
            self.assertIn("## Sources Used As Citations", final_state.report_markdown)
            citation_block = final_state.report_markdown.split("## Queried But Not Used As Citations", 1)[0]
            self.assertNotIn("https://www.sogou.com/link?url=stub", citation_block)
            self.assertEqual(final_state.sources["S001"].url, "https://target.example.com/article")


if __name__ == "__main__":
    unittest.main()
