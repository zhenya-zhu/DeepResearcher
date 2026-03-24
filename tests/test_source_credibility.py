import unittest

from deep_researcher.workflow import _score_source_credibility


class SourceCredibilityTest(unittest.TestCase):
    def test_high_credibility_domain(self):
        self.assertEqual(_score_source_credibility("https://openai.com/research/gpt-4", "GPT-4"), 0.95)
        self.assertEqual(_score_source_credibility("https://arxiv.org/abs/2301.00001", "Paper"), 0.90)

    def test_subdomain_inherits_parent(self):
        self.assertEqual(_score_source_credibility("https://blog.openai.com/post", "Blog"), 0.95)
        self.assertEqual(_score_source_credibility("https://docs.anthropic.com/api", "Docs"), 0.95)

    def test_www_prefix_stripped(self):
        self.assertEqual(_score_source_credibility("https://www.arxiv.org/abs/123", "Paper"), 0.90)

    def test_government_domain(self):
        score = _score_source_credibility("https://www.energy.gov/report", "DOE Report")
        self.assertEqual(score, 0.85)

    def test_academic_domain(self):
        score = _score_source_credibility("https://cs.stanford.edu/paper", "Stanford Paper")
        self.assertEqual(score, 0.80)

    def test_org_domain(self):
        score = _score_source_credibility("https://www.someorg.org/about", "Some Org")
        self.assertEqual(score, 0.65)

    def test_unknown_domain_default(self):
        score = _score_source_credibility("https://random-blog.xyz/post", "Random Blog")
        self.assertEqual(score, 0.5)

    def test_medium_and_substack(self):
        self.assertEqual(_score_source_credibility("https://medium.com/@user/post", "Medium Post"), 0.55)
        self.assertEqual(_score_source_credibility("https://newsletter.substack.com/p/post", "Substack"), 0.55)

    def test_reddit_low_score(self):
        self.assertEqual(_score_source_credibility("https://reddit.com/r/MachineLearning", "Reddit"), 0.40)

    def test_invalid_url_returns_default(self):
        self.assertEqual(_score_source_credibility("not-a-url", "Title"), 0.5)

    def test_github_score(self):
        self.assertEqual(_score_source_credibility("https://github.com/openai/gpt", "Repo"), 0.80)


if __name__ == "__main__":
    unittest.main()
