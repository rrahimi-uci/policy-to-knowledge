"""
Obligation Service — business logic for the Obligation Register & Gap Analysis.

Seeds obligations from graph rules, supports AI-based control suggestions,
and provides GRC-format export.
"""

import csv
import io
import json
from typing import Any, Dict, List, Optional

from . import graph_service, obligation_store


VALID_STATUSES = {"unmapped", "mapped", "partially-mapped", "exempted"}
VALID_CONTROL_TYPES = {"policy", "procedure", "technical-control", "manual-control", "audit", "training"}


def seed_obligations(graph_name: str, provider: str = "openai") -> dict:
    """
    Initialize obligation entries for every rule in a knowledge graph.
    Rules that already have obligations are left untouched (status/notes preserved).
    Re-seeding updates enriched metadata for existing obligations.
    Returns counts of created vs existing.
    """
    graph_data = graph_service.get_graph_data(graph_name, provider)
    if not graph_data:
        return {"error": f"Graph '{graph_name}' not found"}

    rules = graph_data.get("business_rules", [])
    if not rules:
        for et in graph_data.get("entity_types", {}).values():
            rules.extend(r for r in et.get("business_rules", []) if isinstance(r, dict))

    created = 0
    existing = 0
    for rule in rules:
        rid = rule.get("rule_id", "")
        if not rid:
            continue

        # Build enriched fields from rule data
        source_ref = rule.get("source_reference")
        source_ref_str = json.dumps(source_ref) if isinstance(source_ref, (dict, list)) else str(source_ref or "")

        conditions = rule.get("conditions")
        conditions_str = json.dumps(conditions) if isinstance(conditions, (list, dict)) else str(conditions or "")

        consequences = rule.get("consequences")
        consequences_str = json.dumps(consequences) if isinstance(consequences, (list, dict)) else str(consequences or "")

        exceptions = rule.get("exceptions")
        exceptions_str = json.dumps(exceptions) if isinstance(exceptions, (list, dict)) else str(exceptions or "")

        scope = rule.get("applicability_scope")
        scope_str = json.dumps(scope) if isinstance(scope, (dict, list)) else str(scope or "")

        mandatory_val = rule.get("mandatory")
        mandatory_int = 1 if mandatory_val is None else (1 if mandatory_val else 0)

        existing_ob = obligation_store.get_obligation(graph_name, provider, rid)
        if existing_ob:
            existing += 1
            # Re-seed enriched fields without touching status/notes
            obligation_store.upsert_obligation(
                graph_name=graph_name,
                provider=provider,
                rule_id=rid,
                rule_name=rule.get("rule_name", existing_ob.get("rule_name", "")),
                rule_type=rule.get("rule_type", existing_ob.get("rule_type", "")),
                risk_level=rule.get("risk_level", existing_ob.get("risk_level", "")),
                status=existing_ob["status"],
                notes=existing_ob.get("notes", ""),
                description=rule.get("description", ""),
                source_reference=source_ref_str,
                jurisdiction=rule.get("jurisdiction", ""),
                mandatory=mandatory_int,
                effective_date=rule.get("effective_date", ""),
                conditions=conditions_str,
                consequences=consequences_str,
                exceptions=exceptions_str,
                applicability_scope=scope_str,
                audit_frequency=rule.get("audit_frequency", ""),
                enforcement_action=rule.get("enforcement_action", ""),
            )
        else:
            obligation_store.upsert_obligation(
                graph_name=graph_name,
                provider=provider,
                rule_id=rid,
                rule_name=rule.get("rule_name", ""),
                rule_type=rule.get("rule_type", ""),
                risk_level=rule.get("risk_level", ""),
                description=rule.get("description", ""),
                source_reference=source_ref_str,
                jurisdiction=rule.get("jurisdiction", ""),
                mandatory=mandatory_int,
                effective_date=rule.get("effective_date", ""),
                conditions=conditions_str,
                consequences=consequences_str,
                exceptions=exceptions_str,
                applicability_scope=scope_str,
                audit_frequency=rule.get("audit_frequency", ""),
                enforcement_action=rule.get("enforcement_action", ""),
            )
            created += 1

    return {
        "graph_name": graph_name,
        "provider": provider,
        "total_rules": len(rules),
        "created": created,
        "existing": existing,
    }


