"""
Load compliance business rules into JanusGraph for Explorer.

Reads knowledge graph JSON files and creates:
  - business_rule vertices (with full properties)
  - entity_category vertices (domain entity groupings)
  - depends_on edges (rule-to-rule dependency relationships)
  - belongs_to_category edges (rule-to-category links)

Supports multiple graphs:
  - 'g' (compliance/fama) - Fannie Mae business rules
  - 'contracts_g' (contracts/overlays) - overlay/contract rules
"""

import sys
import json
import os
import uuid

from gremlin_python.process.graph_traversal import __

from src.graph_connection import get_traversal
from conf.graph_manifest import get_graph_configs
from conf.config import DATA_LOAD_BATCH_LOG_INTERVAL
from src.log import log as _log

# Graph configurations — driven by graphs.yaml
GRAPH_CONFIGS = get_graph_configs()


def _safe_str(val) -> str:
    """Convert value to a safe string for JanusGraph properties."""
    if val is None:
        return ""
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    return str(val)


def clear_graph(graph_name: str = "g") -> None:
    """Drop all vertices and edges from the specified graph using script submission."""
    from src.graph_connection import get_client
    with get_client(graph_name) as gc:
        count = gc.submit("g.V().count()")[0]
        if count == 0:
            _log("INFO", f"Graph '{graph_name}' is already empty")
            return
        _log("INFO", f"Clearing graph '{graph_name}' ({count} vertices) …")
        gc.submit("g.V().drop()")
        _log("INFO", f"Graph '{graph_name}' cleared")


def clear_all_graphs() -> None:
    """Drop all data from every configured graph."""
    _log("INFO", "Clearing all configured graphs …")
    for graph_name in GRAPH_CONFIGS:
        clear_graph(graph_name)
    _log("INFO", "All graphs cleared")


