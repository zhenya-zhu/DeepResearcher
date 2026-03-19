from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from deep_researcher.semantic_registry import load_semantic_registry


class SemanticRegistryTest(unittest.TestCase):
    def test_loads_default_registry(self) -> None:
        registry = load_semantic_registry()

        self.assertIn("primary_source", registry.profiles)
        self.assertIn("quantitative_metric", registry.profiles)
        self.assertIn("official_docs_pack", registry.source_packs)
        self.assertIn("market_data_pack", registry.source_packs)

    def test_prompt_payload_includes_registry_metadata(self) -> None:
        registry = load_semantic_registry()

        profiles = {item["id"]: item for item in registry.profile_prompt_payload()}
        source_packs = {item["id"]: item for item in registry.source_pack_prompt_payload()}

        self.assertIn("default_query_templates", profiles["primary_source"])
        self.assertEqual(source_packs["market_data_pack"]["allowed_domains"], ["futunn.com", "cn.tradingview.com", "stock.cheesefortune.com"])
        self.assertTrue(source_packs["official_docs_pack"]["preferred"])

    def test_loads_custom_registry_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profiles_path = root / "profiles.json"
            source_packs_path = root / "source-packs.json"
            profiles_path.write_text(json.dumps([
                {
                    "id": "custom_profile",
                    "description": "Custom profile",
                    "default_priority": "high",
                    "default_source_hints": ["Custom hint"],
                    "default_query_templates": ["{subject} custom"],
                    "fallback_enabled": True,
                }
            ]), encoding="utf-8")
            source_packs_path.write_text(json.dumps([
                {
                    "id": "custom_pack",
                    "description": "Custom pack",
                    "applies_to_profiles": ["custom_profile"],
                    "query_templates": ["{subject} site:example.com"],
                    "source_hints": ["Example source"],
                    "allowed_domains": ["example.com"],
                    "priority_bias": "medium",
                    "preferred": False,
                    "optional": True,
                }
            ]), encoding="utf-8")

            registry = load_semantic_registry(profiles_path, source_packs_path)

            self.assertEqual(list(registry.profiles.keys()), ["custom_profile"])
            self.assertEqual(list(registry.source_packs.keys()), ["custom_pack"])


if __name__ == "__main__":
    unittest.main()
