"""Tests for the Sonar-pro response adapter."""

from deep_researcher.sonar_adapter import (
    adapt_sonar_response,
    extract_citations_from_text,
    is_sonar_model,
)


def test_is_sonar_model():
    assert is_sonar_model("sonar-pro") is True
    assert is_sonar_model("sonar") is True
    assert is_sonar_model("anthropic--claude-4.6-sonnet") is False
    assert is_sonar_model("gpt-5") is False


def test_passthrough_valid_json():
    raw = '{"thesis": "AI is transforming search", "findings": [], "status": "draft_ready"}'
    result = adapt_sonar_response(raw)
    assert result["thesis"] == "AI is transforming search"
    assert result["status"] == "draft_ready"


def test_adapts_natural_language_to_schema():
    prose = (
        "AI-powered search engines are transforming how users access information.\n\n"
        "Traditional search engines rely on keyword matching, while AI search uses "
        "semantic understanding to provide direct answers [1]. This shift has been "
        "accelerated by large language models [2].\n\n"
        "However, concerns about accuracy and hallucination remain significant "
        "challenges for the industry [3]."
    )
    result = adapt_sonar_response(prose)
    assert "thesis" in result
    assert "findings" in result
    assert "status" in result
    assert result["status"] == "draft_ready"
    assert len(result["findings"]) >= 2
    # Second finding should have citation refs from [1] and [2]
    findings_with_refs = [f for f in result["findings"] if f["source_ids"]]
    assert len(findings_with_refs) >= 1


def test_extracts_inline_citations():
    text = (
        "According to [research](https://example.com/paper1), AI search is growing. "
        "See also [this report](https://example.com/report2) for details."
    )
    urls = extract_citations_from_text(text)
    assert "https://example.com/paper1" in urls
    assert "https://example.com/report2" in urls
    assert len(urls) == 2


def test_handles_empty_response():
    result = adapt_sonar_response("")
    assert result["thesis"] == ""
    assert result["findings"] == []
    assert result["status"] == "blocked"


def test_handles_partial_json():
    raw = '```json\n{"thesis": "partial", "findings": [{"claim": "test"'
    result = adapt_sonar_response(raw)
    # Should fall through to prose mapping since JSON is incomplete
    assert "thesis" in result
    assert isinstance(result["findings"], list)


def test_extract_citations_deduplicates():
    text = (
        "See [A](https://example.com/a) and [B](https://example.com/a) "
        "and [C](https://example.com/b)."
    )
    urls = extract_citations_from_text(text)
    assert urls == ["https://example.com/a", "https://example.com/b"]


def test_sonar_urls_in_adapted_response():
    prose = (
        "The technology uses [transformers](https://arxiv.org/abs/1706.03762) "
        "as described in the original paper.\n\n"
        "Modern implementations leverage [BERT](https://huggingface.co/bert) "
        "for encoding."
    )
    result = adapt_sonar_response(prose)
    assert "_sonar_urls" in result
    assert "https://arxiv.org/abs/1706.03762" in result["_sonar_urls"]
