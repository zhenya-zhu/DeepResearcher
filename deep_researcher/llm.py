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
            semantic_mode = (_extract_marker(joined, "SEMANTIC_MODE") or "hybrid").strip().lower()
            response = {
                "objective": "Deliver a structured research brief for: {0}".format(question),
                "research_brief": "Focus on market shape, technical options, risks, and recommendations.",
                "input_dependencies": [],
                "source_requirements": ["Public web sources", "Primary documentation when available"],
                "comparison_axes": ["Problem framing", "Execution approach", "Risks"],
                "success_criteria": [
                    "Covers current landscape",
                    "Explains technical tradeoffs",
                    "Surfaces major risks",
                ],
                "risks": ["Source freshness", "Vendor bias"],
                "sections": _mock_planner_sections(question, semantic_mode=semantic_mode),
            }
            return json.dumps(response, ensure_ascii=False)
        if "TASK_KIND: section_research" in joined:
            section_title = _extract_marker(joined, "SECTION_TITLE") or "Section"
            source_ids = re.findall(r"S\d{3}", joined)[:3] or ["S001"]
            response = {
                "thesis": "{0} shows a defensible pattern once the evidence is connected into explicit drivers.".format(section_title),
                "key_drivers": [
                    "{0} has a primary growth or positioning driver visible in the collected evidence.".format(section_title),
                    "The available sources expose at least one tradeoff or constraint that affects the conclusion.",
                ],
                "reasoning_steps": [
                    {
                        "observation": "Collected evidence highlights multiple concrete signals for {0}.".format(section_title),
                        "inference": "{0} can be analyzed through a driver-and-tradeoff lens instead of flat description.".format(section_title),
                        "implication": "The final report should explain why the section matters, not only what facts were found.",
                        "source_ids": source_ids[:2],
                    }
                ],
                "counterpoints": [
                    "Some evidence remains partial, so final claims should preserve uncertainty where coverage is thin."
                ],
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
                "gap_tasks": [],
            }, ensure_ascii=False)
        if "TASK_KIND: audit" in joined:
            return json.dumps({
                "status": "pass",
                "issues": [],
            }, ensure_ascii=False)
        if "TASK_KIND: report_section_writer" in joined:
            title = _extract_marker(joined, "SECTION_TITLE")
            if not title:
                match = re.search(r'"title":\s*"([^"]+)"', joined)
                title = match.group(1) if match else "Section"
            return "\n".join([
                "## {0}".format(title),
                "",
                "**Core Judgment**: {0} can be written as an analytical section instead of a flat fact list. [source:S001]".format(title),
                "",
                "**Why this matters**: the evidence packet carries drivers and reasoning steps that support a decision-useful interpretation. [source:S002]",
                "",
                "- The section packet includes traceable findings and can preserve citations. [source:S001]",
                "- Counterpoints can be stated explicitly when the evidence is incomplete. [source:S002]",
            ])
        if "TASK_KIND: report_overview" in joined:
            return json.dumps({
                "title": "# Mock Deep Research Report",
                "executive_summary": [
                    "The run now assembles the report from smaller section-writing steps instead of relying on one long final write.",
                    "This reduces the probability that the final writer call times out and still preserves analytical structure.",
                ],
                "conclusion": [
                    "Hierarchical report assembly is more robust for long research runs.",
                    "Section-level fallbacks keep the workflow debuggable even when a writer call fails.",
                ],
            }, ensure_ascii=False)
        if "TASK_KIND: report_writer" in joined:
            return (
                "# Mock Deep Research Report\n\n"
                "## Executive Summary\n\n"
                "- This legacy path remains available for compatibility. [source:S001]\n"
            )
        return "{}"


def _extract_marker(text: str, key: str) -> str:
    pattern = r"{0}:\s*(.+)".format(re.escape(key))
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-") or "artifact"


def _mock_evidence_requirement(
    profile_id: str,
    priority: str,
    must_cover: List[str],
    query_hints: List[str],
    preferred_source_packs: List[str] = None,
    rationale: str = "",
) -> Dict[str, object]:
    return {
        "profile_id": profile_id,
        "priority": priority,
        "must_cover": must_cover,
        "preferred_source_packs": preferred_source_packs or [],
        "query_hints": query_hints,
        "rationale": rationale or "Mock planner selected this evidence profile for the section.",
    }


