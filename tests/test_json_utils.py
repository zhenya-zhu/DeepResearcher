import unittest

from deep_researcher.json_utils import extract_first_json


class JsonUtilsTest(unittest.TestCase):
    def test_extract_first_json_from_wrapped_text(self) -> None:
        payload = "noise before {\"hello\": \"world\", \"items\": [1, 2, 3]} noise after"
        parsed = extract_first_json(payload)
        self.assertEqual(parsed["hello"], "world")
        self.assertEqual(parsed["items"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
