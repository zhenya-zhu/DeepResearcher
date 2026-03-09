from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from deep_researcher.model_capabilities import load_model_capability_registry, resolve_model_capability


class ModelCapabilitiesTest(unittest.TestCase):
    def test_default_registry_resolves_known_model(self) -> None:
        capability = resolve_model_capability("anthropic--claude-4.6-sonnet")
        self.assertEqual(capability.family, "claude-4.x")
        self.assertEqual(capability.context_window_tokens, 200000)
        self.assertEqual(capability.matched_by, "prefix")

    def test_custom_registry_override(self) -> None:
        payload = """
{
  "default": {"context_window_tokens": 111111},
  "rules": [
    {
      "pattern": "custom-model",
      "match": "exact",
      "family": "custom",
      "context_window_tokens": 777777
    }
  ]
}
""".strip()
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "model_capabilities.json"
            path.write_text(payload, encoding="utf-8")
            registry = load_model_capability_registry(path)
            exact = resolve_model_capability("custom-model", registry)
            fallback = resolve_model_capability("unknown-model", registry)
        self.assertEqual(exact.context_window_tokens, 777777)
        self.assertEqual(exact.family, "custom")
        self.assertEqual(fallback.context_window_tokens, 111111)
        self.assertEqual(fallback.matched_by, "default")


if __name__ == "__main__":
    unittest.main()
