import unittest

from deep_researcher.json_utils import extract_first_json


class JsonUtilsTest(unittest.TestCase):
    def test_extract_first_json_from_wrapped_text(self) -> None:
        payload = "noise before {\"hello\": \"world\", \"items\": [1, 2, 3]} noise after"
        parsed = extract_first_json(payload)
        self.assertEqual(parsed["hello"], "world")
        self.assertEqual(parsed["items"], [1, 2, 3])

    def test_extract_first_json_prefers_object_over_earlier_array(self) -> None:
        payload = "prefix [1, 2, 3] middle {\"hello\": \"world\"}"
        parsed = extract_first_json(payload)
        self.assertEqual(parsed["hello"], "world")

    def test_extract_first_json_repairs_jsonish_fenced_output(self) -> None:
        payload = """```json
{
  "status": "needs_revision",
  "issues": [
    {
      "severity": "high",
      "section_title": "Section A",
      "reason": "报告引用"2023年营业收入约722亿元"但未标注来源。",
      "suggested_fix": "补上来源"
    }
  ]
}
```"""
        parsed = extract_first_json(payload)
        self.assertEqual(parsed["status"], "needs_revision")
        self.assertEqual(parsed["issues"][0]["severity"], "high")

    def test_extract_first_json_rejects_truncated_top_level_object_instead_of_nested_dict(self) -> None:
        payload = """```json
{
  "thesis": "example",
  "reasoning_steps": [
    {
      "observation": "one",
      "inference": "two"
    }
  ],
  "follow_up_queries": [
    "broken
"""
        with self.assertRaises(ValueError):
            extract_first_json(payload)


if __name__ == "__main__":
    unittest.main()
