"""One compile run: gate, project, verify, report.

Sequencing lives here so the CLI and the tests exercise exactly the same path. The
order is fixed and the reason is the fail-closed rule: the gate runs first and its
report is the only authority the compilers consult.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from policy_ir.enums import CompilerProfile
from policy_ir.models import PolicyIR
from validation.evidence_gate import GateReport, run_gate

from .bpmn import compile_bpmn
from .dmn import CompiledArtifact, compile_dmn
from .graph import project_graph
from .traceability import build_compilation_report, build_manifest, build_traceability
from .verify import validate_bpmn, validate_dmn

#: Targets a run may request. ``graph`` is the legacy projection and is always safe
#: to ask for; ``dmn`` and ``bpmn`` emit only what the gate admitted.
TARGETS = ("graph", "dmn", "bpmn")


@dataclass
class CompileResult:
    """Everything one run produced."""

    report: GateReport
    profile: CompilerProfile
    graph: dict[str, Any] | None = None
    artifacts: tuple[CompiledArtifact, ...] = ()
    structural_problems: tuple[str, ...] = ()
    traceability: dict[str, Any] = field(default_factory=dict)
    compilation_report: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when the IR is well formed and every emitted artefact is clean.

        Refusing to compile a clause is *not* a failure: abstention is a designed
        outcome. A structural problem in something that was emitted is.
        """
        return not self.report.fatal and not self.structural_problems

    def artifact(self, filename: str) -> CompiledArtifact:
        for artifact in self.artifacts:
            if artifact.filename == filename:
                return artifact
        raise KeyError(f"run produced no artefact named {filename!r}")

    def files(self) -> dict[str, str]:
        """Map output filename to file contents, ready to write."""
        out: dict[str, str] = {
            artifact.filename: artifact.xml for artifact in self.artifacts
        }
        if self.graph is not None:
            out["graph-v2.json"] = _json(self.graph)
        out["traceability.json"] = _json(self.traceability)
        out["compilation-report.json"] = _json(self.compilation_report)
        out["manifest.json"] = _json(self.manifest)
        return out


def compile_all(
    ir: PolicyIR,
    texts: Mapping[str, str] | None = None,
    *,
    profile: CompilerProfile = CompilerProfile.EXECUTABLE_SUBSET,
    targets: tuple[str, ...] = TARGETS,
    graph_name: str = "policy_graph",
    run_timestamp: str | None = None,
) -> CompileResult:
    """Run the gate and every requested projection."""
    unknown = sorted(set(targets) - set(TARGETS))
    if unknown:
        raise ValueError(f"unknown target(s) {unknown}; choose from {list(TARGETS)}")

    report = run_gate(ir, texts)
    graph = project_graph(ir, report, graph_name=graph_name) if "graph" in targets else None

    artifacts: list[CompiledArtifact] = []
    problems: list[str] = []
    dmn_artifact: CompiledArtifact | None = None
    if "dmn" in targets:
        dmn_artifact = compile_dmn(ir, report, profile=profile)
        artifacts.append(dmn_artifact)
        problems.extend(f"{dmn_artifact.filename}: {p}" for p in validate_dmn(dmn_artifact.xml))
    if "bpmn" in targets:
        bpmn_artifact = compile_bpmn(ir, report, profile=profile)
        artifacts.append(bpmn_artifact)
        emitted_decisions = frozenset(dmn_artifact.emitted_ids if dmn_artifact else ())
        problems.extend(
            f"{bpmn_artifact.filename}: {p}"
            for p in validate_bpmn(bpmn_artifact.xml, emitted_decision_ids=emitted_decisions)
        )

    return CompileResult(
        report=report,
        profile=profile,
        graph=graph,
        artifacts=tuple(artifacts),
        structural_problems=tuple(problems),
        traceability=build_traceability(ir, report, artifacts),
        compilation_report=build_compilation_report(ir, report, artifacts),
        manifest=build_manifest(
            ir,
            report,
            artifacts,
            profile=profile.value,
            run_timestamp=run_timestamp,
            extra={"structural_problems": list(problems)} if problems else None,
        ),
    )


def _json(value: Any) -> str:
    """Serialise deterministically: sorted keys, stable separators, trailing LF."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