def suggest_controls(graph_name: str, provider: str, rule_id: str) -> List[dict]:
    """
    AI-powered control mapping suggestions based on rule semantics.
    Uses heuristic matching on rule_type, risk_level, and rule_name keywords.
    """
    ob = obligation_store.get_obligation(graph_name, provider, rule_id)
    if not ob:
        return []

    suggestions = []
    rule_name = (ob.get("rule_name") or "").lower()
    rule_type = (ob.get("rule_type") or "").lower()
    risk_level = (ob.get("risk_level") or "").lower()

    # Rule-type based suggestions
    type_map = {
        "compliance": [
            {"control_name": "Regulatory Compliance Review", "control_type": "procedure",
             "description": "Periodic review of regulatory requirements against internal policies"},
            {"control_name": "Compliance Training Program", "control_type": "training",
             "description": "Annual compliance training for all relevant staff"},
        ],
        "eligibility": [
            {"control_name": "Eligibility Verification Checklist", "control_type": "procedure",
             "description": "Systematic verification of eligibility criteria before processing"},
            {"control_name": "Automated Eligibility Screening", "control_type": "technical-control",
             "description": "System-enforced eligibility checks at point of entry"},
        ],
        "validation": [
            {"control_name": "Data Validation Rules", "control_type": "technical-control",
             "description": "Automated validation rules in processing systems"},
            {"control_name": "QC Sampling Procedure", "control_type": "procedure",
             "description": "Quality control sampling of validated records"},
        ],
        "process": [
            {"control_name": "Standard Operating Procedure", "control_type": "procedure",
             "description": "Documented SOP covering the required process steps"},
            {"control_name": "Process Audit Trail", "control_type": "technical-control",
             "description": "System-generated audit trail for process execution"},
        ],
        "prohibition": [
            {"control_name": "Prohibited Activity Monitoring", "control_type": "technical-control",
             "description": "Automated monitoring and alerting for prohibited activities"},
            {"control_name": "Prohibition Compliance Policy", "control_type": "policy",
             "description": "Written policy explicitly prohibiting the activity"},
        ],
        "calculation": [
            {"control_name": "Calculation Validation Engine", "control_type": "technical-control",
             "description": "Automated calculation verification with audit logging"},
            {"control_name": "Manual Calculation Review", "control_type": "manual-control",
             "description": "Secondary review of calculations exceeding threshold"},
        ],
        "documentation": [
            {"control_name": "Document Retention Policy", "control_type": "policy",
             "description": "Document retention and accessibility requirements"},
            {"control_name": "Document Completeness Checklist", "control_type": "procedure",
             "description": "Pre-submission checklist for required documentation"},
        ],
    }

    if rule_type in type_map:
        suggestions.extend(type_map[rule_type])

    # Risk-based additions
    if risk_level == "critical":
        suggestions.append({
            "control_name": "Executive Review & Sign-off",
            "control_type": "manual-control",
            "description": "Senior management review for critical risk items",
        })
        suggestions.append({
            "control_name": "Independent Audit Verification",
            "control_type": "audit",
            "description": "Annual independent audit of critical compliance controls",
        })
    elif risk_level == "high":
        suggestions.append({
            "control_name": "Supervisory Review",
            "control_type": "manual-control",
            "description": "Supervisor-level review and approval",
        })

    # Keyword-based refinements
    if any(kw in rule_name for kw in ("appraisal", "property", "valuation")):
        suggestions.append({
            "control_name": "Appraisal Independence Policy",
            "control_type": "policy",
            "description": "Ensures appraiser independence per FIRREA requirements",
        })
    if any(kw in rule_name for kw in ("wire", "fund", "disburs")):
        suggestions.append({
            "control_name": "Wire Transfer Authorization",
            "control_type": "technical-control",
            "description": "Dual-authorization required for wire transfers",
        })
    if any(kw in rule_name for kw in ("aml", "suspicious", "transaction monitoring")):
        suggestions.append({
            "control_name": "Transaction Monitoring System",
            "control_type": "technical-control",
            "description": "Automated suspicious activity detection and SAR filing",
        })

    # Deduplicate by control_name
    seen = set()
    unique = []
    for s in suggestions:
        if s["control_name"] not in seen:
            seen.add(s["control_name"])
            unique.append(s)

    return unique


def export_obligations(graph_name: str, provider: str = "openai", fmt: str = "csv") -> Any:
    """Export obligation register in GRC-compatible format."""
    obligations = obligation_store.list_obligations(graph_name, provider)

    if fmt == "json":
        heatmap = obligation_store.get_heatmap(graph_name, provider)
        return {
            "graph_name": graph_name,
            "provider": provider,
            "heatmap": heatmap,
            "obligations": obligations,
        }

    # CSV: GRC import format (compatible with Archer, ServiceNow GRC)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Obligation ID",
        "Rule ID",
        "Rule Name",
        "Rule Type",
        "Risk Level",
        "Compliance Status",
        "Description",
        "Jurisdiction",
        "Mandatory",
        "Effective Date",
        "Audit Frequency",
        "Enforcement Action",
        "Control Name",
        "Control Type",
        "Control Description",
        "Control Owner",
        "Evidence URL",
        "Notes",
    ])
    for ob in obligations:
        controls = ob.get("controls", [])
        base = [
            ob["id"], ob["rule_id"], ob.get("rule_name", ""),
            ob.get("rule_type", ""), ob.get("risk_level", ""),
            ob["status"],
            ob.get("description", ""),
            ob.get("jurisdiction", ""),
            "Yes" if ob.get("mandatory", 1) else "No",
            ob.get("effective_date", ""),
            ob.get("audit_frequency", ""),
            ob.get("enforcement_action", ""),
        ]
        if not controls:
            writer.writerow(base + ["", "", "", "", "", ob.get("notes", "")])
        else:
            for ctrl in controls:
                writer.writerow(base + [
                    ctrl.get("control_name", ""),
                    ctrl.get("control_type", ""),
                    ctrl.get("description", ""),
                    ctrl.get("owner", ""),
                    ctrl.get("evidence_url", ""),
                    ob.get("notes", ""),
                ])
    return output.getvalue()
