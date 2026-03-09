from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Optional
import json


@dataclass(frozen=True)
class ModelCapabilityRule:
    pattern: str
    match: str
    context_window_tokens: int
    family: str = ""
    source_url: str = ""
    notes: str = ""

    def matches(self, model: str) -> bool:
        normalized = model.lower()
        if self.match == "exact":
            return normalized == self.pattern.lower()
        if self.match == "contains":
            return self.pattern.lower() in normalized
        return normalized.startswith(self.pattern.lower())


@dataclass(frozen=True)
class ModelCapabilityRegistry:
    default_context_window_tokens: int
    rules: List[ModelCapabilityRule]


@dataclass(frozen=True)
class ResolvedModelCapability:
    model: str
    family: str
    context_window_tokens: int
    matched_pattern: str
    matched_by: str
    source_url: str
    notes: str


def _registry_from_payload(payload: Dict[str, Any]) -> ModelCapabilityRegistry:
    rules = []
    for item in payload.get("rules", []):
        rules.append(ModelCapabilityRule(
            pattern=item["pattern"],
            match=item.get("match", "prefix"),
            context_window_tokens=int(item["context_window_tokens"]),
            family=item.get("family", ""),
            source_url=item.get("source_url", ""),
            notes=item.get("notes", ""),
        ))
    default = payload.get("default", {})
    return ModelCapabilityRegistry(
        default_context_window_tokens=int(default.get("context_window_tokens", 128000)),
        rules=rules,
    )


@lru_cache(maxsize=8)
def _load_registry_cached(path_str: str) -> ModelCapabilityRegistry:
    with Path(path_str).open("r", encoding="utf-8") as handle:
        return _registry_from_payload(json.load(handle))


@lru_cache(maxsize=1)
def _load_default_registry_cached() -> ModelCapabilityRegistry:
    payload = json.loads(resources.files("deep_researcher").joinpath("model_capabilities.json").read_text(encoding="utf-8"))
    return _registry_from_payload(payload)


def load_model_capability_registry(path: Optional[Path] = None) -> ModelCapabilityRegistry:
    if path is None:
        return _load_default_registry_cached()
    return _load_registry_cached(str(path.resolve()))


def resolve_model_capability(model: str, registry: Optional[ModelCapabilityRegistry] = None) -> ResolvedModelCapability:
    active_registry = registry or load_model_capability_registry()
    for rule in active_registry.rules:
        if rule.matches(model):
            return ResolvedModelCapability(
                model=model,
                family=rule.family or rule.pattern,
                context_window_tokens=rule.context_window_tokens,
                matched_pattern=rule.pattern,
                matched_by=rule.match,
                source_url=rule.source_url,
                notes=rule.notes,
            )
    return ResolvedModelCapability(
        model=model,
        family="default",
        context_window_tokens=active_registry.default_context_window_tokens,
        matched_pattern="default",
        matched_by="default",
        source_url="",
        notes="Fallback capability profile.",
    )
