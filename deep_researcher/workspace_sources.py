from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List
import csv
import json
import re

from .search import extract_relevant_passages

try:
    from pypdf import PdfReader  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    PdfReader = None


_SUPPORTED_SUFFIXES = {".txt", ".md", ".rst", ".json", ".csv", ".tsv", ".pdf"}
_AUTO_SOURCE_DIRS = ("workspace_sources", "workspace", "inputs", "reports", "private_sources")
_EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "runs",
    "tests",
    "docs",
    "plan",
    "deep_researcher",
    "deep_researcher.egg-info",
}
_FILE_HINTS = (
    "年报",
    "季报",
    "半年报",
    "财报",
    "公告",
    "report",
    "annual",
    "quarter",
    "quarterly",
    "financial",
    "earnings",
    "10-k",
    "10q",
)


@dataclass
class WorkspaceDocument:
    path: Path
    title: str
    text: str
    source_type: str


@dataclass
class WorkspaceEvidence:
    path: Path
    title: str
    excerpt: str
    snippet: str
    source_type: str
    score: int


def discover_workspace_documents(
    project_root: Path,
    configured_paths: List[Path],
    question: str,
    max_documents: int,
    max_chars_per_document: int,
) -> List[WorkspaceDocument]:
    documents = []
    seen = set()
    for path in _candidate_paths(project_root, configured_paths, question):
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        text = _read_workspace_text(path, max_chars_per_document)
        if not text.strip():
            continue
        documents.append(WorkspaceDocument(
            path=resolved,
            title=path.stem,
            text=text,
            source_type=path.suffix.lower().lstrip(".") or "text",
        ))
        if len(documents) >= max_documents:
            break
    return documents


def select_workspace_evidence(
    documents: List[WorkspaceDocument],
    question: str,
    section_title: str,
    section_queries: List[str],
    must_cover: List[str],
    max_documents: int,
    max_chars_per_excerpt: int,
) -> List[WorkspaceEvidence]:
    if not documents:
        return []
    query = " ".join(
        item
        for item in [
            question,
            section_title,
            " ".join(section_queries[:3]),
            " ".join(must_cover[:4]),
        ]
        if item
    ).strip()
    terms = _query_terms(query)
    scored = []
    for document in documents:
        meta = "{0} {1}".format(document.title, document.path.name).lower()
        body = document.text.lower()
        meta_score = sum(4 for term in terms if term in meta)
        body_score = sum(1 for term in terms if term in body)
        if not meta_score and not body_score and terms:
            continue
        excerpt = _compose_workspace_excerpt(
            document.text,
            query=query or document.title,
            must_cover=must_cover,
            max_chars=max_chars_per_excerpt,
        )
        if not excerpt.strip():
            continue
        excerpt_score = sum(2 for term in terms if term in excerpt.lower())
        score = meta_score + body_score + excerpt_score
        scored.append(WorkspaceEvidence(
            path=document.path,
            title=document.title,
            excerpt=excerpt.strip(),
            snippet=_first_snippet_line(excerpt),
            source_type=document.source_type,
            score=score,
        ))
    scored.sort(key=lambda item: (-item.score, len(item.excerpt), item.path.name.lower()))
    return scored[:max_documents]


def _candidate_paths(project_root: Path, configured_paths: List[Path], question: str) -> Iterable[Path]:
    if configured_paths:
        for path in configured_paths:
            resolved = path if path.is_absolute() else (project_root / path)
            if resolved.is_file():
                if resolved.suffix.lower() in _SUPPORTED_SUFFIXES:
                    yield resolved
                continue
            if resolved.is_dir():
                yield from _iter_supported_files(resolved)
        return

    for dirname in _AUTO_SOURCE_DIRS:
        candidate_dir = project_root / dirname
        if candidate_dir.is_dir():
            yield from _iter_supported_files(candidate_dir)

    question_hints = tuple(_query_terms(question))
    for child in sorted(project_root.iterdir()):
        if not child.is_file() or child.suffix.lower() not in _SUPPORTED_SUFFIXES:
            continue
        lowered = child.name.lower()
        if any(hint in lowered for hint in _FILE_HINTS) or any(hint in lowered for hint in question_hints):
            yield child


