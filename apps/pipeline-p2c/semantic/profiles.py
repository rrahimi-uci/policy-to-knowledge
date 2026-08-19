"""Versioned, data-only domain profiles for Policy IR assembly."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from policy_ir._parsing import SchemaError, as_str, as_tuple_of_str, check_keys
from policy_ir.models import PolicyIR
from policy_ir.scope import AuthoritySource, ScopeDimensionDefinition


class ProfileError(ValueError):
    """A profile is malformed or incompatible with a semantic package."""


@dataclass(frozen=True)
class DomainProfile:
    """Configuration that can narrow a corpus without changing compiler semantics.

    A profile may reject an undeclared relation type or source format, but it cannot
    make an unevidenced or ill-typed record executable.  That rule keeps domain
    configuration from becoming an escape hatch around the evidence gate.
    """

    profile_id: str
    version: str
    language: str = "en"
    relation_types: tuple[str, ...] = ()
    terminology: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    scope_dimensions: tuple[ScopeDimensionDefinition, ...] = ()
    authority_sources: tuple[AuthoritySource, ...] = ()
    supported_media_types: tuple[str, ...] = ()
    extraction_guidance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "version": self.version,
            "language": self.language,
            "relation_types": list(self.relation_types),
            "terminology": {key: list(value) for key, value in sorted(self.terminology.items())},
            "scope_dimensions": [item.to_dict() for item in self.scope_dimensions],
            "authority_sources": [item.to_dict() for item in self.authority_sources],
            "supported_media_types": list(self.supported_media_types),
            "extraction_guidance": self.extraction_guidance,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DomainProfile":
        record = "DomainProfile"
        try:
            check_keys(
                data,
                record,
                ["profile_id", "version"],
                [
                    "language", "relation_types", "terminology", "scope_dimensions",
                    "authority_sources", "supported_media_types", "extraction_guidance",
                ],
            )
            terminology = data.get("terminology", {})
            if not isinstance(terminology, Mapping):
                raise SchemaError(f"{record}.terminology must be an object")
            guidance = data.get("extraction_guidance", "")
            if not isinstance(guidance, str):
                raise SchemaError(f"{record}.extraction_guidance must be a string")
            return cls(
                profile_id=as_str(data["profile_id"], record, "profile_id"),
                version=as_str(data["version"], record, "version"),
                language=as_str(data.get("language", "en"), record, "language"),
                relation_types=as_tuple_of_str(data.get("relation_types", ()), record, "relation_types"),
                terminology={
                    as_str(key, record, "terminology key"): as_tuple_of_str(value, record, f"terminology.{key}")
                    for key, value in terminology.items()
                },
                scope_dimensions=tuple(
                    ScopeDimensionDefinition.from_dict(item)
                    for item in data.get("scope_dimensions", ())
                ),
                authority_sources=tuple(
                    AuthoritySource.from_dict(item) for item in data.get("authority_sources", ())
                ),
                supported_media_types=as_tuple_of_str(
                    data.get("supported_media_types", ()), record, "supported_media_types"
                ),
                extraction_guidance=guidance,
            )
        except SchemaError as exc:
            raise ProfileError(str(exc)) from exc

    def validate(self, ir: PolicyIR) -> tuple[str, ...]:
        """Return deterministic incompatibilities; admission remains the gate's job."""
        errors: list[str] = []
        allowed_media = set(self.supported_media_types)
        errors.extend(
            f"document {document.document_id!r} has unsupported media type {document.media_type!r}"
            for document in ir.documents
            if allowed_media and document.media_type not in allowed_media
        )
        allowed_relations = set(self.relation_types)
        errors.extend(
            f"semantic relation {relation.relation_id!r} uses undeclared type {relation.relation_type!r}"
            for relation in ir.semantic_relations
            if allowed_relations and relation.relation_type not in allowed_relations
        )
        return tuple(errors)


_GENERIC_RELATIONS = (
    "defines", "aliases", "applies_to", "governs", "requires", "prohibits",
    "permits", "produces", "uses", "delegates_to", "triggers", "precedes",
    "exception_to", "overrides", "references",
)


def generic_profile() -> DomainProfile:
    """The portable baseline; domain profiles only add corpus-specific vocabulary."""
    return DomainProfile(profile_id="generic", version="1", relation_types=_GENERIC_RELATIONS)


def load_profile(path: Path | None) -> DomainProfile:
    """Load a profile file, or the generic profile when no configuration is supplied."""
    if path is None:
        return generic_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"cannot load domain profile {path}: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ProfileError("domain profile root must be an object")
    return DomainProfile.from_dict(data)
