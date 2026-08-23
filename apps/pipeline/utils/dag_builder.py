"""Deterministic construction of dependency DAGs from an optimized knowledge graph.

Agent 5 (and 5.5/5.6/5.7) attach a canonical dependency-edge list to
``dependency_details.dependencies`` on the optimized graph (see
``dependency_edges()`` in ``utils/kg_readiness.py``). This module partitions
*every* rule in the graph into one or more directed acyclic graphs built from
those edges.

The 100%-coverage guarantee is structural, not best-effort: every rule
(including one with zero dependency edges) is assigned to exactly one
weakly-connected component, and every component becomes exactly one DAG in
the output. A rule cycle — which a graph that has passed Agent 5.5 readiness
should not contain, but which this module does not assume away — is condensed
into a single "cycle group" node via Kosaraju's algorithm so the emitted
per-component graph is provably acyclic (SCC-condensation of any directed
graph is itself a DAG) while every original rule is still accounted for
inside the group.

No third-party graph library is used, matching the rest of ``utils/`` (see
``kg_readiness.py``'s own hand-rolled traversal).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from utils.kg_readiness import dependency_edges

# Rule fields copied onto each DAG node — enough to read a DAG standalone
# without re-joining the full optimized graph for basic context.
_NODE_METADATA_FIELDS = (
    "rule_type",
    "entity_or_relationship",
    "description",
    "mandatory",
    "risk_level",
)


def _weakly_connected_components(
    node_ids: list[str], edges: list[tuple[str, str]]
) -> dict[str, str]:
    """Union-find over an undirected view of the edges. Returns node -> root."""
    parent = {node_id: node_id for node_id in node_ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for source, target in edges:
        union(source, target)

    return {node_id: find(node_id) for node_id in node_ids}


def _strongly_connected_components(
    node_ids: list[str], adjacency: Mapping[str, list[str]]
) -> list[list[str]]:
    """Kosaraju's algorithm (two iterative DFS passes). Returns SCCs, any size."""
    visited: set[str] = set()
    finish_order: list[str] = []

    def dfs_postorder(start: str) -> None:
        stack: list[tuple[str, iter]] = [(start, iter(adjacency.get(start, [])))]
        visited.add(start)
        while stack:
            node, remaining = stack[-1]
            advanced = False
            for neighbour in remaining:
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append((neighbour, iter(adjacency.get(neighbour, []))))
                    advanced = True
                    break
            if not advanced:
                stack.pop()
                finish_order.append(node)

    for node_id in node_ids:
        if node_id not in visited:
            dfs_postorder(node_id)

    reverse_adjacency: dict[str, list[str]] = defaultdict(list)
    for source, targets in adjacency.items():
        for target in targets:
            reverse_adjacency[target].append(source)

    visited2: set[str] = set()
    components: list[list[str]] = []

    def collect_component(start: str) -> list[str]:
        stack = [start]
        visited2.add(start)
        component = []
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbour in reverse_adjacency.get(node, []):
                if neighbour not in visited2:
                    visited2.add(neighbour)
                    stack.append(neighbour)
        return component

    for node_id in reversed(finish_order):
        if node_id not in visited2:
            components.append(collect_component(node_id))

    return components


