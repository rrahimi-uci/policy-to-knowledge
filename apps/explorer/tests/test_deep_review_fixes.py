"""Regression tests for the deep bug-review fixes (2026-06).

Bugs fixed (apps/explorer only):

1. (server.py) `get_vertex_details` and `find_related_rules` chat tools fell back
   to the literal traversal source ``"g"`` when the LLM omitted ``graph_name``.
   ``get_traversal`` only remaps ``None`` (not ``"g"``) to DEFAULT_GRAPH, so in a
   multi-graph setup these tools queried a non-existent ``g`` traversal source.
   Both must fall back to ``get_default_traversal_source()`` like every other tool.

2. (detail.js) ``openReference`` referenced the undefined global ``highlightTerms``
   (``!highlightTerms.length``), throwing a ReferenceError before ``window.open``
   whenever a ``source_text`` was present — so the source-document link silently
   failed. The backend already guards source_text vs highlight, so the frontend
   guard must drop the undefined reference.

3. (graph.js / create.js) Server-controlled node/edge properties (rule_type,
   category, label, dependency_type) were interpolated raw into ``innerHTML``,
   a stored-XSS surface. They must be escaped via ``escapeHtml``.

4. (actions.js) ``setReviewStatus`` pushed to ``data.reviewHistory`` without
   initializing it, unlike ``setApprovalStatus`` — a latent TypeError for any
   stored annotation lacking ``reviewHistory``.

These are fast, OFFLINE source-assertion tests (no live JanusGraph / OpenSearch),
matching the established convention for JS and prefix/source checks in this suite.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # apps/explorer/


# ────────────────────────────────────────────────────────────────────
# Bug 1: chat tools must default graph_name to the loaded default source
# ────────────────────────────────────────────────────────────────────

def _server_src() -> str:
    return (REPO_ROOT / "src" / "server.py").read_text()


def test_get_vertex_details_defaults_to_default_traversal_source():
    """get_vertex_details must not fall back to the literal 'g' traversal source."""
    src = _server_src()
    start = src.index('elif function_name == "get_vertex_details":')
    body = src[start:start + 400]
    assert 'function_args.get("graph_name") or get_default_traversal_source()' in body, (
        "get_vertex_details must default graph_name to get_default_traversal_source(); "
        "the literal 'g' is not a valid traversal source in a multi-graph setup."
    )
    assert 'function_args.get("graph_name", "g")' not in body, (
        "get_vertex_details must not fall back to the literal 'g' traversal source."
    )


def test_find_related_rules_defaults_to_default_traversal_source():
    """_execute_find_related_rules must not fall back to the literal 'g'."""
    src = _server_src()
    start = src.index("def _execute_find_related_rules")
    body = src[start:start + 600]
    assert 'function_args.get("graph_name") or get_default_traversal_source()' in body, (
        "_execute_find_related_rules must default graph_name to "
        "get_default_traversal_source()."
    )
    assert 'function_args.get("graph_name", "g")' not in body, (
        "_execute_find_related_rules must not fall back to the literal 'g'."
    )


def test_no_chat_tool_falls_back_to_literal_g_traversal_source():
    """No chat-tool handler should resolve graph_name to the bare string 'g'."""
    src = _server_src()
    assert 'function_args.get("graph_name", "g")' not in src, (
        "A chat tool still defaults graph_name to the literal 'g' traversal "
        "source; use `or get_default_traversal_source()` instead."
    )


# ────────────────────────────────────────────────────────────────────
# Bug 2: openReference must not reference the undefined `highlightTerms`
# ────────────────────────────────────────────────────────────────────

def test_open_reference_does_not_use_undefined_highlightTerms():
    """openReference must not gate source_text highlighting on the undefined
    global `highlightTerms` — referencing it throws and aborts window.open()."""
    detail_js = (REPO_ROOT / "ui" / "js" / "detail.js").read_text()
    assert "highlightTerms" not in detail_js, (
        "detail.js references `highlightTerms`, which is defined nowhere in the "
        "frontend — `!highlightTerms.length` throws a ReferenceError and breaks "
        "the reference link. Drop the undefined guard."
    )
    start = detail_js.index("function openReference")
    end = detail_js.index("\n}", start)
    body = detail_js[start:end]
    assert "if (sourceText) {" in body, (
        "openReference should apply source_text highlighting whenever sourceText "
        "is present (the backend already guards source_text vs highlight terms)."
    )


# ────────────────────────────────────────────────────────────────────
# Bug 3: server-controlled props must be escaped before innerHTML
# ────────────────────────────────────────────────────────────────────

def test_graph_js_tooltip_escapes_server_props():
    """The node tooltip must escape label / rule_type / category."""
    graph_js = (REPO_ROOT / "ui" / "js" / "graph.js").read_text()
    start = graph_js.index("function onNodeHover")
    body = graph_js[start:start + 600]
    assert "${escapeHtml(String(d.label))}" in body
    assert "${escapeHtml(String(d.rule_type))}" in body
    assert "${escapeHtml(String(d.category))}" in body
    # The raw, unescaped interpolations must be gone.
    assert "<span>${d.label}</span>" not in body
    assert "${d.rule_type}`" not in body
    assert "Category: <span>${d.category}</span>" not in body


def test_graph_js_legend_rows_escape_type_and_label():
    """Legend rows must escape the server-derived node type and edge label."""
    graph_js = (REPO_ROOT / "ui" / "js" / "graph.js").read_text()
    assert "</div> ${escapeHtml(String(type))}`" in graph_js
    assert "</div> ${escapeHtml(String(label))}`" in graph_js
    assert "</div> ${type}`" not in graph_js
    assert "</div> ${label}`" not in graph_js


def test_graph_js_vertex_fetch_encodes_params():
    """The vertex fetch must URL-encode both the id and graph_name."""
    graph_js = (REPO_ROOT / "ui" / "js" / "graph.js").read_text()
    assert (
        "/api/vertex/${encodeURIComponent(d.id)}?graph_name="
        "${encodeURIComponent(currentGraphName)}"
    ) in graph_js, "graph.js must URL-encode the vertex id and graph_name."
    assert "/api/vertex/${d.id}?graph_name=${currentGraphName}" not in graph_js


def test_create_js_escapes_server_controlled_props():
    """create.js must escape dependency_type and rule_type/label before innerHTML."""
    create_js = (REPO_ROOT / "ui" / "js" / "create.js").read_text()
    assert "${escapeHtml(String(c.dependency_type || ''))}</span>" in create_js
    assert "${escapeHtml(String(n.rule_type || n.label || ''))}</span>" in create_js
    # Raw interpolations gone
    assert ">${c.dependency_type}</span>" not in create_js
    assert ">${n.rule_type || n.label}</span>" not in create_js


# ────────────────────────────────────────────────────────────────────
# Bug 4: setReviewStatus must initialize reviewHistory before push
# ────────────────────────────────────────────────────────────────────

def test_set_review_status_initializes_review_history():
    """setReviewStatus must guard reviewHistory like setApprovalStatus guards
    approvalHistory, or it throws on stored annotations lacking the key."""
    actions_js = (REPO_ROOT / "ui" / "js" / "actions.js").read_text()
    start = actions_js.index("function setReviewStatus")
    end = actions_js.index("function setApprovalStatus")
    body = actions_js[start:end]
    # The guard must appear before the push.
    guard_idx = body.index("if (!data.reviewHistory) data.reviewHistory = [];")
    push_idx = body.index("data.reviewHistory.push(")
    assert guard_idx < push_idx, (
        "setReviewStatus must initialize data.reviewHistory before pushing to it."
    )
