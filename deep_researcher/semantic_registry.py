from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import json


@dataclass(frozen=True)
class EvidenceProfile:
    profile_id: str
    description: str
    default_priority: str
    default_source_hints: List[str]
    default_query_templates: List[str]
    fallback_enabled: bool


@dataclass(frozen=True)
class SourcePack:
    pack_id: str
    description: str
    applies_to_profiles: List[str]
    query_templates: List[str]
    source_hints: List[str]
    allowed_domains: List[str]
    priority_bias: str
    preferred: bool
    optional: bool


@dataclass(frozen=True)
class SemanticRegistry:
    profiles: Dict[str, EvidenceProfile]
    source_packs: Dict[str, SourcePack]

    def profile_ids(self) -> List[str]:
        return list(self.profiles.keys())

    def source_pack_ids(self) -> List[str]:
        return list(self.source_packs.keys())

    def profile_prompt_payload(self) -> List[Dict[str, object]]:
        return [
            {
                "id": item.profile_id,
                "description": item.description,
                "default_priority": item.default_priority,
                "default_source_hints": item.default_source_hints,
                "default_query_templates": item.default_query_templates,
                "fallback_enabled": item.fallback_enabled,
            }
            for item in self.profiles.values()
        ]

    def source_pack_prompt_payload(self) -> List[Dict[str, object]]:
        return [
            {
                "id": item.pack_id,
                "description": item.description,
                "applies_to_profiles": item.applies_to_profiles,
                "query_templates": item.query_templates,
                "source_hints": item.source_hints,
                "allowed_domains": item.allowed_domains,
                "priority_bias": item.priority_bias,
                "preferred": item.preferred,
                "optional": item.optional,
            }
            for item in self.source_packs.values()
        ]

    def preferred_source_packs_for_profile(self, profile_id: str) -> List[str]:
        packs = []
        for source_pack in self.source_packs.values():
            if profile_id not in source_pack.applies_to_profiles:
                continue
            if source_pack.preferred:
                packs.append(source_pack.pack_id)
        return packs


def load_semantic_registry(
    evidence_profiles_file: Optional[Path] = None,
    source_packs_file: Optional[Path] = None,
) -> SemanticRegistry:
    root = Path(__file__).resolve().parent
    profiles_path = evidence_profiles_file or (root / "evidence_profiles.json")
    source_packs_path = source_packs_file or (root / "source_packs.json")
    profiles_payload = json.loads(profiles_path.read_text(encoding="utf-8"))
    source_packs_payload = json.loads(source_packs_path.read_text(encoding="utf-8"))
    profiles: Dict[str, EvidenceProfile] = {}
    source_packs: Dict[str, SourcePack] = {}
    for item in profiles_payload:
        profile = EvidenceProfile(
            profile_id=str(item["id"]),
            description=str(item["description"]),
            default_priority=str(item["default_priority"]),
            default_source_hints=[str(value) for value in item.get("default_source_hints", [])],
            default_query_templates=[str(value) for value in item.get("default_query_templates", [])],
            fallback_enabled=bool(item.get("fallback_enabled", False)),
        )
        profiles[profile.profile_id] = profile
    for item in source_packs_payload:
        source_pack = SourcePack(
            pack_id=str(item["id"]),
            description=str(item["description"]),
            applies_to_profiles=[str(value) for value in item.get("applies_to_profiles", [])],
            query_templates=[str(value) for value in item.get("query_templates", [])],
            source_hints=[str(value) for value in item.get("source_hints", [])],
            allowed_domains=[str(value) for value in item.get("allowed_domains", [])],
            priority_bias=str(item.get("priority_bias", "medium")),
            preferred=bool(item.get("preferred", False)),
            optional=bool(item.get("optional", True)),
        )
        source_packs[source_pack.pack_id] = source_pack
    return SemanticRegistry(profiles=profiles, source_packs=source_packs)
