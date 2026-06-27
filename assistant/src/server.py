"""
Explorer — Flask API server providing:
  - Graph data endpoints for the D3.js visualization of compliance business rules
  - Full-text search proxy (OpenSearch via Gremlin)
  - Semantic search endpoint (OpenSearch k-NN)
  - AI chat agent with OpenAI tool calling and SSE streaming
  - Gremlin query console for interactive exploration
"""

import sys
import json
import time
import re
import logging
import os
import shutil
import tarfile
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote as _url_quote
from html import escape as _html_escape

from flask import Flask, jsonify, request, send_from_directory, Response
from flask_cors import CORS
from gremlin_python.process.traversal import P, TextP, Order
from gremlin_python.process.graph_traversal import __
from gremlin_python.driver.driver_remote_connection import DriverRemoteConnection
from gremlin_python.driver.serializer import GraphSONSerializersV3d0
from openai import OpenAI
from dotenv import load_dotenv

from src.graph_connection import get_traversal
from src.semantic_search import SemanticSearchEngine
from src.models import init_db, SessionLocal, NodeAnnotation, GraphRelease, GraphState
from src.docs_sync import copy_docs_tree, docs_folder_rel
from src.cache import get_cache
from conf.config import (
    JANUSGRAPH_HOST,
    JANUSGRAPH_PORT,
    DEFAULT_GRAPH,
    OPENAI_CHAT_MODEL,
    OPENAI_REASONING_EFFORT,
    supports_reasoning_effort,
    MAX_TOOL_ROUNDS,
    SERVER_HOST,
    SERVER_PORT,
    FLASK_DEBUG,
    SEMANTIC_SEARCH_DEFAULT_TOP_K,
    TEXT_SEARCH_MAX_RESULTS,
    FUZZY_MATCH_MAX_CANDIDATES,
    SIBLING_RULES_MAX_RESULTS,
    STATS_HUB_RULES_LIMIT,
)
from conf.graph_manifest import (
    get_graphs,
    get_graph_configs,
    get_traversal_sources,
    get_graph_enum_description,
    get_default_traversal_source,
    get_docs_folder,
    get_loaded_graphs,
    get_loaded_traversal_sources,
    invalidate_cache as _invalidate_manifest_cache,
    add_graph_to_manifest,
    remove_graph_from_manifest,
    resolve_graph_key,
    resolve_traversal_source,
)
from conf.config import URL_PREFIX
from src.log import log as _log

# Load environment variables
load_dotenv()

# Application root for KG / docs / pipeline-output paths.
# Defaults to the container layout (/app); can be overridden with CA_APP_ROOT
# when running assistant directly on the host (./start.sh).
APP_ROOT = Path(os.environ.get("CA_APP_ROOT", "/app")).resolve()

app = Flask(__name__, static_folder="../ui", static_url_path="")
CORS(app, origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:4000"])

# Shared semantic search engine
_engine = SemanticSearchEngine()

# Initialize OpenAI client
_openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── Graph data-presence cache ─────────────────────────────────────────────────
# Querying JanusGraph on every chat request to check whether a graph has data
# is too expensive, so we cache the result per traversal_source with a TTL.
# Call _invalidate_graph_data_cache(ts) after any clean/remove to force a
# fresh check on the next request.
_GRAPH_DATA_TTL = 120  # seconds
_graph_data_cache: dict[str, tuple[bool, float]] = {}  # ts -> (has_data, timestamp)


def _graph_has_jg_data(traversal_source: str) -> bool:
    """Return True if JanusGraph has at least one vertex for traversal_source.

    Result is cached for _GRAPH_DATA_TTL seconds.  Falls back to True on
    connection errors so a temporary JanusGraph hiccup doesn't hide graphs.
    """
    entry = _graph_data_cache.get(traversal_source)
    if entry and time.time() - entry[1] < _GRAPH_DATA_TTL:
        return entry[0]
    try:
        with get_traversal(traversal_source) as (g, _conn):
            has = g.V().limit(1).count().next() > 0
    except Exception as exc:
        # Assume data present so a temporary hiccup doesn't hide graphs, but do
        # NOT cache this guess — otherwise the wrong answer is served for the
        # full TTL even after JanusGraph recovers. Re-query on the next call.
        _log("WARNING", f"_graph_has_jg_data({traversal_source}) failed, assuming present: {exc}")
        return True
    _graph_data_cache[traversal_source] = (has, time.time())
    return has


def _invalidate_graph_data_cache(traversal_source: str) -> None:
    """Force the next _graph_has_jg_data() call to re-query JanusGraph."""
    _graph_data_cache.pop(traversal_source, None)


def _log_cache_usage(response) -> None:
    """Log OpenAI prompt cache hits for observability."""
    usage = getattr(response, "usage", None)
    if not usage:
        return
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) if details else 0
    if cached:
        _log("DEBUG", f"Prompt cache hit: {cached}/{usage.prompt_tokens} tokens cached")


# Initialize SQLite database
init_db()


# ── Static UI ─────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/logo.svg")
def logo():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return send_from_directory(root_dir, "logo.svg")


@app.route("/api/")
def api_health():
    """Simple health-check endpoint used by the frontend status badge."""
    return jsonify({"status": "ok"})


# ── Persistent Node Annotations (SQLAlchemy) ─────────────────────

@app.route("/api/annotations/<node_id>", methods=["GET"])
def get_annotation(node_id):
    """Return stored annotation for a node, or defaults if none exists."""
    session = SessionLocal()
    try:
        row = session.get(NodeAnnotation, node_id)
        if row:
            return jsonify(row.to_dict())
        return jsonify({
            "comments": [], "reviewed": None, "reviewHistory": [],
            "approved": None, "approvalHistory": [],
            "versionHistory": [], "deleted": False, "deletedAt": None, "edits": {},
        })
    finally:
        session.close()


@app.route("/api/annotations/<node_id>", methods=["PUT"])
def put_annotation(node_id):
    """Create or update the full annotation object for a node."""
    data = request.get_json(force=True)
    session = SessionLocal()
    try:
        row = session.get(NodeAnnotation, node_id)
        if row:
            row.update_from_dict(data)
        else:
            row = NodeAnnotation.from_dict(node_id, data)
            session.add(row)
        session.commit()
        return jsonify(row.to_dict()), 200
    except Exception as exc:
        session.rollback()
        _log("ERROR", f"Failed to save annotation for {node_id}: {exc}")
        return jsonify({"error": str(exc)}), 500
    finally:
        session.close()


@app.route("/api/annotations", methods=["GET"])
def list_annotations():
    """Return all stored annotations keyed by node_id."""
    session = SessionLocal()
    try:
        rows = session.query(NodeAnnotation).all()
        result = {row.node_id: row.to_dict() for row in rows}
        return jsonify(result)
    finally:
        session.close()


@app.route("/api/annotations/<node_id>", methods=["DELETE"])
def delete_annotation(node_id):
    """Remove all annotations for a node."""
    session = SessionLocal()
    try:
        row = session.get(NodeAnnotation, node_id)
        if row:
            session.delete(row)
            session.commit()
        return jsonify({"ok": True})
    except Exception as exc:
        session.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        session.close()


# ── AI Rewrite (GPT-4o-mini) ─────────────────────────────────────

_REWRITE_MODEL = "gpt-4o-mini"

_REWRITE_SYSTEM_PROMPT = (
    "You are a compliance writing assistant for a financial regulatory knowledge graph. "
    "Rewrite the user's text to be clearer, more precise, and professional while "
    "preserving all factual content and regulatory meaning. "
    "Return ONLY the rewritten text with no preamble, explanation, or quotes."
)


@app.route("/api/rewrite", methods=["POST"])
def rewrite_text():
    """Use GPT-4o-mini to rewrite user-supplied text for clarity and precision."""
    body = request.get_json(force=True)
    text = (body.get("text") or "").strip()
    context = (body.get("context") or "").strip()

    if not text:
        return jsonify({"error": "text is required"}), 400
    if len(text) > 4000:
        return jsonify({"error": "text exceeds 4000 character limit"}), 400

    # Build messages
    messages = [{"role": "system", "content": _REWRITE_SYSTEM_PROMPT}]
    user_content = text
    if context:
        user_content = f"Field: {context}\n\n{text}"
    messages.append({"role": "user", "content": user_content})

    try:
        resp = _openai_client.chat.completions.create(
            model=_REWRITE_MODEL,
            messages=messages,
            temperature=0.4,
            max_tokens=1024,
        )
        rewritten = (resp.choices[0].message.content or "").strip()
        _log("INFO", f"Rewrite: {len(text)} chars → {len(rewritten)} chars")
        return jsonify({"rewritten": rewritten})
    except Exception as exc:
        _log("ERROR", f"Rewrite failed: {exc}")
        return jsonify({"error": str(exc)}), 500


# ── AI Rule-ID Suggestion (GPT-4o-mini) ──────────────────────────

_RULE_ID_SYSTEM_PROMPT = (
    "You are a rule-ID generator for a financial regulatory compliance knowledge graph.\n"
    "Given a rule name, entity name, and rule type, produce a concise rule_id that "
    "follows the convention:\n"
    "  BR_{ENTITY}_{RULE_TYPE}_{SEQ}_{SUB}\n"
    "Where:\n"
    "  - ENTITY is the entity in UPPER_SNAKE_CASE (e.g. REGULATED_INSTITUTION, APPRAISAL_REPORT)\n"
    "  - RULE_TYPE is one of: CONSTRAINT, ELIGIBILITY, PROCESS, PROHIBITION, DOCUMENTATION, VALIDATION, COMPLIANCE, CALCULATION, DEFINITION\n"
    "  - SEQ is a 3-digit sequence group number (e.g. 001)\n"
    "  - SUB is a 3-digit sub-sequence (e.g. 001)\n\n"
    "Examples of existing rule IDs:\n"
    "  BR_REGULATED_INSTITUTION_VALIDATION_001_001\n"
    "  BR_APPRAISAL_REPORT_CONSTRAINT_008_003\n"
    "  BR_AGENCY_GUIDELINE_COMPLIANCE_007_007\n"
    "  BR_LOAN_APPLICATION_ELIGIBILITY_002_004\n\n"
    "Return ONLY the rule_id string, nothing else. No quotes, no explanation."
)


