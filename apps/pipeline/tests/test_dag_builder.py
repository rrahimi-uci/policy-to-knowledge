"""Tests for utils/dag_builder.py — the stage-6 dependency-DAG construction.

The central requirement (per the feature request) is that the generated DAGs
cover 100% of the original knowledge graph: every rule must appear in exactly
one output DAG, whether or not it has any dependency edges, and regardless of
cycles in the input.
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.dag_builder import build_dependency_dags


def _rule(rule_id: str, **extra):
    return {"rule_id": rule_id, "rule_type": "obligation", "description": f"desc {rule_id}", **extra}


def _graph(rule_ids, edges):
    """edges: list of (source_rule_id, target_rule_id, dependency_type)."""
    return {
        "business_rules": [_rule(rid) for rid in rule_ids],
        "dependency_details": {
            "dependencies": [
                {"source_rule_id": s, "target_rule_id": t, "dependency_type": dt}
                for s, t, dt in edges
            ]
        },
    }


def _all_rule_ids(result):
    return [rid for dag in result["dags"] for rid in dag["rule_ids"]]


class TestCoverageGuarantee:
    """The 100%-coverage requirement, exercised across distinct graph shapes."""

    def test_all_isolated_rules(self):
        graph = _graph(["R1", "R2", "R3"], [])
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        assert result["coverage"]["total_rules"] == 3
        assert sorted(_all_rule_ids(result)) == ["R1", "R2", "R3"]
        assert len(result["dags"]) == 3
        assert all(dag["is_acyclic"] for dag in result["dags"])

    def test_simple_chain(self):
        graph = _graph(["R1", "R2", "R3"], [("R1", "R2", "prerequisite"), ("R2", "R3", "prerequisite")])
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        assert len(result["dags"]) == 1
        dag = result["dags"][0]
        assert sorted(dag["rule_ids"]) == ["R1", "R2", "R3"]
        assert dag["topological_order"] == ["R1", "R2", "R3"]
        assert dag["is_acyclic"] is True

    def test_mixed_isolated_and_connected(self):
        graph = _graph(
            ["A", "B", "C", "D", "E"],
            [("A", "B", "prerequisite"), ("B", "C", "prerequisite")],
        )
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        assert sorted(_all_rule_ids(result)) == ["A", "B", "C", "D", "E"]
        # One 3-node component + two singleton components.
        sizes = sorted(len(dag["rule_ids"]) for dag in result["dags"])
        assert sizes == [1, 1, 3]

    def test_disconnected_components(self):
        graph = _graph(
            ["A", "B", "C", "D"],
            [("A", "B", "prerequisite"), ("C", "D", "prerequisite")],
        )
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        assert len(result["dags"]) == 2
        assert {frozenset(dag["rule_ids"]) for dag in result["dags"]} == {
            frozenset(["A", "B"]),
            frozenset(["C", "D"]),
        }

    def test_empty_graph(self):
        result = build_dependency_dags({"business_rules": []})
        assert result["coverage"]["total_rules"] == 0
        assert result["coverage"]["complete"] is True
        assert result["dags"] == []

    def test_rules_missing_rule_id_are_excluded_not_crashing(self):
        graph = {
            "business_rules": [{"rule_id": "R1"}, {"description": "no id"}],
            "dependency_details": {"dependencies": []},
        }
        result = build_dependency_dags(graph)
        assert result["coverage"]["total_rules"] == 1
        assert result["coverage"]["complete"] is True


class TestCycleHandling:
    """A cyclic dependency must not break acyclicity of the output, and must
    not drop any rule."""

    def test_two_node_cycle_is_condensed(self):
        graph = _graph(["R1", "R2"], [("R1", "R2", "prerequisite"), ("R2", "R1", "prerequisite")])
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        dag = result["dags"][0]
        assert dag["is_acyclic"] is False
        assert len(dag["cycle_groups"]) == 1
        assert sorted(dag["cycle_groups"][0]["rule_ids"]) == ["R1", "R2"]
        # The cycle group is a single node in the topological order.
        assert dag["topological_order"] == [dag["cycle_groups"][0]["group_id"]]
        # Every original rule is still present in rule_ids/nodes even though
        # it was condensed for ordering purposes.
        assert sorted(dag["rule_ids"]) == ["R1", "R2"]

    def test_three_node_cycle_plus_downstream_rule(self):
        # R1 -> R2 -> R3 -> R1 (cycle), and R3 -> R4 (downstream of the cycle).
        graph = _graph(
            ["R1", "R2", "R3", "R4"],
            [
                ("R1", "R2", "prerequisite"),
                ("R2", "R3", "prerequisite"),
                ("R3", "R1", "prerequisite"),
                ("R3", "R4", "prerequisite"),
            ],
        )
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        dag = result["dags"][0]
        assert sorted(dag["rule_ids"]) == ["R1", "R2", "R3", "R4"]
        assert len(dag["cycle_groups"]) == 1
        assert sorted(dag["cycle_groups"][0]["rule_ids"]) == ["R1", "R2", "R3"]
        group_id = dag["cycle_groups"][0]["group_id"]
        # R4 depends on the cycle, so it must come after the cycle group.
        assert dag["topological_order"] == [group_id, "R4"]

    def test_self_loop_is_reported_and_excluded_from_edges(self):
        graph = _graph(["R1", "R2"], [("R1", "R1", "prerequisite"), ("R1", "R2", "prerequisite")])
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        assert len(result["self_loop_edges"]) == 1
        assert result["self_loop_edges"][0]["source_rule_id"] == "R1"
        # The self-loop must not appear as a real edge, and must not turn R1
        # into a (spurious) cycle group.
        dag = result["dags"][0]
        assert dag["cycle_groups"] == []
        assert dag["is_acyclic"] is True
        assert [e for e in dag["edges"] if e["source_rule_id"] == e["target_rule_id"]] == []

    def test_cycle_across_a_larger_component_still_fully_covered(self):
        # A 5-cycle plus two extra rules hanging off it in each direction.
        cycle = [("R1", "R2", "x"), ("R2", "R3", "x"), ("R3", "R4", "x"), ("R4", "R5", "x"), ("R5", "R1", "x")]
        graph = _graph(
            ["R1", "R2", "R3", "R4", "R5", "UP", "DOWN"],
            cycle + [("UP", "R1", "prerequisite"), ("R3", "DOWN", "prerequisite")],
        )
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        assert sorted(_all_rule_ids(result)) == ["DOWN", "R1", "R2", "R3", "R4", "R5", "UP"]
        dag = result["dags"][0]
        assert len(dag["cycle_groups"]) == 1
        assert sorted(dag["cycle_groups"][0]["rule_ids"]) == ["R1", "R2", "R3", "R4", "R5"]
        group_id = dag["cycle_groups"][0]["group_id"]
        assert dag["topological_order"] == ["UP", group_id, "DOWN"]


class TestDanglingAndMalformedEdges:
    def test_edge_to_unknown_rule_is_dropped_and_reported(self):
        graph = _graph(["R1"], [("R1", "GHOST", "prerequisite")])
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        assert len(result["dropped_edges"]) == 1
        assert result["dropped_edges"][0]["target_rule_id"] == "GHOST"
        # R1 is still covered as an isolated node.
        assert result["dags"][0]["rule_ids"] == ["R1"]

    def test_per_rule_dependencies_fallback_when_no_canonical_edges(self):
        # dependency_edges() falls back to per-rule "dependencies" lists when
        # dependency_details.dependencies is absent (see kg_readiness.py).
        graph = {
            "business_rules": [
                {"rule_id": "R1", "rule_type": "obligation", "description": "d1"},
                {
                    "rule_id": "R2",
                    "rule_type": "obligation",
                    "description": "d2",
                    "dependencies": [{"depends_on_rule": "R1", "dependency_type": "prerequisite"}],
                },
            ]
        }
        result = build_dependency_dags(graph)
        assert result["coverage"]["complete"] is True
        assert len(result["dags"]) == 1
        assert result["dags"][0]["topological_order"] == ["R1", "R2"]

    def test_duplicate_edges_are_deduplicated(self):
        graph = _graph(
            ["R1", "R2"],
            [("R1", "R2", "prerequisite"), ("R1", "R2", "prerequisite")],
        )
        result = build_dependency_dags(graph)
        assert len(result["dags"][0]["edges"]) == 1


class TestDeterminism:
    def test_repeated_calls_produce_identical_output(self):
        graph = _graph(
            ["R5", "R1", "R3", "R2", "R4"],
            [("R1", "R2", "a"), ("R3", "R4", "b")],
        )
        first = build_dependency_dags(graph)
        second = build_dependency_dags(graph)
        assert first == second

    def test_dag_ids_are_stable_regardless_of_input_rule_order(self):
        rule_ids = ["R1", "R2", "R3", "R4"]
        edges = [("R1", "R2", "x"), ("R3", "R4", "x")]
        forward = build_dependency_dags(_graph(rule_ids, edges))
        shuffled_ids = list(rule_ids)
        random.Random(42).shuffle(shuffled_ids)
        reversed_graph = _graph(shuffled_ids, list(reversed(edges)))
        backward = build_dependency_dags(reversed_graph)
        assert [d["dag_id"] for d in forward["dags"]] == [d["dag_id"] for d in backward["dags"]]
        assert [sorted(d["rule_ids"]) for d in forward["dags"]] == [
            sorted(d["rule_ids"]) for d in backward["dags"]
        ]


class TestStressRandomGraphs:
    """Randomized graphs (with cycles, isolated nodes, and dangling edges all
    mixed in) must always yield 100% coverage and a per-DAG acyclic order."""

    def test_random_graphs_always_fully_covered(self):
        rng = random.Random(1234)
        for trial in range(25):
            n = rng.randint(1, 60)
            rule_ids = [f"R{i}" for i in range(n)]
            edges = []
            for _ in range(rng.randint(0, n * 2)):
                s, t = rng.choice(rule_ids), rng.choice(rule_ids)
                edges.append((s, t, "prerequisite"))
            # Occasionally reference a rule that doesn't exist.
            if rng.random() < 0.3 and rule_ids:
                edges.append((rng.choice(rule_ids), "GHOST", "prerequisite"))

            result = build_dependency_dags(_graph(rule_ids, edges))
            assert result["coverage"]["complete"] is True, f"trial {trial} failed coverage"
            assert sorted(_all_rule_ids(result)) == sorted(rule_ids), f"trial {trial} lost a rule"
            for dag in result["dags"]:
                # Every DAG's topological_order must be a valid permutation
                # of its (condensed) node set, with no leftovers.
                condensed_ids = set(dag["topological_order"])
                expected = set(dag["rule_ids"]) - {
                    rid for group in dag["cycle_groups"] for rid in group["rule_ids"]
                }
                expected |= {group["group_id"] for group in dag["cycle_groups"]}
                assert condensed_ids == expected, f"trial {trial} dag {dag['dag_id']} bad topo order"
