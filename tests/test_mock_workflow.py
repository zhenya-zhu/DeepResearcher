from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deep_researcher.config import AppConfig
from deep_researcher.workflow import DeepResearcher


class MockWorkflowTest(unittest.TestCase):
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
            run_dir = Path(runner.run_dir or "")
            self.assertTrue((run_dir / "report.md").exists())
            self.assertTrue((run_dir / "trace.html").exists())
            self.assertTrue((run_dir / "events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
