"""Deterministic review queues and evaluation summaries for semantic assembly."""

from __future__ import annotations

from typing import Any

from policy_ir.enums import Status
from policy_ir.models import PolicyIR
from validation.evidence_gate import GateReport

from .synthesis import synthesis_report


def review_queue(ir: PolicyIR, report: GateReport) -> dict[str, Any]:
    """Return every refused semantic record as a stable, reviewer-facing queue."""
    items: list[dict[str, Any]] = []
    for kind, records in (
        ("clause", report.clauses), ("decision", report.decisions),
        ("process", report.processes), ("dependency", report.dependencies),
        ("semantic_relation", report.semantic_relations),
    ):
        for element_id, element in sorted(records.items()):
            if element.blockers:
                items.append({
                    "kind": kind, "element_id": element_id,
                    "blockers": [blocker.to_dict() for blocker in element.blockers],
                })
    for opportunity in synthesis_report(ir):
        if opportunity.status == "abstain":
            items.append({
                "kind": "synthesis", "element_id": opportunity.clause_id,
                "target": opportunity.target, "missing": list(opportunity.missing),
            })
    return {"items": items, "total": len(items)}


def semantic_metrics(ir: PolicyIR, report: GateReport) -> dict[str, Any]:
    """Coverage and admission metrics; no score claims semantic correctness."""
    opportunities = synthesis_report(ir)
    return {
        "documents": len(ir.documents),
        "chunks": len(ir.chunks),
        "coverage": {
            status: sum(1 for entry in ir.coverage if entry.status == status)
            for status in sorted({entry.status for entry in ir.coverage})
        },
        "clauses": len(ir.clauses),
        "semantic_relations": len(ir.semantic_relations),
        "graph_eligible_clauses": sum(
            item.has(Status.GRAPH_ELIGIBLE) for item in report.clauses.values()
        ),
        "admitted_decisions": len(report.admitted_decisions()),
        "admitted_processes": len(report.admitted_processes()),
        "synthesis": {
            "ready_for_explicit_model": sum(
                item.status == "ready_for_explicit_model" for item in opportunities
            ),
            "abstentions": sum(item.status == "abstain" for item in opportunities),
        },
        "blockers": report.counts_by_code(),
    }
