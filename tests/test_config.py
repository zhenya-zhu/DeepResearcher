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

    def test_reads_evidence_profiles_file_env(self) -> None:
        env = {
            "DEEP_RESEARCHER_EVIDENCE_PROFILES_FILE": "/tmp/custom-evidence-profiles.json",
        }
        with patch.dict("os.environ", env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.evidence_profiles_file, Path("/tmp/custom-evidence-profiles.json"))

    def test_reads_source_packs_file_env(self) -> None:
        env = {
            "DEEP_RESEARCHER_SOURCE_PACKS_FILE": "/tmp/custom-source-packs.json",
        }
        with patch.dict("os.environ", env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.source_packs_file, Path("/tmp/custom-source-packs.json"))

    def test_reads_network_mode_env(self) -> None:
        env = {
            "DEEP_RESEARCHER_NETWORK_MODE": "direct",
        }
        with patch.dict("os.environ", env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.network_mode, "direct")

    def test_reads_semantic_mode_env(self) -> None:
        env = {
            "DEEP_RESEARCHER_SEMANTIC_MODE": "native",
        }
        with patch.dict("os.environ", env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.semantic_mode, "native")

    def test_reads_workspace_source_env(self) -> None:
        env = {
            "DEEP_RESEARCHER_WORKSPACE_SOURCES": "/tmp/reports:/tmp/annual-report.pdf",
        }
        with patch.dict("os.environ", env, clear=True):
            config = AppConfig.from_env()
        self.assertEqual(config.workspace_sources, [Path("/tmp/reports"), Path("/tmp/annual-report.pdf")])


if __name__ == "__main__":
    unittest.main()
