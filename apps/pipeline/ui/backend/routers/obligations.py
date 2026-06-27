"""
Obligations router — Obligation Register & Gap Analysis endpoints.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import obligation_store, obligation_service

router = APIRouter(prefix="/api/obligations", tags=["obligations"])


class UpdateStatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


class AddControlRequest(BaseModel):
    control_name: str
    control_type: str = "policy"
    description: str = ""
    evidence_url: str = ""
    owner: str = ""


# ── Obligation endpoints ──────────────────────────────────────────────────

@router.post("/{graph_name}/seed")
def seed_obligations(graph_name: str, provider: str = "openai"):
    """Initialize obligations from all rules in a knowledge graph."""
    result = obligation_service.seed_obligations(graph_name, provider)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.get("/{graph_name}/heatmap")
def get_heatmap(graph_name: str, provider: str = "openai"):
    """Get compliance heatmap aggregation."""
    return obligation_store.get_heatmap(graph_name, provider)


@router.get("/{graph_name}/stats")
def get_obligation_stats(graph_name: str, provider: str = "openai"):
    """Aggregated statistics for the obligation register."""
    obligations = obligation_store.list_obligations(graph_name, provider)
    if not obligations:
        return {"total": 0}

    jurisdictions: dict[str, int] = {}
    mandatory_count = 0
    with_effective_date = 0
    by_audit_freq: dict[str, int] = {}

    for ob in obligations:
        j = ob.get("jurisdiction", "")
        if j:
            jurisdictions[j] = jurisdictions.get(j, 0) + 1
        if ob.get("mandatory", 1):
            mandatory_count += 1
        if ob.get("effective_date"):
            with_effective_date += 1
        af = ob.get("audit_frequency", "")
        if af:
            by_audit_freq[af] = by_audit_freq.get(af, 0) + 1

    return {
        "total": len(obligations),
        "mandatory_count": mandatory_count,
        "optional_count": len(obligations) - mandatory_count,
        "with_effective_date": with_effective_date,
        "jurisdictions": jurisdictions,
        "by_audit_frequency": by_audit_freq,
    }


@router.get("/{graph_name}/export/{fmt}")
def export_obligations(graph_name: str, fmt: str, provider: str = "openai"):
    """Export obligation register as CSV (GRC-compatible) or JSON."""
    if fmt not in ("json", "csv"):
        raise HTTPException(400, f"Unsupported format: {fmt}")

    result = obligation_service.export_obligations(graph_name, provider, fmt)

    if fmt == "json":
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content=result,
            headers={"Content-Disposition": f'attachment; filename="{graph_name}_obligations.json"'},
        )
    else:
        from fastapi.responses import Response
        return Response(
            content=result,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{graph_name}_obligations.csv"'},
        )


@router.get("/{graph_name}")
def list_obligations(graph_name: str, provider: str = "openai"):
    """List all obligations for a knowledge graph."""
    obligations = obligation_store.list_obligations(graph_name, provider)
    heatmap = obligation_store.get_heatmap(graph_name, provider)
    return {"obligations": obligations, "heatmap": heatmap}


@router.delete("/{graph_name}")
def reset_obligations(graph_name: str, provider: str = "openai"):
    """Delete all obligations for a graph (reset)."""
    count = obligation_store.delete_obligations(graph_name, provider)
    return {"deleted_count": count}


# ── Detail & rule-specific endpoints ──────────────────────────────────────

@router.get("/{graph_name}/{rule_id}/detail")
def get_obligation_detail(graph_name: str, rule_id: str, provider: str = "openai"):
    """Get full enriched detail for a single obligation."""
    ob = obligation_store.get_obligation(graph_name, provider, rule_id)
    if not ob:
        raise HTTPException(404, f"Obligation for rule '{rule_id}' not found")

    # Parse JSON fields for the frontend
    for field in ("source_reference", "conditions", "consequences", "exceptions", "applicability_scope"):
        raw = ob.get(field, "")
        if raw and isinstance(raw, str):
            try:
                ob[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                pass
    return ob


@router.get("/{graph_name}/{rule_id}/suggest")
def suggest_controls(graph_name: str, rule_id: str, provider: str = "openai"):
    """Get AI-suggested control mappings for a specific obligation."""
    if not obligation_store.get_obligation(graph_name, provider, rule_id):
        raise HTTPException(404, f"Obligation '{rule_id}' not found")
    suggestions = obligation_service.suggest_controls(graph_name, provider, rule_id)
    return {"suggestions": suggestions}


@router.put("/{graph_name}/{rule_id}")
def update_obligation(graph_name: str, rule_id: str, body: UpdateStatusRequest, provider: str = "openai"):
    """Update the compliance status of an obligation."""
    if body.status not in obligation_service.VALID_STATUSES:
        raise HTTPException(
            400,
            f"Invalid status '{body.status}'. Must be one of: {', '.join(sorted(obligation_service.VALID_STATUSES))}",
        )
    result = obligation_store.update_obligation_status(
        graph_name, provider, rule_id, body.status, body.notes
    )
    if not result:
        raise HTTPException(404, f"Obligation for rule '{rule_id}' not found. Run /seed first.")
    return result


# ── Control mapping ───────────────────────────────────────────────────────

@router.post("/{graph_name}/{rule_id}/controls")
def add_control(graph_name: str, rule_id: str, body: AddControlRequest, provider: str = "openai"):
    """Link an internal control to an obligation."""
    if body.control_type not in obligation_service.VALID_CONTROL_TYPES:
        raise HTTPException(
            400,
            f"Invalid control_type '{body.control_type}'. Must be one of: {', '.join(sorted(obligation_service.VALID_CONTROL_TYPES))}",
        )
    ob = obligation_store.get_obligation(graph_name, provider, rule_id)
    if not ob:
        raise HTTPException(404, f"Obligation for rule '{rule_id}' not found")

    control = obligation_store.add_control(
        obligation_id=ob["id"],
        control_name=body.control_name,
        control_type=body.control_type,
        description=body.description,
        evidence_url=body.evidence_url,
        owner=body.owner,
    )
    return control


@router.delete("/controls/{control_id}")
def remove_control(control_id: int):
    """Remove a control mapping."""
    if not obligation_store.delete_control(control_id):
        raise HTTPException(404, f"Control {control_id} not found")
    return {"deleted": control_id}
