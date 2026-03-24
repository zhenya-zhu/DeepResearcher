from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import os
import re


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_choice(name: str, default: str, allowed: List[str]) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in allowed:
        return normalized
    return default


def _env_int_alias(names: List[str], default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value is None or value == "":
            continue
        try:
            return int(value)
        except ValueError:
            continue
    return default


def _split_models(raw: Optional[str], defaults: List[str]) -> List[str]:
    if not raw:
        return list(defaults)
    parts = [item.strip() for item in raw.split(",")]
    return [item for item in parts if item] or list(defaults)


def _split_paths(raw: Optional[str]) -> List[Path]:
    if not raw:
        return []
    parts = [item.strip() for item in re.split(r"[\n{0}]".format(re.escape(os.pathsep)), raw)]
    return [Path(item) for item in parts if item]


@dataclass
class ModelSelection:
    candidates: List[str]
    temperature: float = 0.2
    max_output_tokens: int = 1800


@dataclass
class AppConfig:
    base_url: str = "http://localhost:6655/litellm/v1"
    anthropic_base_url: str = "http://localhost:6655/anthropic/v1"
    anthropic_version: str = "2023-06-01"
    api_key: str = ""
    proxy_url: str = "http://proxy.sin.sap.corp:8080"
    network_mode: str = "auto"
    semantic_mode: str = "hybrid"
    timeout_seconds: int = 120
    rpm_limit: int = 16
    max_rounds: int = 3
    max_sections: int = 7
    max_queries_per_section: int = 3
    max_results_per_query: int = 8
    max_sources_per_section: int = 8
    max_chars_per_source: int = 4000
    search_region: str = "us-en"
    run_root: Path = field(default_factory=lambda: Path("runs"))
    model_capabilities_file: Optional[Path] = None
    evidence_profiles_file: Optional[Path] = None
    source_packs_file: Optional[Path] = None
    workspace_sources: List[Path] = field(default_factory=list)
    use_mock_llm: bool = False
    use_mock_tools: bool = False
    verbose: bool = True
    max_workspace_documents: int = 16
    max_workspace_sources_per_section: int = 3
    max_chars_per_workspace_document: int = 120000
    max_chars_per_workspace_excerpt: int = 2600
    planner: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
        temperature=0.2,
        max_output_tokens=8000,
    ))
    researcher: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
        temperature=0.2,
        max_output_tokens=5000,
    ))
    writer: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.6-sonnet", "gpt-5", "anthropic--claude-4.6-opus"],
        temperature=0.2,
        max_output_tokens=12000,
    ))
    verifier: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
        temperature=0.0,
        max_output_tokens=8000,
    ))
    fast: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.5-haiku", "gpt-5-mini", "sonar"],
        temperature=0.1,
        max_output_tokens=1000,
    ))

    @classmethod
    def from_env(cls) -> "AppConfig":
        api_key = os.getenv("DEEP_RESEARCHER_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        config = cls(
            base_url=os.getenv("DEEP_RESEARCHER_BASE_URL", "http://localhost:6655/litellm/v1"),
            anthropic_base_url=os.getenv("DEEP_RESEARCHER_ANTHROPIC_BASE_URL", "http://localhost:6655/anthropic/v1"),
            anthropic_version=os.getenv("DEEP_RESEARCHER_ANTHROPIC_VERSION", "2023-06-01"),
            api_key=api_key,
            proxy_url=os.getenv("DEEP_RESEARCHER_PROXY_URL", "http://proxy.sin.sap.corp:8080"),
            network_mode=_env_choice("DEEP_RESEARCHER_NETWORK_MODE", "auto", ["auto", "proxy", "direct"]),
            semantic_mode=_env_choice("DEEP_RESEARCHER_SEMANTIC_MODE", "hybrid", ["hybrid", "native"]),
            timeout_seconds=_env_int("DEEP_RESEARCHER_TIMEOUT_SECONDS", 120),
            rpm_limit=_env_int("DEEP_RESEARCHER_RPM_LIMIT", 16),
            max_rounds=_env_int("DEEP_RESEARCHER_MAX_ROUNDS", 3),
            max_sections=_env_int("DEEP_RESEARCHER_MAX_SECTIONS", 7),
            max_queries_per_section=_env_int("DEEP_RESEARCHER_MAX_QUERIES_PER_SECTION", 3),
            max_results_per_query=_env_int("DEEP_RESEARCHER_MAX_RESULTS_PER_QUERY", 8),
            max_sources_per_section=_env_int("DEEP_RESEARCHER_MAX_SOURCES_PER_SECTION", 8),
            max_chars_per_source=_env_int("DEEP_RESEARCHER_MAX_CHARS_PER_SOURCE", 4000),
            search_region=os.getenv("DEEP_RESEARCHER_SEARCH_REGION", "us-en"),
            run_root=Path(os.getenv("DEEP_RESEARCHER_RUN_ROOT", "runs")),
            model_capabilities_file=(
                Path(os.getenv("DEEP_RESEARCHER_MODEL_CAPABILITIES_FILE"))
                if os.getenv("DEEP_RESEARCHER_MODEL_CAPABILITIES_FILE")
                else None
            ),
            evidence_profiles_file=(
                Path(os.getenv("DEEP_RESEARCHER_EVIDENCE_PROFILES_FILE"))
                if os.getenv("DEEP_RESEARCHER_EVIDENCE_PROFILES_FILE")
                else None
            ),
            source_packs_file=(
                Path(os.getenv("DEEP_RESEARCHER_SOURCE_PACKS_FILE"))
                if os.getenv("DEEP_RESEARCHER_SOURCE_PACKS_FILE")
                else None
            ),
            workspace_sources=_split_paths(os.getenv("DEEP_RESEARCHER_WORKSPACE_SOURCES")),
            use_mock_llm=_env_bool("DEEP_RESEARCHER_USE_MOCK_LLM", False),
            use_mock_tools=_env_bool("DEEP_RESEARCHER_USE_MOCK_TOOLS", False),
            max_workspace_documents=_env_int("DEEP_RESEARCHER_MAX_WORKSPACE_DOCUMENTS", 16),
            max_workspace_sources_per_section=_env_int("DEEP_RESEARCHER_MAX_WORKSPACE_SOURCES_PER_SECTION", 3),
            max_chars_per_workspace_document=_env_int("DEEP_RESEARCHER_MAX_CHARS_PER_WORKSPACE_DOCUMENT", 120000),
            max_chars_per_workspace_excerpt=_env_int("DEEP_RESEARCHER_MAX_CHARS_PER_WORKSPACE_EXCERPT", 2600),
        )
        config.planner = ModelSelection(
            candidates=_split_models(
                os.getenv("DEEP_RESEARCHER_PLANNER_MODELS"),
                ["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
            ),
            temperature=_env_float("DEEP_RESEARCHER_PLANNER_TEMPERATURE", 0.2),
            max_output_tokens=_env_int_alias(
                ["DEEP_RESEARCHER_PLANNER_MAX_OUTPUT_TOKENS", "DEEP_RESEARCHER_PLANNER_MAX_TOKENS"],
                8000,
            ),
        )
        config.researcher = ModelSelection(
            candidates=_split_models(
                os.getenv("DEEP_RESEARCHER_RESEARCHER_MODELS"),
                ["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
            ),
            temperature=_env_float("DEEP_RESEARCHER_RESEARCHER_TEMPERATURE", 0.2),
            max_output_tokens=_env_int_alias(
                ["DEEP_RESEARCHER_RESEARCHER_MAX_OUTPUT_TOKENS", "DEEP_RESEARCHER_RESEARCHER_MAX_TOKENS"],
                5000,
            ),
        )
        config.writer = ModelSelection(
            candidates=_split_models(
                os.getenv("DEEP_RESEARCHER_WRITER_MODELS"),
                ["anthropic--claude-4.6-sonnet", "gpt-5", "anthropic--claude-4.6-opus"],
            ),
            temperature=_env_float("DEEP_RESEARCHER_WRITER_TEMPERATURE", 0.2),
            max_output_tokens=_env_int_alias(
                ["DEEP_RESEARCHER_WRITER_MAX_OUTPUT_TOKENS", "DEEP_RESEARCHER_WRITER_MAX_TOKENS"],
                12000,
            ),
        )
        config.verifier = ModelSelection(
            candidates=_split_models(
                os.getenv("DEEP_RESEARCHER_VERIFIER_MODELS"),
                ["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
            ),
            temperature=_env_float("DEEP_RESEARCHER_VERIFIER_TEMPERATURE", 0.0),
            max_output_tokens=_env_int_alias(
                ["DEEP_RESEARCHER_VERIFIER_MAX_OUTPUT_TOKENS", "DEEP_RESEARCHER_VERIFIER_MAX_TOKENS"],
                8000,
            ),
        )
        config.fast = ModelSelection(
            candidates=_split_models(
                os.getenv("DEEP_RESEARCHER_FAST_MODELS"),
                ["anthropic--claude-4.5-haiku", "gpt-5-mini", "sonar"],
            ),
            temperature=_env_float("DEEP_RESEARCHER_FAST_TEMPERATURE", 0.1),
            max_output_tokens=_env_int_alias(
                ["DEEP_RESEARCHER_FAST_MAX_OUTPUT_TOKENS", "DEEP_RESEARCHER_FAST_MAX_TOKENS"],
                1000,
            ),
        )
        return config
