from typing import Any
import json
import re


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if match:
        return match.group(1)
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            body_lines = lines[1:]
            if body_lines and body_lines[-1].strip() == "```":
                body_lines = body_lines[:-1]
            return "\n".join(body_lines).strip()
    return text


def _repair_jsonish_text(text: str) -> str:
    repaired_lines = []
    for line in text.splitlines():
        match = re.match(r'(\s*"[^"]+"\s*:\s*")(.*?)("\s*,?\s*)$', line)
        if not match:
            repaired_lines.append(line)
            continue
        prefix, content, suffix = match.groups()
        content = re.sub(r'(?<!\\)"', r'\\"', content)
        repaired_lines.append(prefix + content + suffix)
    return "\n".join(repaired_lines)


def _decode_first_json(text: str) -> Any:
    decoder = json.JSONDecoder()
    first_value = None
    for match in re.finditer(r"[\[{]", text):
        start = match.start()
        try:
            value, _ = decoder.raw_decode(text[start:])
            if isinstance(value, dict):
                return value
            if first_value is None:
                first_value = value
        except json.JSONDecodeError:
            continue
    if first_value is not None:
        return first_value
    raise ValueError("No JSON object found in model response.")


def _decode_from_start(text: str) -> Any:
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "[{":
        raise ValueError("Candidate does not start with JSON.")
    decoder = json.JSONDecoder()
    value, _ = decoder.raw_decode(stripped)
    return value


def extract_first_json(text: str) -> Any:
    stripped = _strip_code_fence(text)
    candidates = [stripped] if stripped != text else [text]
    for candidate in candidates:
        normalized = candidate.lstrip()
        if normalized.startswith("{") or normalized.startswith("["):
            try:
                parsed = _decode_from_start(candidate)
                if isinstance(parsed, dict):
                    return parsed
                raise ValueError("Expected JSON object at response start.")
            except Exception:
                repaired = _repair_jsonish_text(candidate)
                if repaired != candidate:
                    try:
                        parsed = _decode_from_start(repaired)
                        if isinstance(parsed, dict):
                            return parsed
                    except Exception:
                        pass
                raise ValueError("Top-level JSON object is invalid or incomplete.")
        try:
            return _decode_first_json(candidate)
        except ValueError:
            repaired = _repair_jsonish_text(candidate)
            if repaired != candidate:
                try:
                    return _decode_first_json(repaired)
                except ValueError:
                    continue
    raise ValueError("No JSON object found in model response.")


def dumps_pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
