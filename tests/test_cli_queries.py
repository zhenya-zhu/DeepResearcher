from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deep_researcher.cli import load_numbered_queries
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


if __name__ == "__main__":
    unittest.main()
