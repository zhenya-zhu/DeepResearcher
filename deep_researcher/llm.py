from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
import json
import math
import re
import time
import urllib.error
import urllib.request

from .config import ModelSelection
from .json_utils import extract_first_json
from .model_capabilities import ModelCapabilityRegistry, resolve_model_capability
from .tracing import RunArtifacts


@dataclass
class ModelResult:
    model: str
    content: str


@dataclass
class _CircuitState:
    failures: int = 0
    open_until: float = 0.0


def infer_context_window_tokens(model: str, capability_registry: ModelCapabilityRegistry = None) -> int:
    return resolve_model_capability(model, capability_registry).context_window_tokens


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def estimate_messages_tokens(messages: List[Dict[str, str]]) -> int:
    total = 0
    for message in messages:
        total += 6
        total += estimate_text_tokens(message.get("role", ""))
        total += estimate_text_tokens(message.get("content", ""))
    return total


def input_budget_tokens(
    model: str,
    max_output_tokens: int,
    reserve_tokens: int = 8192,
    capability_registry: ModelCapabilityRegistry = None,
) -> int:
    context_window_tokens = infer_context_window_tokens(model, capability_registry)
    budget = context_window_tokens - max_output_tokens - reserve_tokens
    return max(4096, budget)


class OpenAICompatibleBackend:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_output_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = "Bearer {0}".format(self.api_key)
        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError("LLM HTTP error {0}: {1}".format(exc.code, details)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("LLM connection failed: {0}".format(exc.reason)) from exc
        parsed = json.loads(raw)
        message = parsed["choices"][0]["message"]["content"]
        if isinstance(message, str):
            return message
        if isinstance(message, list):
            chunks = []
            for item in message:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        chunks.append(item.get("text", ""))
                    elif "text" in item:
                        chunks.append(item["text"])
            return "\n".join(chunks)
        return str(message)


class AnthropicCompatibleBackend:
    def __init__(self, base_url: str, api_key: str, anthropic_version: str, timeout_seconds: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.anthropic_version = anthropic_version
        self.timeout_seconds = timeout_seconds

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        system_parts = []
        anthropic_messages = []
        for message in messages:
            role = message["role"]
            content = message["content"]
            if role == "system":
                system_parts.append(content)
                continue
            if role not in {"user", "assistant"}:
                continue
            anthropic_messages.append({
                "role": role,
                "content": content,
            })

        payload = {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": anthropic_messages,
            "temperature": temperature,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.anthropic_version,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/messages",
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError("Anthropic HTTP error {0}: {1}".format(exc.code, details)) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Anthropic connection failed: {0}".format(exc.reason)) from exc

        parsed = json.loads(raw)
        content = parsed.get("content", [])
        if isinstance(content, list):
            chunks = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    chunks.append(item.get("text", ""))
            return "\n".join(chunks)
        return str(content)


class MultiProviderBackend:
    def __init__(self, openai_backend: OpenAICompatibleBackend, anthropic_backend: AnthropicCompatibleBackend) -> None:
        self.openai_backend = openai_backend
        self.anthropic_backend = anthropic_backend

    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        if model.startswith("anthropic--"):
            return self.anthropic_backend.chat(
                model=model,
                messages=messages,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        return self.openai_backend.chat(
            model=model,
            messages=messages,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )


class MockBackend:
    def chat(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> str:
        joined = "\n".join(message["content"] for message in messages)
        if "TASK_KIND: planner" in joined:
            question = _extract_marker(joined, "QUESTION") or "research task"
            response = {
                "objective": "Deliver a structured research brief for: {0}".format(question),
                "research_brief": "Focus on market shape, technical options, risks, and recommendations.",
                "success_criteria": [
                    "Covers current landscape",
                    "Explains technical tradeoffs",
                    "Surfaces major risks",
                ],
                "risks": ["Source freshness", "Vendor bias"],
                "sections": [
                    {
                        "id": "context",
                        "title": "Context and Scope",
                        "goal": "Clarify the problem, market, and scope.",
                        "queries": [question, "{0} overview".format(question)],
                    },
                    {
                        "id": "landscape",
                        "title": "Landscape",
                        "goal": "Map major players and approaches.",
                        "queries": ["{0} landscape".format(question), "{0} competitors".format(question)],
                    },
                    {
                        "id": "risks",
                        "title": "Risks and Constraints",
                        "goal": "Explain major delivery and adoption risks.",
                        "queries": ["{0} risks".format(question), "{0} limitations".format(question)],
                    },
                    {
                        "id": "recommendation",
                        "title": "Recommendation",
                        "goal": "Provide a decision-oriented recommendation.",
                        "queries": ["{0} best practices".format(question), "{0} implementation strategy".format(question)],
                    },
                ],
            }
            return json.dumps(response, ensure_ascii=False)
        if "TASK_KIND: section_research" in joined:
            section_title = _extract_marker(joined, "SECTION_TITLE") or "Section"
            source_ids = re.findall(r"S\d{3}", joined)[:3] or ["S001"]
            response = {
                "summary": "{0} is supported by the collected sources and can be drafted.".format(section_title),
                "findings": [
                    {
                        "claim": "{0} has multiple signals worth tracking.".format(section_title),
                        "source_ids": source_ids[:2],
                    },
                    {
                        "claim": "{0} should be evaluated with explicit constraints and tradeoffs.".format(section_title),
                        "source_ids": source_ids[-2:],
                    },
                ],
                "open_questions": [],
                "follow_up_queries": [],
                "confidence": "medium",
                "status": "draft_ready",
            }
            return json.dumps(response, ensure_ascii=False)
        if "TASK_KIND: gap_review" in joined:
            return json.dumps({
                "continue_research": False,
                "global_gaps": [],
                "focus_sections": [],
            }, ensure_ascii=False)
        if "TASK_KIND: audit" in joined:
            return json.dumps({
                "status": "pass",
                "issues": [],
            }, ensure_ascii=False)
        if "TASK_KIND: report_writer" in joined:
            return (
                "# Mock Deep Research Report\n\n"
                "## Executive Summary\n\n"
                "This report was generated in mock mode to validate the workflow.\n\n"
                "## Findings\n\n"
                "- The workflow can plan, collect evidence, and synthesize sections. [source:S001]\n"
                "- The trace and checkpoints make intermediate debugging straightforward. [source:S002]\n"
            )
        return "{}"


def _extract_marker(text: str, key: str) -> str:
    pattern = r"{0}:\s*(.+)".format(re.escape(key))
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "artifact"


def render_messages(messages: List[Dict[str, str]]) -> str:
    parts = []
    for index, message in enumerate(messages, start=1):
        parts.append("## Message {0} [{1}]\n\n{2}".format(index, message["role"], message["content"]))
    return "\n\n".join(parts)


class ModelRouter:
    def __init__(
        self,
        backend: Any,
        rate_limiter: Any,
        tracker: RunArtifacts,
        capability_registry: ModelCapabilityRegistry = None,
    ) -> None:
        self.backend = backend
        self.rate_limiter = rate_limiter
        self.tracker = tracker
        self.capability_registry = capability_registry
        self.circuit: Dict[str, _CircuitState] = {}
        self.cooldown_seconds = 60.0
        self.failure_threshold = 2
        self.max_attempts_per_model = 2

    def _state(self, model: str) -> _CircuitState:
        if model not in self.circuit:
            self.circuit[model] = _CircuitState()
        return self.circuit[model]

    def complete_text(self, task_name: str, messages: List[Dict[str, str]], selection: ModelSelection) -> ModelResult:
        last_error = None
        prompt_token_estimate = estimate_messages_tokens(messages)
        prompt_artifact = self.tracker.write_text(
            "artifacts/prompts/{0}.md".format(_safe_name(task_name)),
            render_messages(messages),
        )
        for model in selection.candidates:
            capability = resolve_model_capability(model, self.capability_registry)
            context_window_tokens = capability.context_window_tokens
            prompt_budget_tokens = input_budget_tokens(
                model,
                selection.max_output_tokens,
                capability_registry=self.capability_registry,
            )
            state = self._state(model)
            now = time.monotonic()
            if state.open_until > now:
                self.tracker.log(
                    "llm",
                    task_name,
                    "Skipping model in cooldown: {0}".format(model),
                    level="WARN",
                    data={"model": model, "cooldown_until": state.open_until},
                    artifacts={"prompt": prompt_artifact},
                )
                continue
            if prompt_token_estimate > prompt_budget_tokens:
                self.tracker.log(
                    "context",
                    task_name,
                    "Prompt estimate exceeds configured input budget",
                    level="WARN",
                    data={
                        "model": model,
                        "context_window_tokens": context_window_tokens,
                        "model_family": capability.family,
                        "capability_match": capability.matched_pattern,
                        "capability_match_type": capability.matched_by,
                        "capability_source_url": capability.source_url,
                        "prompt_token_estimate": prompt_token_estimate,
                        "prompt_budget_tokens": prompt_budget_tokens,
                        "max_output_tokens": selection.max_output_tokens,
                    },
                    artifacts={"prompt": prompt_artifact},
                )
            for attempt in range(1, self.max_attempts_per_model + 1):
                waited = self.rate_limiter.wait()
                if waited > 0:
                    self.tracker.log(
                        "llm",
                        task_name,
                        "Rate limiter delayed model call",
                        data={"model": model, "wait_seconds": round(waited, 2)},
                        artifacts={"prompt": prompt_artifact},
                    )
                try:
                    content = self.backend.chat(
                        model=model,
                        messages=messages,
                        temperature=selection.temperature,
                        max_output_tokens=selection.max_output_tokens,
                    )
                    response_artifact = self.tracker.write_text(
                        "artifacts/responses/{0}-{1}.md".format(_safe_name(task_name), _safe_name(model)),
                        content,
                    )
                    state.failures = 0
                    state.open_until = 0.0
                    self.tracker.log(
                        "llm",
                        task_name,
                        "Model call succeeded",
                        data={
                            "model": model,
                            "attempt": attempt,
                            "context_window_tokens": context_window_tokens,
                            "model_family": capability.family,
                            "capability_match": capability.matched_pattern,
                            "capability_match_type": capability.matched_by,
                            "capability_source_url": capability.source_url,
                            "prompt_token_estimate": prompt_token_estimate,
                            "prompt_budget_tokens": prompt_budget_tokens,
                            "max_output_tokens": selection.max_output_tokens,
                        },
                        artifacts={"prompt": prompt_artifact, "response": response_artifact},
                    )
                    return ModelResult(model=model, content=content)
                except Exception as exc:
                    last_error = exc
                    state.failures += 1
                    if state.failures >= self.failure_threshold:
                        state.open_until = time.monotonic() + self.cooldown_seconds
                    self.tracker.log(
                        "llm",
                        task_name,
                        "Model call failed",
                        level="ERROR",
                        data={
                            "model": model,
                            "attempt": attempt,
                            "error": str(exc),
                            "failures": state.failures,
                            "cooldown_until": state.open_until,
                            "context_window_tokens": context_window_tokens,
                            "model_family": capability.family,
                            "capability_match": capability.matched_pattern,
                            "capability_match_type": capability.matched_by,
                            "capability_source_url": capability.source_url,
                            "prompt_token_estimate": prompt_token_estimate,
                            "prompt_budget_tokens": prompt_budget_tokens,
                            "max_output_tokens": selection.max_output_tokens,
                        },
                        artifacts={"prompt": prompt_artifact},
                    )
                    if attempt < self.max_attempts_per_model:
                        time.sleep(min(attempt, 2))
        raise RuntimeError("All candidate models failed for {0}: {1}".format(task_name, last_error))

    def complete_json(self, task_name: str, messages: List[Dict[str, str]], selection: ModelSelection) -> Tuple[str, Dict[str, Any]]:
        result = self.complete_text(task_name, messages, selection)
        try:
            parsed = extract_first_json(result.content)
        except Exception as exc:
            raise RuntimeError("JSON parsing failed for {0} via model {1}: {2}".format(task_name, result.model, exc)) from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Expected JSON object for {0}, got {1}".format(task_name, type(parsed).__name__))
        return result.model, parsed
