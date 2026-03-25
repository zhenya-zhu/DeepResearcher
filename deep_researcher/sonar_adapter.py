"""Adapter for Sonar-pro responses that may not follow strict JSON schemas.

Sonar-pro is a search-augmented LLM that returns natural language with inline
citations ([1], [2], etc.) and sometimes a citations array. When the researcher
prompt asks for JSON, Sonar may return valid JSON, partially valid JSON, or
plain prose. This adapter handles all three cases.
"""

import re
from typing import Any, Dict, List

from deep_researcher.json_utils import extract_first_json


def is_sonar_model(model_name: str) -> bool:
    """Check if the model name refers to a Sonar variant."""
    return "sonar" in model_name.lower()


def extract_citations_from_text(text: str) -> List[str]:
    """Extract URLs from inline markdown links in Sonar responses.

    Sonar often returns citations as markdown links like [Title](url) or
    numbered references [1] with a references section at the end.
    """
    urls: List[str] = []
    for match in re.finditer(r'\[(?:[^\]]*)\]\((https?://[^\)]+)\)', text):
        url = match.group(1).strip()
        if url not in urls:
            urls.append(url)
    return urls


def _split_into_findings(text: str) -> List[Dict[str, Any]]:
    """Split prose text into individual finding dicts.

    Looks for paragraph breaks or numbered points to split into
    separate findings with inline citations preserved.
    """
    findings: List[Dict[str, Any]] = []
    paragraphs = re.split(r'\n\s*\n', text.strip())
    for para in paragraphs:
        para = para.strip()
        if not para or len(para) < 20:
            continue
        citation_ids = []
        for ref_match in re.finditer(r'\[(\d+)\]', para):
            citation_ids.append("sonar-ref-{0}".format(ref_match.group(1)))
        findings.append({
            "claim": para[:300],
            "source_ids": citation_ids,
            "confidence": "medium",
        })
    return findings[:10]


def adapt_sonar_response(raw_text: str) -> Dict[str, Any]:
    """Attempt to parse Sonar output into the researcher JSON schema.

    First tries standard JSON extraction. If that fails, maps the natural
    language response to the expected schema structure.

    Expected researcher schema:
        {
            "thesis": str,
            "key_drivers": [str],
            "reasoning_steps": [str],
            "counterpoints": [str],
            "summary": str,
            "findings": [{"claim": str, "source_ids": [str], "confidence": str}],
            "open_questions": [str],
            "follow_up_queries": [str],
            "status": str
        }
    """
    if not raw_text or not raw_text.strip():
        return _empty_response()

    try:
        parsed = extract_first_json(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, RuntimeError):
        pass

    return _map_prose_to_schema(raw_text)


def _map_prose_to_schema(text: str) -> Dict[str, Any]:
    """Map a natural language Sonar response to the researcher JSON schema."""
    lines = text.strip().splitlines()
    first_para = ""
    for line in lines:
        line = line.strip()
        if line:
            first_para = line
            break

    findings = _split_into_findings(text)
    urls = extract_citations_from_text(text)

    return {
        "thesis": first_para[:500] if first_para else "Unable to extract thesis from response.",
        "key_drivers": [],
        "reasoning_steps": [],
        "counterpoints": [],
        "summary": text[:1000],
        "findings": findings,
        "open_questions": [],
        "follow_up_queries": [],
        "status": "draft_ready",
        "_sonar_urls": urls,
    }


def _empty_response() -> Dict[str, Any]:
    """Return an empty researcher schema for blank responses."""
    return {
        "thesis": "",
        "key_drivers": [],
        "reasoning_steps": [],
        "counterpoints": [],
        "summary": "",
        "findings": [],
        "open_questions": [],
        "follow_up_queries": [],
        "status": "blocked",
    }
