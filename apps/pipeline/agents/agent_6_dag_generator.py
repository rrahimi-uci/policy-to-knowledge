#!/usr/bin/env python3
"""
Dependency DAG Generator

Stage 6 of the extraction pipeline. Reads the optimized knowledge graph
(Agent 5's output — or, absent that, Agent 4's pre-optimization graph, e.g.
under --skip-optimize) and partitions every business rule into one or more
directed acyclic graphs built from the rule dependency edges Agent 5 already
computed.

Every rule is guaranteed to appear in exactly one output DAG: a rule with no
dependencies becomes its own single-node DAG, and a dependency cycle (which
Agent 5.5 readiness should already prevent, but which this stage does not
assume away) is condensed into a single "cycle group" node so the emitted
DAG stays acyclic without dropping any rule. See utils/dag_builder.py for the
partitioning algorithm and its own test coverage.

Author: Reza Rahimi
"""

import json
import os
import sys
from pathlib import Path

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.dag_builder import build_dependency_dags


def _report_markdown(result: dict, source_file: str) -> str:
    coverage = result["coverage"]
    dags = result["dags"]
    cyclic_dags = [dag for dag in dags if not dag["is_acyclic"]]
    sizes = sorted((len(dag["rule_ids"]) for dag in dags), reverse=True)

    lines = ["# Dependency DAG generation report", ""]
    lines.append(f"- Source graph: `{source_file}`")
    lines.append(f"- Total rules: {coverage['total_rules']}")
    lines.append(f"- DAGs generated: {len(dags)}")
    status = "PASS — 100%" if coverage["complete"] else "FAIL"
    lines.append(f"- Coverage: {coverage['covered_rules']}/{coverage['total_rules']} rules ({status})")
    if not coverage["complete"]:
        lines.append(f"- Missing rule_ids: {coverage['missing_rule_ids']}")
        lines.append(f"- Duplicate rule_ids: {coverage['duplicate_rule_ids']}")
    lines.append(f"- Dropped edges (referenced an unknown rule_id): {len(result['dropped_edges'])}")
    lines.append(f"- Self-loop edges (excluded from DAG edges): {len(result['self_loop_edges'])}")

    lines += ["", "## DAG size distribution", ""]
    lines.append(f"- Largest DAG: {sizes[0] if sizes else 0} rules")
    lines.append(f"- Single-rule (isolated) DAGs: {sum(1 for s in sizes if s == 1)}")
    lines.append(f"- Multi-rule DAGs: {sum(1 for s in sizes if s > 1)}")

    lines += ["", "## Cycles", ""]
    if cyclic_dags:
        lines.append(
            f"{len(cyclic_dags)} DAG(s) contain a dependency cycle. Each cycle was condensed "
            "into a single node (`cycle_groups`) so the DAG stays acyclic; the member rules are "
            "still fully covered, but have no single valid execution order among themselves and "
            "require manual review."
        )
        lines.append("")
        for dag in cyclic_dags:
            for group in dag["cycle_groups"]:
                lines.append(f"- {dag['dag_id']} / {group['group_id']}: {', '.join(group['rule_ids'])}")
    else:
        lines.append("- None. Every generated DAG is a pure acyclic graph on its original rule_ids.")

    return "\n".join(lines) + "\n"


class DependencyDAGGenerator:
    """Builds and writes the dependency-DAG artifacts for one optimized graph."""

    def __init__(self, input_file: Path, output_dir: Path):
        self.input_file = Path(input_file)
        self.output_dir = Path(output_dir)

    def generate(self) -> dict:
        with open(self.input_file, "r", encoding="utf-8") as f:
            graph = json.load(f)

        result = build_dependency_dags(graph)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        dag_file = self.output_dir / "dependency_dags.json"
        with open(dag_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "metadata": {
                        "source_file": str(self.input_file),
                        "generator": "agent_6_dag_generator",
                    },
                    **result,
                },
                f,
                indent=2,
            )

        report_file = self.output_dir / "dag_generation_report.md"
        report_file.write_text(_report_markdown(result, str(self.input_file)), encoding="utf-8")

        return result


def main() -> None:
    from utils.config import get_config

    config = get_config()

    # Same source-resolution order as the visualizer (Agent 5 optimized graph
    # first, Agent 4's pre-optimization graph otherwise): dependency edges are
    # computed during Agent 5's optimization pass, so falling back to Agent 4
    # output (e.g. a --skip-optimize run) still works, just with no edges —
    # every rule becomes its own single-node DAG.
    optimized_file = config.get_optimized_dir() / "optimized_compliance_knowledge_graph.json"
    rules_with_entities_file = config.get_rules_with_entities_dir() / "compliance_knowledge_graph.json"

    if optimized_file.exists():
        json_file = optimized_file
        print("📊 Using optimized business rules (Agent 5 output)", flush=True)
    elif rules_with_entities_file.exists():
        json_file = rules_with_entities_file
        print("⚠️  Optimized graph not found — using Agent 4 output (pre-optimization).", flush=True)
        print("    Dependency edges are computed by Agent 5, so this run will likely", flush=True)
        print("    yield only single-rule DAGs with no dependency edges.", flush=True)
    else:
        print("❌ Error: No input file found.", flush=True)
        print("   Looked for:", flush=True)
        print(f"     - {optimized_file}", flush=True)
        print(f"     - {rules_with_entities_file}", flush=True)
        print("   Please run the pipeline up to step 4 or 5 first.", flush=True)
        sys.exit(1)

    output_dir = config.get_dag_dir()

    print("=" * 80, flush=True)
    print("DEPENDENCY DAG GENERATOR", flush=True)
    print("=" * 80, flush=True)
    print(flush=True)

    generator = DependencyDAGGenerator(json_file, output_dir)
    result = generator.generate()

    coverage = result["coverage"]
    dags = result["dags"]
    cyclic = sum(1 for dag in dags if not dag["is_acyclic"])

    print(f"   • Total rules:        {coverage['total_rules']:>5}", flush=True)
    print(f"   • DAGs generated:     {len(dags):>5}", flush=True)
    print(f"   • DAGs with cycles:   {cyclic:>5}  (condensed into cycle groups)", flush=True)
    print(f"   • Dropped edges:      {len(result['dropped_edges']):>5}  (referenced an unknown rule)", flush=True)
    print(f"   • Self-loop edges:    {len(result['self_loop_edges']):>5}", flush=True)
    print(flush=True)

    if not coverage["complete"]:
        print("❌ COVERAGE CHECK FAILED — not every rule is covered by a generated DAG.", flush=True)
        print(f"   Missing rule_ids:   {coverage['missing_rule_ids']}", flush=True)
        print(f"   Duplicate rule_ids: {coverage['duplicate_rule_ids']}", flush=True)
        print("   Inspect dag_generation_report.md for details.", flush=True)
        raise SystemExit(2)

    print(
        f"✅ Coverage check passed: {coverage['covered_rules']}/{coverage['total_rules']} rules "
        f"(100%) are covered by {len(dags)} generated DAG(s).",
        flush=True,
    )
    print(flush=True)
    print("=" * 80, flush=True)
    print("✅ DAG GENERATION COMPLETE", flush=True)
    print("=" * 80, flush=True)


if __name__ == "__main__":
    main()