def _mock_planner_sections(question: str, semantic_mode: str = "hybrid") -> List[Dict[str, object]]:
    lowered = question.lower()
    if "阳光电源" in question or "roe" in lowered or "格雷厄姆" in question or "彼得林奇" in question:
        native = semantic_mode == "native"
        return [
            {
                "id": "history",
                "title": "发展历程与业务演进",
                "goal": "梳理公司从单点产品到多业务平台的演进脉络。",
                "queries": (
                    ["阳光电源 官方 年报 发展历程", "阳光电源 投资者关系 业务演进"]
                    if native else
                    ["阳光电源 发展历程 主营业务", "阳光电源 官方 年报 业务演进"]
                ),
                "must_cover": ["关键里程碑", "业务扩张路径", "技术平台演进"],
                "evidence_requirements": [
                    _mock_evidence_requirement(
                        "primary_source",
                        "high",
                        ["关键里程碑", "业务扩张路径"],
                        ["official report", "investor relations"],
                        ["official_docs_pack"],
                    ),
                    _mock_evidence_requirement(
                        "timeline_history",
                        "medium",
                        ["关键里程碑", "技术平台演进"],
                        ["timeline", "history"],
                    ),
                ],
            },
            {
                "id": "financials",
                "title": "财务质量与关键指标",
                "goal": "解释盈利质量、成长性和需要补齐的核心指标。",
                "queries": (
                    ["阳光电源 site:cn.tradingview.com ROE EPS PEG", "阳光电源 site:futunn.com 营收 净利润 杜邦分析"]
                    if native else
                    ["阳光电源 ROE 营收 净利润", "阳光电源 杜邦分析 估值"]
                ),
                "must_cover": ["ROE", "营收与净利润", "估值指标"],
                "evidence_requirements": [
                    _mock_evidence_requirement(
                        "primary_source",
                        "high",
                        ["ROE", "营收与净利润"],
                        ["annual report", "quarterly report"],
                        ["official_docs_pack"],
                    ),
                    _mock_evidence_requirement(
                        "quantitative_metric",
                        "high",
                        ["ROE", "估值指标"],
                        ["metrics", "valuation", "eps", "peg"],
                        ["market_data_pack"],
                    ),
                    _mock_evidence_requirement(
                        "derivation",
                        "high",
                        ["杜邦分析", "ROE"],
                        ["drivers", "decomposition"],
                    ),
                    _mock_evidence_requirement(
                        "comparative_benchmark",
                        "medium",
                        ["竞争对手对比", "行业位置"],
                        ["peer comparison", "market share"],
                        ["market_data_pack"],
                    ),
                ],
            },
        ]
    if "tpu" in lowered or "光模块" in question or "supply chain" in lowered:
        native = semantic_mode == "native"
        return [
            {
                "id": "architecture",
                "title": "方案结构与关键组件",
                "goal": "解释新方案的核心结构、部件和技术变化。",
                "queries": (
                    ["Google TPU optical module official blog", "Google TPU optical module architecture paper"]
                    if native else
                    ["Google TPU optical module architecture", "Google TPU 光模块 方案"]
                ),
                "must_cover": ["光模块方案", "关键组件", "系统结构"],
                "evidence_requirements": [
                    _mock_evidence_requirement(
                        "implementation_detail",
                        "high",
                        ["光模块方案", "系统结构"],
                        ["architecture", "implementation"],
                    ),
                    _mock_evidence_requirement(
                        "structural_breakdown",
                        "high",
                        ["关键组件", "模块分解"],
                        ["components", "breakdown"],
                    ),
                ],
            },
            {
                "id": "supply-chain",
                "title": "上游供应链与生态依赖",
                "goal": "识别关键供应商和产业链依赖关系。",
                "queries": (
                    ["Google TPU optical module suppliers", "TPU optical module upstream supply chain"]
                    if native else
                    ["Google TPU optical module suppliers", "TPU 光模块 上游 供应链"]
                ),
                "must_cover": ["供应商", "上游环节", "生态依赖"],
                "evidence_requirements": [
                    _mock_evidence_requirement(
                        "ecosystem_supply_chain",
                        "high",
                        ["供应商", "上游环节", "生态依赖"],
                        ["supplier", "upstream"],
                        ["supply_chain_pack"],
                    ),
                    _mock_evidence_requirement(
                        "structural_breakdown",
                        "medium",
                        ["器件与环节映射"],
                        ["component mapping"],
                        ["supply_chain_pack"],
                    ),
                ],
            },
        ]
    native = semantic_mode == "native"
    return [
        {
            "id": "context",
            "title": "Context and Scope",
            "goal": "Clarify the problem, market, and scope.",
            "queries": (
                ["{0} official blog".format(question), "{0} overview".format(question)]
                if native else
                [question, "{0} overview".format(question)]
            ),
            "must_cover": ["Problem definition", "Scope boundaries"],
            "evidence_requirements": [
                _mock_evidence_requirement(
                    "primary_source",
                    "high",
                    ["Problem definition"],
                    ["official docs", "official blog"],
                    ["official_docs_pack"],
                ),
            ],
        },
        {
            "id": "landscape",
            "title": "Landscape",
            "goal": "Map major players and approaches.",
            "queries": ["{0} landscape".format(question), "{0} competitors".format(question)],
            "must_cover": ["Major players", "Approach differences"],
            "evidence_requirements": [
                _mock_evidence_requirement(
                    "comparative_benchmark",
                    "medium",
                    ["Major players", "Approach differences"],
                    ["comparison", "alternatives"],
                ),
            ],
        },
        {
            "id": "mechanics",
            "title": "Mechanics and Implementation",
            "goal": "Explain how the subject works in practice.",
            "queries": (
                ["{0} github repo".format(question), "{0} architecture".format(question)]
                if native else
                ["{0} implementation".format(question), "{0} architecture".format(question)]
            ),
            "must_cover": ["Execution approach", "Tooling or system design"],
            "evidence_requirements": [
                _mock_evidence_requirement(
                    "implementation_detail",
                    "high",
                    ["Execution approach", "Tooling or system design"],
                    ["implementation", "architecture"],
                    ["repo_pack"],
                ),
            ],
        },
        {
            "id": "recommendation",
            "title": "Recommendation",
            "goal": "Provide a decision-oriented recommendation.",
            "queries": ["{0} best practices".format(question), "{0} implementation strategy".format(question)],
            "must_cover": ["Recommended approach", "Implementation guidance"],
            "evidence_requirements": [
                _mock_evidence_requirement(
                    "primary_source",
                    "medium",
                    ["Recommended approach"],
                    ["best practices", "official guidance"],
                    ["official_docs_pack"],
                ),
            ],
        },
    ]


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
