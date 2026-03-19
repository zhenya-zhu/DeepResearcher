from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import io
import unittest

from deep_researcher.cli import load_numbered_queries, load_query_entries, main
from deep_researcher.config import AppConfig
from deep_researcher.workflow import DeepResearcher


class CliQueriesTest(unittest.TestCase):
    def test_load_numbered_queries(self) -> None:
        text = (
            "1. First question\n"
            "extra detail line\n"
            "2. Second question\n"
            "3. Third question\n"
        )
        queries = load_numbered_queries(text)
        self.assertEqual(len(queries), 3)
        self.assertEqual(queries[0], "First question\nextra detail line")
        self.assertEqual(queries[1], "Second question")
        self.assertEqual(queries[2], "Third question")

    def test_load_query_entries_from_json(self) -> None:
        text = """
[
  {"query": "First question", "plan": "Reference plan"},
  {"query": "Second question"},
  "Third question"
]
""".strip()
        entries = load_query_entries(text)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].query, "First question")
        self.assertEqual(entries[0].reference_plan, "Reference plan")
        self.assertEqual(entries[1].query, "Second question")
        self.assertEqual(entries[1].reference_plan, "")
        self.assertEqual(entries[2].query, "Third question")

    def test_load_query_entries_from_relaxed_json_multiline_plan(self) -> None:
        text = """
[
  {
    "query":"First question",
    "plan":"(1) first step
(2) second step"
  }
]
""".strip()
        entries = load_query_entries(text)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].query, "First question")
        self.assertEqual(entries[0].reference_plan, "(1) first step\n(2) second step")

    def test_plan_only_generates_plan_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            config = AppConfig.from_env()
            config.run_root = Path(temp_dir)
            config.use_mock_llm = True
            config.use_mock_tools = True

            runner = DeepResearcher(config)
            state = runner.plan(question="Evaluate deep research planning quality")

            self.assertEqual(state.status, "planned")
            run_dir = Path(runner.run_dir or "")
            self.assertTrue((run_dir / "plan.md").exists())
            self.assertTrue((run_dir / "plan.json").exists())
            self.assertTrue((run_dir / "trace.html").exists())

    def test_compare_semantic_modes_generates_comparison_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main([
                    "--mock",
                    "--plan-only",
                    "--run-root",
                    temp_dir,
                    "--compare-semantic-modes",
                    "研究一下 Deep Research 的进展和原理，重点关注 OpenAI、Gemini、Claude 的 blog、代码、实现",
                ])

            self.assertEqual(exit_code, 0)
            output = stdout.getvalue()
            self.assertIn("Comparison directory:", output)
            compare_dirs = list(Path(temp_dir).glob("semantic-compare-*"))
            self.assertEqual(len(compare_dirs), 1)
            compare_root = compare_dirs[0]
            self.assertTrue((compare_root / "comparison.md").exists())
            self.assertTrue((compare_root / "comparison.json").exists())
            self.assertTrue(any((compare_root / "hybrid").rglob("plan.json")))
            self.assertTrue(any((compare_root / "native").rglob("plan.json")))


if __name__ == "__main__":
    unittest.main()
