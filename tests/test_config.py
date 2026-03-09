import unittest
from unittest.mock import patch
from pathlib import Path

from deep_researcher.config import AppConfig


class ConfigEnvAliasTest(unittest.TestCase):
    def test_prefers_new_max_output_token_env_names(self) -> None:
        env = {
            "DEEP_RESEARCHER_PLANNER_MAX_OUTPUT_TOKENS": "4096",
            "DEEP_RESEARCHER_PLANNER_MAX_TOKENS": "2048",
        }
        with patch.dict("os.environ", env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.planner.max_output_tokens, 4096)

    def test_accepts_legacy_max_tokens_env_names(self) -> None:
        env = {
            "DEEP_RESEARCHER_RESEARCHER_MAX_TOKENS": "3072",
        }
        with patch.dict("os.environ", env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.researcher.max_output_tokens, 3072)

    def test_reads_model_capabilities_file_env(self) -> None:
        env = {
            "DEEP_RESEARCHER_MODEL_CAPABILITIES_FILE": "/tmp/custom-model-capabilities.json",
        }
        with patch.dict("os.environ", env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.model_capabilities_file, Path("/tmp/custom-model-capabilities.json"))


if __name__ == "__main__":
    unittest.main()
