"""
Example Gremlin queries for the Explorer compliance knowledge graph.
Demonstrates traversal of business rules and their dependencies
using OpenSearch-backed full-text search on JanusGraph.
"""

import sys

from gremlin_python.process.traversal import P, TextP, Order
from gremlin_python.process.graph_traversal import __

from src.graph_connection import get_traversal
from conf.config import QUERY_DEFAULT_LIMIT, HIGH_CONFIDENCE_THRESHOLD, QUERY_HIGH_CONFIDENCE_MAX
from src.log import log as _log


def _print_section(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


# ── 1. Basic graph overview ──────────────────────────────────────

def query_vertex_count_by_label(g) -> dict:
    """Count vertices grouped by label."""
    _print_section("1a. Vertex Count by Label")
    results = g.V().groupCount().by(__.label()).next()
    for label, count in results.items():
        print(f"  {label}: {count}")
    return results


def query_edge_count_by_label(g) -> dict:
    """Count edges grouped by label."""
    _print_section("1b. Edge Count by Label")
    results = g.E().groupCount().by(__.label()).next()
    for label, count in results.items():
        print(f"  {label}: {count}")
    return results


def query_rules_by_type(g) -> dict:
    """Count business rules by rule_type."""
    _print_section("1c. Business Rules by Type")
    results = g.V().hasLabel("business_rule").groupCount().by(__.values("rule_type")).next()
    for rtype, count in sorted(results.items(), key=lambda x: -x[1]):
        print(f"  {rtype}: {count}")
    return results


# ── 2. Dependency analysis ───────────────────────────────────────

def query_dependency_types(g) -> dict:
    """Count dependency edges by dependency_type."""
    _print_section("2a. Dependency Types Distribution")
    results = g.E().hasLabel("depends_on").groupCount().by(__.values("dependency_type")).next()
    for dtype, count in sorted(results.items(), key=lambda x: -x[1]):
        print(f"  {dtype}: {count}")
    return results


def query_most_connected_rules(g, limit: int = QUERY_DEFAULT_LIMIT) -> list:
    """Find the most connected business rules (hub rules)."""
    _print_section(f"2b. Top {limit} Most Connected Rules")
    results = (
        g.V().hasLabel("business_rule")
        .project("name", "out_deps", "in_deps", "total")
        .by(__.values("name"))
        .by(__.outE("depends_on").count())
        .by(__.inE("depends_on").count())
        .by(__.bothE("depends_on").count())
        .order().by(__.select("total"), Order.desc)
        .limit(limit)
        .toList()
    )
    for r in results:
        print(f"  {r['name']}")
        print(f"    out={r['out_deps']} in={r['in_deps']} total={r['total']}")
    return results


def query_prerequisite_chain(g, rule_name: str) -> list:
    """Find all prerequisites for a given rule (transitive closure)."""
    _print_section(f"2c. Prerequisites for '{rule_name[:50]}'")
    results = (
        g.V().has("name", rule_name)
        .repeat(__.outE("depends_on").has("dependency_type", "prerequisite").inV().simplePath())
        .until(__.outE("depends_on").has("dependency_type", "prerequisite").count().is_(0))
        .emit()
        .dedup()
        .values("name")
        .toList()
    )
    for name in results:
        print(f"  -> {name}")
    return results


def query_override_rules(g) -> list:
    """Find all override relationships."""
    _print_section("2d. Override Dependencies")
    results = (
        g.E().hasLabel("depends_on").has("dependency_type", "override")
        .project("from", "to", "rationale")
        .by(__.outV().values("name"))
        .by(__.inV().values("name"))
        .by(__.values("rationale"))
        .toList()
    )
    for r in results:
        print(f"  {r['from'][:60]}")
        print(f"    OVERRIDES -> {r['to'][:60]}")
        print(f"    Rationale: {r['rationale'][:100]}...")
    return results


# ── 3. Compliance-specific queries ───────────────────────────────

def query_high_confidence_rules(g, threshold: float = HIGH_CONFIDENCE_THRESHOLD) -> list:
    """Find rules above a confidence threshold."""
    _print_section(f"3a. High Confidence Rules (>{threshold})")
    results = (
        g.V().hasLabel("business_rule")
        .has("confidence_score", P.gt(threshold))
        .project("name", "rule_type", "confidence")
        .by(__.values("name"))
        .by(__.values("rule_type"))
        .by(__.values("confidence_score"))
        .order().by(__.select("confidence"), Order.desc)
        .limit(QUERY_HIGH_CONFIDENCE_MAX)
        .toList()
    )
    for r in results:
        print(f"  [{r['rule_type']}] {r['name'][:60]} (conf={r['confidence']:.1f})")
    return results


def query_rules_needing_review(g) -> list:
    """Find rules flagged for review."""
    _print_section("3b. Rules Requiring Review")
    results = (
        g.V().hasLabel("business_rule")
        .has("requires_review", True)
        .project("name", "rule_type", "confidence", "review_reason")
        .by(__.values("name"))
        .by(__.values("rule_type"))
        .by(__.values("confidence_score"))
        .by(__.values("review_reason"))
        .order().by(__.select("confidence"))
        .toList()
    )
    for r in results:
        print(f"  [{r['rule_type']}] {r['name'][:50]} (conf={r['confidence']:.1f})")
        print(f"    Reason: {r['review_reason']}")
    return results


def query_rules_by_entity_category(g, entity: str) -> list:
    """Find rules belonging to a specific entity/relationship category."""
    _print_section(f"3c. Rules for Entity '{entity}'")
    results = (
        g.V().hasLabel("business_rule")
        .has("entity_or_relationship", entity)
        .project("rule_id", "name", "rule_type")
        .by(__.values("rule_id"))
        .by(__.values("name"))
        .by(__.values("rule_type"))
        .toList()
    )
    for r in results:
        print(f"  [{r['rule_type']}] {r['rule_id']}: {r['name'][:60]}")
    return results


# ── 4. Full-text search ──────────────────────────────────────────

def text_search_rules(g, search_term: str) -> list:
    """Full-text search across rule content."""
    _print_section(f"4a. Text Search: '{search_term}'")
    results = (
        g.V().hasLabel("business_rule")
        .has("content", TextP.containing(search_term))
        .project("name", "rule_type", "snippet")
        .by(__.values("name"))
        .by(__.values("rule_type"))
        .by(__.values("description"))
        .limit(QUERY_DEFAULT_LIMIT)
        .toList()
    )
    for r in results:
        snippet = r["snippet"][:100] + "..." if len(r["snippet"]) > 100 else r["snippet"]
        print(f"  [{r['rule_type']}] {r['name'][:50]}")
        print(f"     {snippet}")
    return results


# ── Runner ────────────────────────────────────────────────────────

def run_all_queries() -> None:
    """Execute all example queries."""
    with get_traversal() as (g, conn):
        print("\n" + "=" * 60)
        print("  Policy to Knowledge EXPLORER — GREMLIN QUERIES")
        print("=" * 60)

        # Overview
        query_vertex_count_by_label(g)
        query_edge_count_by_label(g)
        query_rules_by_type(g)

        # Dependency analysis
        query_dependency_types(g)
        query_most_connected_rules(g, limit=QUERY_DEFAULT_LIMIT)
        query_override_rules(g)

        # Compliance-specific
        query_high_confidence_rules(g, threshold=HIGH_CONFIDENCE_THRESHOLD)
        query_rules_needing_review(g)
        query_rules_by_entity_category(g, "UNDERWRITING")

        # Full-text search
        text_search_rules(g, "borrower")
        text_search_rules(g, "eligibility")
        text_search_rules(g, "DU")

        _print_section("All queries completed!")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    run_all_queries()