def _topological_order(node_ids: list[str], adjacency: Mapping[str, list[str]]) -> list[str]:
    """Kahn's algorithm. Callers must pass an acyclic graph (e.g. an SCC condensation)."""
    in_degree = {node_id: 0 for node_id in node_ids}
    for targets in adjacency.values():
        for target in targets:
            if target in in_degree:
                in_degree[target] += 1

    # Deterministic: always expand the lexicographically-smallest ready node.
    ready = sorted(node_id for node_id, degree in in_degree.items() if degree == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        newly_ready = []
        for target in adjacency.get(node, []):
            if target not in in_degree:
                continue
            in_degree[target] -= 1
            if in_degree[target] == 0:
                newly_ready.append(target)
        ready = sorted(ready + newly_ready)

    if len(order) != len(node_ids):
        # Should be unreachable: the caller is expected to have already
        # condensed any cycle into a single node. Fail loudly rather than
        # silently return a partial/invalid order.
        remaining = sorted(set(node_ids) - set(order))
        raise ValueError(
            f"topological_order: graph still has a cycle after condensation "
            f"(unresolved nodes: {remaining})"
        )
    return order


def _node_payload(rule: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"rule_id": rule.get("rule_id")}
    for field in _NODE_METADATA_FIELDS:
        if field in rule:
            payload[field] = rule[field]
    return payload


def build_dependency_dags(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Partition every rule in ``graph`` into one or more acyclic DAGs.

    Returns::

        {
          "dags": [
            {
              "dag_id": "dag_0001",
              "rule_ids": [...],                 # every rule covered by this DAG
              "nodes": [{"rule_id", "rule_type", ...}, ...],
              "edges": [{"source_rule_id", "target_rule_id", "dependency_type", ...}, ...],
              "cycle_groups": [{"group_id": "dag_0001_cycle_1", "rule_ids": [...]}, ...],
              "topological_order": [...],        # rule_ids and/or cycle group_ids
              "is_acyclic": bool,                 # True only when cycle_groups is empty
            },
            ...
          ],
          "coverage": {
            "total_rules": int,
            "covered_rules": int,
            "complete": bool,               # True iff every rule_id appears in exactly one DAG
            "missing_rule_ids": [...],       # non-empty only on a coverage bug
            "duplicate_rule_ids": [...],     # non-empty only on a coverage bug
          },
          "dropped_edges": [...],            # edges referencing an unknown rule_id
          "self_loop_edges": [...],          # edges where source_rule_id == target_rule_id
        }

    A rule with no dependency edges becomes its own single-node DAG. This is
    a partition, not a best-effort pass: the coverage check above is a
    structural guarantee (every input rule is assigned to exactly one
    weakly-connected component), verified again explicitly so a future bug
    here fails loudly instead of silently dropping a rule.
    """
    rules = [rule for rule in graph.get("business_rules", []) if isinstance(rule, Mapping)]
    rules_by_id = {str(rule.get("rule_id")): rule for rule in rules if rule.get("rule_id")}
    node_ids = list(rules_by_id.keys())
    node_id_set = set(node_ids)

    raw_edges = dependency_edges(graph)
    dropped_edges: list[dict[str, Any]] = []
    self_loop_edges: list[dict[str, Any]] = []
    seen_edge_keys: set[tuple[str, str, str]] = set()
    edges: list[dict[str, Any]] = []
    for edge in raw_edges:
        source = str(edge.get("source_rule_id", ""))
        target = str(edge.get("target_rule_id", ""))
        if not source or not target or source not in node_id_set or target not in node_id_set:
            dropped_edges.append(dict(edge))
            continue
        if source == target:
            self_loop_edges.append(dict(edge))
            continue
        key = (source, target, str(edge.get("dependency_type", "")))
        if key in seen_edge_keys:
            continue
        seen_edge_keys.add(key)
        edges.append(dict(edge))

    edge_pairs = [(str(e["source_rule_id"]), str(e["target_rule_id"])) for e in edges]
    component_of = _weakly_connected_components(node_ids, edge_pairs)

    components: dict[str, list[str]] = defaultdict(list)
    for node_id in node_ids:
        components[component_of[node_id]].append(node_id)

    dags: list[dict[str, Any]] = []
    # Deterministic ordering: sort components by their smallest rule_id.
    for index, root in enumerate(sorted(components, key=lambda r: sorted(components[r])[0]), start=1):
        member_ids = sorted(components[root])
        member_set = set(member_ids)
        dag_id = f"dag_{index:04d}"

        component_edges = [e for e in edges if e["source_rule_id"] in member_set]
        adjacency: dict[str, list[str]] = defaultdict(list)
        for e in component_edges:
            adjacency[e["source_rule_id"]].append(e["target_rule_id"])

        sccs = _strongly_connected_components(member_ids, adjacency)
        cycle_groups: list[dict[str, Any]] = []
        node_to_condensed: dict[str, str] = {}
        cycle_number = 0
        for scc in sccs:
            if len(scc) > 1:
                cycle_number += 1
                group_id = f"{dag_id}_cycle_{cycle_number}"
                cycle_groups.append({"group_id": group_id, "rule_ids": sorted(scc)})
                for rule_id in scc:
                    node_to_condensed[rule_id] = group_id
            else:
                node_to_condensed[scc[0]] = scc[0]

        condensed_adjacency: dict[str, set[str]] = defaultdict(set)
        for e in component_edges:
            cs, ct = node_to_condensed[e["source_rule_id"]], node_to_condensed[e["target_rule_id"]]
            if cs != ct:
                condensed_adjacency[cs].add(ct)
        condensed_node_ids = sorted(set(node_to_condensed.values()))
        topo_order = _topological_order(
            condensed_node_ids, {k: sorted(v) for k, v in condensed_adjacency.items()}
        )

        dags.append(
            {
                "dag_id": dag_id,
                "rule_ids": member_ids,
                "nodes": [_node_payload(rules_by_id[rule_id]) for rule_id in member_ids],
                "edges": component_edges,
                "cycle_groups": cycle_groups,
                "topological_order": topo_order,
                "is_acyclic": not cycle_groups,
            }
        )

    covered_ids: list[str] = [rule_id for dag in dags for rule_id in dag["rule_ids"]]
    covered_set = set(covered_ids)
    duplicate_ids = sorted({rule_id for rule_id in covered_ids if covered_ids.count(rule_id) > 1})
    missing_ids = sorted(node_id_set - covered_set)
    coverage = {
        "total_rules": len(node_ids),
        "covered_rules": len(covered_set),
        "complete": not missing_ids and not duplicate_ids and len(covered_set) == len(node_ids),
        "missing_rule_ids": missing_ids,
        "duplicate_rule_ids": duplicate_ids,
    }

    return {
        "dags": dags,
        "coverage": coverage,
        "dropped_edges": dropped_edges,
        "self_loop_edges": self_loop_edges,
    }
