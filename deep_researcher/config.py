from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import os


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
    timeout_seconds: int = 120
    rpm_limit: int = 16
    max_rounds: int = 2
    max_sections: int = 5
    max_queries_per_section: int = 2
    max_results_per_query: int = 4
    max_sources_per_section: int = 3
    max_chars_per_source: int = 2200
    search_region: str = "us-en"
    run_root: Path = field(default_factory=lambda: Path("runs"))
    model_capabilities_file: Optional[Path] = None
    use_mock_llm: bool = False
    use_mock_tools: bool = False
    planner: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
        temperature=0.2,
        max_output_tokens=4000,
    ))
    researcher: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
        temperature=0.2,
        max_output_tokens=2200,
    ))
    writer: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.6-sonnet", "gpt-5", "anthropic--claude-4.6-opus"],
        temperature=0.2,
        max_output_tokens=2600,
    ))
    verifier: ModelSelection = field(default_factory=lambda: ModelSelection(
        candidates=["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
        temperature=0.0,
        max_output_tokens=1800,
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
            timeout_seconds=_env_int("DEEP_RESEARCHER_TIMEOUT_SECONDS", 120),
            rpm_limit=_env_int("DEEP_RESEARCHER_RPM_LIMIT", 16),
            max_rounds=_env_int("DEEP_RESEARCHER_MAX_ROUNDS", 2),
            max_sections=_env_int("DEEP_RESEARCHER_MAX_SECTIONS", 5),
            max_queries_per_section=_env_int("DEEP_RESEARCHER_MAX_QUERIES_PER_SECTION", 2),
            max_results_per_query=_env_int("DEEP_RESEARCHER_MAX_RESULTS_PER_QUERY", 4),
            max_sources_per_section=_env_int("DEEP_RESEARCHER_MAX_SOURCES_PER_SECTION", 3),
            max_chars_per_source=_env_int("DEEP_RESEARCHER_MAX_CHARS_PER_SOURCE", 2200),
            search_region=os.getenv("DEEP_RESEARCHER_SEARCH_REGION", "us-en"),
            run_root=Path(os.getenv("DEEP_RESEARCHER_RUN_ROOT", "runs")),
            model_capabilities_file=(
                Path(os.getenv("DEEP_RESEARCHER_MODEL_CAPABILITIES_FILE"))
                if os.getenv("DEEP_RESEARCHER_MODEL_CAPABILITIES_FILE")
                else None
            ),
            use_mock_llm=_env_bool("DEEP_RESEARCHER_USE_MOCK_LLM", False),
            use_mock_tools=_env_bool("DEEP_RESEARCHER_USE_MOCK_TOOLS", False),
        )
        config.planner = ModelSelection(
            candidates=_split_models(
                os.getenv("DEEP_RESEARCHER_PLANNER_MODELS"),
                ["anthropic--claude-4.6-sonnet", "gpt-5", "sonar-pro"],
            ),
            temperature=_env_float("DEEP_RESEARCHER_PLANNER_TEMPERATURE", 0.2),
            max_output_tokens=_env_int_alias(
                ["DEEP_RESEARCHER_PLANNER_MAX_OUTPUT_TOKENS", "DEEP_RESEARCHER_PLANNER_MAX_TOKENS"],
                4000,
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
                2200,
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
                2600,
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
                1800,
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
