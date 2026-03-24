import unittest

from deep_researcher.workflow import _extract_outbound_links


class LinkExtractionTest(unittest.TestCase):
    def test_extracts_external_links(self):
        html = (
            '<html><body>'
            '<a href="https://example.com/article">Article</a>'
            '<a href="https://other.com/page">Other</a>'
            '</body></html>'
        )
        links = _extract_outbound_links(html, "https://base.com/start")
        self.assertEqual(len(links), 2)
        self.assertIn("https://example.com/article", links)

    def test_skips_same_domain(self):
        html = (
            '<html><body>'
            '<a href="https://base.com/about">About</a>'
            '<a href="https://external.com/page">External</a>'
            '</body></html>'
        )
        links = _extract_outbound_links(html, "https://base.com/start")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0], "https://external.com/page")

    def test_skips_non_content_urls(self):
        html = (
            '<html><body>'
            '<a href="https://site.com/login">Login</a>'
            '<a href="https://site.com/privacy">Privacy</a>'
            '<a href="https://site.com/article.pdf">PDF</a>'
            '<a href="https://good.com/research">Research</a>'
            '</body></html>'
        )
        links = _extract_outbound_links(html, "https://base.com/page")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0], "https://good.com/research")

    def test_deduplicates_links(self):
        html = (
            '<html><body>'
            '<a href="https://site.com/page">Page 1</a>'
            '<a href="https://site.com/page">Page 2</a>'
            '<a href="https://site.com/page/">Page 3</a>'
            '</body></html>'
        )
        links = _extract_outbound_links(html, "https://base.com/start")
        self.assertEqual(len(links), 1)

    def test_respects_max_links(self):
        html = '<html><body>' + ''.join(
            '<a href="https://site{0}.com/page">Link</a>'.format(i) for i in range(20)
        ) + '</body></html>'
        links = _extract_outbound_links(html, "https://base.com/start", max_links=5)
        self.assertEqual(len(links), 5)

    def test_handles_empty_html(self):
        links = _extract_outbound_links("", "https://base.com")
        self.assertEqual(links, [])

    def test_handles_malformed_html(self):
        links = _extract_outbound_links("<not<valid<html", "https://base.com")
        self.assertEqual(links, [])


if __name__ == "__main__":
    unittest.main()
