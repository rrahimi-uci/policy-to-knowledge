"""Cryptographic provenance declarations for open-benchmark scoring runs.

The benchmark adapters deliberately do not know how a model was run.  This
small, dependency-free module instead validates a post-run declaration that
binds a score to the exact corpus bytes, selected split, prediction artifact,
configuration digest, and declared system variant.  It never receives a
configuration payload, so credentials and prompts are not copied into reports.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


RUN_MANIFEST_SCHEMA_VERSION = "p2c-evaluation-run-v1"
SYSTEM_KINDS = frozenset({"direct_baseline", "policy_ir", "ablation"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$", flags=re.IGNORECASE)


class RunManifestError(ValueError):
    """Raised when a run manifest is malformed or cannot bind a scoring run."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RunManifestError(f"{where} must be an object")
    return value


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunManifestError(f"{where} must be a non-empty string")
    return value


def _require_sha256(value: Any, where: str) -> str:
    digest = _require_string(value, where)
    if not _SHA256.fullmatch(digest):
        raise RunManifestError(f"{where} must be a SHA-256 hexadecimal digest")
    return digest.lower()


@dataclass(frozen=True)
class EvaluationRunManifest:
    """A validated, secret-free declaration for one scored system run."""

    source_path: Path
    source_sha256: str
    run_id: str
    system_id: str
    system_kind: str
    implementation_revision: str
    configuration_sha256: str
    benchmark: str
    benchmark_source_sha256: str
    selection: Mapping[str, Any]
    predictions_sha256: str

    def validate_for_scoring(
        self,
        *,
        benchmark: str,
        source_sha256: str,
        selection: Mapping[str, Any],
        predictions_sha256: str,
    ) -> None:
        """Reject a manifest that describes any artifact other than this run."""
        if self.benchmark != benchmark:
            raise RunManifestError(
                f"run manifest benchmark {self.benchmark!r} does not match {benchmark!r}"
            )
        if self.benchmark_source_sha256 != source_sha256:
            raise RunManifestError("run manifest benchmark.source_sha256 does not match the input corpus")
        if dict(self.selection) != dict(selection):
            raise RunManifestError("run manifest benchmark.selection does not match the selected split")
        if self.predictions_sha256 != predictions_sha256:
            raise RunManifestError("run manifest predictions_sha256 does not match the prediction artifact")

    def to_report_dict(self) -> dict[str, Any]:
        """Return provenance safe to embed in a public score report."""
        return {
            "path": str(self.source_path),
            "sha256": self.source_sha256,
            "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "system": {
                "system_id": self.system_id,
                "kind": self.system_kind,
                "implementation_revision": self.implementation_revision,
            },
            "configuration": {"sha256": self.configuration_sha256},
            "benchmark": {
                "name": self.benchmark,
                "source_sha256": self.benchmark_source_sha256,
                "selection": dict(self.selection),
            },
            "predictions_sha256": self.predictions_sha256,
        }


def load_evaluation_run_manifest(path: Path) -> EvaluationRunManifest:
    """Load a versioned run manifest without loading configuration contents."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunManifestError(f"cannot read {path}: {exc}") from exc
    root = _require_mapping(raw, "run manifest")
    if root.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
        raise RunManifestError(
            f"run manifest.schema_version must be {RUN_MANIFEST_SCHEMA_VERSION!r}"
        )
    system = _require_mapping(root.get("system"), "run manifest.system")
    system_kind = _require_string(system.get("kind"), "run manifest.system.kind")
    if system_kind not in SYSTEM_KINDS:
        raise RunManifestError(
            "run manifest.system.kind must be one of " + ", ".join(sorted(SYSTEM_KINDS))
        )
    configuration = _require_mapping(root.get("configuration"), "run manifest.configuration")
    benchmark = _require_mapping(root.get("benchmark"), "run manifest.benchmark")
    selection = _require_mapping(benchmark.get("selection"), "run manifest.benchmark.selection")
    return EvaluationRunManifest(
        source_path=path,
        source_sha256=_sha256(path),
        run_id=_require_string(root.get("run_id"), "run manifest.run_id"),
        system_id=_require_string(system.get("system_id"), "run manifest.system.system_id"),
        system_kind=system_kind,
        implementation_revision=_require_string(
            system.get("implementation_revision"), "run manifest.system.implementation_revision"
        ),
        configuration_sha256=_require_sha256(
            configuration.get("sha256"), "run manifest.configuration.sha256"
        ),
        benchmark=_require_string(benchmark.get("name"), "run manifest.benchmark.name"),
        benchmark_source_sha256=_require_sha256(
            benchmark.get("source_sha256"), "run manifest.benchmark.source_sha256"
        ),
        selection=dict(selection),
        predictions_sha256=_require_sha256(root.get("predictions_sha256"), "run manifest.predictions_sha256"),
    )


def build_run_manifest_record(
    *,
    run_id: str,
    system_id: str,
    system_kind: str,
    implementation_revision: str,
    configuration_sha256: str,
    benchmark: str,
    benchmark_source_sha256: str,
    selection: Mapping[str, Any],
    predictions_sha256: str,
) -> dict[str, Any]:
    """Build a validated, serialisable manifest record for a newly written run."""
    if system_kind not in SYSTEM_KINDS:
        raise RunManifestError(
            "system_kind must be one of " + ", ".join(sorted(SYSTEM_KINDS))
        )
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": _require_string(run_id, "run_id"),
        "system": {
            "system_id": _require_string(system_id, "system_id"),
            "kind": system_kind,
            "implementation_revision": _require_string(
                implementation_revision, "implementation_revision"
            ),
        },
        "configuration": {"sha256": _require_sha256(configuration_sha256, "configuration_sha256")},
        "benchmark": {
            "name": _require_string(benchmark, "benchmark"),
            "source_sha256": _require_sha256(
                benchmark_source_sha256, "benchmark_source_sha256"
            ),
            "selection": dict(selection),
        },
        "predictions_sha256": _require_sha256(predictions_sha256, "predictions_sha256"),
    }
