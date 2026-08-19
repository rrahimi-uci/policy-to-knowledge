"""Deterministic, position-independent identifiers.

Legacy P2K rule IDs embed the extraction batch number and a per-batch sequence,
so re-running the pipeline with a different batch order changes rule identity.
Every ID here is instead derived from content: the document hash, the exact
evidence span, the normalised clause kind and the schema version. Reordering
inputs cannot change an ID, and two runs over the same bytes produce the same
IDs, which is what makes byte-stable compiler output possible.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

#: Versioned contract identifier. Any change to the enums, the expression
#: grammar or the ID derivation rules must bump this, because it is mixed into
#: every derived ID.
SCHEMA_VERSION = "policy-ir-2.0.0"

#: Length of the hex digest kept in a derived ID. 16 hex characters is 64 bits,
#: which keeps collisions negligible for corpora of a few million clauses while
#: staying short enough to read in a diff.
_DIGEST_LENGTH = 16

_NCNAME_INVALID = re.compile(r"[^A-Za-z0-9_.\-]")
_MULTI_UNDERSCORE = re.compile(r"_{2,}")


def content_digest(*parts: str | bytes) -> str:
    """Hash the given parts with an unambiguous separator.

    The separator matters: without it ``("ab", "c")`` and ``("a", "bc")`` would
    hash identically, which would let two different clauses share an ID.
    """
    digest = hashlib.sha256()
    for part in parts:
        raw = part.encode("utf-8") if isinstance(part, str) else part
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return the hex SHA-256 of text encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ncname(text: str, *, fallback: str = "id") -> str:
    """Coerce text into a valid XML ``NCName``.

    DMN and BPMN both declare element IDs as ``xsd:ID``, so an ID that starts
    with a digit or contains a colon makes the emitted XML invalid. Sanitising
    here rather than at write time means the same ID appears in the IR, the
    traceability manifest and the XML.
    """
    normalized = unicodedata.normalize("NFKD", text)
    cleaned = _NCNAME_INVALID.sub("_", normalized)
    cleaned = _MULTI_UNDERSCORE.sub("_", cleaned).strip("_")
    if not cleaned:
        cleaned = fallback
    if not (cleaned[0].isalpha() or cleaned[0] == "_"):
        cleaned = f"_{cleaned}"
    return cleaned


def derived_id(prefix: str, *parts: str) -> str:
    """Build a content-derived ID of the form ``prefix_<digest>``."""
    digest = content_digest(SCHEMA_VERSION, prefix, *parts)[:_DIGEST_LENGTH]
    return ncname(f"{prefix}_{digest}")


def document_id(source_uri: str, source_sha256: str) -> str:
    return derived_id("doc", source_uri, source_sha256)


def chunk_id(doc_id: str, chunk_sha256: str, char_start: int) -> str:
    return derived_id("chunk", doc_id, chunk_sha256, str(char_start))


def evidence_id(doc_id: str, chunk_sha: str, char_start: int, char_end: int, role: str) -> str:
    return derived_id("ev", doc_id, chunk_sha, str(char_start), str(char_end), role)


def clause_id(doc_sha256: str, evidence_key: str, clause_kind: str) -> str:
    """Derive a clause ID from its document, its evidence and its kind.

    ``evidence_key`` should be the canonical join of the clause's primary
    supporting spans so that splitting a compound sentence into two atomic
    clauses yields two stable, distinct IDs.
    """
    return derived_id("clause", doc_sha256, evidence_key, clause_kind)


def decision_id(name: str, clause_ids: tuple[str, ...]) -> str:
    return derived_id("decision", name, "|".join(sorted(clause_ids)))


def fragment_id(name: str, clause_ids: tuple[str, ...]) -> str:
    return derived_id("fragment", name, "|".join(sorted(clause_ids)))


def dependency_id(source: str, target: str, kind: str) -> str:
    return derived_id("dep", source, target, kind)


def data_definition_id(owning_entity: str, attribute_name: str) -> str:
    return derived_id("data", owning_entity, attribute_name)