def load_data(graph_name: str = "g", json_file: str = None, *, clear_first: bool = False) -> None:
    """Load Explorer knowledge graph data from JSON into JanusGraph.
    
    Args:
        graph_name: Name of the traversal source (e.g., 'g', 'contracts_g')
        json_file: Path to JSON file. If None, uses default from GRAPH_CONFIGS.
        clear_first: If True, clear existing vertices/edges before loading so
            repeated publishes/reloads replace the graph instead of appending.
    """
    # Determine the JSON file to use
    if json_file is None:
        config = GRAPH_CONFIGS.get(graph_name)
        if config is None:
            raise ValueError(f"Unknown graph: {graph_name}. Available: {list(GRAPH_CONFIGS.keys())}")
        json_file = config["file"]
        graph_display_name = config["name"]
    else:
        graph_display_name = graph_name

    if not os.path.isfile(json_file):
        raise FileNotFoundError(
            f"KG file not found for graph '{graph_name}': {json_file}"
        )

    if clear_first:
        _log("INFO", f"Replacing existing data for graph '{graph_name}' before load")
        clear_graph(graph_name)

    with get_traversal(graph_name) as (g, conn):
        # Read JSON
        _log("INFO", f"Loading {graph_display_name} data from {json_file}")
        with open(json_file) as f:
            data = json.load(f)

        rules = data["business_rules"]
        entity_types_def = data.get("entity_types", {})
        relationships_raw = data.get("relationships", {})

        # Normalise the two relationship shapes used by the pipeline:
        #   • dict  → {NAME: {source_entity, target_entity, definition, ...}}
        #   • list  → [{source, target, relationship_type, description, ...}]
        relationships_def: dict[str, dict] = {}
        if isinstance(relationships_raw, dict):
            for name, info in relationships_raw.items():
                if not isinstance(info, dict):
                    continue
                relationships_def[name] = {
                    "source_entity": info.get("source_entity") or info.get("source", ""),
                    "target_entity": info.get("target_entity") or info.get("target", ""),
                    "definition": info.get("definition") or info.get("description", ""),
                    "cardinality": info.get("cardinality", ""),
                }
        elif isinstance(relationships_raw, list):
            for info in relationships_raw:
                if not isinstance(info, dict):
                    continue
                name = info.get("relationship_type") or info.get("name") or ""
                if not name:
                    continue
                relationships_def[name] = {
                    "source_entity": info.get("source_entity") or info.get("source", ""),
                    "target_entity": info.get("target_entity") or info.get("target", ""),
                    "definition": info.get("definition") or info.get("description", ""),
                    "cardinality": info.get("cardinality", ""),
                }

        _log(
            "INFO",
            f"Found {len(rules)} business rules, {len(entity_types_def)} entity type definitions, "
            f"{len(relationships_def)} relationship definitions",
        )

        # ── Step 1: Create entity_category vertices ──────────────
        # We create one vertex per entity *and* one per relationship name so
        # that rules tagged with a relationship in `entity_or_relationship`
        # link to a canonical vertex (rather than falling into the synthetic
        # `_uncategorized_` bucket) and so that the entity↔entity edges added
        # in Step 2.5 below have endpoints to attach to.
        _log("INFO", "Step 1/5 – Creating entity / relationship category vertices")
        category_ids: dict[str, object] = {}
        for cat_name, cat_info in entity_types_def.items():
            definition = cat_info.get("definition", "") if isinstance(cat_info, dict) else ""
            v = (
                g.addV("entity_category")
                .property("vertex_uuid", str(uuid.uuid4()))
                .property("name", cat_name)
                .property("content", definition)
                .property("category", "entity_category")
                .property("node_type", "entity_category")
                .property("kind", "entity")
                .id_()
                .next()
            )
            category_ids[cat_name] = v
        entity_vertex_count = len(category_ids)

        for rel_name, rel_info in relationships_def.items():
            if rel_name in category_ids:
                continue  # don't double-create if name collision with an entity
            definition = rel_info.get("definition", "")
            v = (
                g.addV("entity_category")
                .property("vertex_uuid", str(uuid.uuid4()))
                .property("name", rel_name)
                .property("content", definition)
                .property("category", "entity_category")
                .property("node_type", "entity_category")
                .property("kind", "relationship")
                .id_()
                .next()
            )
            category_ids[rel_name] = v
        _log(
            "INFO",
            f"Created {entity_vertex_count} entity + "
            f"{len(category_ids) - entity_vertex_count} relationship category vertices",
        )

        # ── Step 2: Create business_rule vertices ────────────────
        _log("INFO", "Step 2/5 – Creating business rule vertices")
        rule_id_to_vertex = {}
        batch_size = DATA_LOAD_BATCH_LOG_INTERVAL
        for i, rule in enumerate(rules):
            rid = rule["rule_id"]

            # Use description as the searchable / embeddable content
            content = rule.get("description", "")

            # Compute the reference string:
            # v2 format uses structured `source_reference` object,
            # v1 format uses a plain `reference` string.
            source_ref = rule.get("source_reference")
            if isinstance(source_ref, dict):
                reference_str = source_ref.get("chunk_path", "")
                if source_ref.get("section_id"):
                    reference_str += f" ({source_ref['section_id']})"
            elif isinstance(source_ref, list) and source_ref:
                # Multiple source references — use the first item for the
                # stored reference string (full list is kept in source_reference).
                first = source_ref[0] if isinstance(source_ref[0], dict) else {}
                reference_str = first.get("chunk_path", "")
                if first.get("section_id"):
                    reference_str += f" ({first['section_id']})"
            else:
                reference_str = rule.get("reference", "")

            v = (
                g.addV("business_rule")
                .property("vertex_uuid", str(uuid.uuid4()))
                .property("rule_id", rid)
                .property("name", rule.get("rule_name", rid))
                .property("rule_name", rule.get("rule_name", ""))
                .property("rule_type", rule.get("rule_type", ""))
                .property("description", _safe_str(rule.get("description", "")))
                .property("conditions", _safe_str(rule.get("conditions", "")))
                .property("consequences", _safe_str(rule.get("consequences", "")))
                .property("exceptions", _safe_str(rule.get("exceptions", "")))
                .property("reference", _safe_str(reference_str))
                .property("mandatory", bool(rule.get("mandatory", False)))
                .property("confidence_score", float(rule.get("confidence_score", 0.0)))
                .property("requires_review", bool(rule.get("requires_review", False)))
                .property("review_reason", _safe_str(rule.get("review_reason", "")))
                .property("entity_or_relationship", rule.get("entity_or_relationship", ""))
                .property("entity_type", rule.get("entity_type", ""))
                .property("extraction_notes", _safe_str(rule.get("extraction_notes", "")))
                .property("content", content)
                .property("category", rule.get("rule_type", ""))
                .property("node_type", "business_rule")
                # ── Extended v2 properties ──
                .property("source_reference", _safe_str(rule.get("source_reference", "")))
                .property("effective_date", _safe_str(rule.get("effective_date", "")))
                .property("expiration_date", _safe_str(rule.get("expiration_date", "")))
                .property("superseded_by", _safe_str(rule.get("superseded_by", "")))
                .property("jurisdiction", _safe_str(rule.get("jurisdiction", "")))
                .property("risk_level", _safe_str(rule.get("risk_level", "")))
                .property("related_rules", _safe_str(rule.get("related_rules", "")))
                .property("enforcement_action", _safe_str(rule.get("enforcement_action", "")))
                .property("applicability_scope", _safe_str(rule.get("applicability_scope", "")))
                .property("data_points_required", _safe_str(rule.get("data_points_required", "")))
                .property("audit_frequency", _safe_str(rule.get("audit_frequency", "")))
                .property("reference_verified", bool(rule.get("reference_verified", False)))
                .property("reference_verification_note", _safe_str(rule.get("reference_verification_note", "")))
                .property("confidence_breakdown", _safe_str(rule.get("confidence_breakdown", "")))
                .property("deduplication_info", _safe_str(rule.get("deduplication_info", "")))
                .id_()
                .next()
            )
            rule_id_to_vertex[rid] = v

            if (i + 1) % batch_size == 0:
                _log("INFO", f"  Created {i + 1}/{len(rules)} rule vertices")

        _log("INFO", f"Created {len(rule_id_to_vertex)} business rule vertices")

        # ── Step 3: Create belongs_to_category edges ──────────────
        _log("INFO", "Step 3/5 – Creating category membership edges")
        cat_edge_count = 0
        orphan_rule_ids = []
        for rule in rules:
            rid = rule["rule_id"]
            cat = rule.get("entity_or_relationship", "")
            if cat and cat in category_ids and rid in rule_id_to_vertex:
                (
                    g.V(rule_id_to_vertex[rid])
                    .addE("belongs_to_category")
                    .to(__.V(category_ids[cat]))
                    .property("dependency_type", "categorization")
                    .next()
                )
                cat_edge_count += 1
            elif rid in rule_id_to_vertex:
                orphan_rule_ids.append(rid)
        _log("INFO", f"Created {cat_edge_count} category membership edges")

        # Synthetic '_uncategorized_' fallback: guarantee 100% rule→entity
        # connectivity. Created lazily, only when at least one orphan exists.
        if orphan_rule_ids:
            uncategorized_id = (
                g.addV("entity_category")
                .property("vertex_uuid", str(uuid.uuid4()))
                .property("name", "_uncategorized_")
                .property("content", "Synthetic catch-all category for rules whose entity_or_relationship did not resolve to any canonical Agent 2 entity/relationship.")
                .property("category", "entity_category")
                .property("node_type", "entity_category")
                .property("synthetic", True)
                .id_()
                .next()
            )
            for rid in orphan_rule_ids:
                (
                    g.V(rule_id_to_vertex[rid])
                    .addE("belongs_to_category")
                    .to(__.V(uncategorized_id))
                    .property("dependency_type", "categorization_fallback")
                    .next()
                )
            _log("WARN", f"Attached {len(orphan_rule_ids)} orphan rule(s) to synthetic '_uncategorized_' entity")

        # ── Step 4: Create relates_to edges between entities ─────
        # Materialise the entity-relationship layer so the graph reflects
        # what the Explorer view shows.  Without this, entity vertices that
        # are not referenced by any rule end up disconnected.
        _log("INFO", "Step 4/5 – Creating entity↔entity relationship edges")
        rel_edge_count = 0
        rel_skipped = 0
        for rel_name, rel_info in relationships_def.items():
            if not isinstance(rel_info, dict):
                rel_skipped += 1
                continue
            src = rel_info.get("source_entity")
            tgt = rel_info.get("target_entity")
            if not src or not tgt or src not in category_ids or tgt not in category_ids:
                rel_skipped += 1
                continue
            (
                g.V(category_ids[src])
                .addE("relates_to")
                .to(__.V(category_ids[tgt]))
                .property("name", rel_name)
                .property("relationship_name", rel_name)
                .property("definition", _safe_str(rel_info.get("definition", "")))
                .property("cardinality", _safe_str(rel_info.get("cardinality", "")))
                .next()
            )
            rel_edge_count += 1
        _log(
            "INFO",
            f"Created {rel_edge_count} entity↔entity edges ({rel_skipped} skipped — endpoint not in entity_types)",
        )

        # ── Step 5: Create dependency edges ───────────────────────
        _log("INFO", "Step 5/5 – Creating dependency edges between rules")
        dep_count = 0
        skipped = 0
        for rule in rules:
            source_id = rule["rule_id"]
            if source_id not in rule_id_to_vertex:
                continue
            for dep in rule.get("dependencies", []):
                target_rule_id = dep.get("depends_on_rule", "")
                if target_rule_id not in rule_id_to_vertex:
                    skipped += 1
                    continue
                (
                    g.V(rule_id_to_vertex[source_id])
                    .addE("depends_on")
                    .to(__.V(rule_id_to_vertex[target_rule_id]))
                    .property("dependency_type", dep.get("dependency_type", "unknown"))
                    .property("rationale", _safe_str(dep.get("rationale", "")))
                    .property("impact_if_fails", _safe_str(dep.get("impact_if_fails", "")))
                    .property("strength", int(dep.get("strength", 0)))
                    .next()
                )
                dep_count += 1

        _log("INFO", f"Created {dep_count} dependency edges ({skipped} skipped — target not found)")

        # ── Summary ───────────────────────────────────────────────
        total_v = g.V().count().next()
        total_e = g.E().count().next()
        _log("INFO", f"Load complete for '{graph_name}' — {total_v} vertices, {total_e} edges")


def load_all_graphs() -> None:
    """Load data into all configured graphs.

    Always clears each graph before loading so repeated runs (container
    restarts, redeploys) do not accumulate duplicate vertices/edges in
    JanusGraph's persistent storage.
    """
    _log("INFO", "Loading all configured graphs...")
    skipped = []
    for graph_name, config in GRAPH_CONFIGS.items():
        kg_file = config.get("file", "")
        if kg_file and not os.path.isfile(kg_file):
            _log("WARN", f"Skipping graph '{graph_name}' — KG file not found: {kg_file}")
            skipped.append(graph_name)
            continue
        _log("INFO", f"Loading graph '{graph_name}' ({config['name']})...")
        load_data(graph_name, clear_first=True)
    if skipped:
        _log("WARN", f"Finished with {len(skipped)} graph(s) skipped (missing KG files): {skipped}")
    else:
        _log("INFO", "All graphs loaded successfully")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    
    # Support command line arguments
    if len(sys.argv) > 1:
        graph_to_load = sys.argv[1]
        if graph_to_load == "all":
            load_all_graphs()
        else:
            load_data(graph_to_load)
    else:
        # Default: load all graphs
        load_all_graphs()