def _iter_supported_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in _EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
            continue
        yield path


def _read_workspace_text(path: Path, max_chars: int) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".rst"}:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    if suffix == ".json":
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        except json.JSONDecodeError:
            return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        return "\n".join(_json_to_lines(payload))[:max_chars]
    if suffix in {".csv", ".tsv"}:
        return _csv_to_text(path, delimiter="\t" if suffix == ".tsv" else ",", max_chars=max_chars)
    if suffix == ".pdf":
        return _pdf_to_text(path, max_chars=max_chars)
    return ""


def _json_to_lines(value: Any, prefix: str = "") -> List[str]:
    lines: List[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_prefix = "{0}.{1}".format(prefix, key) if prefix else str(key)
            lines.extend(_json_to_lines(item, child_prefix))
        return lines
    if isinstance(value, list):
        for index, item in enumerate(value):
            child_prefix = "{0}[{1}]".format(prefix, index) if prefix else "[{0}]".format(index)
            lines.extend(_json_to_lines(item, child_prefix))
        return lines
    rendered = "" if value is None else str(value)
    lines.append("{0}: {1}".format(prefix or "value", rendered))
    return lines


def _csv_to_text(path: Path, delimiter: str, max_chars: int) -> str:
    lines: List[str] = []
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        for row in reader:
            parts = []
            for key, value in row.items():
                normalized_key = (key or "").strip()
                normalized_value = (value or "").strip()
                if not normalized_key and not normalized_value:
                    continue
                parts.append("{0}: {1}".format(normalized_key or "column", normalized_value))
            if parts:
                lines.append(" | ".join(parts))
            if sum(len(line) for line in lines) >= max_chars:
                break
    return "\n".join(lines)[:max_chars]


def _pdf_to_text(path: Path, max_chars: int) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""
    chunks: List[str] = []
    current_size = 0
    for page in reader.pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_text = page_text.strip()
        if not page_text:
            continue
        remaining = max_chars - current_size
        if remaining <= 0:
            break
        page_text = page_text[:remaining]
        chunks.append(page_text)
        current_size += len(page_text)
    return "\n\n".join(chunks).strip()


def _query_terms(text: str) -> List[str]:
    cjk_terms = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    latin_terms = [token.lower() for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{1,}", text)]
    return list(dict.fromkeys(cjk_terms + latin_terms))


def _compose_workspace_excerpt(text: str, query: str, must_cover: List[str], max_chars: int) -> str:
    parts = []
    general = extract_relevant_passages(
        text,
        query,
        max_passages=4,
        max_chars=max_chars,
    ).strip()
    if general:
        parts.append(general)
    targeted_terms = _unique_terms(must_cover + _query_terms(query))
    for term in targeted_terms[:8]:
        snippet = _extract_targeted_lines(text, term, max_lines=4)
        if snippet and snippet not in parts:
            parts.append(snippet)
    combined = "\n\n".join(part for part in parts if part).strip()
    return combined[:max_chars].strip()


def _extract_targeted_lines(text: str, term: str, max_lines: int) -> str:
    normalized_term = term.strip()
    if not normalized_term:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    matched = []
    for index, line in enumerate(lines):
        if normalized_term.lower() not in line.lower():
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 2)
        for item in lines[start:end]:
            if item not in matched:
                matched.append(item)
            if len(matched) >= max_lines:
                break
        if len(matched) >= max_lines:
            break
    return "\n".join(matched).strip()


def _unique_terms(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(normalized)
    return result


def _first_snippet_line(text: str, max_chars: int = 220) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:max_chars]
    return text[:max_chars].strip()
