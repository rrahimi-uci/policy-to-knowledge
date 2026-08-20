"""The versioned, pre-result evaluation protocol for PolicyIR experiments.

This module intentionally locks only choices that must be shared by a paired
comparison.  Corpus paths and their digests remain run-time inputs, because the
repository never distributes benchmark data.  A changed prompt, model, decoding
setting, or bootstrap seed is a new protocol rather than an invisible tweak.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


PROTOCOL_ID = "p2c-open-benchmark-policyir-2026-08-20-v2"
LOCKED_MODEL = "gpt-5.2"
DIRECT_PROMPT_VERSION = "p2c-direct-policy-qa-v1"
POLICY_IR_EXTRACTION_PROMPT_VERSION = "p2c-policy-ir-extraction-v2"
POLICY_IR_QUERY_PROMPT_VERSION = "p2c-policy-ir-query-v2"
# GPT-5.2 rejects temperature when reasoning is above ``none``.  Keep this
# record explicit so a future comparison cannot silently use the API default.
OPENAI_DECODING: Mapping[str, Any] = {"reasoning": {"effort": "medium"}}
PAIRED_BOOTSTRAP_SEED = 20260819
PAIRED_BOOTSTRAP_SAMPLES = 10_000


class ProtocolError(ValueError):
    """Raised when a run attempts to depart from the locked comparison protocol."""


def canonical_json_sha256(value: Mapping[str, Any]) -> str:
    """Hash a public configuration record deterministically."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_model_and_decoding(*, model: str, decoding: Mapping[str, Any]) -> None:
    """Refuse a silent model or decoding change in a declared protocol run."""
    if model != LOCKED_MODEL:
        raise ProtocolError(
            f"protocol {PROTOCOL_ID!r} requires model {LOCKED_MODEL!r}, got {model!r}"
        )
    if dict(decoding) != dict(OPENAI_DECODING):
        raise ProtocolError(
            f"protocol {PROTOCOL_ID!r} requires decoding {dict(OPENAI_DECODING)!r}"
        )


def protocol_record(*, prompt_versions: tuple[str, ...]) -> dict[str, Any]:
    """Return the public protocol declaration embedded in every paired run config."""
    return {
        "id": PROTOCOL_ID,
        "model": LOCKED_MODEL,
        "decoding": dict(OPENAI_DECODING),
        "prompt_versions": list(prompt_versions),
        "paired_bootstrap": {
            "samples": PAIRED_BOOTSTRAP_SAMPLES,
            "seed": PAIRED_BOOTSTRAP_SEED,
        },
    }