@app.route("/api/suggest-rule-id", methods=["POST"])
def suggest_rule_id():
    """Use GPT-4o-mini to suggest a rule_id based on the node name."""
    body = request.get_json(force=True)
    name = (body.get("name") or "").strip()
    entity = (body.get("entity") or "").strip()
    rule_type = (body.get("rule_type") or "").strip()

    if not name:
        return jsonify({"error": "name is required"}), 400

    prompt_parts = [f"Rule name: {name}"]
    if entity:
        prompt_parts.append(f"Entity: {entity}")
    if rule_type:
        prompt_parts.append(f"Rule type: {rule_type}")
    user_content = "\n".join(prompt_parts)

    try:
        resp = _openai_client.chat.completions.create(
            model=_REWRITE_MODEL,
            messages=[
                {"role": "system", "content": _RULE_ID_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=80,
        )
        suggested = (resp.choices[0].message.content or "").strip().strip('"').strip("'")
        _log("INFO", f"Rule-ID suggestion for '{name}': {suggested}")
        return jsonify({"rule_id": suggested})
    except Exception as exc:
        _log("ERROR", f"Rule-ID suggestion failed: {exc}")
        return jsonify({"error": str(exc)}), 500


# ── Task Box — pre-populated compliance review / approval tasks ──
# Tasks use `node_name` as the stable identifier. The `node_id` is
# resolved dynamically at startup from the live graph so that vertex
# ID changes (e.g. after a fresh reload) do not make tasks stale.

_TASK_TEMPLATES = [
    {
        "id": "task-1",
        "type": "review",
        "title": "Review Seller Repurchase Fee Rule",
        "description": "Verify the $200 seller repurchase fee rule is correctly captured and conditions align with guidelines.",
        "node_name": "Repurchase Fee $200 When Seller Repurchases Loan",
        "graph_name": "sample_guidelines_g",
        "assignee": "Gina",
        "priority": "high",
        "due_date": "2025-07-28",
        "status": "pending",
        "highlight_terms": ["repurchase", "$200", "seller", "fee"],
    },
    {
        "id": "task-2",
        "type": "review",
        "title": "Review Conforming Loan Limits",
        "description": "Validate the 2025 FHFA conforming loan limits for PR 1-4 unit properties against published guidance.",
        "node_name": "PR Conforming Limits 1-4 Units $806.5k-$1.551M",
        "graph_name": "sample_guidelines_g",
        "assignee": "Rose",
        "priority": "high",
        "due_date": "2025-07-25",
        "status": "pending",
        "highlight_terms": ["conforming limit", "$806,500", "1-unit", "$1,551,250"],
    },
    {
        "id": "task-3",
        "type": "review",
        "title": "Review Credit Report Inclusion Rule",
        "description": "Check that all credit reports used must be included in file requirement is correctly captured and categorized.",
        "node_name": "All Credit Reports Used Must Be Included in File",
        "graph_name": "sample_guidelines_g",
        "assignee": "Jack",
        "priority": "low",
        "due_date": "2025-08-05",
        "status": "pending",
        "highlight_terms": ["credit report", "included", "file"],
    },
    {
        "id": "task-4",
        "type": "approval",
        "title": "Approve Desktop Appraisal Prohibition",
        "description": "Approve the rule prohibiting desktop appraisals for condos, CLT, coop, manufactured housing, and renovation properties.",
        "node_name": "Desktop Appraisal Prohibited for Condos, CLT, Coop, Manufactured, Renovation",
        "graph_name": "sample_guidelines_g",
        "assignee": "Tom",
        "priority": "medium",
        "due_date": "2025-07-29",
        "status": "pending",
        "highlight_terms": ["desktop appraisal", "prohibited", "condos", "manufactured"],
    },
]

# Populated at startup by _resolve_task_node_ids()
_TASKS: list[dict] = []


def _resolve_task_node_ids() -> None:
    """Look up each task's vertex ID from the graph using its stable node_name.

    This runs once at server startup so that tasks always point to the
    correct vertex regardless of ID reassignment after a fresh reload.
    """
    from src.graph_connection import get_traversal
    from gremlin_python.process.graph_traversal import __

    _TASKS.clear()
    for tmpl in _TASK_TEMPLATES:
        task = dict(tmpl)
        graph_name = task["graph_name"]
        node_name = task["node_name"]
        try:
            with get_traversal(graph_name) as (g, conn):
                results = (
                    g.V()
                    .has("name", node_name)
                    .id_()
                    .toList()
                )
                if results:
                    task["node_id"] = str(results[0])
                else:
                    _log("WARN", f"Task '{task['id']}': vertex '{node_name}' not found in {graph_name}")
                    task["node_id"] = None
        except Exception as exc:
            _log("WARN", f"Task '{task['id']}': failed to resolve node_id: {exc}")
            task["node_id"] = None
        _TASKS.append(task)


@app.route("/api/tasks")
def get_tasks():
    """Return the pre-populated list of review and approval tasks."""
    return jsonify({"tasks": _TASKS})


@app.route("/api/tasks/<task_id>/complete", methods=["POST"])
def complete_task(task_id):
    """Mark a task as completed."""
    for task in _TASKS:
        if task["id"] == task_id:
            task["status"] = "completed"
            return jsonify({"ok": True, "task": task})
    return jsonify({"error": "Task not found"}), 404


# ── Known vertex property keys (from schema) ────────────────────
# Used to guarantee ALL properties are returned in bulk queries.
ALL_VERTEX_PROPERTIES = [
    "rule_id", "rule_name", "rule_type", "description",
    "conditions", "consequences", "exceptions", "reference",
    "mandatory", "confidence_score", "requires_review", "review_reason",
    "entity_or_relationship", "entity_type", "extraction_notes",
    "node_type", "name", "content", "category", "vertex_uuid",
    # Extended v2 KG properties
    "source_reference", "effective_date", "expiration_date", "superseded_by",
    "jurisdiction", "risk_level", "related_rules", "enforcement_action",
    "applicability_scope", "data_points_required", "audit_frequency",
    "reference_verified", "reference_verification_note",
    "confidence_breakdown", "deduplication_info",
]

# Default values for each property type
_PROPERTY_DEFAULTS = {
    "rule_id": "", "rule_name": "", "rule_type": "", "description": "",
    "conditions": "", "consequences": "", "exceptions": "", "reference": "",
    "mandatory": False, "confidence_score": 0, "requires_review": False,
    "review_reason": "", "entity_or_relationship": "", "entity_type": "",
    "extraction_notes": "", "node_type": "", "name": "", "content": "",
    "category": "", "vertex_uuid": "",
    # Extended v2 KG properties
    "source_reference": "", "effective_date": "", "expiration_date": "",
    "superseded_by": "", "jurisdiction": "", "risk_level": "",
    "related_rules": "", "enforcement_action": "", "applicability_scope": "",
    "data_points_required": "", "audit_frequency": "",
    "reference_verified": False, "reference_verification_note": "",
    "confidence_breakdown": "", "deduplication_info": "",
}

# ── Resolve graph name ────────────────────────────────────────────

def _resolve_graph_name(name: str | None) -> str:
    """Map the generic alias 'g' (or empty/None) to DEFAULT_GRAPH.

    The frontend initialises currentGraphName to 'g' before any graph
    is loaded. JanusGraph multi-graph setups do not configure a plain
    'g' traversal source, so we must fall back to DEFAULT_GRAPH.
    """
    if not name or name == "g":
        return DEFAULT_GRAPH
    return resolve_traversal_source(name)

# ── Graph data for visualization ─────────────────────────────────

@app.route("/api/graph")
def get_graph():
    """Return full graph as nodes + links for D3 force layout."""
    graph_name = _resolve_graph_name(request.args.get('graph_name'))
    with get_traversal(graph_name) as (g, conn):
        # Vertices — explicitly request ALL known property keys to
        # guarantee every field is serialised even for large graphs.
        raw_vertices = (
            g.V()
            .project("id", "label", "props")
            .by(__.id_())
            .by(__.label())
            .by(__.valueMap(*ALL_VERTEX_PROPERTIES))
            .toList()
        )

        # Edges — include valueMap for all edge properties
        edges = (
            g.E()
            .project("id", "source", "target", "label", "dependency_type", "props")
            .by(__.id_())
            .by(__.outV().id_())
            .by(__.inV().id_())
            .by(__.label())
            .by(__.coalesce(__.values("dependency_type"), __.constant("")))
            .by(__.valueMap())
            .toList()
        )

        # Convert JanusGraph IDs to strings for JSON
        nodes = []
        for v in raw_vertices:
            props = v["props"]
            # valueMap returns lists for each key; unwrap single values
            flat = {}
            for k, val in props.items():
                if isinstance(val, list) and len(val) == 1:
                    flat[k] = val[0]
                else:
                    flat[k] = val
            node = {
                "id": str(v["id"]),
                "label": v["label"],
            }
            # Include ALL properties from the graph — convert values to JSON-safe
            for k, val in flat.items():
                node[k] = _to_json_safe(val)
            # Ensure EVERY known property key is present with a default
            for prop_key, default_val in _PROPERTY_DEFAULTS.items():
                node.setdefault(prop_key, default_val)
            # Derived defaults where the natural value should come from
            # another property when the original is absent.
            if not node.get("name"):
                node["name"] = flat.get("rule_id", "")
            if not node.get("category"):
                node["category"] = flat.get("rule_type", "")
            if not node.get("node_type"):
                node["node_type"] = v["label"]
            nodes.append(node)

        links = []
        for e in edges:
            link = {
                "id": str(e["id"]),
                "source": str(e["source"]),
                "target": str(e["target"]),
                "label": e["label"],
                "dependency_type": e["dependency_type"],
            }
            # Include all edge properties from valueMap if available
            if "props" in e:
                eprops = e["props"]
                for k, val in eprops.items():
                    ev = val[0] if isinstance(val, list) and len(val) == 1 else val
                    link.setdefault(k, _to_json_safe(ev))
            links.append(link)

        return jsonify({"nodes": nodes, "links": links, "graph_name": graph_name})


# ── Vertex detail ─────────────────────────────────────────────────

@app.route("/api/vertex/<vertex_id>")
def get_vertex(vertex_id):
    """Return detailed info about a single vertex and its neighbors."""
    graph_name = _resolve_graph_name(request.args.get('graph_name'))
    try:
        with get_traversal(graph_name) as (g, conn):
            # Try to parse ID as integer (JanusGraph uses long IDs)
            try:
                vid = int(vertex_id)
            except ValueError:
                vid = vertex_id

            props = (
                g.V(vid)
                .project("id", "label", "props")
                .by(__.id_())
                .by(__.label())
                .by(__.valueMap(*ALL_VERTEX_PROPERTIES))
                .next()
            )

            # Flatten valueMap
            flat = {}
            for k, val in props["props"].items():
                if isinstance(val, list) and len(val) == 1:
                    flat[k] = val[0]
                else:
                    flat[k] = val

            neighbors = (
                g.V(vid)
                .both()
                .project("id", "label", "name", "node_type")
                .by(__.id_())
                .by(__.label())
                .by(__.coalesce(__.values("name"), __.values("rule_id"), __.constant("")))
                .by(__.coalesce(__.values("node_type"), __.constant("")))
                .toList()
            )

            # Outgoing dependency edges
            out_deps = (
                g.V(vid)
                .outE("depends_on")
                .project("target_name", "dependency_type", "strength")
                .by(__.inV().coalesce(__.values("name"), __.values("rule_id")))
                .by(__.values("dependency_type"))
                .by(__.coalesce(__.values("strength"), __.constant(0)))
                .toList()
            )

            # Incoming dependency edges (rules that depend on this one)
            in_deps = (
                g.V(vid)
                .inE("depends_on")
                .project("source_name", "dependency_type", "strength")
                .by(__.outV().coalesce(__.values("name"), __.values("rule_id")))
                .by(__.values("dependency_type"))
                .by(__.coalesce(__.values("strength"), __.constant(0)))
                .toList()
            )

            # Build response with ALL known property defaults
            result = {
                "id": str(props["id"]),
                "label": props["label"],
            }
            # Add all properties with defaults
            for prop_key, default_val in _PROPERTY_DEFAULTS.items():
                result[prop_key] = _to_json_safe(flat.get(prop_key, default_val))
            # Override with actual values where available
            for k, v in flat.items():
                result[k] = _to_json_safe(v)
            result["neighbors"] = [
                {"id": str(n["id"]), "label": n["label"], "name": n["name"], "node_type": n["node_type"]}
                for n in neighbors
            ]
            result["depends_on"] = [_to_json_safe(d) for d in out_deps]
            result["depended_by"] = [_to_json_safe(d) for d in in_deps]
            return jsonify(result)

    except Exception as exc:
        err_msg = str(exc) or "Vertex not found"
        _log("WARN", f"get_vertex failed for {vertex_id} on {graph_name}: {err_msg}")
        return jsonify({"error": err_msg}), 404


# ── Full-text search (OpenSearch via Gremlin) ─────────────────────

@app.route("/api/search/text")
def text_search():
    """
    Full-text search over vertex content via the OpenSearch mixed index.
    Query params: q (search term), category (optional filter)
    """
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    if not query:
        return jsonify({"error": "query parameter 'q' is required"}), 400

    with get_traversal() as (g, conn):
        t = g.V().has("content", TextP.containing(query))

        if category:
            t = t.has("category", category)

        results = (
            t.project("id", "name", "label", "category", "content")
            .by(__.id_())
            .by(__.values("name"))
            .by(__.label())
            .by(__.values("category"))
            .by(__.values("content"))
            .toList()
        )

        return jsonify({
            "query": query,
            "category": category or None,
            "count": len(results),
            "results": [
                {
                    "id": str(r["id"]),
                    "name": r["name"],
                    "label": r["label"],
                    "category": r["category"],
                    "content": r["content"],
                }
                for r in results
            ],
        })


# ── Semantic search (OpenSearch k-NN) ──────────────────────────────

@app.route("/api/search/semantic")
def semantic_search():
    """
    Semantic similarity search.
    Query params: q (natural-language query), top_k (default SEMANTIC_SEARCH_DEFAULT_TOP_K), graph_name (optional)
    """
    query = request.args.get("q", "").strip()
    try:
        top_k = int(request.args.get("top_k", str(SEMANTIC_SEARCH_DEFAULT_TOP_K)))
    except (TypeError, ValueError):
        return jsonify({"error": "top_k must be an integer"}), 400
    graph_name = request.args.get("graph_name", "").strip() or None

    if not query:
        return jsonify({"error": "query parameter 'q' is required"}), 400

    try:
        results = _engine.search(query, top_k=top_k, graph_name=graph_name)
        return jsonify({
            "query": query,
            "top_k": top_k,
            "graph_name": graph_name,
            "results": results,
        })
    except Exception as exc:
        _log("ERROR", f"Semantic search failed: {exc}")
        return jsonify({"error": str(exc)}), 500


# ── Gremlin query console ─────────────────────────────────────────

# Pre-built example queries for the UI dropdown
EXAMPLE_QUERIES = [
    {
        "name": "Graph Overview",
        "query": "g.V().groupCount().by(label()).toList()",
        "description": "Count of all vertices grouped by label (business_rule vs entity_category)",
    },
    {
        "name": "Rules by Type",
        "query": "g.V().hasLabel('business_rule').groupCount().by(values('rule_type')).order(local).by(values, desc).toList()",
        "description": "How many constraint, eligibility, process, documentation, validation, prohibition rules exist",
    },
    {
        "name": "Top 10 Hub Rules (Most Dependencies)",
        "query": "g.V().hasLabel('business_rule').project('name','total_deps','out','in').by(values('name')).by(bothE('depends_on').count()).by(outE('depends_on').count()).by(inE('depends_on').count()).order().by(select('total_deps'), desc).limit(10).toList()",
        "description": "The 10 most interconnected rules — high-impact nodes in the compliance graph",
    },
    {
        "name": "Dependency Types Breakdown",
        "query": "g.E().hasLabel('depends_on').groupCount().by(values('dependency_type')).order(local).by(values, desc).toList()",
        "description": "Distribution of dependency types: prerequisite, complementary, conditional, sequential, override, etc.",
    },
    {
        "name": "Strongest Dependencies (strength = 5)",
        "query": "g.E().hasLabel('depends_on').has('strength', 5).project('from','to','type','rationale').by(outV().values('name')).by(inV().values('name')).by(values('dependency_type')).by(values('rationale')).toList()",
        "description": "Critical dependency links with maximum strength rating",
    },
    {
        "name": "High Confidence Rules (> 90%)",
        "query": "g.V().hasLabel('business_rule').has('confidence_score', gt(90.0)).project('name','confidence','type','mandatory').by(values('name')).by(values('confidence_score')).by(values('rule_type')).by(values('mandatory')).order().by(select('confidence'), desc).limit(20).toList()",
        "description": "Most reliably extracted rules — confidence score above 90",
    },
    {
        "name": "Low Confidence Rules (Needs Review)",
        "query": "g.V().hasLabel('business_rule').has('requires_review', true).project('name','confidence','review_reason','type').by(values('name')).by(values('confidence_score')).by(values('review_reason')).by(values('rule_type')).order().by(select('confidence'), asc).limit(20).toList()",
        "description": "Rules flagged for manual review — lowest confidence first",
    },
    {
        "name": "Mandatory Prohibition Rules",
        "query": "g.V().hasLabel('business_rule').has('rule_type','prohibition').has('mandatory', true).project('name','description','confidence').by(values('name')).by(values('description')).by(values('confidence_score')).toList()",
        "description": "All mandatory prohibitions — things the lender must NOT do",
    },
    {
        "name": "Entity Categories with Rule Counts",
        "query": "g.V().hasLabel('entity_category').project('category','rule_count').by(values('name')).by(inE('belongs_to_category').count()).order().by(select('rule_count'), desc).toList()",
        "description": "How many rules belong to each entity category (BORROWER, PROPERTY, UNDERWRITING, etc.)",
    },
    {
        "name": "Prerequisite Chains (2-hop)",
        "query": "g.V().hasLabel('business_rule').as('start').outE('depends_on').has('dependency_type','prerequisite').inV().as('mid').outE('depends_on').has('dependency_type','prerequisite').inV().as('end').select('start','mid','end').by(values('name')).limit(10).toList()",
        "description": "Rules chained by prerequisite dependencies — A requires B requires C",
    },
    {
        "name": "Override Relationships",
        "query": "g.E().hasLabel('depends_on').has('dependency_type','override').project('overriding_rule','overridden_rule','rationale').by(outV().values('name')).by(inV().values('name')).by(values('rationale')).toList()",
        "description": "Rules that supersede other rules (e.g., state law overriding Selling Guide)",
    },
    {
        "name": "Isolated Rules (No Dependencies)",
        "query": "g.V().hasLabel('business_rule').where(bothE('depends_on').count().is(0)).project('name','type','entity','confidence').by(values('name')).by(values('rule_type')).by(values('entity_or_relationship')).by(values('confidence_score')).order().by(select('confidence'), desc).limit(20).toList()",
        "description": "Standalone rules with no dependency connections — potential gaps or self-contained rules",
    },
    {
        "name": "Full-Text Search: 'appraisal'",
        "query": "g.V().has('content', textContains('appraisal')).project('name','type','snippet').by(values('name')).by(coalesce(values('rule_type'), constant('category'))).by(values('content')).limit(10).toList()",
        "description": "Search for 'appraisal' across all rule descriptions via OpenSearch mixed index",
    },
    {
        "name": "Rules by Entity: BORROWER",
        "query": "g.V().hasLabel('business_rule').has('entity_or_relationship','BORROWER').project('name','type','mandatory','confidence').by(values('name')).by(values('rule_type')).by(values('mandatory')).by(values('confidence_score')).order().by(select('type')).toList()",
        "description": "All rules that apply to the BORROWER entity",
    },
    {
        "name": "Vertex Count & Edge Count",
        "query": "g.V().count().toList()",
        "description": "Total number of vertices in the graph",
    },
]


@app.route("/api/gremlin/examples")
def gremlin_examples():
    """Return the list of pre-built example Gremlin queries."""
    return jsonify({"examples": EXAMPLE_QUERIES})


@app.route("/api/gremlin/execute", methods=["POST"])
def gremlin_execute():
    """
    Execute a raw Gremlin query and return results as JSON.
    Accepts {\"query\": \"g.V().count()\"} in the POST body.
    """
    body = request.get_json(silent=True) or {}
    query_str = body.get("query", "").strip()

    if not query_str:
        return jsonify({"error": "query field is required"}), 400

    # Safety: this endpoint executes raw Gremlin/Groovy against JanusGraph. Block
    # mutating and host-level operations unless explicitly opted in via the
    # GREMLIN_ALLOW_MUTATIONS env var (and, ideally, real auth in front of it).
    blocked = _gremlin_safety_violation(query_str)
    if blocked and os.getenv("GREMLIN_ALLOW_MUTATIONS", "false").lower() != "true":
        return jsonify({
            "error": (
                f"Blocked potentially unsafe operation '{blocked}'. This endpoint is "
                "read-only; set GREMLIN_ALLOW_MUTATIONS=true to allow write queries."
            ),
            "query": query_str,
        }), 403

    conn = None
    try:
        url = f"ws://{JANUSGRAPH_HOST}:{JANUSGRAPH_PORT}/gremlin"
        conn = DriverRemoteConnection(
            url, "g",
            message_serializer=GraphSONSerializersV3d0(),
        )
        client = conn._client

        start = time.time()
        raw_result = client.submit(query_str).all().result()
        elapsed_ms = round((time.time() - start) * 1000, 1)

        # Serialize results — JanusGraph returns various types
        serialized = _serialize_gremlin_result(raw_result)

        _log("INFO", f"Gremlin query executed in {elapsed_ms}ms, {len(raw_result)} results")

        return jsonify({
            "query": query_str,
            "elapsed_ms": elapsed_ms,
            "count": len(raw_result),
            "results": serialized,
        })

    except Exception as exc:
        _log("ERROR", f"Gremlin query failed: {exc}")
        error_msg = str(exc)
        # Extract clean error message from GremlinServerError
        if "message" in error_msg and "code" in error_msg:
            try:
                # Try to extract just the message portion
                parts = error_msg.split(":", 1)
                if len(parts) > 1:
                    error_msg = parts[1].strip()[:500]
            except Exception:
                pass
        return jsonify({"error": error_msg[:1000], "query": query_str}), 400
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# Mutating / host-level Gremlin & Groovy tokens that must not run on the
# read-only execute endpoint. Matched case-insensitively as whole words.
_GREMLIN_BLOCKLIST = (
    "drop", "addv", "adde", "property", "remove",
    "system", "thread", "runtime", "process", "file",
    "import", "new ", "evaluate", "java.", "groovy.", "execfile", "exec(",
)


def _gremlin_safety_violation(query_str):
    """Return the first blocked token found in a query, or None if it looks safe."""
    lowered = query_str.lower()
    for token in _GREMLIN_BLOCKLIST:
        # Word-ish boundary so 'property' matches but 'propertyMap'/'properties' (read) don't.
        pattern = re.escape(token) if token.endswith((" ", "(")) else r"\b" + re.escape(token) + r"\b(?!\w)"
        if re.search(pattern, lowered):
            return token.strip()
    return None


def _serialize_gremlin_result(results):
    """Convert Gremlin result objects into JSON-serializable form."""
    serialized = []
    for item in results:
        serialized.append(_to_json_safe(item))
    return serialized


def _to_json_safe(obj):
    """Recursively convert a Gremlin result to JSON-safe types."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(i) for i in obj]
    if isinstance(obj, set):
        return [_to_json_safe(i) for i in obj]
    # Gremlin Path objects
    if hasattr(obj, 'objects'):
        return [_to_json_safe(o) for o in obj.objects]
    # Gremlin Vertex/Edge objects
    if hasattr(obj, 'id') and hasattr(obj, 'label'):
        return {"id": str(obj.id), "label": obj.label}
    return str(obj)


# ── Vertex & Edge Creation ─────────────────────────────────────────

# Valid values for dropdowns / validation
VALID_LABELS = {"business_rule", "entity_category"}
VALID_RULE_TYPES = {"constraint", "eligibility", "process", "prohibition", "documentation", "validation"}
VALID_DEPENDENCY_TYPES = {"prerequisite", "complementary", "conditional", "sequential", "override", "exclusion", "mutual", "hierarchical", "categorization"}

# Rule-type affinity matrix for connection suggestions (higher = more related)
_RULE_TYPE_AFFINITY = {
    ("constraint", "validation"): 0.9,
    ("constraint", "eligibility"): 0.8,
    ("constraint", "prohibition"): 0.7,
    ("eligibility", "documentation"): 0.6,
    ("eligibility", "process"): 0.7,
    ("process", "documentation"): 0.8,
    ("process", "validation"): 0.7,
    ("prohibition", "constraint"): 0.7,
    ("prohibition", "validation"): 0.6,
    ("documentation", "validation"): 0.7,
}

def _rule_type_affinity(type_a: str, type_b: str) -> float:
    """Return affinity score (0–1) between two rule types."""
    if type_a == type_b:
        return 0.5
    return _RULE_TYPE_AFFINITY.get((type_a, type_b),
           _RULE_TYPE_AFFINITY.get((type_b, type_a), 0.3))


# ── Graph lock guard ──────────────────────────────────────────────

def _check_graph_locked(graph_name: str):
    """Return a 403 response if the graph is locked, else None."""
    session = SessionLocal()
    try:
        state = session.get(GraphState, graph_name)
        if state and state.locked:
            return jsonify({
                "errors": [f"Graph is locked at release {state.current_release_version or '?'}. Unlock to make changes."],
                "locked": True,
                "release_version": state.current_release_version,
            }), 403
        return None
    finally:
        session.close()


# ── Release & Lock endpoints ─────────────────────────────────────

@app.route("/api/graph/status")
def get_graph_status():
    """Return the lock/release status for a graph."""
    graph_name = _resolve_graph_name(request.args.get("graph_name"))
    session = SessionLocal()
    try:
        state = session.get(GraphState, graph_name)
        if state:
            return jsonify(state.to_dict())
        return jsonify({
            "graph_name": graph_name,
            "locked": False,
            "locked_at": None,
            "locked_by": None,
            "current_release_id": None,
            "current_release_version": None,
        })
    finally:
        session.close()


@app.route("/api/graph/releases")
def list_releases():
    """List all releases for a graph, newest first."""
    graph_name = _resolve_graph_name(request.args.get("graph_name"))
    session = SessionLocal()
    try:
        rows = (
            session.query(GraphRelease)
            .filter_by(graph_name=graph_name)
            .order_by(GraphRelease.released_at.desc())
            .all()
        )
        return jsonify([r.to_dict() for r in rows])
    finally:
        session.close()


@app.route("/api/graph/release/<release_id>")
def get_release(release_id):
    """Get a single release with its full snapshot."""
    session = SessionLocal()
    try:
        row = session.get(GraphRelease, release_id)
        if not row:
            return jsonify({"errors": ["Release not found"]}), 404
        return jsonify(row.to_dict_with_snapshot())
    finally:
        session.close()


@app.route("/api/graph/release", methods=["POST"])
def create_release():
    """Create a new release: snapshot the current graph and lock it.

    Request JSON:
        {
            "graph_name": "fannie_mae_g",
            "version": "v1.0.0",
            "title": "Q4 2025 Final",
            "notes": "All rules reviewed and approved."
        }
    """
    data = request.get_json(force=True)
    graph_name = _resolve_graph_name(data.get("graph_name"))
    version = (data.get("version") or "").strip()
    title = (data.get("title") or "").strip()
    notes = (data.get("notes") or "").strip()

    if not version:
        return jsonify({"errors": ["version is required"]}), 400
    if not title:
        return jsonify({"errors": ["title is required"]}), 400

    # Snapshot the current live graph
    try:
        with get_traversal(graph_name) as (g, conn):
            raw_vertices = (
                g.V()
                .project("id", "label", "props")
                .by(__.id_())
                .by(__.label())
                .by(__.valueMap())
                .toList()
            )
            raw_edges = (
                g.E()
                .project("id", "label", "source", "target", "props")
                .by(__.id_())
                .by(__.label())
                .by(__.outV().id_())
                .by(__.inV().id_())
                .by(__.valueMap())
                .toList()
            )
    except Exception as exc:
        _log("ERROR", f"Failed to snapshot graph for release: {exc}")
        return jsonify({"errors": [str(exc)]}), 500

    # Build snapshot
    nodes = []
    for v in raw_vertices:
        props = {}
        for k, val in (v.get("props") or {}).items():
            props[k] = val[0] if isinstance(val, list) and len(val) == 1 else val
        props["id"] = str(v["id"])
        props["label"] = v["label"]
        nodes.append(props)

    links = []
    for e in raw_edges:
        ep = {}
        for k, val in (e.get("props") or {}).items():
            ep[k] = val[0] if isinstance(val, list) and len(val) == 1 else val
        ep["id"] = str(e["id"])
        ep["label"] = e["label"]
        ep["source"] = str(e["source"])
        ep["target"] = str(e["target"])
        links.append(ep)

    snapshot = {"nodes": nodes, "links": links}
    release_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    session = SessionLocal()
    try:
        # Check for duplicate version
        existing = (
            session.query(GraphRelease)
            .filter_by(graph_name=graph_name, version=version)
            .first()
        )
        if existing:
            return jsonify({"errors": [f"Version '{version}' already exists for this graph"]}), 409

        release = GraphRelease(
            id=release_id,
            graph_name=graph_name,
            version=version,
            title=title,
            notes=notes,
            released_by="user",
            released_at=now,
            node_count=len(nodes),
            edge_count=len(links),
            snapshot_json=json.dumps(snapshot),
        )
        session.add(release)

        # Upsert the graph lock state
        state = session.get(GraphState, graph_name)
        if not state:
            state = GraphState(graph_name=graph_name)
            session.add(state)
        state.locked = True
        state.locked_at = now
        state.locked_by = "user"
        state.current_release_id = release_id
        state.current_release_version = version

        session.commit()
        _log("INFO", f"Created release {version} for graph '{graph_name}' ({len(nodes)} nodes, {len(links)} edges) — graph locked")
        return jsonify(release.to_dict()), 201
    except Exception as exc:
        session.rollback()
        _log("ERROR", f"Failed to create release: {exc}")
        return jsonify({"errors": [str(exc)]}), 500
    finally:
        session.close()


@app.route("/api/graph/unlock", methods=["POST"])
def unlock_graph():
    """Unlock a graph for editing. Does not delete the release."""
    data = request.get_json(force=True)
    graph_name = _resolve_graph_name(data.get("graph_name"))
    session = SessionLocal()
    try:
        state = session.get(GraphState, graph_name)
        if not state or not state.locked:
            return jsonify({"message": "Graph is already unlocked", "locked": False})
        state.locked = False
        session.commit()
        _log("INFO", f"Unlocked graph '{graph_name}' (release {state.current_release_version} preserved)")
        return jsonify({"message": "Graph unlocked for editing", "locked": False})
    except Exception as exc:
        session.rollback()
        _log("ERROR", f"Failed to unlock graph: {exc}")
        return jsonify({"errors": [str(exc)]}), 500
    finally:
        session.close()


# ── Graph publishing (pipeline output → JanusGraph + OpenSearch) ──

@app.route("/api/graph/available")
def list_available_graphs():
    """List pipeline outputs that can be published to the graph database."""
    pipeline_root = APP_ROOT / "pipeline-output"
    _invalidate_manifest_cache()
    try:
        published_graphs = get_graphs()
    except Exception:
        published_graphs = {}

    results = []
    for provider_dir in sorted(pipeline_root.iterdir()) if pipeline_root.is_dir() else []:
        if not provider_dir.is_dir() or provider_dir.name.startswith("."):
            continue
        provider = provider_dir.name
        for source_dir in sorted(provider_dir.iterdir()):
            if not source_dir.is_dir() or source_dir.name.startswith((".", "_")):
                continue
            source_name = source_dir.name
            optimized = source_dir / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
            merged = source_dir / "agent-4-rules-with-entities" / "compliance_knowledge_graph.json"
            kg_file = optimized if optimized.exists() else merged if merged.exists() else None
            if not kg_file:
                continue
            graph_key = resolve_graph_key(source_name)
            is_published = graph_key in published_graphs
            display_name = source_name.replace("-", " ").replace("_", " ").title()
            if is_published:
                display_name = published_graphs[graph_key].get("display_name", display_name)
            # Read counts from KG file
            rules = 0
            entities = 0
            try:
                kg_data = json.loads(kg_file.read_text(encoding="utf-8"))
                rules = len(kg_data.get("business_rules", []))
                entities = len(kg_data.get("entity_types", {}))
            except Exception:
                pass
            results.append({
                "source_name": source_name,
                "provider": provider,
                "graph_key": graph_key,
                "display_name": display_name,
                "rules": rules,
                "entities": entities,
                "is_optimized": optimized.exists(),
                "is_published": is_published,
            })
    return jsonify({"available": results})


def _publish_callback(callback_url, step, status, detail=None):
    """POST a step update to the kg-backend callback URL (best-effort)."""
    if not callback_url:
        return
    try:
        import requests as req_lib
        req_lib.post(
            callback_url,
            json={"step": step, "status": status, "detail": detail},
            timeout=5,
        )
    except Exception:
        pass  # fire-and-forget


def _rollback_failed_publish(
    graph_key: str,
    kg_path: Path,
    docs_path: Path | None,
    *,
    remove_manifest_entry: bool,
    remove_local_artifacts: bool = True,
) -> None:
    """Best-effort cleanup for a publish that failed after writing local artifacts."""
    if remove_manifest_entry:
        try:
            remove_graph_from_manifest(graph_key)
            _log("INFO", f"Rolled back manifest entry for '{graph_key}'")
        except Exception as exc:
            _log(
                "ERROR",
                f"Failed to roll back manifest entry for '{graph_key}': {exc}",
                error=type(exc).__name__,
            )

    if remove_local_artifacts and docs_path:
        try:
            shutil.rmtree(docs_path, ignore_errors=True)
        except Exception as exc:
            _log(
                "ERROR",
                f"Failed to remove copied docs for '{graph_key}': {exc}",
                error=type(exc).__name__,
            )

    if remove_local_artifacts:
        try:
            kg_path.unlink(missing_ok=True)
        except Exception as exc:
            _log(
                "ERROR",
                f"Failed to remove KG file for '{graph_key}': {exc}",
                error=type(exc).__name__,
            )


@app.route("/api/graph/publish", methods=["POST"])
def publish_graph():
    """Publish a pipeline-generated KG: save config, open graph at runtime,
    create schema, load data, and build search embeddings — all in one step.

    No container restart required.

    Two request modes are supported:

    1. ``application/json`` — read artifacts from the local
       ``/app/pipeline-output`` mount (works when assistant and
       pipeline share the same filesystem, e.g. docker-compose).
       Body: ``{"source_name": "...", "provider": "openai",
                "display_name": "...", "callback_url": "..."}``

    2. ``multipart/form-data`` — caller uploads the artifacts directly,
       no shared filesystem required (used for Azure Container Apps).
       Form fields:
         - ``source_name``     (str, required)
         - ``provider``        (str, default "openai")
         - ``display_name``    (str, optional)
         - ``callback_url``    (str, optional)
         - ``kg_file``         (file, required) — KG JSON produced by the pipeline
         - ``docs_archive``    (file, optional) — tar.gz of organized documents
                               (i.e. the contents of ``agent-1-organized-documents``)
    """
    # Accept multipart uploads or JSON
    is_multipart = request.content_type and request.content_type.startswith("multipart/")

    upload_temp_dir: Optional[Path] = None
    try:
        if is_multipart:
            source_name = (request.form.get("source_name") or "").strip()
            provider = (request.form.get("provider") or "openai").strip()
            display_name = (request.form.get("display_name") or "").strip()
            callback_url = request.form.get("callback_url") or None

            kg_upload = request.files.get("kg_file")
            docs_upload = request.files.get("docs_archive")
            if not source_name:
                return jsonify({"error": "source_name is required"}), 400
            if not kg_upload:
                return jsonify({"error": "kg_file (multipart) is required"}), 400

            # Materialize uploads into a temp staging dir that mirrors the
            # pipeline-output layout expected by the rest of this function.
            upload_temp_dir = Path(tempfile.mkdtemp(prefix="publish_upload_"))
            staging_base = upload_temp_dir / provider / source_name
            (staging_base / "agent-5-optimized").mkdir(parents=True, exist_ok=True)
            kg_upload.save(str(staging_base / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"))

            if docs_upload:
                docs_target = staging_base / "agent-1-organized-documents"
                docs_target.mkdir(parents=True, exist_ok=True)
                archive_path = upload_temp_dir / "docs_archive"
                docs_upload.save(str(archive_path))
                try:
                    with tarfile.open(archive_path, mode="r:*") as tf:
                        # Guard against path traversal in archive members
                        safe_root = docs_target.resolve()
                        for member in tf.getmembers():
                            member_path = (docs_target / member.name).resolve()
                            if not str(member_path).startswith(str(safe_root)):
                                return jsonify({"error": f"Unsafe path in docs_archive: {member.name}"}), 400
                        tf.extractall(docs_target)
                except Exception as exc:
                    return jsonify({"error": f"Failed to extract docs_archive: {exc}"}), 400

            base = staging_base
        else:
            data = request.get_json(force=True)
            source_name = data.get("source_name", "").strip()
            provider = data.get("provider", "openai").strip()
            display_name = data.get("display_name", "").strip()
            callback_url = data.get("callback_url")
            base = APP_ROOT / "pipeline-output" / provider / source_name

        if not source_name:
            return jsonify({"error": "source_name is required"}), 400

        return _do_publish_graph(
            base=base,
            source_name=source_name,
            provider=provider,
            display_name=display_name,
            callback_url=callback_url,
        )
    finally:
        if upload_temp_dir and upload_temp_dir.exists():
            shutil.rmtree(upload_temp_dir, ignore_errors=True)


def _do_publish_graph(*, base: Path, source_name: str, provider: str,
                      display_name: str, callback_url):
    """Core publish logic — operates on a *base* directory with the
    standard pipeline-output layout (``agent-5-optimized`` /
    ``agent-4-rules-with-entities`` and ``agent-1-organized-documents``).
    """
    # ── 1. Locate KG JSON ────────────────────────────────────────
    _publish_callback(callback_url, "P1", "running", "Locating KG data")
    optimized = base / "agent-5-optimized" / "optimized_compliance_knowledge_graph.json"
    merged = base / "agent-4-rules-with-entities" / "compliance_knowledge_graph.json"

    if optimized.exists():
        kg_source = optimized
    elif merged.exists():
        kg_source = merged
    else:
        _publish_callback(callback_url, "P1", "failed", f"No KG file found for '{source_name}'")
        return jsonify({"error": f"No KG file found for '{source_name}' (provider={provider})"}), 404

    # ── 2. Derive graph key ──────────────────────────────────────
    graph_key = resolve_graph_key(source_name)
    traversal_source = f"{graph_key}_g"
    display = display_name or source_name.replace("-", " ").replace("_", " ").title()
    existing_graph = None

    # Existing graphs can be refreshed in place so Explorer and Graph DB do
    # not drift when a pipeline output is regenerated.
    _invalidate_manifest_cache()
    try:
        existing_graph = get_graphs().get(graph_key)
    except Exception:
        existing_graph = None

    if existing_graph:
        traversal_source = existing_graph.get("traversal_source", traversal_source) or traversal_source
        display = display_name or existing_graph.get("display_name", display)
        _log("INFO", f"Refreshing existing published graph '{graph_key}' from {kg_source}")

    p1_detail = f"Found KG at {kg_source.name}"
    if existing_graph:
        p1_detail += f"; refreshing existing graph '{graph_key}'"
    _publish_callback(callback_url, "P1", "completed", p1_detail)

    # ── 3. Read and save KG JSON ─────────────────────────────────
    _publish_callback(callback_url, "P2", "running", "Saving KG and updating configuration")
    try:
        kg_data = json.loads(kg_source.read_text(encoding="utf-8"))
    except Exception as exc:
        _publish_callback(callback_url, "P2", "failed", f"Failed to read KG file: {exc}")
        return jsonify({"error": f"Failed to read KG file: {exc}"}), 500

    rule_count = len(kg_data.get("business_rules", []))
    entity_count = len(kg_data.get("entity_types", {}))

    dest_rel = (existing_graph or {}).get("kg_file") or f"kgs/{graph_key}-kg.json"
    dest_path = APP_ROOT / dest_rel
    docs_dest = None
    remove_manifest_on_failure = existing_graph is None
    remove_local_artifacts_on_failure = existing_graph is None
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(kg_data, f, ensure_ascii=False)
    except Exception as exc:
        _publish_callback(callback_url, "P2", "failed", f"Failed to save KG file: {exc}")
        return jsonify({"error": f"Failed to save KG file: {exc}"}), 500

    _log("INFO", f"Saved KG to {dest_path} ({dest_path.stat().st_size} bytes)")

    # ── 3b. Copy organized documents to kbs/ for reference resolution ─
    docs_rel = None
    organized_docs = base / "agent-1-organized-documents"
    if organized_docs.is_dir():
        docs_rel = (existing_graph or {}).get("docs_folder") or docs_folder_rel(graph_key)
        docs_dest = APP_ROOT / docs_rel
        try:
            copy_docs_tree(organized_docs, docs_dest)
            _log("INFO", f"Copied organized documents to {docs_dest}")
        except Exception as exc:
            _rollback_failed_publish(
                graph_key,
                dest_path,
                docs_dest,
                remove_manifest_entry=False,
                remove_local_artifacts=remove_local_artifacts_on_failure,
            )
            _publish_callback(callback_url, "P2", "failed", f"Failed to copy organized documents: {exc}")
            return jsonify({"error": f"Failed to copy organized documents: {exc}"}), 500

    # ── 4. Update graphs.yaml + regenerate JanusGraph configs ────
    try:
        if existing_graph is None:
            add_graph_to_manifest(
                graph_key=graph_key,
                display_name=display,
                traversal_source=traversal_source,
                cassandra_keyspace=f"janusgraph_{graph_key}",
                opensearch_index=f"{graph_key}_search",
                kg_file=dest_rel,
                docs_folder=docs_rel,
            )
            _log("INFO", f"Added '{graph_key}' to graphs.yaml and regenerated JanusGraph configs")
        else:
            _log("INFO", f"Reusing existing manifest entry for '{graph_key}'")
    except ValueError as exc:
        _rollback_failed_publish(
            graph_key,
            dest_path,
            docs_dest,
            remove_manifest_entry=False,
            remove_local_artifacts=remove_local_artifacts_on_failure,
        )
        _publish_callback(callback_url, "P2", "failed", str(exc))
        return jsonify({"error": str(exc)}), 409
    except Exception as exc:
        _rollback_failed_publish(
            graph_key,
            dest_path,
            docs_dest,
            remove_manifest_entry=remove_manifest_on_failure,
            remove_local_artifacts=remove_local_artifacts_on_failure,
        )
        _publish_callback(callback_url, "P2", "failed", f"Failed to update manifest: {exc}")
        return jsonify({"error": f"Failed to update manifest: {exc}"}), 500

    p2_detail = f"Saved KG ({rule_count} rules, {entity_count} entities)"
    if existing_graph is None:
        p2_detail += " and updated config"
    else:
        p2_detail += " and refreshed existing graph config"
    _publish_callback(callback_url, "P2", "completed", p2_detail)

    # ── 5. Open graph at runtime (no restart needed) ─────────────
    _publish_callback(callback_url, "P3", "running", "Opening graph runtime in JanusGraph")
    try:
        with get_traversal(traversal_source) as (g, conn):
            g.V().limit(1).count().next()
    except Exception as exc:
        _log("INFO", f"Graph '{graph_key}' not accessible — opening at runtime ({exc})")
        try:
            from src.schema import open_graph_runtime
            open_graph_runtime(
                graph_ref=(existing_graph or {}).get("graph_ref", graph_key),
                traversal_source=traversal_source,
                cassandra_keyspace=(existing_graph or {}).get("cassandra_keyspace", f"janusgraph_{graph_key}"),
                opensearch_index=(existing_graph or {}).get("opensearch_index", f"{graph_key}_search"),
            )
        except Exception as open_exc:
            _log("ERROR", f"Runtime graph open failed for '{graph_key}': {open_exc}",
                 error=type(open_exc).__name__)
            _rollback_failed_publish(
                graph_key,
                dest_path,
                docs_dest,
                remove_manifest_entry=remove_manifest_on_failure,
                remove_local_artifacts=remove_local_artifacts_on_failure,
            )
            _publish_callback(callback_url, "P3", "failed", f"Failed to open graph: {open_exc}")
            return jsonify({"error": f"Failed to open graph on JanusGraph: {open_exc}"}), 500

    _publish_callback(callback_url, "P3", "completed", "Graph runtime opened successfully")

    # ── 6. Create schema ─────────────────────────────────────────
    _publish_callback(callback_url, "P4", "running", "Creating graph schema")
    _log("INFO", f"Creating schema for '{graph_key}'")
    try:
        from src.schema import _build_schema_script, _submit_script
        schema_script = _build_schema_script((existing_graph or {}).get("graph_ref", graph_key))
        _submit_script(schema_script, traversal_source=traversal_source)
    except Exception as exc:
        _log("ERROR", f"Schema creation failed for '{graph_key}': {exc}",
             error=type(exc).__name__)
        _rollback_failed_publish(
            graph_key,
            dest_path,
            docs_dest,
            remove_manifest_entry=remove_manifest_on_failure,
            remove_local_artifacts=remove_local_artifacts_on_failure,
        )
        _publish_callback(callback_url, "P4", "failed", f"Schema creation failed: {exc}")
        return jsonify({"error": f"Schema creation failed: {exc}"}), 500

    _publish_callback(callback_url, "P4", "completed", "Schema created successfully")

    # ── 7. Load data ─────────────────────────────────────────────
    _publish_callback(callback_url, "P5", "running", "Loading rules and entities into graph")
    _log("INFO", f"Loading data for '{graph_key}'")
    try:
        from src.data_loader import load_data
        load_data(traversal_source, json_file=str(dest_path), clear_first=True)
    except Exception as exc:
        _log("ERROR", f"Data loading failed for '{graph_key}': {exc}",
             error=type(exc).__name__)
        _rollback_failed_publish(
            graph_key,
            dest_path,
            docs_dest,
            remove_manifest_entry=remove_manifest_on_failure,
            remove_local_artifacts=remove_local_artifacts_on_failure,
        )
        _publish_callback(callback_url, "P5", "failed", f"Data loading failed: {exc}")
        return jsonify({"error": f"Data loading failed: {exc}"}), 500

    _publish_callback(callback_url, "P5", "completed", f"Loaded {rule_count} rules, {entity_count} entities")

    # ── 8. Index embeddings ──────────────────────────────────────
    _publish_callback(callback_url, "P6", "running", "Building semantic search embeddings")
    _log("INFO", f"Indexing embeddings for '{graph_key}'")

    # On republish, drop stale OpenSearch embeddings for this traversal
    # source and invalidate Redis / in-process caches so search results
    # cannot bleed across versions.
    try:
        deleted = _engine.delete_embeddings_for_graph(traversal_source)
        if deleted:
            _log("INFO", f"Cleared {deleted} stale embeddings for '{traversal_source}' before re-indexing")
    except Exception as exc:
        _log("WARN", f"Failed to clear stale embeddings for '{traversal_source}': {exc}")
    try:
        cleared = get_cache().clear_pattern("p2k:semantic_search:*")
        if cleared:
            _log("INFO", f"Cleared {cleared} cached semantic-search entries from Redis")
    except Exception as exc:
        _log("WARN", f"Failed to clear Redis semantic-search cache: {exc}")
    _invalidate_graph_data_cache(traversal_source)

    warning = None
    try:
        _engine.index_graph_embeddings(traversal_source)
    except Exception as exc:
        _log("WARN", f"Embedding indexing failed for '{graph_key}': {exc}")
        warning = f"Data loaded but semantic indexing failed: {exc}"

    if warning:
        _publish_callback(callback_url, "P6", "completed", warning)
    else:
        _publish_callback(callback_url, "P6", "completed", "Embeddings indexed successfully")

    _log("INFO", f"Graph '{graph_key}' published and activated successfully")

    result = {
        "status": "activated",
        "graph_key": graph_key,
        "traversal_source": traversal_source,
        "display_name": display,
        "rules": rule_count,
        "entities": entity_count,
    }
    if warning:
        result["status"] = "partial"
        result["warning"] = warning
    return jsonify(result)


@app.route("/api/graph/activate", methods=["POST"])
def activate_graph():
    """Load data and build embeddings for a published-but-not-yet-loaded graph.

    Uses runtime graph opening — no container restart required.

    Expects JSON: {"graph_key": "sample_guidelines"}
    """
    data = request.get_json(force=True)
    graph_key = resolve_graph_key(data.get("graph_key", "").strip())

    if not graph_key:
        return jsonify({"error": "graph_key is required"}), 400

    _invalidate_manifest_cache()
    graphs = get_graphs()
    if graph_key not in graphs:
        return jsonify({"error": f"Graph '{graph_key}' not found in manifest"}), 404

    graph_info = graphs[graph_key]
    traversal_source = graph_info["traversal_source"]
    display = graph_info.get("display_name", graph_key)

    # Ensure graph is open in JanusGraph (runtime open if needed)
    try:
        with get_traversal(traversal_source) as (g, conn):
            count = g.V().limit(1).count().next()
        if count > 0:
            return jsonify({
                "status": "already_loaded",
                "graph_key": graph_key,
                "message": f"Graph '{display}' already has data",
            })
    except Exception:
        # Graph not open — try runtime open
        _log("INFO", f"Graph '{graph_key}' not accessible — opening at runtime")
        try:
            from src.schema import open_graph_runtime
            open_graph_runtime(
                graph_ref=graph_key,
                traversal_source=traversal_source,
                cassandra_keyspace=graph_info.get("cassandra_keyspace", f"janusgraph_{graph_key}"),
                opensearch_index=graph_info.get("opensearch_index", f"{graph_key}_search"),
            )
        except Exception as exc:
            _log("ERROR", f"Runtime graph open failed for '{graph_key}': {exc}",
                 error=type(exc).__name__)
            return jsonify({
                "error": f"Cannot open graph '{graph_key}': {exc}",
            }), 503

    # ── Create schema ────────────────────────────────────────────
    _log("INFO", f"Activating graph '{graph_key}' — creating schema")
    try:
        from src.schema import _build_schema_script, _submit_script
        schema_script = _build_schema_script(graph_info.get("graph_ref", graph_key))
        _submit_script(schema_script, traversal_source=traversal_source)
    except Exception as exc:
        _log("ERROR", f"Schema creation failed for '{graph_key}': {exc}",
             error=type(exc).__name__)
        return jsonify({"error": f"Schema creation failed: {exc}"}), 500

    # ── Load data ────────────────────────────────────────────────
    _log("INFO", f"Loading data for '{graph_key}'")
    root = APP_ROOT
    kg_file = graph_info.get("kg_file", "")
    kg_path = root / kg_file if kg_file else None
    if not kg_path or not kg_path.exists():
        return jsonify({"error": f"KG file not found: {kg_file}"}), 404

    try:
        from src.data_loader import load_data
        load_data(traversal_source, json_file=str(kg_path), clear_first=True)
    except Exception as exc:
        _log("ERROR", f"Data loading failed for '{graph_key}': {exc}",
             error=type(exc).__name__)
        return jsonify({"error": f"Data loading failed: {exc}"}), 500

    # ── Index embeddings ─────────────────────────────────────────
    _log("INFO", f"Indexing embeddings for '{graph_key}'")
    try:
        _engine.index_graph_embeddings(traversal_source)
    except Exception as exc:
        _log("WARN", f"Embedding indexing failed for '{graph_key}': {exc}")
        return jsonify({
            "status": "partial",
            "warning": f"Data loaded but semantic indexing failed: {exc}",
            "graph_key": graph_key,
        })

    _log("INFO", f"Graph '{graph_key}' activated successfully")
    return jsonify({
        "status": "activated",
        "graph_key": graph_key,
        "display_name": display,
    })


@app.route("/api/graph/published")
def list_published_graphs():
    """Return the list of graphs currently registered in the manifest."""
    _invalidate_manifest_cache()
    result = []
    for key, graph in get_graphs().items():
        ts = graph["traversal_source"]
        result.append({
            "graph_key": key,
            "display_name": graph.get("display_name", key),
            "traversal_source": ts,
            "has_data": _graph_has_jg_data(ts),
        })
    return jsonify({"graphs": result})


@app.route("/api/graph/clean", methods=["POST"])
def clean_graph():
    """Drop all vertices/edges and embeddings for a graph. Config is kept."""
    body = request.get_json(force=True)
    graph_name = _resolve_graph_name(body.get("graph_name"))

    locked_resp = _check_graph_locked(graph_name)
    if locked_resp:
        return locked_resp

    from src.data_loader import clear_graph as _clear_graph

    vertices_dropped = 0
    embeddings_deleted = 0
    errors = []

    # 1. Drop all vertices/edges from JanusGraph
    try:
        with get_traversal(graph_name) as (g, conn):
            vertices_dropped = g.V().count().next()
        _clear_graph(graph_name)
    except Exception as exc:
        errors.append(f"Failed to clear graph data: {exc}")

    # 2. Delete embeddings for this graph from OpenSearch
    try:
        embeddings_deleted = _engine.delete_embeddings_for_graph(graph_name)
    except Exception as exc:
        errors.append(f"Failed to delete embeddings: {exc}")

    if errors:
        return jsonify({
            "ok": False,
            "errors": errors,
            "vertices_dropped": vertices_dropped,
            "embeddings_deleted": embeddings_deleted,
        }), 500

    _invalidate_graph_data_cache(graph_name)
    return jsonify({
        "ok": True,
        "vertices_dropped": vertices_dropped,
        "embeddings_deleted": embeddings_deleted,
    })


@app.route("/api/graph/<graph_key>", methods=["DELETE"])
def remove_graph(graph_key: str):
    """Permanently remove a graph: clean data, remove manifest entry, delete files."""
    graphs = get_graphs()
    if graph_key not in graphs:
        return jsonify({"errors": [f"Graph '{graph_key}' not found"]}), 404

    graph = graphs[graph_key]
    graph_name = graph["traversal_source"]

    locked_resp = _check_graph_locked(graph_name)
    if locked_resp:
        return locked_resp

    from src.data_loader import clear_graph as _clear_graph

    root = Path(__file__).resolve().parent.parent
    errors = []

    # 1. Drop graph data
    try:
        _clear_graph(graph_name)
    except Exception as exc:
        errors.append(f"Failed to clear graph data: {exc}")

    # 2. Delete embeddings
    try:
        _engine.delete_embeddings_for_graph(graph_name)
    except Exception as exc:
        errors.append(f"Failed to delete embeddings: {exc}")

    # 3. Remove manifest entry
    try:
        remove_graph_from_manifest(graph_key)
        _invalidate_manifest_cache()
    except Exception as exc:
        errors.append(f"Failed to remove manifest entry: {exc}")

    # 4. Delete KG JSON file
    kg_rel = graph.get("kg_file", "")
    if kg_rel:
        kg_path = root / kg_rel
        try:
            kg_path.unlink(missing_ok=True)
        except Exception as exc:
            errors.append(f"Failed to delete KG file: {exc}")

    # 5. Delete docs folder
    docs_rel = graph.get("docs_folder", "")
    if docs_rel:
        docs_path = root / docs_rel
        try:
            shutil.rmtree(docs_path, ignore_errors=True)
        except Exception as exc:
            errors.append(f"Failed to delete docs folder: {exc}")

    # 6. Delete JanusGraph properties file
    props_file = root / "conf" / f"janusgraph-{graph_key}.properties"
    try:
        props_file.unlink(missing_ok=True)
    except Exception as exc:
        errors.append(f"Failed to delete properties file: {exc}")

    # 7. Delete SQLite release and state records so the graph disappears from
    #    the release history and lock-state endpoints immediately.
    try:
        session = SessionLocal()
        session.query(GraphRelease).filter(GraphRelease.graph_name == graph_name).delete()
        session.query(GraphState).filter(GraphState.graph_name == graph_name).delete()
        session.commit()
        session.close()
    except Exception as exc:
        errors.append(f"Failed to delete database records: {exc}")

    # 8. Evict the data-presence cache so the system prompt no longer lists
    #    this graph on the very next chat request.
    _invalidate_graph_data_cache(graph_name)

    if errors:
        return jsonify({"ok": False, "errors": errors}), 500

    return jsonify({"ok": True, "removed": graph_key})


@app.route("/api/vertex", methods=["POST"])
def create_vertex():
    """Create a new vertex in JanusGraph with full properties.

    Request JSON:
        {
            "graph_name": "compliance_g",
            "label": "business_rule",
            "properties": {
                "name": "...",
                "content": "...",
                ...
            }
        }
    """
    body = request.get_json(force=True)
    graph_name = _resolve_graph_name(body.get("graph_name"))

    locked_resp = _check_graph_locked(graph_name)
    if locked_resp:
        return locked_resp

    label = body.get("label", "business_rule")
    props = body.get("properties") or {}
    if not isinstance(props, dict):
        return jsonify({"error": "'properties' must be an object"}), 400

    # Strip read-only / system-managed fields that clients must not set
    for _ro in ("vertex_uuid", "node_type"):
        props.pop(_ro, None)

    # ── Validation ──
    errors = []
    if label not in VALID_LABELS:
        errors.append(f"label must be one of: {', '.join(sorted(VALID_LABELS))}")
    if not (props.get("name") or "").strip():
        errors.append("properties.name is required")
    if not (props.get("content") or "").strip() or len((props.get("content") or "").strip()) < 10:
        errors.append("properties.content is required (min 10 characters)")
    if label == "business_rule" and props.get("rule_type") and props["rule_type"] not in VALID_RULE_TYPES:
        errors.append(f"rule_type must be one of: {', '.join(sorted(VALID_RULE_TYPES))}")
    if "confidence_score" in props:
        try:
            cs = float(props["confidence_score"])
            if cs < 0 or cs > 100:
                errors.append("confidence_score must be between 0 and 100")
        except (ValueError, TypeError):
            errors.append("confidence_score must be a number")
    if errors:
        return jsonify({"errors": errors}), 400

    try:
        with get_traversal(graph_name) as (g, conn):
            # Check name uniqueness
            existing = g.V().has("name", props["name"].strip()).count().next()
            if existing > 0:
                return jsonify({"errors": [f"A vertex named '{props['name']}' already exists in this graph"]}), 409

            # Build addV traversal
            vertex_id = str(uuid.uuid4())
            t = g.addV(label)
            t = t.property("vertex_uuid", vertex_id)
            t = t.property("name", props["name"].strip())
            t = t.property("content", props["content"].strip())
            t = t.property("node_type", label)
            t = t.property("category", props.get("rule_type", props.get("category", "")))

            # Map remaining properties
            str_fields = ["rule_id", "rule_name", "rule_type", "description", "conditions",
                          "consequences", "exceptions", "reference", "review_reason",
                          "entity_or_relationship", "entity_type", "extraction_notes",
                          # Extended v2 KG string properties
                          "source_reference", "effective_date", "expiration_date",
                          "superseded_by", "jurisdiction", "risk_level",
                          "related_rules", "enforcement_action", "applicability_scope",
                          "data_points_required", "audit_frequency",
                          "reference_verification_note", "confidence_breakdown",
                          "deduplication_info"]
            for f in str_fields:
                if f in props and props[f]:
                    t = t.property(f, str(props[f]))

            bool_fields = ["mandatory", "requires_review", "reference_verified"]
            for f in bool_fields:
                if f in props:
                    t = t.property(f, bool(props[f]))

            if "confidence_score" in props:
                t = t.property("confidence_score", float(props["confidence_score"]))

            # Execute & retrieve ID
            vid = t.id_().next()

            # Auto-create belongs_to_category edge if applicable
            entity = props.get("entity_or_relationship", "").strip()
            if entity:
                try:
                    cat_vid = g.V().hasLabel("entity_category").has("name", entity).id_().next()
                    g.V(vid).addE("belongs_to_category").to(__.V(cat_vid)).property("dependency_type", "categorization").next()
                except StopIteration:
                    pass  # category doesn't exist yet, skip

            # Fetch created vertex for response
            created = (
                g.V(vid)
                .project("id", "label", "props")
                .by(__.id_())
                .by(__.label())
                .by(__.valueMap(*ALL_VERTEX_PROPERTIES))
                .next()
            )
            flat = {}
            for k, val in created["props"].items():
                flat[k] = val[0] if isinstance(val, list) and len(val) == 1 else val

        # Index in OpenSearch k-NN for semantic search
        try:
            _engine.index_single_vertex(
                vertex_name=props["name"].strip(),
                vertex_label=label,
                content=props["content"].strip(),
                graph_name=graph_name,
            )
        except Exception as exc:
            _log("WARN", f"Semantic indexing deferred for new vertex: {exc}")

        result = {"id": str(vid), "label": label, **{k: _to_json_safe(v) for k, v in flat.items()}}
        _log("INFO", f"Created vertex '{props['name']}' (id={vid}) in graph '{graph_name}'")
        return jsonify(result), 201

    except Exception as exc:
        _log("ERROR", f"Failed to create vertex: {exc}")
        return jsonify({"errors": [str(exc)]}), 500


@app.route("/api/edge", methods=["POST"])
def create_edge():
    """Create an edge between two existing vertices.

    Request JSON:
        {
            "graph_name": "compliance_g",
            "source_id": "12345",
            "target_id": "67890",
            "label": "depends_on",
            "properties": {
                "dependency_type": "prerequisite",
                "strength": 4,
                "rationale": "...",
                "impact_if_fails": "..."
            }
        }
    """
    body = request.get_json(force=True)
    graph_name = _resolve_graph_name(body.get("graph_name"))

    locked_resp = _check_graph_locked(graph_name)
    if locked_resp:
        return locked_resp

    source_id = body.get("source_id")
    target_id = body.get("target_id")
    edge_label = body.get("label", "depends_on")
    props = body.get("properties") or {}
    if not isinstance(props, dict):
        return jsonify({"error": "'properties' must be an object"}), 400

    # ── Validation ──
    errors = []
    if not source_id:
        errors.append("source_id is required")
    if not target_id:
        errors.append("target_id is required")
    if edge_label not in ("depends_on", "belongs_to_category"):
        errors.append("label must be 'depends_on' or 'belongs_to_category'")
    if props.get("dependency_type") and props["dependency_type"] not in VALID_DEPENDENCY_TYPES:
        errors.append(f"dependency_type must be one of: {', '.join(sorted(VALID_DEPENDENCY_TYPES))}")
    if "strength" in props:
        try:
            s = int(props["strength"])
            if s < 1 or s > 5:
                errors.append("strength must be between 1 and 5")
        except (ValueError, TypeError):
            errors.append("strength must be an integer")
    if errors:
        return jsonify({"errors": errors}), 400

    try:
        with get_traversal(graph_name) as (g, conn):
            src = int(source_id) if str(source_id).isdigit() else source_id
            tgt = int(target_id) if str(target_id).isdigit() else target_id

            # Verify both vertices exist
            src_exists = g.V(src).count().next()
            tgt_exists = g.V(tgt).count().next()
            if not src_exists:
                return jsonify({"errors": [f"Source vertex {source_id} not found"]}), 404
            if not tgt_exists:
                return jsonify({"errors": [f"Target vertex {target_id} not found"]}), 404

            # Build edge
            t = g.V(src).addE(edge_label).to(__.V(tgt))
            if props.get("dependency_type"):
                t = t.property("dependency_type", props["dependency_type"])
            if "strength" in props:
                t = t.property("strength", int(props["strength"]))
            if props.get("rationale"):
                t = t.property("rationale", str(props["rationale"]))
            if props.get("impact_if_fails"):
                t = t.property("impact_if_fails", str(props["impact_if_fails"]))

            eid = t.id_().next()

            # Fetch source/target names for response
            src_name = g.V(src).values("name").next()
            tgt_name = g.V(tgt).values("name").next()

        result = {
            "id": str(eid),
            "source": str(source_id),
            "target": str(target_id),
            "label": edge_label,
            "source_name": src_name,
            "target_name": tgt_name,
            **{k: _to_json_safe(v) for k, v in props.items()},
        }
        _log("INFO", f"Created edge {source_id} --[{edge_label}]--> {target_id} in graph '{graph_name}'")
        return jsonify(result), 201

    except Exception as exc:
        _log("ERROR", f"Failed to create edge: {exc}")
        return jsonify({"errors": [str(exc)]}), 500


@app.route("/api/vertex/<vertex_id>", methods=["DELETE"])
def delete_vertex(vertex_id):
    """Permanently delete a vertex and all its incident edges from JanusGraph.

    Query params:
        graph_name (str): The traversal source / graph name.
    """
    graph_name = _resolve_graph_name(request.args.get("graph_name"))

    locked_resp = _check_graph_locked(graph_name)
    if locked_resp:
        return locked_resp

    try:
        try:
            vid = int(vertex_id)
        except (ValueError, TypeError):
            vid = vertex_id

        with get_traversal(graph_name) as (g, conn):
            count = g.V(vid).count().next()
            if count == 0:
                return jsonify({"errors": [f"Vertex {vertex_id} not found"]}), 404

            try:
                name = g.V(vid).values("name").next()
            except StopIteration:
                name = str(vertex_id)

            # drop() on a vertex cascades to all incident edges in JanusGraph
            g.V(vid).drop().toList()

        # Remove SQLite per-node annotations
        try:
            _session = SessionLocal()
            row = _session.get(NodeAnnotation, str(vertex_id))
            if row:
                _session.delete(row)
                _session.commit()
            _session.close()
        except Exception:
            pass

        _log("INFO", f"Deleted vertex '{name}' (id={vertex_id}) from graph '{graph_name}'")
        return jsonify({"deleted": True, "id": str(vertex_id), "name": name}), 200

    except Exception as exc:
        _log("ERROR", f"Failed to delete vertex {vertex_id}: {exc}")
        return jsonify({"errors": [str(exc)]}), 500


@app.route("/api/edge", methods=["DELETE"])
def delete_edge():
    """Delete an edge identified by source_id, target_id, and label.

    Request JSON:
        {
            "graph_name": "compliance_g",
            "source_id": "...",
            "target_id": "...",
            "label": "depends_on"
        }
    """
    body = request.get_json(force=True)
    graph_name = _resolve_graph_name(body.get("graph_name"))

    locked_resp = _check_graph_locked(graph_name)
    if locked_resp:
        return locked_resp

    source_id = body.get("source_id")
    target_id = body.get("target_id")
    edge_label = body.get("label", "depends_on")

    if not source_id or not target_id:
        return jsonify({"errors": ["source_id and target_id are required"]}), 400

    try:
        try:
            src = int(source_id)
        except (ValueError, TypeError):
            src = source_id
        try:
            tgt = int(target_id)
        except (ValueError, TypeError):
            tgt = target_id

        with get_traversal(graph_name) as (g, conn):
            count = (
                g.V(src).outE(edge_label)
                .where(__.inV().hasId(tgt))
                .count().next()
            )
            if count == 0:
                return jsonify({"errors": ["Edge not found"]}), 404
            g.V(src).outE(edge_label).where(__.inV().hasId(tgt)).drop().toList()

        _log("INFO", f"Deleted edge {source_id} --[{edge_label}]--> {target_id} in graph '{graph_name}'")
        return jsonify({"deleted": True}), 200

    except Exception as exc:
        _log("ERROR", f"Failed to delete edge {source_id}->{target_id}: {exc}")
        return jsonify({"errors": [str(exc)]}), 500


@app.route("/api/edge/reverse", methods=["POST"])
def reverse_edge():
    """Reverse an edge direction: drop it and recreate with swapped source/target.

    Request JSON:
        {
            "graph_name": "compliance_g",
            "source_id": "...",
            "target_id": "...",
            "label": "depends_on"
        }
    """
    body = request.get_json(force=True)
    graph_name = _resolve_graph_name(body.get("graph_name"))

    locked_resp = _check_graph_locked(graph_name)
    if locked_resp:
        return locked_resp

    source_id = body.get("source_id")
    target_id = body.get("target_id")
    edge_label = body.get("label", "depends_on")

    if not source_id or not target_id:
        return jsonify({"errors": ["source_id and target_id are required"]}), 400

    try:
        try:
            src = int(source_id)
        except (ValueError, TypeError):
            src = source_id
        try:
            tgt = int(target_id)
        except (ValueError, TypeError):
            tgt = target_id

        with get_traversal(graph_name) as (g, conn):
            try:
                edge_info = (
                    g.V(src).outE(edge_label)
                    .where(__.inV().hasId(tgt))
                    .project("id", "props")
                    .by(__.id_())
                    .by(__.valueMap())
                    .next()
                )
            except StopIteration:
                return jsonify({"errors": ["Edge not found"]}), 404

            # Capture existing edge properties
            eprops = {}
            for k, val in edge_info["props"].items():
                eprops[k] = val[0] if isinstance(val, list) and len(val) == 1 else val

            # Drop old edge
            g.V(src).outE(edge_label).where(__.inV().hasId(tgt)).drop().toList()

            # Recreate with swapped direction, preserving properties
            t = g.V(tgt).addE(edge_label).to(__.V(src))
            for k, v in eprops.items():
                if v is not None and v != "":
                    t = t.property(k, v)
            new_eid = t.id_().next()

        _log(
            "INFO",
            f"Reversed edge {source_id} --[{edge_label}]--> {target_id} "
            f"(new_id={new_eid}) in graph '{graph_name}'"
        )
        return jsonify({
            "reversed": True,
            "new_id": str(new_eid),
            "source": str(target_id),
            "target": str(source_id),
        }), 200

    except Exception as exc:
        _log("ERROR", f"Failed to reverse edge {source_id}->{target_id}: {exc}")
        return jsonify({"errors": [str(exc)]}), 500


@app.route("/api/vertex/suggest-connections", methods=["POST"])
def suggest_connections():
    """Suggest potential connections for a new vertex using 3-signal scoring.

    Request JSON:
        {
            "graph_name": "compliance_g",
            "name": "My New Rule",
            "content": "Full text content...",
            "rule_type": "constraint",
            "entity_or_relationship": "BORROWER",
            "category": "Underwriting",
            "top_k": 5
        }
    """
    body = request.get_json(force=True)
    graph_name = _resolve_graph_name(body.get("graph_name"))
    content = body.get("content", "").strip()
    name = body.get("name", "").strip()
    rule_type = body.get("rule_type", "")
    entity = body.get("entity_or_relationship", "")
    category = body.get("category", "")
    try:
        top_k = int(body.get("top_k", 5))
    except (TypeError, ValueError):
        return jsonify({"errors": ["top_k must be an integer"]}), 400

    if not content:
        return jsonify({"errors": ["content is required for suggestions"]}), 400

    try:
        # ── Signal 1: Semantic similarity (50% weight) ──
        semantic_results = _engine.search(content, top_k=top_k * 3, graph_name=graph_name)

        # ── Signal 2 & 3: Structural proximity + rule-type affinity ──
        suggestions = []
        seen_names = set()

        with get_traversal(graph_name) as (g, conn):
            for sr in semantic_results:
                sr_name = sr.get("name", "")
                if sr_name == name or sr_name in seen_names:
                    continue
                seen_names.add(sr_name)

                # Look up full vertex info
                try:
                    vinfo = (
                        g.V().has("name", sr_name)
                        .project("id", "label", "rule_type", "entity_or_relationship",
                                 "category", "dep_count", "confidence_score")
                        .by(__.id_())
                        .by(__.label())
                        .by(__.coalesce(__.values("rule_type"), __.constant("")))
                        .by(__.coalesce(__.values("entity_or_relationship"), __.constant("")))
                        .by(__.coalesce(__.values("category"), __.constant("")))
                        .by(__.bothE("depends_on").count())
                        .by(__.coalesce(__.values("confidence_score"), __.constant(0)))
                        .next()
                    )
                except StopIteration:
                    continue

                # Semantic score (0–1 from k-NN, normalized)
                semantic_score = min(float(sr.get("similarity", 0)), 1.0)

                # Structural proximity score
                structural_score = 0.0
                reasons = [f"Semantic similarity: {semantic_score:.2f}"]
                if entity and vinfo.get("entity_or_relationship") == entity:
                    structural_score += 0.5
                    reasons.append(f"Same entity: {entity}")
                if category and vinfo.get("category") == category:
                    structural_score += 0.3
                    reasons.append(f"Same category: {category}")
                if rule_type and vinfo.get("rule_type") == rule_type:
                    structural_score += 0.2
                    reasons.append(f"Same rule type: {rule_type}")

                # Rule-type affinity score
                target_type = vinfo.get("rule_type", "")
                affinity_score = _rule_type_affinity(rule_type, target_type) if rule_type and target_type else 0.3

                # Blended score: semantic 50%, structural 30%, affinity 20%
                final_score = (semantic_score * 0.5) + (structural_score * 0.3) + (affinity_score * 0.2)

                # Suggest edge properties based on heuristics
                if rule_type == "prerequisite" or target_type == "prerequisite":
                    suggested_dep_type = "prerequisite"
                    suggested_direction = "outgoing"
                elif rule_type == "validation" and target_type == "constraint":
                    suggested_dep_type = "complementary"
                    suggested_direction = "outgoing"
                elif target_type == "process" and rule_type in ("constraint", "eligibility"):
                    suggested_dep_type = "sequential"
                    suggested_direction = "incoming"
                elif rule_type == "prohibition" and target_type == "constraint":
                    suggested_dep_type = "override"
                    suggested_direction = "outgoing"
                else:
                    suggested_dep_type = "complementary"
                    suggested_direction = "outgoing"

                suggestions.append({
                    "vertex_id": str(vinfo["id"]),
                    "vertex_name": sr_name,
                    "vertex_label": vinfo.get("label", ""),
                    "match_score": round(final_score, 3),
                    "match_reasons": reasons,
                    "confidence_score": vinfo.get("confidence_score", 0),
                    "dependency_count": vinfo.get("dep_count", 0),
                    "suggested_edge": {
                        "label": "depends_on",
                        "dependency_type": suggested_dep_type,
                        "direction": suggested_direction,
                        "strength": max(1, min(5, round(final_score * 5))),
                        "rationale": f"Both rules relate to {entity or category or rule_type or 'the same domain'}",
                    },
                })

        # Sort by score descending, take top_k
        suggestions.sort(key=lambda x: x["match_score"], reverse=True)
        suggestions = suggestions[:top_k]

        return jsonify({"suggestions": suggestions})

    except Exception as exc:
        _log("ERROR", f"Connection suggestion failed: {exc}")
        return jsonify({"errors": [str(exc)]}), 500


# ── Reference / chunk endpoints ─────────────────────────────────────

_chunk_index_cache: dict = {}  # docs_folder → (mtime, index)
_kb_text_index_cache: dict = {}  # docs_folder → (timestamp, list of enriched entries)


def _build_chunk_index(docs_folder: str) -> list:
    """Build a list of {title, path, chunk_id} from all _metadata.json files in a docs folder.

    Results are cached; cache is invalidated when any _metadata.json file is newer
    than the cached timestamp.

    Paths recorded in _metadata.json may be relative to either:
      1. The top-level docs_folder  (e.g. sample-guidelines, fannie-mae)
      2. The parent of the _metadata.json file  (e.g. revolution
         where metadata lives inside agent-1-organized-documents/<sub>/)

    We try both and keep whichever resolves to an existing file.  The stored
    ``path`` is always relative to ``docs_folder`` so that ``serve_chunk``
    can locate the file later.
    """
    # Check cache
    cached = _chunk_index_cache.get(docs_folder)
    if cached:
        cache_ts, cache_idx = cached
        # Quick freshness check: if cache is < 60s old, reuse it
        if time.time() - cache_ts < 60:
            return cache_idx
    index = []
    norm_docs = os.path.normpath(docs_folder)
    for root, _dirs, files in os.walk(docs_folder):
        if "_metadata.json" in files:
            meta_path = os.path.join(root, "_metadata.json")
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                for entry in meta.get("structure", []):
                    title = entry.get("title", "")
                    rel_path = entry.get("path", "")
                    chunk_id = entry.get("chunk_id", "")
                    if not title or not rel_path:
                        continue

                    # Try 1: path relative to docs_folder (works for most KBs)
                    abs_chunk = os.path.normpath(os.path.join(docs_folder, rel_path))
                    if os.path.isfile(abs_chunk):
                        stored_path = rel_path
                    else:
                        # Try 2: path relative to _metadata.json's parent directory
                        # (handles KBs where metadata is nested inside a subdirectory
                        #  like agent-1-organized-documents/)
                        abs_chunk = os.path.normpath(os.path.join(os.path.dirname(root), rel_path))
                        if os.path.isfile(abs_chunk):
                            # Re-express as relative to docs_folder
                            stored_path = os.path.relpath(abs_chunk, norm_docs)
                        else:
                            continue

                    index.append({
                        "title": title,
                        "path": stored_path,
                        "chunk_id": chunk_id,
                        # Normalized title for matching (lowercase, stripped of dates/parens)
                        "norm": re.sub(r'[\s()/_,\-]+', ' ', title.lower()).strip(),
                    })
            except Exception:
                pass
    _chunk_index_cache[docs_folder] = (time.time(), index)
    return index


def _build_kb_text_index(docs_folder: str, graph_name: str) -> list:
    """Build an in-memory searchable text index of KB chunk content.

    Each entry: {title, path, chunk_id, content_snippet, norm, graph_name}.
    Cached for 5 minutes to avoid re-reading files on every search.
    """
    cached = _kb_text_index_cache.get(docs_folder)
    if cached:
        cache_ts, cache_idx = cached
        if time.time() - cache_ts < 300:
            return cache_idx

    chunk_meta = _build_chunk_index(docs_folder)
    entries = []
    for entry in chunk_meta:
        abs_path = os.path.normpath(os.path.join(docs_folder, entry["path"]))
        try:
            with open(abs_path, "r", encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()
            # Strip markdown headers for clean text matching
            body = re.sub(r"^#+\s.*$", "", raw, flags=re.MULTILINE).strip()
            snippet = body[:1200]
        except Exception:
            snippet = ""
        entries.append({
            "title":          entry["title"],
            "path":           entry["path"],
            "chunk_id":       entry.get("chunk_id", ""),
            "content_snippet": snippet,
            "norm":           entry["norm"],
            "graph_name":     graph_name,
        })

    _kb_text_index_cache[docs_folder] = (time.time(), entries)
    return entries


def _match_reference(reference: str, chunk_index: list) -> list:
    """Find the best matching chunks for a reference string. Returns list of matches."""
    ref_lower = reference.lower().strip()
    ref_norm = re.sub(r'[\s()/_,\-]+', ' ', ref_lower).strip()
    ref_codes = set(re.findall(r'[A-Z]\d[\-\.\d]+', reference))

    scored = []
    for entry in chunk_index:
        title_norm = entry["norm"]
        title_lower = entry["title"].lower()

        # Exact title match
        if ref_lower == title_lower:
            scored.append((100, entry))
            continue

        # Reference contained in title
        if ref_lower in title_lower:
            scored.append((90, entry))
            continue

        # Title contained in reference
        if title_lower in ref_lower:
            scored.append((85, entry))
            continue

        # Section code match (e.g., 'B2-1.5-04' in both)
        title_codes = set(re.findall(r'[A-Z]\d[\-\.\d]+', entry["title"]))
        if ref_codes and ref_codes & title_codes:
            overlap = len(ref_codes & title_codes) / max(len(ref_codes), 1)
            scored.append((70 + int(overlap * 20), entry))
            continue

        # Chunk ID match (e.g., 'FAMA_097' in reference)
        if entry["chunk_id"] and entry["chunk_id"].lower() in ref_lower:
            scored.append((75, entry))
            continue

        # Word overlap score — but guard against section-code mismatch.
        # If the reference has a section code (e.g. B3-4.3-17) and the
        # candidate title also has a section code but a DIFFERENT one,
        # skip this candidate.  Otherwise word overlap on common terms
        # like "Personal" can match the wrong document chunk.
        ref_words = set(ref_norm.split())
        title_words = set(title_norm.split())
        if ref_words and title_words:
            if ref_codes and title_codes and not (ref_codes & title_codes):
                # Both sides have section codes that don't overlap — skip
                continue
            overlap = len(ref_words & title_words)
            ratio = overlap / max(len(ref_words), len(title_words))
            if ratio > 0.4:
                scored.append((int(ratio * 60), entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored[:5]]


@app.route("/api/reference/resolve")
def resolve_reference():
    """Resolve a reference string to matching chunk file(s).

    Query params:
        ref: the reference string from the node (plain text or source_reference JSON)
        graph_name: traversal source to determine which docs folder to search
        source_reference: optional JSON string with structured source_reference object
    """
    ref = request.args.get("ref", "").strip()
    source_ref_param = request.args.get("source_reference", "").strip()
    graph_name = _resolve_graph_name(request.args.get("graph_name"))

    if not ref and not source_ref_param:
        return jsonify({"error": "'ref' parameter is required"}), 400

    docs_folder = get_docs_folder(graph_name)
    if not docs_folder or not os.path.isdir(docs_folder):
        return jsonify({"error": f"No docs folder configured for graph '{graph_name}'"}), 404

    # Try structured source_reference first for direct chunk_path resolution
    source_ref_obj = None
    if source_ref_param:
        try:
            source_ref_obj = json.loads(source_ref_param)
        except (json.JSONDecodeError, TypeError):
            pass

    # Normalize source_ref_obj: if it's a list of source_reference dicts,
    # treat each item as a separate source_reference to resolve.
    source_ref_items = []
    if source_ref_obj and isinstance(source_ref_obj, list):
        source_ref_items = [
            item for item in source_ref_obj
            if isinstance(item, dict) and item.get("chunk_path")
        ]
    elif source_ref_obj and isinstance(source_ref_obj, dict) and source_ref_obj.get("chunk_path"):
        source_ref_items = [source_ref_obj]

    results = []
    if source_ref_items:
        chunk_index = _build_chunk_index(docs_folder)

        for sr_item in source_ref_items:
            chunk_path = sr_item["chunk_path"]
            # Extract word positions from this source_reference for highlighting
            item_start_word = sr_item.get("start_word_position")
            item_end_word = sr_item.get("end_word_position")
            item_source_text = sr_item.get("source_text")

            def _make_match_entry(entry, *, _sr=sr_item, _sw=item_start_word,
                                  _ew=item_end_word, _st=item_source_text):
                """Build a match dict including word positions from source_reference."""
                encoded_path = _url_quote(entry['path'], safe='')
                match_entry = {
                    "title": entry["title"],
                    "chunk_id": entry["chunk_id"],
                    "path": entry["path"],
                    "url": f"{URL_PREFIX}/api/reference/chunk?graph_name={_url_quote(graph_name, safe='')}&path={encoded_path}",
                    "section_id": _sr.get("section_id", ""),
                }
                if _sw is not None:
                    match_entry["start_word_position"] = _sw
                if _ew is not None:
                    match_entry["end_word_position"] = _ew
                if _st:
                    match_entry["source_text"] = _st
                return match_entry

            # Try exact path match first
            matched = False
            for entry in chunk_index:
                if entry["path"].endswith(chunk_path) or chunk_path.endswith(entry["path"]):
                    results.append(_make_match_entry(entry))
                    matched = True
                    break
            # Fallback: fuzzy match on chunk_path segments
            if not matched:
                path_segments = [s.strip() for s in chunk_path.replace("\\", "/").split("/") if s.strip()]
                for entry in chunk_index:
                    entry_segments = entry["path"].replace("\\", "/").split("/")
                    # Count matching path segments
                    matching = sum(1 for seg in path_segments if any(seg.lower() in es.lower() for es in entry_segments))
                    if matching >= max(1, len(path_segments) // 2):
                        results.append(_make_match_entry(entry))

    if not results and ref:
        # Fallback to standard fuzzy matching on reference string
        chunk_index = _build_chunk_index(docs_folder)
        matches = _match_reference(ref, chunk_index)
        for m in matches:
            encoded_path = _url_quote(m['path'], safe='')
            results.append({
                "title": m["title"],
                "chunk_id": m["chunk_id"],
                "path": m["path"],
                "url": f"{URL_PREFIX}/api/reference/chunk?graph_name={_url_quote(graph_name, safe='')}&path={encoded_path}",
            })

    return jsonify({"reference": ref, "matches": results})


@app.route("/api/reference/chunk")
def serve_chunk():
    """Serve a chunk text file as a styled HTML page.

    Query params:
        graph_name: traversal source to determine docs folder
        path: relative path of the chunk within the docs folder
    """
    graph_name = _resolve_graph_name(request.args.get("graph_name"))
    rel_path = request.args.get("path", "").strip()
    theme = request.args.get("theme", "dark").strip()
    if theme not in ("light", "dark"):
        theme = "dark"

    if not rel_path:
        return jsonify({"error": "'path' parameter is required"}), 400

    docs_folder = get_docs_folder(graph_name)
    if not docs_folder:
        return jsonify({"error": f"No docs folder configured for graph '{graph_name}'"}), 404

    # Security: ensure path doesn't escape the docs folder. Reject absolute
    # inputs and verify containment via realpath + commonpath (a plain
    # startswith check is fooled by sibling dirs like "<docs>-evil/").
    if os.path.isabs(rel_path):
        return jsonify({"error": "Invalid path"}), 403
    base = os.path.realpath(docs_folder)
    full_path = os.path.realpath(os.path.join(base, rel_path))
    if full_path != base and os.path.commonpath([full_path, base]) != base:
        return jsonify({"error": "Invalid path"}), 403

    if not os.path.isfile(full_path):
        return jsonify({"error": f"Chunk file not found: {rel_path}"}), 404

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    filename = os.path.basename(rel_path)
    title = _html_escape(os.path.splitext(filename)[0])
    path_parts = rel_path.replace("\\", "/").split("/")
    breadcrumb_items = [_html_escape(p) for p in path_parts]

    # ── Parse structured metadata from chunk header ──
    meta = {}
    body_lines = []
    in_header = True
    past_first_heading = False
    for line in content.split("\n"):
        stripped = line.strip()
        if in_header:
            if stripped.startswith("# "):
                meta["heading"] = stripped[2:].strip()
                past_first_heading = True
                continue
            if past_first_heading and stripped.startswith("**") and ":**" in stripped:
                # e.g. **Source:** FAMA.pdf
                key_val = stripped.lstrip("*").split(":**", 1)
                if len(key_val) == 2:
                    k = key_val[0].strip().rstrip("*")
                    v = key_val[1].strip().rstrip("*")
                    meta[k.lower()] = v
                    continue
            if stripped == "---":
                in_header = False
                continue
            if past_first_heading and not stripped:
                continue
            # Not a header line
            in_header = False
            body_lines.append(line)
        else:
            body_lines.append(line)

    body_text = "\n".join(body_lines)

    # ── Render body content as structured HTML ──
    rendered_body = _render_chunk_body(body_text)

    # ── Build metadata badges ──
    meta_html = ""
    if meta:
        badges = []
        if meta.get("chunk id"):
            badges.append(f'<span class="badge badge-id">{_html_escape(meta["chunk id"])}</span>')
        if meta.get("source"):
            badges.append(f'<span class="badge badge-source">{_html_escape(meta["source"])}</span>')
        if meta.get("pages"):
            badges.append(f'<span class="badge badge-pages">Pages {_html_escape(meta["pages"])}</span>')
        if badges:
            meta_html = '<div class="meta-badges">' + "".join(badges) + "</div>"

    # ── Build breadcrumb HTML ──
    bc_html = ""
    for i, part in enumerate(breadcrumb_items[:-1]):
        bc_html += f'<span class="bc-part">{part}</span><span class="bc-sep">/</span>'
    if breadcrumb_items:
        bc_html += f'<span class="bc-current">{breadcrumb_items[-1]}</span>'

    # ── Section path pill ──
    section_path_html = ""
    if meta.get("section path"):
        sp_parts = [_html_escape(p.strip()) for p in meta["section path"].split(">")]
        section_path_html = '<div class="section-path">' + \
            '<span class="sp-sep"> › </span>'.join(
                f'<span class="sp-part">{p}</span>' for p in sp_parts
            ) + '</div>'

    # ── Display title ──
    display_title = _html_escape(meta.get("heading", title))

    # ── Graph display name ──
    graph_display = ""
    try:
        graphs = get_graphs()
        for _k, g in graphs.items():
            if g.get("traversal_source") == graph_name:
                graph_display = g.get("display_name", graph_name)
                break
    except Exception:
        graph_display = graph_name

    # ── Highlight terms (passed via query param for task-box integration) ──
    highlight_raw = request.args.get("highlight", "").strip()
    if highlight_raw:
        terms = [t.strip() for t in highlight_raw.split(",") if t.strip()]
        # Sort longest-first so longer phrases are highlighted before shorter substrings
        terms.sort(key=len, reverse=True)
        for term in terms:
            escaped_term = re.escape(term)
            # Case-insensitive replacement — wrap each match in <mark>
            rendered_body = re.sub(
                f'(?<![<\\w])({escaped_term})(?![>\\w])',
                r'<mark class="highlight-term">\1</mark>',
                rendered_body,
                flags=re.IGNORECASE,
            )

    # ── Source-text highlighting (from source_reference) ──
    source_text_raw = request.args.get("source_text", "").strip()
    if source_text_raw and not highlight_raw:
        # Split source_text into sentence-level segments for reliable matching
        # (source_text may span multiple paragraphs in rendered HTML)
        segments = _split_source_text_to_segments(source_text_raw)
        for seg in segments:
            escaped_seg = re.escape(_html_escape(seg))
            rendered_body = re.sub(
                f'({escaped_seg})',
                r'<mark class="highlight-ref">\1</mark>',
                rendered_body,
                flags=re.IGNORECASE,
            )

    # ── Word-position highlighting (fallback when source_text doesn't match) ──
    start_word_raw = request.args.get("start_word", "").strip()
    end_word_raw = request.args.get("end_word", "").strip()
    # Only apply if no highlight marks were already inserted
    if (start_word_raw and end_word_raw
            and '<mark class="highlight-ref">' not in rendered_body
            and '<mark class="highlight-term">' not in rendered_body):
        try:
            start_word = int(start_word_raw)
            end_word = int(end_word_raw)
            if 0 <= start_word < end_word:
                rendered_body = _highlight_word_range_in_html(
                    rendered_body, start_word, end_word
                )
        except (ValueError, TypeError):
            pass

    html = _build_reference_html(
        display_title, bc_html, meta_html, section_path_html,
        rendered_body, graph_display, theme
    )
    return Response(html, mimetype="text/html")


def _split_source_text_to_segments(source_text: str) -> list[str]:
    """Split source_text into sentence-level segments for reliable HTML matching.

    Source text from the KG may span multiple paragraphs or contain '...' elisions.
    We split into individual sentences so each can be matched within a single HTML element.
    """
    # First split on '...' ellipsis markers (indicates truncation)
    parts = re.split(r'\s*\.{3}\s*', source_text)
    segments = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Split long parts into individual sentences (on '. ' followed by uppercase)
        sentences = re.split(r'(?<=\.)\s+(?=[A-Z])', part)
        for s in sentences:
            s = s.strip()
            if len(s) >= 8:  # Skip very short fragments
                segments.append(s)
    return segments


def _highlight_word_range_in_html(html_str: str, start_word: int, end_word: int) -> str:
    """Highlight a range of words in rendered HTML by their position in visible text.

    Splits the rendered HTML into tags and text segments, counts words in text
    segments, and wraps the target word range with <mark> tags.
    """
    # Split HTML into alternating text and tag parts
    parts = re.split(r'(<[^>]+>)', html_str)
    word_count = 0
    result = []
    mark_open = False

    for part in parts:
        if part.startswith('<'):
            # HTML tag — pass through unchanged
            result.append(part)
            continue

        # Text content — process word by word
        tokens = re.split(r'(\s+)', part)
        for token in tokens:
            if not token:
                continue
            if token.isspace():
                result.append(token)
            else:
                # It's a word
                if word_count == start_word and not mark_open:
                    result.append('<mark class="highlight-ref">')
                    mark_open = True
                result.append(token)
                word_count += 1
                if word_count >= end_word and mark_open:
                    result.append('</mark>')
                    mark_open = False

    # Close mark if end_word exceeds total words
    if mark_open:
        result.append('</mark>')

    return ''.join(result)


def _render_chunk_body(text: str) -> str:
    """Convert chunk plain text to structured HTML with headings, paragraphs, and lists."""
    lines = text.split("\n")
    html_parts = []
    in_list = False
    paragraph_buf = []

    def flush_paragraph():
        nonlocal paragraph_buf
        if paragraph_buf:
            combined = " ".join(paragraph_buf)
            combined = _inline_format(combined)
            html_parts.append(f"<p>{combined}</p>")
            paragraph_buf = []

    def close_list():
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            flush_paragraph()
            close_list()
            continue

        # Horizontal rule
        if stripped == "---" or stripped == "***" or stripped == "___":
            flush_paragraph()
            close_list()
            html_parts.append("<hr/>")
            continue

        # Headings
        heading_match = re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if heading_match:
            flush_paragraph()
            close_list()
            level = len(heading_match.group(1))
            tag = f"h{min(level + 1, 6)}"  # offset by 1 since h1 is the page title
            h_text = _inline_format(_html_escape(heading_match.group(2)))
            html_parts.append(f"<{tag}>{h_text}</{tag}>")
            continue

        # Bullet list items
        if stripped.startswith("- ") or stripped.startswith("* ") or stripped.startswith("• "):
            flush_paragraph()
            if not in_list:
                html_parts.append('<ul class="chunk-list">')
                in_list = True
            item_text = _inline_format(_html_escape(stripped[2:]))
            html_parts.append(f"<li>{item_text}</li>")
            continue

        # Lines that look like sub-section titles (short, no period, often Title Case)
        if (len(stripped) < 80 and not stripped.endswith(".")
                and not stripped.endswith(",")
                and stripped[0].isupper()
                and not any(c in stripped for c in ["**", "##"])
                and re.match(r'^[A-Z][A-Za-z0-9\s,\-–—()\'"/]+$', stripped)
                and len(stripped.split()) <= 10):
            flush_paragraph()
            close_list()
            h_text = _inline_format(_html_escape(stripped))
            html_parts.append(f'<h4 class="subsection">{h_text}</h4>')
            continue

        # Regular paragraph text
        close_list()
        paragraph_buf.append(_html_escape(stripped))

    flush_paragraph()
    close_list()
    return "\n".join(html_parts)


def _inline_format(text: str) -> str:
    """Apply inline formatting (bold, italic, code) to already-escaped HTML text."""
    # Bold: **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
    # Italic: *text* or _text_ (but not inside words)
    text = re.sub(r'(?<!\w)\*([^*]+?)\*(?!\w)', r'<em>\1</em>', text)
    # Inline code: `text`
    text = re.sub(r'`([^`]+?)`', r'<code>\1</code>', text)
    return text


def _build_reference_html(
    title: str, breadcrumb_html: str, meta_html: str,
    section_path_html: str, body_html: str, graph_name: str,
    theme: str = "dark"
) -> str:
    """Build the complete reference HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title} — Explorer Reference</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet"/>
<style>
  :root {{
    --bg: #0b0d14;
    --surface: #12141f;
    --surface-elevated: #181b28;
    --border: #232738;
    --border-bright: #2e3348;
    --text: #e2e8f0;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --accent: #818cf8;
    --accent-light: #a5b4fc;
    --indigo-bg: rgba(99,102,241,0.08);
    --cyan: #22d3ee;
    --emerald: #34d399;
    --amber: #fbbf24;
    --rose: #fb7185;
    --violet: #a78bfa;
  }}
  body.light-theme {{
    --bg: #f8fafc;
    --surface: #ffffff;
    --surface-elevated: #f1f5f9;
    --border: #e2e8f0;
    --border-bright: #cbd5e1;
    --text: #1e293b;
    --text-secondary: #475569;
    --text-muted: #94a3b8;
    --accent: #6366f1;
    --accent-light: #818cf8;
    --indigo-bg: rgba(99,102,241,0.06);
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.75;
    -webkit-font-smoothing: antialiased;
  }}

  /* ── Header ── */
  .ref-header {{
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 1.25rem 2rem;
    position: sticky;
    top: 0;
    z-index: 10;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
  }}
  .ref-header-inner {{
    max-width: 900px;
    margin: 0 auto;
  }}
  .header-top {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.5rem;
  }}
  .header-logo {{
    width: 28px; height: 28px;
    border-radius: 8px;
    object-fit: contain;
    flex-shrink: 0;
  }}
  .header-brand {{
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}
  .graph-badge {{
    font-size: 0.65rem;
    font-weight: 600;
    color: var(--accent);
    background: var(--indigo-bg);
    padding: 0.15rem 0.5rem;
    border-radius: 100px;
    border: 1px solid rgba(99,102,241,0.15);
  }}
  .ref-title {{
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--text);
    line-height: 1.4;
    margin-bottom: 0.35rem;
  }}
  .breadcrumb {{
    font-size: 0.7rem;
    color: var(--text-muted);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0;
  }}
  .bc-part {{ color: var(--text-muted); }}
  .bc-sep {{ color: var(--border-bright); margin: 0 0.3rem; }}
  .bc-current {{ color: var(--accent); font-weight: 500; }}

  /* ── Meta badges ── */
  .meta-badges {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-top: 0.6rem;
  }}
  .badge {{
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.2rem 0.6rem;
    border-radius: 100px;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    border: 1px solid transparent;
  }}
  .badge-id {{
    background: rgba(34,211,238,0.08);
    color: var(--cyan);
    border-color: rgba(34,211,238,0.15);
  }}
  .badge-source {{
    background: rgba(167,139,250,0.08);
    color: var(--violet);
    border-color: rgba(167,139,250,0.15);
  }}
  .badge-pages {{
    background: rgba(251,191,36,0.08);
    color: var(--amber);
    border-color: rgba(251,191,36,0.15);
  }}

  /* ── Section path ── */
  .section-path {{
    margin-top: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: var(--surface-elevated);
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 0.7rem;
    color: var(--text-secondary);
    line-height: 1.5;
  }}
  .sp-part {{ color: var(--text-secondary); }}
  .sp-sep {{ color: var(--border-bright); }}

  /* ── Content ── */
  .ref-content {{
    max-width: 900px;
    margin: 1.5rem auto;
    padding: 0 2rem 3rem;
  }}
  .content-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 2rem 2.25rem;
    box-shadow: 0 4px 24px rgba(0,0,0,0.12);
  }}

  /* ── Typography ── */
  .content-card h2 {{
    font-size: 1.15rem;
    font-weight: 700;
    color: var(--text);
    margin: 1.75rem 0 0.6rem;
    padding-bottom: 0.35rem;
    border-bottom: 1px solid var(--border);
  }}
  .content-card h2:first-child {{ margin-top: 0; }}
  .content-card h3 {{
    font-size: 1rem;
    font-weight: 600;
    color: var(--text);
    margin: 1.5rem 0 0.5rem;
  }}
  .content-card h4 {{
    font-size: 0.92rem;
    font-weight: 600;
    color: var(--accent-light);
    margin: 1.35rem 0 0.4rem;
  }}
  .content-card h4.subsection {{
    font-size: 0.88rem;
    font-weight: 600;
    color: var(--accent);
    margin: 1.5rem 0 0.35rem;
    padding-left: 0.75rem;
    border-left: 3px solid var(--accent);
  }}
  .content-card p {{
    margin: 0.5rem 0;
    font-size: 0.9rem;
    color: var(--text);
    line-height: 1.8;
  }}
  .content-card hr {{
    border: none;
    height: 1px;
    background: var(--border);
    margin: 1.5rem 0;
  }}
  .content-card ul.chunk-list {{
    margin: 0.5rem 0 0.5rem 1.25rem;
    padding: 0;
  }}
  .content-card ul.chunk-list li {{
    font-size: 0.9rem;
    color: var(--text);
    margin: 0.3rem 0;
    line-height: 1.7;
  }}
  .content-card ul.chunk-list li::marker {{
    color: var(--accent);
  }}
  .content-card strong {{
    font-weight: 600;
    color: var(--text);
  }}
  .content-card em {{
    color: var(--text-secondary);
  }}
  .content-card code {{
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.82rem;
    background: var(--surface-elevated);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 0.1rem 0.35rem;
  }}

  /* ── Footer ── */
  .ref-footer {{
    max-width: 900px;
    margin: 0 auto;
    padding: 0 2rem 2rem;
    text-align: center;
  }}
  .ref-footer p {{
    font-size: 0.68rem;
    color: var(--text-muted);
  }}

  /* ── Actions bar ── */
  .actions-bar {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 1.25rem;
  }}
  .action-btn {{
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.4rem 0.8rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface-elevated);
    color: var(--text-secondary);
    font-size: 0.75rem;
    font-weight: 500;
    cursor: pointer;
    text-decoration: none;
    font-family: inherit;
    transition: all 0.15s ease;
  }}
  .action-btn:hover {{
    border-color: var(--accent);
    color: var(--accent);
    background: var(--indigo-bg);
  }}
  .action-btn svg {{ width: 14px; height: 14px; }}

  /* ── Highlight marks ── */
  mark.highlight-term {{
    background: rgba(251,191,36,0.25);
    color: var(--amber);
    padding: 0.05rem 0.25rem;
    border-radius: 3px;
    border-bottom: 2px solid var(--amber);
    font-weight: 600;
  }}
  body.light-theme mark.highlight-term {{
    background: rgba(251,191,36,0.3);
    color: #92400e;
  }}
  mark.highlight-ref {{
    background: rgba(99,102,241,0.18);
    color: var(--accent-light);
    padding: 0.05rem 0.2rem;
    border-radius: 3px;
    border-bottom: 2px solid var(--accent);
  }}
  body.light-theme mark.highlight-ref {{
    background: rgba(99,102,241,0.15);
    color: #4338ca;
    border-bottom-color: #6366f1;
  }}

  /* Auto-scroll to first highlight */
  mark.highlight-ref:first-of-type {{
    scroll-margin-top: 120px;
  }}

  /* ── Print ── */
  @media print {{
    .ref-header {{ position: static; border-bottom: 2px solid #333; background: #fff; }}
    .ref-header, .ref-header * {{ color: #333 !important; }}
    body {{ background: #fff; color: #111; }}
    .content-card {{ box-shadow: none; border: 1px solid #ddd; }}
    .actions-bar {{ display: none; }}
    .badge {{ border: 1px solid #aaa; }}
  }}

  /* ── Responsive ── */
  @media (max-width: 768px) {{
    .ref-header {{ padding: 1rem; }}
    .ref-content {{ padding: 0 1rem 2rem; }}
    .content-card {{ padding: 1.25rem; }}
    .ref-title {{ font-size: 1rem; }}
  }}
</style>
</head>
<body{' class="light-theme"' if theme == 'light' else ''}>
<div class="ref-header">
  <div class="ref-header-inner">
    <div class="header-top">
      <img class="header-logo" src="{URL_PREFIX}/logo.svg" alt="Explorer"/>
      <span class="header-brand">Explorer</span>
      <span class="graph-badge">{_html_escape(graph_name)}</span>
    </div>
    <h1 class="ref-title">{title}</h1>
    <div class="breadcrumb">{breadcrumb_html}</div>
    {meta_html}
    {section_path_html}
  </div>
</div>
<div class="ref-content">
  <div class="actions-bar">
    <button class="action-btn" onclick="window.print()" title="Print this document">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
      Print
    </button>
    <button class="action-btn" onclick="navigator.clipboard.writeText(document.querySelector('.content-card').innerText).then(()=>{{this.innerHTML='<svg viewBox=&quot;0 0 24 24&quot; fill=&quot;none&quot; stroke=&quot;currentColor&quot; stroke-width=&quot;2&quot; width=&quot;14&quot; height=&quot;14&quot;><path d=&quot;M20 6L9 17l-5-5&quot;/></svg> Copied!';setTimeout(()=>{{this.innerHTML='<svg viewBox=&quot;0 0 24 24&quot; fill=&quot;none&quot; stroke=&quot;currentColor&quot; stroke-width=&quot;2&quot; width=&quot;14&quot; height=&quot;14&quot;><rect x=&quot;9&quot; y=&quot;9&quot; width=&quot;13&quot; height=&quot;13&quot; rx=&quot;2&quot;/><path d=&quot;M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1&quot;/></svg> Copy'}},1500)}})" title="Copy text to clipboard">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
      Copy
    </button>
    <a class="action-btn" href="javascript:window.close()" title="Close tab">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      Close
    </a>
  </div>
  <div class="content-card">
    {body_html}
  </div>
</div>
<div class="ref-footer">
  <p>Policy to Knowledge Copilot — Source Document Reference</p>
</div>
<script>
// Auto-scroll to the first highlighted reference mark on page load
document.addEventListener('DOMContentLoaded', function() {{
  var mark = document.querySelector('mark.highlight-ref, mark.highlight-term');
  if (mark) {{
    setTimeout(function() {{ mark.scrollIntoView({{ behavior: 'smooth', block: 'center' }}); }}, 300);
  }}
}});
</script>
</body>
</html>"""


@app.route("/api/vertex/schema", methods=["GET"])
def vertex_schema():
    """Return the vertex schema metadata for the create form.

    Accepts optional ``graph_name`` query parameter.  When provided the
    response includes ``live_rule_types`` and ``live_edge_labels`` derived
    from the actual graph data so the UI legend can adapt per-graph.
    """
    graph_name = _resolve_graph_name(request.args.get("graph_name"))

    live_rule_types: list[str] = []
    live_edge_labels: list[str] = []
    try:
        with get_traversal(graph_name) as (g, conn):
            # Distinct rule_type values present in the graph
            rt_raw = (
                g.V().hasLabel("business_rule")
                .values("rule_type")
                .dedup()
                .toList()
            )
            live_rule_types = sorted({str(r) for r in rt_raw if r})

            # Distinct edge labels present in the graph
            el_raw = g.E().label().dedup().toList()
            live_edge_labels = sorted({str(e) for e in el_raw if e})
    except Exception:
        pass  # fall back to empty lists; UI uses hardcoded defaults

    return jsonify({
        "labels": sorted(VALID_LABELS),
        "rule_types": sorted(VALID_RULE_TYPES),
        "dependency_types": sorted(VALID_DEPENDENCY_TYPES),
        "edge_labels": ["depends_on", "belongs_to_category"],
        "live_rule_types": live_rule_types,
        "live_edge_labels": live_edge_labels,
        "properties": {
            "business_rule": {
                "required": ["name", "content"],
                "optional": ["rule_id", "rule_name", "rule_type", "description",
                             "conditions", "consequences", "exceptions", "reference",
                             "mandatory", "confidence_score", "requires_review",
                             "review_reason", "entity_or_relationship", "entity_type",
                             "extraction_notes", "category",
                             "source_reference", "effective_date", "expiration_date",
                             "superseded_by", "jurisdiction", "risk_level",
                             "related_rules", "enforcement_action",
                             "applicability_scope", "data_points_required",
                             "audit_frequency", "reference_verified",
                             "reference_verification_note",
                             "confidence_breakdown", "deduplication_info"],
            },
            "entity_category": {
                "required": ["name", "content"],
                "optional": ["category"],
            },
        },
    })


# ── Node Reference Helpers ──────────────────────────────────────────

def _safe_name(val) -> str:
    """Extract a string from a value that may be a list (JanusGraph multi-value property)."""
    if isinstance(val, list):
        return str(val[0]) if val else ""
    return str(val) if val else ""


def _lookup_vertex_ids_by_names(names: list[str]) -> dict:
    """Batch-lookup vertex IDs for a list of vertex names."""
    if not names:
        return {}
    with get_traversal() as (g, conn):
        try:
            results = (
                g.V().has("name", P.within(*names))
                .project("id", "name", "label")
                .by(__.id_())
                .by(__.values("name"))
                .by(__.label())
                .toList()
            )
            return {
                r["name"]: {"id": str(r["id"]), "name": r["name"], "label": r["label"]}
                for r in results
            }
        except Exception:
            return {}


def _collect_node_refs(frontend_event: dict, node_refs: dict, names_without_ids: set) -> None:
    """Extract node name->ID mappings from a tool result event."""
    evt_type = frontend_event.get("type", "")

    if evt_type == "search":
        for node in frontend_event.get("nodes", []):
            name = _safe_name(node.get("name"))
            nid = node.get("id")
            if name and nid:
                node_refs[name] = {
                    "id": str(nid),
                    "name": name,
                    "label": node.get("label", "business_rule"),
                }

    elif evt_type == "vertex":
        vdata = frontend_event.get("data", {})
        props = vdata.get("properties", {})
        name = _safe_name(props.get("name"))
        if name and vdata.get("id"):
            node_refs[name] = {
                "id": str(vdata["id"]),
                "name": name,
                "label": vdata.get("label", ""),
            }
        for n in vdata.get("neighbors", []):
            nname = _safe_name(n.get("name"))
            if nname and n.get("id"):
                node_refs[nname] = {
                    "id": str(n["id"]),
                    "name": nname,
                    "label": n.get("label", ""),
                }
        for d in vdata.get("depends_on", []):
            tname = _safe_name(d.get("target_name"))
            if tname and tname not in node_refs:
                names_without_ids.add(tname)
        for d in vdata.get("depended_by", []):
            sname = _safe_name(d.get("source_name"))
            if sname and sname not in node_refs:
                names_without_ids.add(sname)

    elif evt_type == "related_rules":
        for node in frontend_event.get("nodes", []):
            nname = _safe_name(node.get("name"))
            if nname and node.get("id"):
                node_refs[nname] = {
                    "id": str(node["id"]),
                    "name": nname,
                    "label": node.get("label", "business_rule"),
                }
        rule = frontend_event.get("data", {}).get("rule", {})
        rname = _safe_name(rule.get("name"))
        if rname and rule.get("id"):
            node_refs[rname] = {
                "id": str(rule["id"]),
                "name": rname,
                "label": rule.get("label", ""),
            }
        for d in frontend_event.get("data", {}).get("depends_on", []):
            tname = _safe_name(d.get("target_name"))
            tid = d.get("target_id")
            if tname and tid:
                node_refs[tname] = {"id": str(tid), "name": tname, "label": "business_rule"}
            elif tname and tname not in node_refs:
                names_without_ids.add(tname)
        for d in frontend_event.get("data", {}).get("depended_by", []):
            sname = _safe_name(d.get("source_name"))
            sid = d.get("source_id")
            if sname and sid:
                node_refs[sname] = {"id": str(sid), "name": sname, "label": "business_rule"}
            elif sname and sname not in node_refs:
                names_without_ids.add(sname)

    elif evt_type == "gremlin":
        for r in frontend_event.get("results", []):
            if isinstance(r, dict) and r.get("name"):
                rname = _safe_name(r["name"])
                if not rname:
                    continue
                if r.get("id"):
                    node_refs[rname] = {
                        "id": str(r["id"]),
                        "name": rname,
                        "label": "business_rule",
                    }
                elif rname not in node_refs:
                    names_without_ids.add(rname)

    elif evt_type == "statistics":
        # hub_rules_top_5 is nested per-graph inside data.graphs.<name>.statistics
        graphs_data = frontend_event.get("data", {}).get("graphs", {})
        for graph_info in graphs_data.values():
            stats = graph_info.get("statistics", {}) if isinstance(graph_info, dict) else {}
            for hub in stats.get("hub_rules_top_5", []):
                if isinstance(hub, dict) and hub.get("name"):
                    hname = _safe_name(hub["name"])
                    if hname and hname not in node_refs:
                        names_without_ids.add(hname)


# ── Explorer Chatbot ────────────────────────────────────────

def _build_chat_tools():
    """Build chat tool definitions dynamically.

    Rebuilt per-request so graph add/remove operations (via /api/graph/publish
    or DELETE /api/graph/<key>) are reflected in tool enums without restarting
    the server.
    """
    return [
    {
        "type": "function",
        "function": {
            "name": "semantic_search",
            "description": (
                "Search the knowledge graph using vector-based semantic similarity (OpenSearch k-NN). "
                "USE WHEN: the user asks a conceptual or topic-based question "
                "('rules about income verification', 'what relates to appraisal requirements', "
                "'anything about debt-to-income'). Returns rules ranked by meaning similarity. "
                "DO NOT USE WHEN: looking for an exact word/phrase (use text_search), "
                "asking about graph structure like counts, rankings, or paths (use execute_gremlin), "
                "or already knowing the rule name (use find_related_rules)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural language search query describing the concept or topic to find"},
                    "top_k": {"type": "integer", "description": f"Number of results (default {SEMANTIC_SEARCH_DEFAULT_TOP_K})", "default": SEMANTIC_SEARCH_DEFAULT_TOP_K},
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "text_search",
            "description": (
                "Full-text keyword search over rule content using the OpenSearch mixed index (via Gremlin). "
                "USE WHEN: searching for specific words, exact phrases, or acronyms in rule text "
                "('DTI ratio', 'Form 1003', 'appraisal waiver'). Optionally filter by entity category. "
                "DO NOT USE WHEN: searching by meaning/concept (use semantic_search), "
                "or analyzing graph structure (use execute_gremlin)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Exact text, keywords, or phrases to search for in rule content"},
                    "category": {"type": "string", "description": "Optional entity category filter (e.g., 'BORROWER', 'PROPERTY', 'UNDERWRITING')"},
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_gremlin",
            "description": (
                "Execute a Gremlin graph traversal on JanusGraph for structural/relational analysis. "
                "USE WHEN: the question involves graph structure — counting vertices/edges, "
                "ranking rules by dependency count, finding dependency chains or paths between rules, "
                "aggregating by property (groupCount), discovering isolated nodes, comparing connectivity, "
                "or any quantitative graph metric. Query must start with 'g.' — the server binds 'g' to "
                "the chosen traversal source. "
                "DO NOT USE WHEN: finding rules by topic or content (use semantic_search or text_search)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Gremlin query string starting with g. (e.g., g.V().count())"},
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_graph_data",
            "description": (
                "Load the complete graph structure (all nodes and edges) for D3.js visualization. "
                "USE ONLY WHEN: the user explicitly asks to 'show the graph', 'load the visualization', "
                "or 'display the full graph'. "
                "DO NOT USE for answering questions — use search or Gremlin tools instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "graph_name": {
                        "type": "string",
                        "description": get_graph_enum_description(),
                        "enum": get_loaded_traversal_sources(),
                        "default": get_default_traversal_source()
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_vertex_details",
            "description": (
                "Get all properties, neighbors, and dependency edges for a single vertex; "
                "optionally highlights it on the graph visualization. "
                "USE WHEN: drilling into a specific node after finding its ID/name via search, "
                "or when the user says 'show me node X' / 'open rule X'. "
                "Pass either a numeric vertex ID or the exact vertex name."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vertex_id": {"type": "string", "description": "Numeric vertex ID or the exact vertex name"},
                    "show_on_graph": {"type": "boolean", "description": "Highlight this node on the graph visualization (default: true)", "default": True},
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                },
                "required": ["vertex_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_related_rules",
            "description": (
                "Find a rule by name (exact or fuzzy) and return its FULL dependency neighborhood in one call: "
                "all outgoing deps (rules it depends on), all incoming deps (rules that depend on it), "
                "its category, and sibling rules in the same category. "
                "USE WHEN: the user asks 'tell me about rule X', 'what depends on X', "
                "'what are X's relationships', or you already know/can approximate the rule name. "
                "Prefer this over chaining semantic_search → get_vertex_details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_name": {"type": "string", "description": "The rule name or partial name to search for"},
                    "show_on_graph": {"type": "boolean", "description": "Navigate to this rule on the graph (default: true)", "default": True},
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                },
                "required": ["rule_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_graph_statistics",
            "description": (
                "Get a comprehensive statistical overview of ALL knowledge graphs: vertex/edge counts, "
                "rule type distribution, dependency type breakdown, entity categories, confidence score "
                "distribution, hub rules (most connected), and isolated rules. "
                "USE WHEN: the user asks 'how many rules', 'what types of rules exist', 'give me an "
                "overview', 'what does the graph look like', or any composition/coverage question."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_rules",
            "description": (
                "Compare 2 or more rules side-by-side: properties, dependencies, categories, confidence, "
                "and overlap analysis. Returns structured comparison data. "
                "USE WHEN: the user asks 'compare rule A and rule B', 'what is the difference between X and Y', "
                "'how do these rules relate', or any comparative question involving specific rule names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of 2+ rule names (exact or partial) to compare",
                        "minItems": 2
                    },
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                },
                "required": ["rule_names"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_dependency_path",
            "description": (
                "Find the dependency path(s) between two rules in the graph. Uses graph traversal to "
                "discover how rule A connects to rule B through intermediate dependency chains. "
                "USE WHEN: the user asks 'how are these rules connected', 'what is the path from X to Y', "
                "'is there a dependency chain between A and B', or 'show me the relationship path'. "
                "Returns all shortest paths up to the specified depth."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_rule": {"type": "string", "description": "Name of the starting rule (exact or partial match)"},
                    "to_rule": {"type": "string", "description": "Name of the target rule (exact or partial match)"},
                    "max_depth": {"type": "integer", "description": "Maximum traversal depth (default 6, max 10)", "default": 6},
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                },
                "required": ["from_rule", "to_rule"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_source_reference",
            "description": (
                "Read the original source document text that backs a specific rule. Resolves the rule's "
                "reference and source_reference properties to the actual regulatory document chunk in the "
                "knowledge base. Returns the document text, metadata, and highlighted excerpts. "
                "USE WHEN: the user asks 'what does the source say about rule X', 'show me the original text', "
                "'where does this rule come from', or 'cite the source for rule X'. "
                "DO NOT USE for general search — use semantic_search or text_search instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_name": {"type": "string", "description": "The exact or partial rule name to look up the source for"},
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                },
                "required": ["rule_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_review_status",
            "description": (
                "Get the review and approval status of rules across the knowledge graph. Shows which rules "
                "are reviewed, approved, have comments, or still need attention. "
                "USE WHEN: the user asks 'what needs review', 'what has been approved', 'show me commented rules', "
                "'review status', 'pending approvals', or any question about the annotation/review workflow. "
                "Can filter by status type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "description": "Filter annotations by status",
                        "enum": ["all", "needs_review", "needs_approval", "reviewed", "approved", "commented"],
                        "default": "all"
                    },
                    "graph_name": {"type": "string", "description": get_graph_enum_description(), "enum": get_loaded_traversal_sources(), "default": get_default_traversal_source()}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cross_graph_search",
            "description": (
                "Search for rules across ALL loaded knowledge graphs simultaneously and merge results. "
                "USE THIS AS THE DEFAULT when the user does not specify a particular graph and asks a "
                "general conceptual question ('what are the income verification rules', 'find appraisal "
                "requirements', 'any rules about DTI'). Runs semantic + text search on every graph, "
                "deduplicates, and ranks by relevance. Set mode='both' to run semantic AND text in parallel "
                "for best coverage. Set include_kb=true to also search source KB documents. "
                "PREFER over single-graph semantic_search when: the user's intent is exploratory or domain "
                "is unclear, or you want maximum recall across all compliance domains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query — natural language for semantic, keywords for text, or both"},
                    "mode": {
                        "type": "string",
                        "description": "Search mode: 'semantic' (meaning/concept), 'text' (exact keywords), or 'both' (run both and merge, best coverage)",
                        "enum": ["semantic", "text", "both"],
                        "default": "both"
                    },
                    "top_k": {"type": "integer", "description": "Max results per graph per search type (default 8)", "default": 8},
                    "include_kb": {"type": "boolean", "description": "Also search source KB documents (regulatory text chunks) in addition to graph rules", "default": False}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search the original source regulatory documents (PDFs, guidelines, overlays) stored in the "
                "knowledge base — the raw text that rules were extracted from. Returns matching document "
                "chunks with title, content excerpts, and source attribution. "
                "USE WHEN: the user asks what the source document says about a topic, needs a specific "
                "clause or section number, asks 'where does the guideline say X', wants to verify rule "
                "provenance, or needs text that may not have been captured as a graph rule. "
                "This searches DOCUMENTS not extracted rules — complement with cross_graph_search for rules."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords or phrases to find in source documents"},
                    "graph_name": {
                        "type": "string",
                        "description": f"Restrict to one graph's KB ({get_graph_enum_description()}). Omit to search ALL knowledge bases.",
                        "enum": get_loaded_traversal_sources()
                    },
                    "top_k": {"type": "integer", "description": "Max chunks to return (default 10)", "default": 10}
                },
                "required": ["query"]
            }
        }
    }
]


def _build_chat_system_prompt(active_graph: Optional[str] = None):
    """Build the chat system prompt dynamically.

    Rebuilt per-request so the available-graphs list reflects the current
    manifest (graph add/remove takes effect immediately, no restart needed).

    If ``active_graph`` is provided and matches a loaded traversal source,
    it is used as the default graph for tool calls (overriding the
    manifest-wide default). This lets the LLM answer about whichever
    graph the user is currently viewing in the UI.
    """
    loaded_sources = set(get_loaded_traversal_sources())
    if active_graph and active_graph in loaded_sources:
        default_graph = active_graph
    else:
        default_graph = get_default_traversal_source()

    active_note = ""
    if active_graph and active_graph in loaded_sources:
        active_note = (
            f"\n\n## Active Graph Context\nThe user is currently viewing the **{active_graph}** graph in the UI. "
            f"Unless they explicitly name a different graph, ALL tool calls MUST use graph_name=\"{active_graph}\"."
        )

    return ("""You are Explorer, an elite compliance knowledge graph analyst. You reason through complex questions step-by-step, chain multiple tools together iteratively, and deliver insights that go beyond surface-level answers. You have access to multiple knowledge graphs, each containing different compliance domains.

## Available Knowledge Graphs
This system contains multiple separate knowledge graphs (loaded dynamically from graphs.yaml):
""" + "\n".join(
    f'- **{graph.get("display_name", key)}** [graph_name: "{graph["traversal_source"]}"] — Knowledge graph loaded from {graph.get("kg_file", "N/A")}'
    for key, graph in get_loaded_graphs().items()
    if _graph_has_jg_data(graph["traversal_source"])
) + """

When users ask about a specific graph, use the appropriate graph_name parameter in your tool calls. If no specific graph is mentioned, default to \"""" + default_graph + """\".""" + active_note + """

## CRITICAL: Output Discipline — Answer Marker Protocol
You MUST begin every response with the exact text: |||ANSWER_START|||
This marker is automatically removed before the user sees your reply.
All text you produce BEFORE the marker is silently discarded — use that space freely for private reasoning.
After |||ANSWER_START||| output ONLY the clean, formatted answer. NEVER include:
- Internal planning or deliberation ("Let me think…", "I need to…", "Ok let's…")
- Tool-selection reasoning or self-talk
- Step-by-step narration of actions taken
- Raw Gremlin query text unless explicitly requested
Everything below (Core Principles, Analytical Framework, Patterns) is YOUR INTERNAL playbook. None of it should appear after |||ANSWER_START|||.

## Core Principles
1. **Be iterative** — You can call tools multiple times across multiple rounds. First search to find relevant rules, then drill deeper into their dependencies, then cross-reference with statistics. Don't try to answer everything in one shot.
2. **Be thorough** — Always prefer getting MORE data over guessing. If a search returns interesting rules, look up their details and dependencies.
3. **Be analytical** — Don't just list results. Identify patterns, highlight critical dependencies, explain cascading effects, and note anomalies.
4. **Be evidence-based** — Cite specific rule names, dependency types, confidence scores, and counts. Never make claims without data.
5. **NEVER invent graph statistics** — You MUST NOT state node counts, edge counts, link counts, or "the graph contains X nodes and Y links" unless those numbers came directly from a tool response in this conversation. If asked about graph size, call `get_graph_statistics` (or `get_graph_overview`) FIRST. Do not guess. Do not write template responses like "The X graph has been loaded for visualization. It contains N nodes and M links" — that text is forbidden.

## Your Analytical Framework (internal — never reproduce in your response)
Internally follow this process to decide your tool calls:
1. **Understand** — What is the user truly asking? What would constitute a complete, useful answer?
2. **Discover** — Use search tools to find relevant rules and entities. Cast a wide net first.
3. **Investigate** — For important findings, drill deeper: get vertex details, trace dependencies, check related rules.
4. **Analyze** — Look for patterns, clusters, dependency chains, anomalies, coverage gaps.
5. **Synthesize** — Structure your answer with clear sections, tables, and actionable insights.

## Multi-Step Reasoning Patterns (internal — never reproduce in your response)
You should chain tools across multiple rounds. Here are common patterns:

**Pattern: Deep Dive on a Rule**
Round 1: semantic_search("rule topic") → find relevant rules
Round 2: find_related_rules(best_match) → get full dependency neighborhood
Round 3: get_vertex_details(interesting_dependent) → explore a key connection

**Pattern: Comparative Analysis**
Round 1: semantic_search("topic A") + semantic_search("topic B")
Round 2: compare_rules(rule_names=[ruleA, ruleB]) → side-by-side comparison with overlap analysis

**Pattern: Path Discovery**
Round 1: semantic_search("rule A topic") + semantic_search("rule B topic") → find exact names
Round 2: find_dependency_path(from_rule, to_rule) → discover dependency chain between them

**Pattern: Impact Assessment**
Round 1: find_related_rules("rule name") → get dependencies
Round 2: execute_gremlin(count downstream dependents) → assess impact breadth

**Pattern: Coverage Analysis**
Round 1: get_graph_statistics() → understand overall graph shape
Round 2: semantic_search("topic") → find rules in area of interest
Round 3: execute_gremlin(rules in category without dependencies) → find gaps

**Pattern: Source Verification**
Round 1: semantic_search("rule topic") → find the rule
Round 2: get_source_reference(rule_name) → retrieve original document text backing the rule

**Pattern: Review Dashboard**
Round 1: get_review_status(filter="needs_review") → see what needs attention
Round 2: get_vertex_details(vertex_id) → inspect specific rules needing review

**Pattern: Cross-Domain Discovery**
Round 1: cross_graph_search(query="topic", mode="both", include_kb=true) → find matches across all graphs AND KB docs
Round 2: compare_rules(rule_names=[...]) → compare rules from different domains

**Pattern: Full Research (Rules + Source Documents)**
Round 1: cross_graph_search(query="topic", mode="both", include_kb=true, top_k=8) → broad sweep of graph rules + KB
Round 2: search_knowledge_base(query="topic") → deeper KB chunk search for policy/guideline text
Round 3: synthesize graph rules and source document excerpts into a unified answer

**Pattern: KB Deep Dive**
Round 1: search_knowledge_base(query="topic") → find relevant KB chunks
Round 2: get_source_reference(rule_name=...) → retrieve original document text for specific rules found

## Graph Schema

Vertex labels (366 total):
- "business_rule" — properties: name, rule_id, rule_type (constraint|eligibility|process|prohibition|documentation|validation), description, content, category, entity_or_relationship, mandatory (boolean), confidence_score (float 0-100), requires_review (boolean), review_reason, conditions, consequences, exceptions, reference, source_reference (JSON: chunk_path, section_id, source_text, text_match_score), effective_date, expiration_date, superseded_by, jurisdiction (e.g. "agency:FHLMC"), risk_level (high|medium|low), related_rules (JSON array of rule_ids), enforcement_action, applicability_scope (JSON: loan_types[], occupancy_types[], transaction_types[]), data_points_required (JSON array), audit_frequency (e.g. "at_origination"), reference_verified (boolean), reference_verification_note, confidence_breakdown (JSON: extraction_clarity, numeric_precision, context_completeness, source_authority, logical_consistency), deduplication_info (JSON: merged_from[], merge_count, rationale)
- "entity_category" — properties: name, content, description

Edge labels (457 total):
- "depends_on" (between business_rules) — properties: dependency_type (prerequisite|complementary|conditional|sequential|override|mutual|hierarchical), strength (1-5), rationale
- "belongs_to_category" (business_rule → entity_category)

Key metrics to remember:
- Strength 5 = critical dependency (must not break)
- Confidence < 70 = likely needs human review
- Override dependencies = one rule supersedes another
- Prerequisite chains can cascade failures

## CRITICAL: Confidence Score Scale
confidence_score is stored on a **0–100 scale** (e.g. 53.5, 72.0, 98.25), NOT 0–1.
When the user says "below 0.6" or "less than 0.8", they almost certainly mean 60 or 80 on the 100-point scale.
ALWAYS normalize fractional inputs: multiply by 100 before querying. For example:
- User says "below 0.6" → query `has('confidence_score', lt(60.0))`
- User says "above 0.9" → query `has('confidence_score', gt(90.0))`
- User says "below 70" → query `has('confidence_score', lt(70.0))` (already on correct scale)
If ambiguous, check the actual score range first with a min/max aggregation before filtering.

## Gremlin Query Syntax (IMPORTANT)
- Use Groovy-style Gremlin (this runs on JanusGraph/TinkerPop server)
- Sort descending: use `desc` not `decr` — e.g. `.order().by(values, desc)` or `.order().by(select('x'), desc)`
- Sort ascending: use `asc`
- Always use the exact label names: 'business_rule', 'entity_category', 'depends_on', 'belongs_to_category'
- For counting edges: `bothE('depends_on').count()`, `outE('depends_on').count()`, `inE('depends_on').count()`
- For ordering by computed value: `.project('name','deps').by(values('name')).by(bothE('depends_on').count()).order().by(select('deps'), desc)`
- For text search: `has('content', textContains('keyword'))`
- For getting properties: `values('name')`, `valueMap(true)` or `.project(...)` with `.by()` steps

## Example Gremlin Queries
- Count all vertices: `g.V().count()`
- Top 5 most connected rules: `g.V().hasLabel('business_rule').project('name','total_deps').by(values('name')).by(bothE('depends_on').count()).order().by(select('total_deps'), desc).limit(5).toList()`
- Rules by type: `g.V().hasLabel('business_rule').groupCount().by(values('rule_type')).toList()`
- Entity categories with counts: `g.V().hasLabel('entity_category').project('category','count').by(values('name')).by(inE('belongs_to_category').count()).order().by(select('count'), desc).toList()`
- Dependencies by type: `g.E().hasLabel('depends_on').groupCount().by(values('dependency_type')).toList()`
- Rules in a category: `g.V().hasLabel('entity_category').has('name', 'CategoryName').in('belongs_to_category').values('name').toList()`
- Dependency chain: `g.V().has('name','RuleName').repeat(out('depends_on')).until(outE('depends_on').count().is(0)).path().by(values('name')).toList()`
- Find shared dependencies: `g.V().has('name','RuleA').out('depends_on').where(__.in('depends_on').has('name','RuleB')).values('name').toList()`
- Rules with most incoming deps (most depended upon): `g.V().hasLabel('business_rule').project('name','in_count').by(values('name')).by(inE('depends_on').count()).order().by(select('in_count'), desc).limit(10).toList()`
- All critical strength-5 prerequisites: `g.E().hasLabel('depends_on').has('dependency_type','prerequisite').has('strength', 5).project('from','to','rationale').by(outV().values('name')).by(inV().values('name')).by(values('rationale')).toList()`

## Tool Selection Strategy
Follow this decision tree IN ORDER to choose the right tool(s):

### Decision Tree (evaluate top to bottom)
1. **Does the user ask for an overview, counts, or composition of the graph?**
   → `get_graph_statistics` (covers all graphs at once)
2. **Does the user ask to SHOW / VISUALIZE / LOAD the full graph?**
   → `get_graph_data` with the right graph_name
3. **Does the user reference a specific rule by name?**
   → `find_related_rules` — gives full neighborhood in one call. Then optionally follow up with `get_vertex_details` or `execute_gremlin` for deeper analysis.
4. **Does the user want to compare two or more specific rules?**
   → `compare_rules` — side-by-side properties, dependencies, and overlap analysis for named rules.
5. **Does the user ask about the relationship or path between two rules?**
   → `find_dependency_path` — finds the shortest dependency chain between two named rules.
6. **Does the user ask for the original source document / reference behind a rule?**
   → `get_source_reference` (for a specific named rule) **OR** `search_knowledge_base` (when the user wants to search source documents, guidelines, or policies by topic without knowing the exact rule name).
7. **Does the user ask about review status, approval status, or annotation progress?**
   → `get_review_status` — summarizes annotation/review/approval state, pending tasks, and recent comments.
8. **Is the question about a concept, topic, or regulatory area WITHOUT specifying a particular graph?**
   → **DEFAULT: `cross_graph_search` with `mode="both"` and `include_kb=true`** — searches ALL graphs AND knowledge-base documents simultaneously. This is the right choice whenever the user asks a general question like "what are the rules about X?", "find anything related to Y", or "search for Z". Use `top_k=8` or higher for broad queries. Only narrow to `semantic_search` / `text_search` if the user explicitly names a specific graph.
9. **Does the user ask to search source documents, guidelines, or policy files by keyword or topic?**
   → `search_knowledge_base` — full-text search across KB markdown chunks, title-boosted, multi-term scoring. Use when the user says "find in the guidelines", "look in the source docs", "search the knowledge base", or similar.
10. **Does the question involve graph structure: counts, rankings, dependency chains, paths, aggregations, connectivity, or comparisons between rules?**
    → `execute_gremlin` — write a Gremlin traversal. This is the ONLY tool that can answer structural questions.
11. **Does the question involve a concept, topic, or meaning within a SPECIFIC named graph?**
    → `semantic_search` with `graph_name` — finds rules by semantic meaning via OpenSearch k-NN vectors.
12. **Does the question look for a specific word, phrase, or exact term within a SPECIFIC named graph?**
    → `text_search` with `graph_name` — full-text keyword search via OpenSearch mixed index.

### Search Escalation Pattern
When a single-graph search returns few or weak results, automatically escalate:
- Round 1: `semantic_search` or `text_search` on the named graph
- Round 2: `cross_graph_search(mode="both", include_kb=true)` — widens to all graphs + KB documents
- Round 3: `search_knowledge_base` — targeted KB document search if graph results are thin

### Combined Graph + KB Pattern
For research questions (e.g. "explain the appraisal requirements", "what do the guidelines say about DTI?"):
- Round 1: `cross_graph_search(query=..., mode="both", include_kb=true, top_k=8)` — gets graph rules AND KB matches in one call
- Round 2: `search_knowledge_base(query=...)` — supplements with deeper KB chunk text
- Synthesize both into a unified answer citing rule names and source documents

### When Tools MUST NOT Be Used
| Tool                  | Never use when…                                                                  |
|-----------------------|----------------------------------------------------------------------------------|
| semantic_search       | Question is about counts, rankings, paths, or structure                          |
| text_search           | Question is about meaning/concepts (not exact words)                             |
| execute_gremlin       | Question is about finding rules by topic (not structure)                         |
| get_graph_data        | Question can be answered with search or stats                                    |
| compare_rules         | Only one rule is mentioned (use find_related_rules instead)                      |
| find_dependency_path  | Only one rule is mentioned, or no path question is asked                         |
| get_source_reference  | User is not asking about the source/origin of a NAMED rule                       |
| cross_graph_search    | User explicitly names a single graph AND wants structure (use execute_gremlin)   |
| search_knowledge_base | User wants graph rule data (not source documents)                                |

### Multi-Graph Awareness
Always pass the correct `graph_name` parameter when the user mentions a specific domain:
- Compliance / FAMA → graph_name = the first traversal source (default)
- Contracts / overlays / Revolution → use the contracts traversal source
- Commercial lending → use the commercial lending traversal source
- **If unclear or no graph is mentioned → use `cross_graph_search` to cover all graphs at once.**

## Showing Nodes on the Graph
When a user asks to "show", "display", "visualize", or "open" a specific rule or node:
1. First find the node (via semantic_search, text_search, or execute_gremlin)
2. Then call get_vertex_details(vertex_id=<id>, show_on_graph=true) or find_related_rules for the node(s)
3. Always reference the exact names of rules you found rather than paraphrasing them

## Response Formatting Standards
You MUST format responses using rich Markdown for readability:
- **Tables**: ALWAYS use Markdown tables when presenting lists of rules, comparisons, rankings, or any structured data with 2+ columns. Example:
  | Rule | Type | Confidence | Dependencies |
  |------|------|-----------|-------------|
  | Rule A | constraint | 95.0 | 5 |
- **Headers**: Use ## and ### to organize sections in longer responses
- **Bold**: Use **bold** for rule names, key terms, and important findings
- **Lists**: Use numbered lists for rankings/steps, bullet lists for features/properties
- **Blockquotes**: Use > for highlighting key insights, rule content excerpts, or important warnings
- **Code blocks**: Use ```gremlin for Gremlin queries shown to the user
- **Key insights**: End analytical responses with a "## Key Insights" or "## Summary" section highlighting the most important findings
- Include specific numbers, counts, and data points — not vague summaries
- When showing dependencies, explain the dependency TYPE (prerequisite = must be done first, override = supersedes, complementary = works together, etc.)
- Highlight cascading effects — if rule A depends on B which depends on C, explain the chain
- Flag anomalies — low confidence rules, isolated rules, potential gaps
- Cross-reference data from multiple tool results when available

Be thorough, analytical, and conversational. Always ground your answers in the actual data returned by tools. When you don't have enough information, say what additional investigation would help and consider doing another tool call to get it.

Remember: Begin with |||ANSWER_START||| then output ONLY the clean, formatted answer. All text before the marker is discarded.""")


def _execute_chat_tool(function_name, function_args):
    """Execute a chat tool. Returns (llm_result, frontend_event)."""
    if function_name == "semantic_search":
        search_graph = function_args.get("graph_name") or get_default_traversal_source()
        results = _engine.search(
            function_args["query"],
            top_k=function_args.get("top_k", SEMANTIC_SEARCH_DEFAULT_TOP_K),
            graph_name=search_graph,
        )
        # Enrich results with full vertex properties from the correct graph
        with get_traversal(search_graph) as (g, conn):
            for r in results:
                try:
                    vprops = (
                        g.V().has("name", r["name"])
                        .project("id", "rule_type", "entity_or_relationship", "mandatory",
                                 "confidence_score", "description", "conditions", "consequences",
                                 "exceptions", "requires_review", "dep_count")
                        .by(__.id_())
                        .by(__.coalesce(__.values("rule_type"), __.constant("")))
                        .by(__.coalesce(__.values("entity_or_relationship"), __.constant("")))
                        .by(__.coalesce(__.values("mandatory"), __.constant(False)))
                        .by(__.coalesce(__.values("confidence_score"), __.constant(0)))
                        .by(__.coalesce(__.values("description"), __.constant("")))
                        .by(__.coalesce(__.values("conditions"), __.constant("")))
                        .by(__.coalesce(__.values("consequences"), __.constant("")))
                        .by(__.coalesce(__.values("exceptions"), __.constant("")))
                        .by(__.coalesce(__.values("requires_review"), __.constant(False)))
                        .by(__.bothE("depends_on").count())
                        .next()
                    )
                    r["id"] = str(vprops["id"])
                    r["rule_type"] = vprops["rule_type"]
                    r["entity_or_relationship"] = vprops["entity_or_relationship"]
                    r["mandatory"] = vprops["mandatory"]
                    r["confidence_score"] = vprops["confidence_score"]
                    r["description"] = vprops["description"]
                    r["conditions"] = vprops["conditions"]
                    r["consequences"] = vprops["consequences"]
                    r["exceptions"] = vprops["exceptions"]
                    r["requires_review"] = vprops["requires_review"]
                    r["dependency_count"] = vprops["dep_count"]
                except Exception:
                    r["id"] = None
        # Tag every result with the graph it came from so the frontend can load the right graph
        for r in results:
            r["graph_name"] = search_graph
        llm_result = {"results": results, "count": len(results)}
        frontend_event = {
            "type": "search",
            "tool": "semantic_search",
            "query": function_args["query"],
            "graph_name": search_graph,
            "nodes": results,
        }
        return llm_result, frontend_event

    elif function_name == "text_search":
        text_graph = function_args.get("graph_name") or get_default_traversal_source()
        with get_traversal(text_graph) as (g, conn):
            t = g.V().has("content", TextP.containing(function_args["query"]))
            if function_args.get("category"):
                t = t.has("category", function_args["category"])
            raw = (
                t.project("id", "name", "label", "rule_type", "content", "description",
                          "entity_or_relationship", "mandatory", "confidence_score", "dep_count")
                .by(__.id_())
                .by(__.values("name"))
                .by(__.label())
                .by(__.coalesce(__.values("rule_type"), __.constant("")))
                .by(__.values("content"))
                .by(__.coalesce(__.values("description"), __.constant("")))
                .by(__.coalesce(__.values("entity_or_relationship"), __.constant("")))
                .by(__.coalesce(__.values("mandatory"), __.constant(False)))
                .by(__.coalesce(__.values("confidence_score"), __.constant(0)))
                .by(__.bothE("depends_on").count())
                .limit(TEXT_SEARCH_MAX_RESULTS)
                .toList()
            )
            nodes = [
                {
                    "id": str(r["id"]),
                    "name": r["name"],
                    "label": r["label"],
                    "rule_type": r["rule_type"],
                    "content": r["content"][:500],
                    "description": r["description"],
                    "entity_or_relationship": r["entity_or_relationship"],
                    "mandatory": r["mandatory"],
                    "confidence_score": r["confidence_score"],
                    "dependency_count": r["dep_count"],
                    "graph_name": text_graph,
                }
                for r in raw
            ]
        llm_result = {"results": nodes, "count": len(nodes)}
        frontend_event = {
            "type": "search",
            "tool": "text_search",
            "query": function_args["query"],
            "graph_name": text_graph,
            "nodes": nodes,
        }
        return llm_result, frontend_event

    elif function_name == "execute_gremlin":
        query_str = function_args["query"]
        gremlin_graph = function_args.get("graph_name") or get_default_traversal_source()
        # The chat agent can emit arbitrary Gremlin; apply the same read-only
        # guard as the HTTP endpoint so a prompt-injected query can't mutate data.
        blocked = _gremlin_safety_violation(query_str)
        if blocked and os.getenv("GREMLIN_ALLOW_MUTATIONS", "false").lower() != "true":
            return (
                {"error": f"Blocked unsafe Gremlin operation '{blocked}' (read-only mode)."},
                {"type": "error", "tool": "execute_gremlin",
                 "message": f"Blocked unsafe operation '{blocked}'."},
            )
        conn = None
        try:
            url = f"ws://{JANUSGRAPH_HOST}:{JANUSGRAPH_PORT}/gremlin"
            conn = DriverRemoteConnection(
                url, gremlin_graph, message_serializer=GraphSONSerializersV3d0()
            )
            client = conn._client
            raw_result = client.submit(query_str).all().result()
            serialized = _serialize_gremlin_result(raw_result)
        finally:
            if conn:
                conn.close()
        llm_result = {"results": serialized, "count": len(raw_result)}
        frontend_event = {
            "type": "gremlin",
            "query": query_str,
            "results": serialized,
            "count": len(raw_result),
        }
        return llm_result, frontend_event

    elif function_name == "get_graph_data":
        graph_name = function_args.get("graph_name") or get_default_traversal_source()
        with get_traversal(graph_name) as (g, conn):
            raw_vertices = (
                g.V()
                .project("id", "label", "props")
                .by(__.id_())
                .by(__.label())
                .by(__.valueMap(*ALL_VERTEX_PROPERTIES))
                .toList()
            )
            nodes = []
            for v in raw_vertices:
                props = v["props"]
                flat = {
                    k: val[0] if isinstance(val, list) and len(val) == 1 else val
                    for k, val in props.items()
                }
                nodes.append({
                    "id": str(v["id"]),
                    "label": v["label"],
                    "name": flat.get("name", flat.get("rule_id", "")),
                    "category": flat.get("category", flat.get("rule_type", "")),
                    "node_type": flat.get("node_type", v["label"]),
                    "rule_type": flat.get("rule_type", ""),
                    "confidence_score": flat.get("confidence_score", 0),
                    "mandatory": flat.get("mandatory", False),
                    "requires_review": flat.get("requires_review", False),
                    "entity_or_relationship": flat.get("entity_or_relationship", ""),
                })
            edges = (
                g.E()
                .project("id", "source", "target", "label", "dependency_type")
                .by(__.id_())
                .by(__.outV().id_())
                .by(__.inV().id_())
                .by(__.label())
                .by(__.coalesce(__.values("dependency_type"), __.constant("")))
                .toList()
            )
            links = [
                {
                    "id": str(e["id"]),
                    "source": str(e["source"]),
                    "target": str(e["target"]),
                    "label": e["label"],
                    "dependency_type": e["dependency_type"],
                }
                for e in edges
            ]
        graph_display_name = get_graph_configs().get(graph_name, {}).get("name", graph_name)
        llm_result = {
            "graph_name": graph_name,
            "graph_display_name": graph_display_name,
            "nodes_count": len(nodes),
            "links_count": len(links),
            "message": f"{graph_display_name} graph loaded for visualization.",
        }
        frontend_event = {"type": "graph", "data": {"nodes": nodes, "links": links, "graph_name": graph_name}}
        return llm_result, frontend_event

    elif function_name == "get_vertex_details":
        graph_name = function_args.get("graph_name", "g")
        with get_traversal(graph_name) as (g, conn):
            vid_str = function_args["vertex_id"]
            # Try numeric ID first, then fall back to name lookup
            if vid_str.isdigit():
                vid = int(vid_str)
            else:
                try:
                    vid = g.V().has("name", vid_str).id_().next()
                except StopIteration:
                    return (
                        {"error": f"No vertex found with name: {vid_str}"},
                        {"type": "error", "message": f"No vertex found with name: {vid_str}"},
                    )
            props = (
                g.V(vid)
                .project("id", "label", "props")
                .by(__.id_())
                .by(__.label())
                .by(__.valueMap(*ALL_VERTEX_PROPERTIES))
                .next()
            )
            flat = {
                k: val[0] if isinstance(val, list) and len(val) == 1 else val
                for k, val in props["props"].items()
            }

            # Fetch neighbors
            neighbors = (
                g.V(vid)
                .both()
                .project("id", "label", "name")
                .by(__.id_())
                .by(__.label())
                .by(__.coalesce(__.values("name"), __.values("rule_id"), __.constant("")))
                .toList()
            )

            # Outgoing dependencies
            out_deps = (
                g.V(vid)
                .outE("depends_on")
                .project("target_name", "dependency_type", "strength")
                .by(__.inV().coalesce(__.values("name"), __.values("rule_id")))
                .by(__.values("dependency_type"))
                .by(__.coalesce(__.values("strength"), __.constant(0)))
                .toList()
            )

            # Incoming dependencies
            in_deps = (
                g.V(vid)
                .inE("depends_on")
                .project("source_name", "dependency_type", "strength")
                .by(__.outV().coalesce(__.values("name"), __.values("rule_id")))
                .by(__.values("dependency_type"))
                .by(__.coalesce(__.values("strength"), __.constant(0)))
                .toList()
            )

            result = {
                "id": str(props["id"]),
                "label": props["label"],
                "properties": {k: _to_json_safe(v) for k, v in flat.items()},
                "neighbors": [
                    {"id": str(n["id"]), "label": n["label"], "name": n["name"]}
                    for n in neighbors
                ],
                "depends_on": [_to_json_safe(d) for d in out_deps],
                "depended_by": [_to_json_safe(d) for d in in_deps],
            }
        # Build rich frontend event with all detail data
        frontend_event = {
            "type": "vertex",
            "data": result,
            "graph_name": graph_name,
            "show_on_graph": function_args.get("show_on_graph", True),
        }
        llm_result = result
        return llm_result, frontend_event

    elif function_name == "find_related_rules":
        return _execute_find_related_rules(function_args)

    elif function_name == "get_graph_statistics":
        return _execute_get_graph_statistics()

    elif function_name == "compare_rules":
        return _execute_compare_rules(function_args)

    elif function_name == "find_dependency_path":
        return _execute_find_dependency_path(function_args)

    elif function_name == "get_source_reference":
        return _execute_get_source_reference(function_args)

    elif function_name == "get_review_status":
        return _execute_get_review_status(function_args)

    elif function_name == "cross_graph_search":
        return _execute_cross_graph_search(function_args)

    elif function_name == "search_knowledge_base":
        return _execute_search_knowledge_base(function_args)

    return {"error": f"Unknown tool: {function_name}"}, {"type": "error", "message": f"Unknown tool: {function_name}"}


def _execute_find_related_rules(function_args):
    """Compound tool: find a rule and return its full dependency neighborhood."""
    rule_name = function_args["rule_name"]
    show_on_graph = function_args.get("show_on_graph", True)
    graph_name = function_args.get("graph_name", "g")

    with get_traversal(graph_name) as (g, conn):
        # Try exact match first, then fallback to fuzzy (textContains)
        try:
            vid = g.V().has("name", rule_name).id_().next()
        except StopIteration:
            # Fuzzy: search by textContains on content or partial name match
            candidates = (
                g.V().hasLabel("business_rule")
                .has("content", TextP.containing(rule_name))
                .project("id", "name", "score")
                .by(__.id_())
                .by(__.values("name"))
                .by(__.values("confidence_score"))
                .limit(FUZZY_MATCH_MAX_CANDIDATES)
                .toList()
            )
            if not candidates:
                return (
                    {"error": f"No rule found matching: {rule_name}", "suggestion": "Try a semantic_search to find the correct rule name."},
                    {"type": "error", "message": f"No rule found matching: {rule_name}"},
                )
            vid = candidates[0]["id"]

        # Get the rule's full properties
        props = (
            g.V(vid)
            .project("id", "label", "props")
            .by(__.id_())
            .by(__.label())
            .by(__.valueMap(*ALL_VERTEX_PROPERTIES))
            .next()
        )
        flat = {
            k: val[0] if isinstance(val, list) and len(val) == 1 else val
            for k, val in props["props"].items()
        }

        # Get category
        category_name = None
        try:
            category_name = g.V(vid).out("belongs_to_category").values("name").next()
        except StopIteration:
            pass

        # Outgoing dependencies (this rule depends on)
        out_deps = (
            g.V(vid)
            .outE("depends_on")
            .project("target_id", "target_name", "dependency_type", "strength", "rationale")
            .by(__.inV().id_())
            .by(__.inV().coalesce(__.values("name"), __.values("rule_id")))
            .by(__.values("dependency_type"))
            .by(__.coalesce(__.values("strength"), __.constant(0)))
            .by(__.coalesce(__.values("rationale"), __.constant("")))
            .toList()
        )

        # Incoming dependencies (rules that depend on this one)
        in_deps = (
            g.V(vid)
            .inE("depends_on")
            .project("source_id", "source_name", "dependency_type", "strength", "rationale")
            .by(__.outV().id_())
            .by(__.outV().coalesce(__.values("name"), __.values("rule_id")))
            .by(__.values("dependency_type"))
            .by(__.coalesce(__.values("strength"), __.constant(0)))
            .by(__.coalesce(__.values("rationale"), __.constant("")))
            .toList()
        )

        # Rules in the same category
        sibling_rules = []
        if category_name:
            sibling_rules = (
                g.V().hasLabel("entity_category").has("name", category_name)
                .in_("belongs_to_category")
                .has("name", P.neq(flat.get("name", "")))
                .project("id", "name", "rule_type")
                .by(__.id_())
                .by(__.values("name"))
                .by(__.values("rule_type"))
                .limit(SIBLING_RULES_MAX_RESULTS)
                .toList()
            )

        result = {
            "rule": {
                "id": str(props["id"]),
                "label": props["label"],
                "name": flat.get("name", ""),
                "rule_id": flat.get("rule_id", ""),
                "rule_type": flat.get("rule_type", ""),
                "description": flat.get("description", ""),
                "content": flat.get("content", ""),
                "category": category_name or flat.get("category", ""),
                "entity_or_relationship": flat.get("entity_or_relationship", ""),
                "mandatory": flat.get("mandatory", False),
                "confidence_score": flat.get("confidence_score", 0),
                "conditions": flat.get("conditions", ""),
                "consequences": flat.get("consequences", ""),
                "exceptions": flat.get("exceptions", ""),
            },
            "depends_on": [_to_json_safe(d) for d in out_deps],
            "depended_by": [_to_json_safe(d) for d in in_deps],
            "same_category_rules": [_to_json_safe(s) for s in sibling_rules],
            "total_outgoing": len(out_deps),
            "total_incoming": len(in_deps),
        }

        # Build navigation targets
        nav_nodes = [{"id": str(props["id"]), "name": flat.get("name", ""), "label": props["label"]}]
        for d in out_deps:
            nav_nodes.append({"id": str(d["target_id"]), "name": d["target_name"], "label": "business_rule"})
        for d in in_deps:
            nav_nodes.append({"id": str(d["source_id"]), "name": d["source_name"], "label": "business_rule"})

        frontend_event = {
            "type": "related_rules",
            "data": result,
            "graph_name": graph_name,
            "show_on_graph": show_on_graph,
            "nodes": nav_nodes if show_on_graph else [],
        }
        return result, frontend_event


def _get_single_graph_statistics(graph_name: str):
    """Get statistics for a single graph."""
    with get_traversal(graph_name) as (g, conn):
        # Vertex count by label
        vertex_counts = g.V().groupCount().by(__.label()).next()

        # Edge count by label
        edge_counts = g.E().groupCount().by(__.label()).next()

        # Rule type distribution
        rule_types = g.V().hasLabel("business_rule").groupCount().by(__.values("rule_type")).next()

        # Dependency type distribution
        dep_types = g.E().hasLabel("depends_on").groupCount().by(__.values("dependency_type")).next()

        # Entity category distribution
        entity_cats = (
            g.V().hasLabel("entity_category")
            .project("name", "rule_count")
            .by(__.values("name"))
            .by(__.in_("belongs_to_category").count())
            .order().by(__.select("rule_count"), Order.desc)
            .toList()
        )

        # Confidence score distribution
        high_conf = g.V().hasLabel("business_rule").has("confidence_score", P.gt(90)).count().next()
        mid_conf = g.V().hasLabel("business_rule").has("confidence_score", P.inside(70, 90.01)).count().next()
        low_conf = g.V().hasLabel("business_rule").has("confidence_score", P.lte(70)).count().next()

        # Mandatory vs optional
        mandatory_count = g.V().hasLabel("business_rule").has("mandatory", True).count().next()
        review_count = g.V().hasLabel("business_rule").has("requires_review", True).count().next()

        # Risk level distribution (v2 KG)
        risk_levels = {}
        try:
            risk_levels = g.V().hasLabel("business_rule").has("risk_level", P.neq("")).groupCount().by(__.values("risk_level")).next()
            risk_levels = _to_json_safe(risk_levels)
        except Exception:
            pass

        # Jurisdiction distribution (v2 KG)
        jurisdictions = {}
        try:
            jurisdictions = g.V().hasLabel("business_rule").has("jurisdiction", P.neq("")).groupCount().by(__.values("jurisdiction")).next()
            jurisdictions = _to_json_safe(jurisdictions)
        except Exception:
            pass

        # Reference verification counts (v2 KG)
        ref_verified_count = 0
        ref_unverified_count = 0
        try:
            ref_verified_count = g.V().hasLabel("business_rule").has("reference_verified", True).count().next()
            ref_unverified_count = g.V().hasLabel("business_rule").has("reference_verified", False).count().next()
        except Exception:
            pass

        # Most connected rules
        hub_rules = (
            g.V().hasLabel("business_rule")
            .project("name", "total_deps")
            .by(__.values("name"))
            .by(__.bothE("depends_on").count())
            .order().by(__.select("total_deps"), Order.desc)
            .limit(STATS_HUB_RULES_LIMIT)
            .toList()
        )

        # Isolated rules (no dependencies)
        isolated = g.V().hasLabel("business_rule").where(__.bothE("depends_on").count().is_(0)).count().next()

        return {
            "vertex_counts": _to_json_safe(vertex_counts),
            "edge_counts": _to_json_safe(edge_counts),
            "rule_type_distribution": _to_json_safe(rule_types),
            "dependency_type_distribution": _to_json_safe(dep_types),
            "entity_categories": [_to_json_safe(c) for c in entity_cats],
            "confidence_distribution": {
                "high_above_90": high_conf,
                "medium_70_to_90": mid_conf,
                "low_below_70": low_conf,
            },
            "mandatory_rules": mandatory_count,
            "rules_requiring_review": review_count,
            "hub_rules_top_5": [_to_json_safe(h) for h in hub_rules],
            "isolated_rules_count": isolated,
            "risk_level_distribution": risk_levels,
            "jurisdiction_distribution": jurisdictions,
            "reference_verification": {
                "verified": ref_verified_count,
                "unverified": ref_unverified_count,
            },
        }


def _execute_get_graph_statistics():
    """Get comprehensive graph statistics for all loaded graphs."""
    from conf.graph_manifest import get_loaded_traversal_sources

    available_graphs = get_loaded_traversal_sources()
    graph_configs = get_graph_configs()  # keyed by traversal_source
    all_stats = {}

    # Get stats for each graph
    for graph_name in available_graphs:
        try:
            stats = _get_single_graph_statistics(graph_name)

            # Use display name from manifest, with fallback
            graph_display_name = graph_configs.get(graph_name, {}).get("name", graph_name)

            all_stats[graph_name] = {
                "name": graph_display_name,
                "statistics": stats
            }
        except Exception as e:
            _log("ERROR", f"Error getting stats for graph {graph_name}: {e}")
            all_stats[graph_name] = {
                "name": graph_name,
                "error": str(e)
            }
    
    # Create summary
    total_vertices = sum(
        sum(g["statistics"]["vertex_counts"].values()) 
        for g in all_stats.values() 
        if "statistics" in g
    )
    total_edges = sum(
        sum(g["statistics"]["edge_counts"].values()) 
        for g in all_stats.values() 
        if "statistics" in g
    )
    
    result = {
        "summary": {
            "total_graphs": len(all_stats),
            "total_vertices": total_vertices,
            "total_edges": total_edges,
        },
        "graphs": all_stats
    }
    
    frontend_event = {"type": "statistics", "data": result}
    return result, frontend_event


def _resolve_rule_vertex(g, rule_name: str):
    """Resolve a rule name to a vertex ID, trying exact then fuzzy match.

    Returns (vertex_id, actual_name) or raises StopIteration if not found.
    """
    try:
        vid = g.V().has("name", rule_name).id_().next()
        return vid, rule_name
    except StopIteration:
        candidates = (
            g.V().hasLabel("business_rule")
            .has("content", TextP.containing(rule_name))
            .project("id", "name")
            .by(__.id_())
            .by(__.values("name"))
            .limit(1)
            .toList()
        )
        if candidates:
            return candidates[0]["id"], candidates[0]["name"]
        raise StopIteration(f"No rule found matching: {rule_name}")


def _execute_compare_rules(function_args):
    """Compare 2+ rules side-by-side: properties, dependencies, overlap."""
    rule_names = function_args["rule_names"]
    graph_name = function_args.get("graph_name") or get_default_traversal_source()

    if len(rule_names) < 2:
        return (
            {"error": "At least 2 rule names are required for comparison"},
            {"type": "error", "message": "At least 2 rule names are required"},
        )

    rules_data = []
    nav_nodes = []

    with get_traversal(graph_name) as (g, conn):
        for rname in rule_names:
            try:
                vid, actual_name = _resolve_rule_vertex(g, rname)
            except StopIteration:
                rules_data.append({"name": rname, "error": f"Not found: {rname}"})
                continue

            props = (
                g.V(vid)
                .project("id", "label", "props")
                .by(__.id_())
                .by(__.label())
                .by(__.valueMap(*ALL_VERTEX_PROPERTIES))
                .next()
            )
            flat = {
                k: val[0] if isinstance(val, list) and len(val) == 1 else val
                for k, val in props["props"].items()
            }

            # Category
            category = None
            try:
                category = g.V(vid).out("belongs_to_category").values("name").next()
            except StopIteration:
                pass

            # Dependencies
            out_deps = (
                g.V(vid).outE("depends_on")
                .project("target_name", "dependency_type")
                .by(__.inV().coalesce(__.values("name"), __.values("rule_id")))
                .by(__.values("dependency_type"))
                .toList()
            )
            in_deps = (
                g.V(vid).inE("depends_on")
                .project("source_name", "dependency_type")
                .by(__.outV().coalesce(__.values("name"), __.values("rule_id")))
                .by(__.values("dependency_type"))
                .toList()
            )

            rules_data.append({
                "id": str(props["id"]),
                "name": flat.get("name", actual_name),
                "rule_id": flat.get("rule_id", ""),
                "rule_type": flat.get("rule_type", ""),
                "description": flat.get("description", ""),
                "category": category or flat.get("category", ""),
                "entity_or_relationship": flat.get("entity_or_relationship", ""),
                "mandatory": flat.get("mandatory", False),
                "confidence_score": flat.get("confidence_score", 0),
                "conditions": flat.get("conditions", ""),
                "consequences": flat.get("consequences", ""),
                "exceptions": flat.get("exceptions", ""),
                "jurisdiction": flat.get("jurisdiction", ""),
                "risk_level": flat.get("risk_level", ""),
                "depends_on": [_to_json_safe(d) for d in out_deps],
                "depended_by": [_to_json_safe(d) for d in in_deps],
                "total_dependencies": len(out_deps) + len(in_deps),
            })
            nav_nodes.append({"id": str(props["id"]), "name": flat.get("name", actual_name), "label": props["label"]})

    # Compute overlap analysis
    valid_rules = [r for r in rules_data if "error" not in r]
    overlap = {}
    if len(valid_rules) >= 2:
        # Shared dependencies (rules that multiple compared rules depend on)
        all_out_targets = [set(d["target_name"] for d in r.get("depends_on", [])) for r in valid_rules]
        shared_deps = set.intersection(*all_out_targets) if all_out_targets else set()

        # Shared dependents (rules that depend on multiple compared rules)
        all_in_sources = [set(d["source_name"] for d in r.get("depended_by", [])) for r in valid_rules]
        shared_dependents = set.intersection(*all_in_sources) if all_in_sources else set()

        # Same category?
        categories = [r.get("category", "") for r in valid_rules]
        same_category = len(set(c for c in categories if c)) <= 1

        # Same entity?
        entities = [r.get("entity_or_relationship", "") for r in valid_rules]
        same_entity = len(set(e for e in entities if e)) <= 1

        overlap = {
            "shared_dependencies": list(shared_deps),
            "shared_dependents": list(shared_dependents),
            "same_category": same_category,
            "same_entity": same_entity,
            "categories": list(set(c for c in categories if c)),
            "entities": list(set(e for e in entities if e)),
        }

    result = {
        "rules": rules_data,
        "overlap_analysis": overlap,
        "graph_name": graph_name,
    }
    frontend_event = {
        "type": "compare",
        "data": result,
        "graph_name": graph_name,
        "nodes": nav_nodes,
    }
    return result, frontend_event


def _execute_find_dependency_path(function_args):
    """Find dependency path(s) between two rules."""
    from_rule = function_args["from_rule"]
    to_rule = function_args["to_rule"]
    max_depth = min(int(function_args.get("max_depth", 6)), 10)
    graph_name = function_args.get("graph_name") or get_default_traversal_source()

    with get_traversal(graph_name) as (g, conn):
        # Resolve both rule names
        try:
            from_vid, from_name = _resolve_rule_vertex(g, from_rule)
        except StopIteration:
            return (
                {"error": f"Source rule not found: {from_rule}", "suggestion": "Try semantic_search to find the correct name."},
                {"type": "error", "message": f"Source rule not found: {from_rule}"},
            )
        try:
            to_vid, to_name = _resolve_rule_vertex(g, to_rule)
        except StopIteration:
            return (
                {"error": f"Target rule not found: {to_rule}", "suggestion": "Try semantic_search to find the correct name."},
                {"type": "error", "message": f"Target rule not found: {to_rule}"},
            )

        if from_vid == to_vid:
            return (
                {"error": "Source and target are the same rule", "from_rule": from_name, "to_rule": to_name},
                {"type": "error", "message": "Source and target are the same rule"},
            )

        # Find paths using repeat/until with both() to traverse in either direction
        try:
            raw_paths = (
                g.V(from_vid)
                .repeat(__.both("depends_on").simplePath())
                .until(__.hasId(to_vid).or_().loops().is_(P.gte(max_depth)))
                .hasId(to_vid)
                .path()
                .by(__.project("id", "name", "rule_type")
                    .by(__.id_())
                    .by(__.coalesce(__.values("name"), __.values("rule_id"), __.constant("?")))
                    .by(__.coalesce(__.values("rule_type"), __.constant(""))))
                .limit(5)
                .toList()
            )
        except Exception:
            raw_paths = []

        # Process paths
        paths = []
        nav_nodes = []
        seen_ids = set()
        for raw_path in raw_paths:
            path_steps = []
            for step in raw_path:
                step_data = _to_json_safe(step)
                path_steps.append(step_data)
                sid = str(step_data.get("id", ""))
                if sid and sid not in seen_ids:
                    seen_ids.add(sid)
                    nav_nodes.append({"id": sid, "name": step_data.get("name", ""), "label": "business_rule"})
            paths.append(path_steps)

        # Also get edge details for the shortest path
        edge_details = []
        if paths:
            shortest = paths[0]
            for i in range(len(shortest) - 1):
                src_id = shortest[i].get("id")
                tgt_id = shortest[i + 1].get("id")
                if src_id and tgt_id:
                    try:
                        edge_info = (
                            g.V(src_id).bothE("depends_on")
                            .where(__.otherV().hasId(tgt_id))
                            .project("dependency_type", "strength", "direction")
                            .by(__.values("dependency_type"))
                            .by(__.coalesce(__.values("strength"), __.constant(0)))
                            .by(__.choose(
                                __.outV().hasId(src_id),
                                __.constant("outgoing"),
                                __.constant("incoming")
                            ))
                            .next()
                        )
                        edge_details.append(_to_json_safe(edge_info))
                    except (StopIteration, Exception):
                        edge_details.append({"dependency_type": "unknown", "strength": 0, "direction": "unknown"})

        result = {
            "from_rule": from_name,
            "to_rule": to_name,
            "paths_found": len(paths),
            "paths": paths,
            "shortest_path_length": len(paths[0]) - 1 if paths else None,
            "edge_details": edge_details,
            "graph_name": graph_name,
        }

        if not paths:
            result["message"] = f"No dependency path found between '{from_name}' and '{to_name}' within {max_depth} hops."

        frontend_event = {
            "type": "dependency_path",
            "data": result,
            "graph_name": graph_name,
            "nodes": nav_nodes,
        }
        return result, frontend_event


def _execute_get_source_reference(function_args):
    """Look up the source document text backing a specific rule."""
    rule_name = function_args["rule_name"]
    graph_name = function_args.get("graph_name") or get_default_traversal_source()

    with get_traversal(graph_name) as (g, conn):
        # Resolve rule name
        try:
            vid, actual_name = _resolve_rule_vertex(g, rule_name)
        except StopIteration:
            return (
                {"error": f"Rule not found: {rule_name}", "suggestion": "Try semantic_search to find the correct name."},
                {"type": "error", "message": f"Rule not found: {rule_name}"},
            )

        # Get reference properties
        props = (
            g.V(vid)
            .project("name", "reference", "source_reference", "rule_id")
            .by(__.coalesce(__.values("name"), __.constant("")))
            .by(__.coalesce(__.values("reference"), __.constant("")))
            .by(__.coalesce(__.values("source_reference"), __.constant("")))
            .by(__.coalesce(__.values("rule_id"), __.constant("")))
            .next()
        )

    reference = props.get("reference", "")
    source_reference_raw = props.get("source_reference", "")

    # Parse source_reference if it's JSON
    source_ref_obj = None
    if source_reference_raw:
        try:
            source_ref_obj = json.loads(source_reference_raw) if isinstance(source_reference_raw, str) else source_reference_raw
        except (json.JSONDecodeError, TypeError):
            pass

    # Resolve docs folder
    docs_folder = get_docs_folder(graph_name)
    if not docs_folder or not os.path.isdir(docs_folder):
        return (
            {
                "rule_name": actual_name,
                "reference": reference,
                "source_reference": source_reference_raw,
                "error": f"No docs folder configured for graph '{graph_name}'",
            },
            {"type": "source_reference", "data": {"error": "No docs folder"}},
        )

    # Build chunk index and resolve
    chunk_index = _build_chunk_index(docs_folder)

    # Try structured source_reference first
    resolved_chunks = []
    if source_ref_obj:
        items = source_ref_obj if isinstance(source_ref_obj, list) else [source_ref_obj]
        for sr_item in items:
            if not isinstance(sr_item, dict):
                continue
            chunk_path = sr_item.get("chunk_path", "")
            if chunk_path:
                for entry in chunk_index:
                    if entry["path"].endswith(chunk_path) or chunk_path.endswith(entry["path"]):
                        # Read chunk content
                        abs_path = os.path.normpath(os.path.join(docs_folder, entry["path"]))
                        try:
                            with open(abs_path, "r", encoding="utf-8") as f:
                                chunk_text = f.read()
                            # Truncate for LLM context
                            if len(chunk_text) > 3000:
                                chunk_text = chunk_text[:3000] + "\n\n[… truncated — full document available via reference viewer]"
                            resolved_chunks.append({
                                "title": entry["title"],
                                "chunk_id": entry["chunk_id"],
                                "path": entry["path"],
                                "text": chunk_text,
                                "source_text": sr_item.get("source_text", ""),
                                "section_id": sr_item.get("section_id", ""),
                                "start_word_position": sr_item.get("start_word_position"),
                                "end_word_position": sr_item.get("end_word_position"),
                            })
                        except Exception:
                            pass
                        break

    # Fallback to reference string matching
    if not resolved_chunks and reference:
        matches = _match_reference(reference, chunk_index)
        for m in matches[:2]:  # Top 2 matches
            abs_path = os.path.normpath(os.path.join(docs_folder, m["path"]))
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    chunk_text = f.read()
                if len(chunk_text) > 3000:
                    chunk_text = chunk_text[:3000] + "\n\n[… truncated — full document available via reference viewer]"
                resolved_chunks.append({
                    "title": m["title"],
                    "chunk_id": m["chunk_id"],
                    "path": m["path"],
                    "text": chunk_text,
                })
            except Exception:
                pass

    result = {
        "rule_name": actual_name,
        "rule_id": props.get("rule_id", ""),
        "reference": reference,
        "source_reference": source_reference_raw,
        "resolved_chunks": resolved_chunks,
        "chunks_found": len(resolved_chunks),
    }

    if not resolved_chunks:
        result["message"] = f"No source document chunks could be resolved for reference: {reference or '(empty)'}"

    frontend_event = {
        "type": "source_reference",
        "data": result,
        "graph_name": graph_name,
    }
    return result, frontend_event


def _execute_get_review_status(function_args):
    """Get review/approval/annotation status across rules."""
    status_filter = function_args.get("filter", "all")
    graph_name = function_args.get("graph_name") or get_default_traversal_source()

    # Query all annotations from SQLite
    session = SessionLocal()
    try:
        query = session.query(NodeAnnotation).filter(
            NodeAnnotation.deleted.is_(False) | NodeAnnotation.deleted.is_(None)
        )
        all_annotations = query.all()
    finally:
        session.close()

    # Cross-reference with graph vertices to get rule names
    vertex_names = {}
    try:
        with get_traversal(graph_name) as (g, conn):
            for ann in all_annotations:
                nid = ann.node_id
                if nid and nid.isdigit():
                    try:
                        name = g.V(int(nid)).values("name").next()
                        vertex_names[nid] = name
                    except (StopIteration, Exception):
                        pass
    except Exception:
        pass

    # Categorize annotations
    reviewed_rules = []
    approved_rules = []
    needs_review = []
    needs_approval = []
    commented_rules = []

    for ann in all_annotations:
        nid = ann.node_id
        rule_name = vertex_names.get(nid, f"vertex:{nid}")
        entry = {
            "node_id": nid,
            "rule_name": rule_name,
            "reviewed": ann.reviewed,
            "approved": ann.approved,
        }

        # Parse comments
        comments = []
        if ann.comments_json:
            try:
                comments = json.loads(ann.comments_json)
            except (json.JSONDecodeError, TypeError):
                pass
        entry["comment_count"] = len(comments)
        if comments:
            entry["latest_comment"] = comments[-1] if isinstance(comments[-1], dict) else {"text": str(comments[-1])}

        # Parse edits
        has_edits = False
        if ann.edits_json:
            try:
                edits = json.loads(ann.edits_json)
                has_edits = bool(edits.get("name") or edits.get("content"))
            except (json.JSONDecodeError, TypeError):
                pass
        entry["has_edits"] = has_edits

        if ann.reviewed == "yes":
            reviewed_rules.append(entry)
        elif ann.reviewed != "yes":
            needs_review.append(entry)

        if ann.approved == "yes":
            approved_rules.append(entry)
        elif ann.approved != "yes":
            needs_approval.append(entry)

        if comments:
            commented_rules.append(entry)

    # Apply filter
    if status_filter == "reviewed":
        filtered = reviewed_rules
    elif status_filter == "approved":
        filtered = approved_rules
    elif status_filter == "needs_review":
        filtered = needs_review
    elif status_filter == "needs_approval":
        filtered = needs_approval
    elif status_filter == "commented":
        filtered = commented_rules
    else:
        filtered = None  # Return summary for "all"

    # Build open tasks summary
    pending_tasks = [t for t in _TASKS if t.get("status") == "pending"]

    result = {
        "summary": {
            "total_annotated_rules": len(all_annotations),
            "reviewed": len(reviewed_rules),
            "approved": len(approved_rules),
            "needs_review": len(needs_review),
            "needs_approval": len(needs_approval),
            "with_comments": len(commented_rules),
            "pending_tasks": len(pending_tasks),
        },
        "graph_name": graph_name,
    }

    if filtered is not None:
        result["filtered_rules"] = filtered[:20]  # Cap at 20 for LLM context
        result["filter_applied"] = status_filter
        result["total_matching"] = len(filtered)
    else:
        # For "all", include top-level summaries with sample rules
        result["recently_reviewed"] = reviewed_rules[:5]
        result["recently_approved"] = approved_rules[:5]
        result["recent_comments"] = commented_rules[:5]
        result["open_tasks"] = [
            {"id": t["id"], "title": t["title"], "type": t["type"], "priority": t.get("priority", ""), "assignee": t.get("assignee", "")}
            for t in pending_tasks[:10]
        ]

    frontend_event = {"type": "review_status", "data": result, "graph_name": graph_name}
    return result, frontend_event


def _cross_graph_semantic(query: str, top_k: int, available_graphs: list, graph_configs: dict) -> list:
    """Run semantic search across all graphs and return enriched results."""
    results = []
    for gname in available_graphs:
        display_name = graph_configs.get(gname, {}).get("name", gname)
        try:
            hits = _engine.search(query, top_k=top_k, graph_name=gname)
            with get_traversal(gname) as (g, conn):
                for r in hits:
                    try:
                        vp = (
                            g.V().has("name", r["name"])
                            .project("id", "rule_type", "confidence_score", "description",
                                     "risk_level", "mandatory", "entity_or_relationship", "dep_count")
                            .by(__.id_())
                            .by(__.coalesce(__.values("rule_type"), __.constant("")))
                            .by(__.coalesce(__.values("confidence_score"), __.constant(0)))
                            .by(__.coalesce(__.values("description"), __.constant("")))
                            .by(__.coalesce(__.values("risk_level"), __.constant("")))
                            .by(__.coalesce(__.values("mandatory"), __.constant(False)))
                            .by(__.coalesce(__.values("entity_or_relationship"), __.constant("")))
                            .by(__.bothE("depends_on").count())
                            .next()
                        )
                        r.update({
                            "id": str(vp["id"]),
                            "rule_type": vp["rule_type"],
                            "confidence_score": vp["confidence_score"],
                            "description": vp["description"],
                            "risk_level": vp["risk_level"],
                            "mandatory": vp["mandatory"],
                            "entity_or_relationship": vp["entity_or_relationship"],
                            "dependency_count": vp["dep_count"],
                        })
                    except Exception:
                        r["id"] = None
                    r["graph_name"] = gname
                    r["graph_display_name"] = display_name
                    r["search_method"] = "semantic"
            results.extend(hits)
        except Exception as exc:
            _log("WARN", f"Cross-graph semantic search failed for {gname}: {exc}")
    return results


def _cross_graph_text(query: str, top_k: int, available_graphs: list, graph_configs: dict) -> list:
    """Run text search across all graphs and return enriched results."""
    # Split query into terms for broader OR-style matching when multi-word
    terms = [t.strip() for t in query.split() if len(t.strip()) > 2]
    results = []
    for gname in available_graphs:
        display_name = graph_configs.get(gname, {}).get("name", gname)
        try:
            with get_traversal(gname) as (g, conn):
                # Try full phrase first; fall back to first significant term
                t = g.V().hasLabel("business_rule").has("content", TextP.containing(query))
                raw = (
                    t.project("id", "name", "rule_type", "content", "description",
                               "confidence_score", "risk_level", "mandatory", "dep_count")
                    .by(__.id_())
                    .by(__.values("name"))
                    .by(__.coalesce(__.values("rule_type"), __.constant("")))
                    .by(__.values("content"))
                    .by(__.coalesce(__.values("description"), __.constant("")))
                    .by(__.coalesce(__.values("confidence_score"), __.constant(0)))
                    .by(__.coalesce(__.values("risk_level"), __.constant("")))
                    .by(__.coalesce(__.values("mandatory"), __.constant(False)))
                    .by(__.bothE("depends_on").count())
                    .limit(top_k)
                    .toList()
                )
                # If full-phrase returns nothing and query is multi-word, try lead term
                if not raw and terms:
                    raw = (
                        g.V().hasLabel("business_rule")
                        .has("content", TextP.containing(terms[0]))
                        .project("id", "name", "rule_type", "content", "description",
                                  "confidence_score", "risk_level", "mandatory", "dep_count")
                        .by(__.id_())
                        .by(__.values("name"))
                        .by(__.coalesce(__.values("rule_type"), __.constant("")))
                        .by(__.values("content"))
                        .by(__.coalesce(__.values("description"), __.constant("")))
                        .by(__.coalesce(__.values("confidence_score"), __.constant(0)))
                        .by(__.coalesce(__.values("risk_level"), __.constant("")))
                        .by(__.coalesce(__.values("mandatory"), __.constant(False)))
                        .by(__.bothE("depends_on").count())
                        .limit(top_k)
                        .toList()
                    )
                for r in raw:
                    results.append({
                        "id": str(r["id"]),
                        "name": r["name"],
                        "rule_type": r["rule_type"],
                        "content": r["content"][:400],
                        "description": r["description"],
                        "confidence_score": r["confidence_score"],
                        "risk_level": r["risk_level"],
                        "mandatory": r["mandatory"],
                        "dependency_count": r["dep_count"],
                        "graph_name": gname,
                        "graph_display_name": display_name,
                        "search_method": "text",
                        "similarity": float(r["confidence_score"]) / 100.0,
                    })
        except Exception as exc:
            _log("WARN", f"Cross-graph text search failed for {gname}: {exc}")
    return results


def _execute_cross_graph_search(function_args):
    """Search across all loaded knowledge graphs simultaneously.

    Supports mode='semantic'|'text'|'both'. 'both' runs both search types,
    deduplicates by rule name, and ranks by best similarity score for maximum
    recall. include_kb=True also searches KB source document chunks.
    """
    query = function_args["query"]
    mode = function_args.get("mode") or function_args.get("search_type", "both")
    top_k = int(function_args.get("top_k", 8))
    include_kb = bool(function_args.get("include_kb", False))

    available_graphs = get_loaded_traversal_sources()
    graph_configs = get_graph_configs()

    all_results: list = []

    if mode in ("semantic", "both"):
        all_results.extend(_cross_graph_semantic(query, top_k, available_graphs, graph_configs))

    if mode in ("text", "both"):
        all_results.extend(_cross_graph_text(query, top_k, available_graphs, graph_configs))

    # Deduplicate: keep best similarity score per (graph_name, rule_name) pair
    seen: dict = {}
    deduped: list = []
    for r in all_results:
        key = (r.get("graph_name", ""), r.get("name", ""))
        sim = float(r.get("similarity", 0))
        if key not in seen or sim > seen[key]:
            seen[key] = sim
            deduped.append(r)
        else:
            # Update similarity on existing entry if this one is higher
            for existing in deduped:
                if (existing.get("graph_name") == key[0] and existing.get("name") == key[1]):
                    if sim > float(existing.get("similarity", 0)):
                        existing.update(r)
                    break

    # Sort: primary by similarity descending, secondary by confidence_score
    deduped.sort(key=lambda r: (float(r.get("similarity", 0)), float(r.get("confidence_score", 0))), reverse=True)

    # Per-graph result summary
    per_graph: dict = {}
    for r in deduped:
        gname = r.get("graph_name", "")
        if gname not in per_graph:
            per_graph[gname] = {"display_name": r.get("graph_display_name", gname), "count": 0}
        per_graph[gname]["count"] += 1

    # Optional KB document search
    kb_results: list = []
    if include_kb:
        kb_args = {"query": query, "top_k": min(top_k, 10)}
        kb_result, _ = _execute_search_knowledge_base(kb_args)
        kb_results = kb_result.get("results", [])

    result = {
        "query": query,
        "mode": mode,
        "total_results": len(deduped),
        "per_graph_summary": per_graph,
        "results": deduped,
        **({"kb_results": kb_results, "kb_total": len(kb_results)} if include_kb else {}),
    }
    frontend_event = {
        "type": "cross_graph_search",
        "data": result,
        "nodes": deduped,
    }
    return result, frontend_event


def _execute_search_knowledge_base(function_args):
    """Search source KB documents (regulatory text chunks) across all graphs.

    Uses keyword matching against chunk titles and content. Returns ranked
    chunks with title, content excerpts, and source attribution.
    """
    query = function_args["query"]
    graph_name_filter = function_args.get("graph_name")
    top_k = int(function_args.get("top_k", 10))

    query_lower = query.lower().strip()
    query_terms = [t for t in re.sub(r"[^\w\s]", " ", query_lower).split() if len(t) > 2]

    graph_configs = get_graph_configs()
    graphs_to_search = [graph_name_filter] if graph_name_filter else get_loaded_traversal_sources()

    all_results: list = []

    for gname in graphs_to_search:
        docs_folder = get_docs_folder(gname)
        if not docs_folder or not os.path.isdir(docs_folder):
            continue
        display_name = graph_configs.get(gname, {}).get("name", gname)
        try:
            entries = _build_kb_text_index(docs_folder, gname)
            for entry in entries:
                searchable = (entry["title"] + " " + entry["content_snippet"]).lower()

                # Exact phrase match scores highest
                if query_lower in searchable:
                    freq = searchable.count(query_lower)
                    score = 100.0 + freq * 5.0
                elif query_terms:
                    # Partial: count how many terms hit, weighted by frequency
                    hit_count = sum(1 for t in query_terms if t in searchable)
                    if hit_count == 0:
                        continue
                    freq_sum = sum(searchable.count(t) for t in query_terms if t in searchable)
                    score = (hit_count / len(query_terms)) * 80.0 + min(freq_sum, 10) * 1.5
                else:
                    continue

                # Boost for title match
                if query_lower in entry["title"].lower():
                    score += 15.0
                elif any(t in entry["title"].lower() for t in query_terms):
                    score += 8.0

                all_results.append({
                    "title":           entry["title"],
                    "chunk_id":        entry.get("chunk_id", ""),
                    "path":            entry["path"],
                    "content_snippet": entry["content_snippet"][:500],
                    "graph_name":      gname,
                    "graph_display_name": display_name,
                    "relevance_score": round(score, 2),
                })
        except Exception as exc:
            _log("WARN", f"KB search failed for {gname}: {exc}")

    all_results.sort(key=lambda r: r["relevance_score"], reverse=True)
    all_results = all_results[:top_k]

    result = {
        "query":         query,
        "total_results": len(all_results),
        "results":       all_results,
    }
    frontend_event = {
        "type":  "kb_search",
        "query": query,
        "nodes": all_results,
    }
    return result, frontend_event


@app.route("/api/chat", methods=["POST"])
def chat():
    """Explorer chatbot (non-streaming fallback)."""
    body = request.get_json(silent=True) or {}
    user_message = body.get("message", "").strip()
    conversation_history = body.get("history", [])
    active_graph = (body.get("active_graph") or "").strip() or None

    if not user_message:
        return jsonify({"error": "message field is required"}), 400

    try:
        messages = [{"role": "system", "content": _build_chat_system_prompt(active_graph)}]
        for msg in conversation_history:
            if msg.get("role") in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        _re_kwargs = {"reasoning_effort": OPENAI_REASONING_EFFORT} if supports_reasoning_effort(OPENAI_CHAT_MODEL) else {}
        response = _openai_client.chat.completions.create(
            model=OPENAI_CHAT_MODEL, messages=messages,
            tools=_build_chat_tools(), tool_choice="auto",
            **_re_kwargs,
        )
        _log_cache_usage(response)
        assistant_message = response.choices[0].message
        tool_calls = assistant_message.tool_calls

        tool_results = []
        if tool_calls:
            messages.append(assistant_message)
            for tc in tool_calls:
                fn_name = tc.function.name
                fn_args = json.loads(tc.function.arguments)
                _log("INFO", f"Tool call: {fn_name} with args {fn_args}")
                llm_result, frontend_event = _execute_chat_tool(fn_name, fn_args)
                tool_results.append(frontend_event)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(llm_result),
                })
            final_response = _openai_client.chat.completions.create(
                model=OPENAI_CHAT_MODEL, messages=messages,
                **_re_kwargs,
            )
            _log_cache_usage(final_response)
            final_content = _extract_answer(final_response.choices[0].message.content or "")
            return jsonify({
                "message": final_content,
                "tool_results": tool_results,
            })

        content = _extract_answer(assistant_message.content or "")
        return jsonify({"message": content, "tool_results": []})

    except Exception as exc:
        _log("ERROR", f"Chat failed: {exc}")
        return jsonify({"error": str(exc)}), 500


def _sse(event: str, data: dict) -> str:
    """Format a server-sent event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


_ANSWER_MARKER = "|||ANSWER_START|||"


def _extract_answer(text: str) -> str:
    """Strip any thinking/reasoning tokens that precede the answer marker."""
    idx = text.find(_ANSWER_MARKER)
    if idx != -1:
        return text[idx + len(_ANSWER_MARKER):].lstrip("\n")
    return text


def _describe_plan(tool_calls) -> str:
    """Generate a human-readable execution plan from detected tool calls."""
    steps = []
    for tc in tool_calls:
        name = tc.function.name
        args = json.loads(tc.function.arguments)
        if name == "semantic_search":
            steps.append(f'Semantic search for "{args.get("query", "")}"')
        elif name == "text_search":
            steps.append(f'Text search for "{args.get("query", "")}"')
        elif name == "execute_gremlin":
            q = args.get("query", "")
            if "count" in q.lower():
                steps.append("Run aggregation query on graph")
            elif "order" in q.lower() and "desc" in q.lower():
                steps.append("Run ranking query on graph")
            elif "groupCount" in q:
                steps.append("Run grouping/distribution query on graph")
            elif "repeat" in q.lower() or "path" in q.lower():
                steps.append("Trace dependency paths in graph")
            else:
                steps.append("Execute graph traversal query")
        elif name == "get_graph_data":
            steps.append("Load full graph for visualization")
        elif name == "get_vertex_details":
            steps.append(f'Retrieve details for vertex "{args.get("vertex_id", "")}"')
        elif name == "find_related_rules":
            steps.append(f'Find related rules for "{args.get("rule_name", "")}"')
        elif name == "get_graph_statistics":
            steps.append("Gather graph statistics and metrics")
    return " → ".join(steps) if steps else "Processing request"


@app.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """Explorer chatbot with SSE streaming and process visibility."""
    body = request.get_json(silent=True) or {}
    user_message = body.get("message", "").strip()
    history = body.get("history", [])
    active_graph = (body.get("active_graph") or "").strip() or None

    if not user_message:
        return jsonify({"error": "message field is required"}), 400

    def generate():
        messages = [{"role": "system", "content": _build_chat_system_prompt(active_graph)}]
        for msg in history:
            if msg.get("role") in ("user", "assistant"):
                messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        navigate_targets = []  # Collect nodes to navigate to on graph
        node_refs = {}  # name -> {id, name, label} for clickable references
        names_without_ids = set()  # names needing batch lookup

        try:
            round_num = 0
            while round_num < MAX_TOOL_ROUNDS:
                round_num += 1

                # ── Analyze and decide next action ──
                if round_num == 1:
                    yield _sse("step", {"label": "Analyzing your question", "status": "active"})
                else:
                    yield _sse("step", {"label": f"Deeper analysis (round {round_num})", "status": "active"})

                _re_kwargs = {"reasoning_effort": OPENAI_REASONING_EFFORT} if supports_reasoning_effort(OPENAI_CHAT_MODEL) else {}
                response = _openai_client.chat.completions.create(
                    model=OPENAI_CHAT_MODEL, messages=messages,
                    tools=_build_chat_tools(), tool_choice="auto",
                    **_re_kwargs,
                )
                _log_cache_usage(response)
                assistant_msg = response.choices[0].message
                tool_calls = assistant_msg.tool_calls

                if round_num == 1:
                    yield _sse("step", {"label": "Analyzing your question", "status": "done"})
                else:
                    yield _sse("step", {"label": f"Deeper analysis (round {round_num})", "status": "done"})

                if not tool_calls:
                    # No more tools needed — model is ready to answer directly
                    content = _extract_answer(assistant_msg.content or "")
                    if content:
                        yield _sse("token", {"content": content})
                    break

                # ── Show execution plan ──
                plan = _describe_plan(tool_calls)
                if round_num > 1:
                    plan = f"Follow-up: {plan}"
                yield _sse("thinking", {"content": plan})

                # ── Execute tools with process visibility ──
                messages.append(assistant_msg)

                for tc in tool_calls:
                    fn_name = tc.function.name
                    fn_args = json.loads(tc.function.arguments)
                    _log("INFO", f"Stream tool call (round {round_num}): {fn_name} with args {fn_args}")

                    yield _sse("tool_call", {"name": fn_name, "args": fn_args})

                    try:
                        llm_result, frontend_event = _execute_chat_tool(fn_name, fn_args)
                    except Exception as e:
                        _log("ERROR", f"Tool {fn_name} failed: {e}")
                        llm_result = {"error": str(e)}
                        frontend_event = {"type": "error", "message": str(e)}

                    yield _sse("tool_result", frontend_event)

                    # Collect node references for clickable links
                    _collect_node_refs(frontend_event, node_refs, names_without_ids)

                    # Track vertex details for graph navigation
                    if frontend_event.get("type") == "vertex" and frontend_event.get("show_on_graph"):
                        vdata = frontend_event.get("data", {})
                        navigate_targets.append({
                            "id": vdata.get("id"),
                            "name": vdata.get("properties", {}).get("name", ""),
                            "label": vdata.get("label", ""),
                            "graph_name": frontend_event.get("graph_name", ""),
                        })

                    # Track related_rules navigate targets
                    if frontend_event.get("type") == "related_rules" and frontend_event.get("show_on_graph"):
                        for node in frontend_event.get("nodes", []):
                            if node.get("id"):
                                navigate_targets.append({
                                    "id": node["id"],
                                    "name": node.get("name", ""),
                                    "label": node.get("label", ""),
                                    "graph_name": frontend_event.get("graph_name", node.get("graph_name", "")),
                                })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(llm_result),
                    })

                # Continue loop — model gets another chance to call more tools
                # or produce a final answer

            # Batch-lookup IDs for names discovered without IDs
            remaining = names_without_ids - set(node_refs.keys())
            if remaining:
                try:
                    looked_up = _lookup_vertex_ids_by_names(list(remaining))
                    node_refs.update(looked_up)
                except Exception:
                    pass

            # Emit node references so frontend can linkify the response
            if node_refs:
                yield _sse("node_references", {"references": node_refs})

            # Emit navigate events for any vertex results that should show on graph
            for target in navigate_targets:
                if target.get("id"):
                    yield _sse("navigate", target)

            # ── Final synthesis (if loop ended because model used all rounds) ──
            # If the last round had tool calls, we need a final synthesis pass
            if tool_calls:
                yield _sse("step", {"label": "Reasoning and composing answer", "status": "active"})

                stream = _openai_client.chat.completions.create(
                    model=OPENAI_CHAT_MODEL, messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                    **_re_kwargs,
                )

                # Buffer until answer marker found; discard thinking tokens
                _buf: list = []
                _marker_found = False
                _stream_usage = None
                for chunk in stream:
                    if getattr(chunk, 'usage', None):
                        _stream_usage = chunk
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        if _marker_found:
                            yield _sse("token", {"content": delta.content})
                        else:
                            _buf.append(delta.content)
                            _joined = "".join(_buf)
                            _idx = _joined.find(_ANSWER_MARKER)
                            if _idx != -1:
                                _marker_found = True
                                _after = _joined[_idx + len(_ANSWER_MARKER):].lstrip("\n")
                                if _after:
                                    yield _sse("token", {"content": _after})
                                _buf = []
                # Flush remaining buffer if marker was never found —
                # strip any thinking preamble just in case
                if not _marker_found and _buf:
                    _final = "".join(_buf)
                    yield _sse("token", {"content": _extract_answer(_final)})

                if _stream_usage:
                    _log_cache_usage(_stream_usage)

                yield _sse("step", {"label": "Reasoning and composing answer", "status": "done"})

            yield _sse("done", {})

        except Exception as e:
            _log("ERROR", f"Chat stream failed: {e}")
            yield _sse("error", {"message": str(e)})

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Admin: Force Clean / Rebuild / Consistency ───────────────────

@app.route("/api/admin/reset", methods=["POST"])
def admin_force_reset():
    """Force-clean and rebuild all data stores.

    Body (JSON, all optional):
        scope: "all" (default) | "graphs" | "embeddings" | "sqlite"
        confirm: must be true to proceed

    This endpoint is DESTRUCTIVE — it clears data and rebuilds from
    the KG JSON files.  Existing annotations, releases, and lock
    states in SQLite will be lost when scope includes 'sqlite' or 'all'.
    """
    data = request.get_json(silent=True) or {}
    if not data.get("confirm"):
        return jsonify({"error": "Set 'confirm': true in the request body to proceed"}), 400

    scope = data.get("scope", "all")
    report: dict = {"scope": scope, "steps": []}

    try:
        from src.schema import create_schema
        from src.data_loader import clear_all_graphs, load_all_graphs

        if scope in ("all", "sqlite"):
            # Re-create SQLite tables (drops and recreates)
            from src.models import Base, engine as _db_engine
            Base.metadata.drop_all(_db_engine)
            Base.metadata.create_all(_db_engine)
            report["steps"].append("SQLite database reset (annotations, releases, lock states)")

        if scope in ("all", "graphs"):
            create_schema()
            report["steps"].append("Graph schema ensured")
            clear_all_graphs()
            report["steps"].append("All graphs cleared")
            load_all_graphs()
            report["steps"].append("All knowledge graphs reloaded from KG files")

        if scope in ("all", "embeddings", "graphs"):
            _engine.delete_index()
            _engine.index_all_graph_embeddings()
            report["steps"].append("Embedding index rebuilt")

        # Re-resolve tasks after data reload
        try:
            _resolve_task_node_ids()
            resolved = sum(1 for t in _TASKS if t.get("node_id"))
            report["steps"].append(f"Tasks re-resolved: {resolved}/{len(_TASKS)} linked")
        except Exception as exc:
            report["steps"].append(f"Task resolution failed: {exc}")

        # Run consistency checks
        consistency = _run_consistency_checks()
        report["consistency"] = consistency

        _log("INFO", f"Force reset complete (scope={scope}): {len(report['steps'])} steps")
        return jsonify({"ok": True, "report": report})

    except Exception as exc:
        _log("ERROR", f"Force reset failed: {exc}")
        return jsonify({"error": str(exc), "report": report}), 500


@app.route("/api/admin/consistency")
def admin_consistency_check():
    """Run consistency checks across all data stores and return a report.

    Checks:
      - Graph vertex/edge counts per graph
      - Embedding count vs vertex count per graph
      - Task node_id resolution status
      - Orphaned annotations (SQLite rows referencing missing vertices)
      - Reference → chunk resolution coverage
    """
    try:
        report = _run_consistency_checks()
        return jsonify({"ok": True, "report": report})
    except Exception as exc:
        _log("ERROR", f"Consistency check failed: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/admin/rebuild-embeddings", methods=["POST"])
def admin_rebuild_embeddings():
    """Force-rebuild the OpenSearch embedding index for all graphs.

    Body (JSON, optional):
        graph_name: rebuild only this graph (default: all)
    """
    data = request.get_json(silent=True) or {}
    graph_name = data.get("graph_name")
    try:
        if graph_name:
            count = _engine.index_graph_embeddings(graph_name)
            _log("INFO", f"Rebuilt embeddings for '{graph_name}': {count} docs")
            return jsonify({"ok": True, "graph_name": graph_name, "embeddings": count})
        else:
            _engine.delete_index()
            total = _engine.index_all_graph_embeddings()
            _log("INFO", f"Rebuilt all embeddings: {total} docs")
            return jsonify({"ok": True, "total_embeddings": total})
    except Exception as exc:
        _log("ERROR", f"Embedding rebuild failed: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/admin/rebuild-tasks", methods=["POST"])
def admin_rebuild_tasks():
    """Re-resolve task node IDs from the live graph."""
    try:
        _resolve_task_node_ids()
        resolved = sum(1 for t in _TASKS if t.get("node_id"))
        unresolved = [t["id"] for t in _TASKS if not t.get("node_id")]
        _log("INFO", f"Tasks re-resolved: {resolved}/{len(_TASKS)} linked")
        return jsonify({
            "ok": True,
            "resolved": resolved,
            "total": len(_TASKS),
            "unresolved_task_ids": unresolved,
            "tasks": _TASKS,
        })
    except Exception as exc:
        _log("ERROR", f"Task rebuild failed: {exc}")
        return jsonify({"error": str(exc)}), 500


def _run_consistency_checks() -> dict:
    """Run comprehensive consistency checks and return a structured report."""
    report: dict = {
        "graphs": {},
        "embeddings": {},
        "tasks": {},
        "annotations": {},
        "references": {},
        "issues": [],
    }

    configs = get_graph_configs()

    # ── 1. Graph vertex/edge counts ──────────────────────────────
    for ts, cfg in configs.items():
        try:
            with get_traversal(ts) as (g, conn):
                v_count = g.V().count().next()
                e_count = g.E().count().next()
                report["graphs"][ts] = {
                    "name": cfg["name"],
                    "vertices": v_count,
                    "edges": e_count,
                    "status": "ok" if v_count > 0 else "empty",
                }
                if v_count == 0:
                    report["issues"].append(f"Graph '{ts}' is empty — no vertices loaded")
        except Exception as exc:
            report["graphs"][ts] = {"name": cfg["name"], "status": "error", "error": str(exc)}
            report["issues"].append(f"Graph '{ts}' unreachable: {exc}")

    # ── 2. Embedding counts vs vertex counts ─────────────────────
    for ts, g_info in report["graphs"].items():
        emb_count = _engine.embedding_count(ts)
        v_count = g_info.get("vertices", 0)
        status = "ok"
        if emb_count == 0 and v_count > 0:
            status = "missing"
            report["issues"].append(f"Embeddings missing for '{ts}' ({v_count} vertices, 0 embeddings)")
        elif emb_count != v_count:
            status = "stale"
            report["issues"].append(
                f"Embedding count mismatch for '{ts}': {emb_count} embeddings vs {v_count} vertices"
            )
        report["embeddings"][ts] = {
            "indexed": emb_count,
            "expected": v_count,
            "status": status,
        }

    # ── 3. Task resolution ───────────────────────────────────────
    resolved = sum(1 for t in _TASKS if t.get("node_id"))
    unresolved = [{"id": t["id"], "node_name": t["node_name"], "graph": t["graph_name"]}
                  for t in _TASKS if not t.get("node_id")]
    report["tasks"] = {
        "total": len(_TASKS),
        "resolved": resolved,
        "unresolved": unresolved,
    }
    for u in unresolved:
        report["issues"].append(f"Task '{u['id']}' cannot find vertex '{u['node_name']}' in {u['graph']}")

    # ── 4. Orphaned annotations ──────────────────────────────────
    session = SessionLocal()
    try:
        all_annotations = session.query(NodeAnnotation.node_id).all()
        orphaned = []
        for (node_id,) in all_annotations:
            # Check if this vertex still exists in any graph
            found = False
            for ts in configs:
                try:
                    with get_traversal(ts) as (g, conn):
                        exists = g.V(node_id).count().next()
                        if exists > 0:
                            found = True
                            break
                except Exception:
                    pass
            if not found:
                orphaned.append(node_id)
        report["annotations"] = {
            "total": len(all_annotations),
            "orphaned": len(orphaned),
            "orphaned_ids": orphaned[:20],  # Cap at 20 for readability
        }
        if orphaned:
            report["issues"].append(
                f"{len(orphaned)} annotation(s) reference vertices that no longer exist"
            )
    finally:
        session.close()

    # ── 5. Reference → chunk resolution coverage ────────────────
    for ts, cfg in configs.items():
        docs_folder = get_docs_folder(ts)
        if not docs_folder or not os.path.isdir(docs_folder):
            report["references"][ts] = {"status": "no_docs_folder"}
            continue
        try:
            chunk_index = _build_chunk_index(docs_folder)
            with get_traversal(ts) as (g, conn):
                # Fetch both reference and source_reference for each vertex
                ref_pairs = (
                    g.V()
                    .has("reference")
                    .project("reference", "source_reference")
                    .by(__.values("reference"))
                    .by(__.coalesce(__.values("source_reference"), __.constant("")))
                    .toList()
                )
            total_refs = len(ref_pairs)
            resolved_refs = 0
            unresolved_refs = []
            for pair in ref_pairs:
                ref_str = pair.get("reference", "")
                sr_str = pair.get("source_reference", "")

                resolved = False

                # ── Try structured source_reference resolution first ──
                if sr_str:
                    try:
                        sr_obj = json.loads(sr_str)
                    except (json.JSONDecodeError, TypeError):
                        sr_obj = None
                    # Normalize to list of items
                    sr_items = []
                    if isinstance(sr_obj, dict) and sr_obj.get("chunk_path"):
                        sr_items = [sr_obj]
                    elif isinstance(sr_obj, list):
                        sr_items = [
                            item for item in sr_obj
                            if isinstance(item, dict) and item.get("chunk_path")
                        ]
                    for sr_item in sr_items:
                        chunk_path = sr_item["chunk_path"]
                        for entry in chunk_index:
                            if entry["path"].endswith(chunk_path) or chunk_path.endswith(entry["path"]):
                                resolved = True
                                break
                        if resolved:
                            break

                # ── Fallback: fuzzy matching on reference string ──
                if not resolved and ref_str:
                    matches = _match_reference(ref_str, chunk_index)
                    if matches:
                        resolved = True

                if resolved:
                    resolved_refs += 1
                elif ref_str:
                    unresolved_refs.append(ref_str)

            report["references"][ts] = {
                "total_refs": total_refs,
                "resolved": resolved_refs,
                "unresolved": len(unresolved_refs),
                "unresolved_samples": unresolved_refs[:10],
                "status": "ok" if len(unresolved_refs) == 0 else "partial",
            }
            if unresolved_refs:
                report["issues"].append(
                    f"Graph '{ts}': {len(unresolved_refs)}/{total_refs} references cannot resolve to doc chunks"
                )
        except Exception as exc:
            report["references"][ts] = {"status": "error", "error": str(exc)}

    report["issue_count"] = len(report["issues"])
    return report


# ── Startup ───────────────────────────────────────────────────────

# ── WSGI Prefix Middleware ─────────────────────────────────────────

class _PrefixMiddleware:
    """Strip URL_PREFIX from incoming requests so Flask routes stay unchanged.

    Requests to ``/`` are redirected to ``<prefix>/``.
    Requests outside the prefix return 404.
    """

    def __init__(self, wsgi_app, prefix: str):
        self.app = wsgi_app
        self.prefix = prefix.rstrip("/")

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        # Redirect bare prefix (no trailing slash) so the browser resolves
        # relative CSS/JS paths against <prefix>/ instead of /.
        if path == self.prefix:
            start_response("302 Found", [("Location", self.prefix + "/")])
            return [b""]
        if path.startswith(self.prefix + "/"):
            environ["PATH_INFO"] = path[len(self.prefix):] or "/"
            environ["SCRIPT_NAME"] = self.prefix
            return self.app(environ, start_response)
        if path == "/":
            start_response("302 Found", [("Location", self.prefix + "/")])
            return [b""]
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"Not Found"]


def create_app():
    """Initialize semantic engine, resolve task vertex IDs, and return Flask app."""
    try:
        # Smart re-indexing: only rebuild embeddings that are missing or stale
        _engine.index_all_if_needed()
        _log("INFO", "Semantic search engine initialized (all graphs)")
    except Exception as exc:
        _log("WARN", f"Semantic engine init deferred: {exc}")

    # Resolve task node_ids from stable node_name properties
    try:
        _resolve_task_node_ids()
        resolved = sum(1 for t in _TASKS if t.get("node_id"))
        _log("INFO", f"Task node IDs resolved: {resolved}/{len(_TASKS)} tasks linked to live vertices")
    except Exception as exc:
        _log("WARN", f"Task node ID resolution deferred: {exc}")

    # Wrap with prefix middleware when URL_PREFIX is set
    wrapped = app
    if URL_PREFIX and URL_PREFIX != "/":
        wrapped.wsgi_app = _PrefixMiddleware(wrapped.wsgi_app, URL_PREFIX)

    return wrapped


if __name__ == "__main__":
    application = create_app()
    url = f"http://{SERVER_HOST}:{SERVER_PORT}"
    if URL_PREFIX and URL_PREFIX != "/":
        url += URL_PREFIX
    _log("INFO", f"Starting Explorer on {url}")
    application.run(host=SERVER_HOST, port=SERVER_PORT, debug=FLASK_DEBUG)
