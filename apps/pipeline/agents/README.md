# Pipeline Agents

Agent reference for the Policy to Knowledge extraction and comparison pipeline.
Each agent is a self-contained module in this directory. Steps 1–7 turn source
documents into an optimized knowledge graph and its dependency DAGs (driven by
`cli/extract.py`); steps 5.5–5.7 complete readiness, remediate evidence-backed
gaps, and certify claim-level grounding before DAG generation and
visualization; agents 7–10 compare and merge two existing graphs (driven by
`cli/compare.py`).

```text
Extraction  (cli/extract.py):
  Documents → [1] → [2] → [3] → [3.5] → [4] → [5] → [5.5] → [5.6*] → [5.7] → [6] → [7]

Comparison  (cli/compare.py — independent step numbering, see note below):
  KG₁ + KG₂ → [7] → [8] → [9] → [10] → Comparison Reports
```

`5.6*` runs only when Agent 5.5 identifies evidence-backed remediation work.
Extraction step `[6]` (Dependency DAG Generation) and comparison step `[7]`
(Rule-Type Clusterer) are unrelated stages in two separate CLIs whose step
numbers happen to both reach "7" — see the note below the Agent Summary table.

All LLM-using agents call the OpenAI model configured in `config.json`
(default reasoning model `gpt-5.2`, `reasoning_effort: medium`; the optimizer
agent uses the configured optimizer model). See [Configuration](#configuration).

## Agent Summary

| # | Agent | File | Class | LLM | Parallel workers |
| --- | --- | --- | --- | :---: | :---: |
| 1 | Document Organizer | `agent_1_document_organizer.py` | `DocumentChunkingAgent` | ✓ | — |
| 2 | Entity & Relationship Extractor | `agent_2_entity_extractor.py` | `ComplianceEntityRelationshipAgent` | ✓ | — |
| 3 | Rules Extractor | `agent_3_rules_extractor.py` | `BusinessRulesExtractor` | ✓ | `pipeline.max_workers` (40) |
| 3.5 | Rule Validator | `agent_3_5_rule_validator.py` | `RuleValidationAgent` | ✓ | — |
| 4 | Rules + Entities Merger | `agent_4_rules_with_entities_merger.py` | `KnowledgeEnricher` | — | — |
| 5 | Knowledge Graph Optimizer | `agent_5_knowledge_graph_optimizer.py` | `KnowledgeGraphOptimizer` | ✓ | — |
| 5.5 | Executable Readiness | `agent_5_5_executable_readiness.py` | `ExecutableReadinessCompleter` | ✓ | 16 local / 8 API |
| 5.6 | Focused Readiness Remediation | `agent_5_6_readiness_remediator.py` | `ReadinessRemediator` | ✓ | 40 local / 8 API |
| 5.7 | Independent Grounding Verifier | `agent_5_7_grounding_verifier.py` | `GroundingVerifier` | ✓ | 40 local / 16 API |
| 6 | Dependency DAG Generation | `agent_6_dag_generator.py` | `DependencyDAGGenerator` | — | — |
| 7¹ | Visualization & Report | `agent_6_visualization_and_report.py` | `KnowledgeGraphVisualizer` | — | — |
| 7² | Rule-Type Clusterer | `agent_7_rule_type_clusterer.py` | `RuleBehaviorClusterer` | — | — |
| 8 | Semantic Rule Matcher | `agent_8_semantic_rule_matcher.py` | `SemanticRuleMatcher` | ✓ | `--workers` (31) |
| 9 | Set Operations | `agent_9_set_operations.py` | `SetOperationsCalculator` | — | — |
| 10 | Set Visualization | `agent_10_set_visualization.py` | `SetOperationsVisualizer` | — | — |

¹ `cli/extract.py --step 7`. ² `cli/compare.py`'s own, independent step
numbering — unrelated to ¹ even though both reach "7". See below.

> **Why is `agent_6_visualization_and_report.py` step 7, and why do two
> files both start with `agent_6_`?** Its output directory,
> `agent-6-visualization-and-report/`, already exists inside several
> canonical `pipeline-output/` example batches committed to this repo.
> Renaming the script (and that directory, in every existing batch) purely
> to match its new step number was judged not worth the churn when Agent 6
> (DAG generation) was inserted immediately before it — only the CLI-facing
> step number moved, not the script's filename or its output directory.
> Comparison's `agent_7_rule_type_clusterer.py` is a separate, unrelated
> file with its own independent numbering (`cli/compare.py`, not
> `cli/extract.py`) — the shared "7" between it and extraction step 7 is
> coincidental, not a collision.

Per-document outputs land in `pipeline-output/<source>/agent-N-.../`; comparison
outputs land in `pipeline-output/_merged/<g1>_<g2>/agent-N-.../`.

---

## Extraction agents (1–7)

### Agent 1 — Document Organizer

Chunks and organizes source documents using their table-of-contents structure.

| | |
|---|---|
| **Consumes** | Raw files from `compliance-files/<batch>/` |
| **Produces** | Text chunks in `agent-1-organized-documents/` |
| **Run** | `.venv/bin/python cli/extract.py --step 1` |

- Extracts the PDF table of contents from bookmarks (PyPDF2).
- Falls back to LLM-assisted TOC detection and structure analysis when no
  bookmarks exist.
- Format-specific chunkers preserve section references, page numbers, and metadata.

| Format | Chunker | Method |
|--------|---------|--------|
| PDF | `PDFChunker` | TOC-based, or LLM reasoning fallback |
| Markdown | `MarkdownChunker` | Header-based (LangChain) |
| CSV/TSV | `CSVChunker` | Row-based (pandas) |
| Excel | `ExcelChunker` | Sheet-aware (pandas) |
| DOCX | `DocxChunker` | Heading-based (python-docx) |
| TXT | `TextChunker` | LLM structure analysis |

```json
"document_organizer": {
  "chunk_size_target": 2000,
  "max_chunk_size": 3000,
  "min_chunk_size": 500,
  "supported_formats": [".pdf", ".txt", ".docx", ".md"]
}
```

> The CLI discovers `.pdf`, `.txt`, `.md`, and `.docx` files (`pipeline.supported_extensions`).
> Agent 1 also ships `CSVChunker` (`.csv`, `.tsv`) and `ExcelChunker` (`.xlsx`, `.xls`)
> tools that can be invoked directly, but those extensions are not auto-discovered by default.

### Agent 2 — Entity & Relationship Extractor

Extracts entity types and relationships using iterative prompt optimization.

| | |
|---|---|
| **Consumes** | Organized chunks from Agent 1 |
| **Produces** | `agent-2-entities/entity_types_and_relationships.json` |
| **Run** | `.venv/bin/python cli/extract.py --step 2` |

- Meta-agent prompt optimization across `n_iterations` refinement passes.
- Entities carry name, definition, attributes, and examples; relationships carry
  cardinality, directionality, and constraints.
- Quality scoring across five factors (20 points each, 100 max).

```json
"entity_extractor": {
  "n_iterations": 3,
  "min_score_threshold": 70,
  "scoring_weights": {
    "completeness": 20,
    "relationship_quality": 20,
    "attribute_coverage": 20,
    "clarity": 20,
    "consistency": 20
  }
}
```

### Agent 3 — Rules Extractor

Extracts business rules with parallel batch processing.

| | |
|---|---|
| **Consumes** | Organized chunks (Agent 1) + entity definitions (Agent 2) |
| **Produces** | `agent-3-rules/compliance_rules_with_entities.json` |
| **Run** | `.venv/bin/python cli/extract.py --step 3` |

- Parallel batches via `ThreadPoolExecutor` (10 workers).
- 11 rule categories: Eligibility, Compliance, Documentation, Process,
  Calculation, Validation, Notification, Timing, Audit, Exception Handling,
  Reporting.
- Five-factor confidence scoring (source specificity, metric clarity, condition
  completeness, example quality, consequence clarity).

```json
"rules_extractor": {
  "target_rules": 300,
  "rules_per_batch": 10,
  "rules_per_batch_openai": 10
}
```

### Agent 3.5 — Rule Validator

Validates extracted rules for quality, consistency, and completeness.
Non-blocking: the pipeline continues even if validation reports issues.

| | |
|---|---|
| **Consumes** | Rules from Agent 3 |
| **Produces** | `agent-3-5-validation/validation_summary.txt` |
| **Run** | Automatically after Agent 3 (`--step 3`) |

- Assesses completeness, specificity, and consistency.
- Detects duplicates, validates cross-references, analyzes confidence scores, and
  emits recommendations.

### Agent 4 — Rules + Entities Merger

Merges business rules with entity definitions into a complete knowledge graph.
No LLM calls.

| | |
|---|---|
| **Consumes** | Rules (Agent 3) + entities (Agent 2) |
| **Produces** | `agent-4-rules-with-entities/compliance_knowledge_graph.json` |
| **Run** | `.venv/bin/python cli/extract.py --step 4` |

- Combines rules with entity context and maintains referential integrity.
- Exports a unified knowledge-graph structure to JSON.

### Agent 5 — Knowledge Graph Optimizer

Optimizes the knowledge graph through deduplication and dependency analysis.

| | |
|---|---|
| **Consumes** | Complete KG from Agent 4 |
| **Produces** | `agent-5-optimized/optimized_compliance_knowledge_graph.json` (deduplicated rules plus an embedded dependency graph and optimization metadata) |
| **Run** | `.venv/bin/python cli/extract.py --step 5` |

- Conservative deduplication that preserves meaningful variations.
- Batched processing for large rule sets (50 rules per batch).
- Classifies seven dependency types:

| Type | Description |
|------|-------------|
| `prerequisite` | Rule A must be satisfied before Rule B |
| `sequential` | Rules must be executed in order |
| `conditional` | Rule B applies only if Rule A is met |
| `complementary` | Rules work together |
| `contradictory` | Rules conflict |
| `override` | Rule B supersedes Rule A |
| `validation` | Rule B validates Rule A's outcome |

> Skip this step with `--skip-optimize`; Steps 6 and 7 then use Agent 4 output directly.

### Agent 5.5 — Executable Readiness

Completes the optimized graph for direct DMN/BPMN use and fails the extraction
pass when any non-negotiable invariant or unresolved rule remains.

| | |
|---|---|
| **Consumes** | Agent 4 corpus baseline, Agent 5 graph, and every organized source chunk |
| **Produces** | Final optimized graph, `kg_readiness_report.{json,md}`, and `corpus_manifest.json` |
| **Run** | Automatically as part of `cli/extract.py --step 5` |

- Derives dependency chains by graph traversal and performs entity-local
  co-firing/conflict analysis.
- Rechecks exception and scope evidence against the full organized corpus;
  unresolved findings remain explicit and set `requires_review: true`.
- Enforces corpus integrity, canonical entity naming, uniform final schema, and
  zero dangling rule references.

### Agent 5.6 — Focused Readiness Remediation

Processes only Agent 5.5 failures, in checkpointed parallel batches, and then
reruns the deterministic readiness gates. It never forces unresolved evidence
to pass.

| | |
|---|---|
| **Consumes** | Optimized graph and Agent 5.5 readiness report |
| **Produces** | Remediated graph and `agent_5_6_remediation_report.json` |
| **Run** | Automatically when needed, or `cli/extract.py --step 5.6` |

### Agent 5.7 — Independent Grounding Verifier

Projects every final rule into atomic executable claims and independently
checks each claim against the cited organized source. The stage cannot rewrite
claims and fails closed on unsupported, contradicted, missing, duplicate, or
invalidly cited results.

| | |
|---|---|
| **Consumes** | Final optimized graph and organized source corpus |
| **Produces** | Grounded graph, `kg_grounding_report.{json,md}`, and a reusable JSONL checkpoint |
| **Run** | Automatically after readiness, or `cli/extract.py --step 5.7` |

### Agent 6 — Dependency DAG Generation

Partitions every rule into one or more directed acyclic graphs built from the
dependency edges Agent 5 computed. No LLM calls — purely deterministic graph
construction (see `utils/dag_builder.py`).

| | |
|---|---|
| **Consumes** | Agent 5's optimized KG (or Agent 4 output directly under `--skip-optimize`, with no dependency edges to build from) |
| **Produces** | `agent-6-dag-generation/dependency_dags.json` and `dag_generation_report.md` |
| **Run** | `.venv/bin/python cli/extract.py --step 6` |

- Every rule is assigned to exactly one weakly-connected dependency component,
  which becomes one output DAG — a rule with no dependencies becomes its own
  single-node DAG. This is a structural guarantee, not a best-effort pass: the
  union of every generated DAG's rules always equals the full rule set.
- A dependency cycle (Kosaraju's algorithm detects any strongly-connected
  component of size > 1) is condensed into a single `cycle_groups` node so the
  emitted DAG stays acyclic without dropping any rule from it.
- Fails the extraction pass (nonzero exit) if the coverage check ever finds a
  missing or duplicated rule — this should be unreachable given the
  partitioning algorithm, but the step does not just trust that.

### Agent 7 — Visualization & Report

Generates an interactive HTML visualization and report. No LLM calls.

| | |
|---|---|
| **Consumes** | Agent 5.7-certified optimized KG, or explicitly uncertified Agent 4 output with `--skip-optimize` |
| **Produces** | `agent-6-visualization-and-report/<source>_knowledge_graph.html` |
| **Run** | `.venv/bin/python cli/extract.py --step 7` |

- Interactive network graph (vis.js), color-coded by rule type.
- Searchable, sortable rules table with a dependency evidence column.
- Self-contained HTML with a statistics dashboard.
- Refuses optimized input when its Agent 5.7 graph/corpus certificate is absent,
  failed, or stale.

---

## Comparison agents (7–10)

These agents run via `cli/compare.py` and operate on two optimized graphs
(`--g1`, `--g2`). Use `--list` to see available graphs.

### Agent 7 — Rule-Type Clusterer

Groups rules from both graphs by behavior (the "how" dimension) so comparison
happens within like-for-like clusters. No LLM calls.

| | |
|---|---|
| **Consumes** | Two optimized KGs (G1, G2) |
| **Produces** | `_merged/<g1>_<g2>/agent-7-rule-clusters/rule_clusters.json` |
| **Run** | `.venv/bin/python cli/compare.py --g1 <g1> --g2 <g2>` |

Eight rule behaviors:

| Behavior | Description | Example |
|----------|-------------|---------|
| `formula` | Defines a calculation | DTI = Total Debt / Income |
| `classification` | Defines a category | Property Type: SFR, Condo |
| `threshold` | Numeric min/max limit | LTV ≤ 97% |
| `prohibition` | Forbids something | No prepayment penalties |
| `timing` | Deadline or time window | Appraisal valid 120 days |
| `sequence` | Specific order | Inspect → Appraise → Underwrite |
| `method` | How to verify or execute | Use automated underwriting |
| `mandate` | Requires existence | Flood insurance required |

Ten rule domains: borrower, income, property, loan, appraisal, underwriting,
documentation, closing, servicing, compliance.

### Agent 8 — Semantic Rule Matcher

Compares rules within each behavior cluster using LLM semantic matching.

| | |
|---|---|
| **Consumes** | Rule clusters from Agent 7 |
| **Produces** | `agent-8-rule-matches/match_results.json` |
| **Run** | `.venv/bin/python cli/compare.py --g1 <g1> --g2 <g2> --workers 15 --batch-size 10` |

- Batched parallel processing (10 rule pairs per LLM call) via `ThreadPoolExecutor`.
- Workers and batch size are configurable with `--workers` and `--batch-size`.
- Emits a confidence score for each match.

| Classification | Description | Action |
|----------------|-------------|--------|
| `IDENTICAL` | Same rule, same thresholds | Merge (keep one) |
| `EQUIVALENT` | Same practical effect | Merge with a note |
| `CONTRADICTORY` | Conflicting requirements | Flag for review |
| `UNRELATED` | No meaningful connection | Keep separate |

### Agent 9 — Set Operations

Computes set operations from the match results. No LLM calls.

| | |
|---|---|
| **Consumes** | Match results from Agent 8 |
| **Produces** | Five JSON files in `agent-9-set-operations/` |
| **Run** | `.venv/bin/python cli/compare.py --g1 <g1> --g2 <g2>` |

| Operation | Symbol | Description | Output |
|-----------|--------|-------------|--------|
| Intersection | G1 ∩ G2 | Rules in both graphs | `intersection.json` |
| Left difference | G1 − G2 | Rules only in G1 | `g1_minus_g2.json` |
| Right difference | G2 − G1 | Rules only in G2 | `g2_minus_g1.json` |
| Union | G1 ∪ G2 | All unique rules | `union.json` |
| Contradictions | G1 ⊕ G2 | Conflicting pairs | `contradictions.json` |

### Agent 10 — Set Visualization

Renders an HTML view for each set-operation result. No LLM calls.

| | |
|---|---|
| **Consumes** | Set-operation results from Agent 9 |
| **Produces** | Six HTML files in `agent-10-visualizations/` |
| **Run** | `.venv/bin/python cli/compare.py --g1 <g1> --g2 <g2>` |

| File | Contents |
|------|----------|
| `index.html` | Summary dashboard with Venn diagram |
| `intersection.html` | G1 ∩ G2 rules |
| `g1_minus_g2.html` | G1 − G2 rules |
| `g2_minus_g1.html` | G2 − G1 rules |
| `union.html` | G1 ∪ G2 rules |
| `contradictions.html` | Conflicting rule pairs |

Node shapes encode origin: ellipse for matched rules, rectangle for G1-only,
circle for G2-only.

---

## Configuration

LLM-using agents read their model from `config.json` (copy from
`config.example.json`; override the path with `P2K_CONFIG_PATH`). All values are
also editable from the UI Settings page.

```json
{
  "openai": {
    "models": {
      "reasoning": "gpt-5.2",
      "reasoning_effort": "medium",
      "optimizer": "gpt-5.2",
      "embeddings": "text-embedding-ada-002"
    }
  },
  "optimizer": { "model": "gpt-5-mini" }
}
```

Worker counts and batch sizes:

| Agent | Setting | Default | Set via |
|-------|---------|---------|---------|
| 3 | workers | 30 | `pipeline.max_workers` in `config.json` (or `MAX_WORKERS` env) |
| 3 | `rules_per_batch` | 10 | `config.json` |
| 8 | workers | 31 | `--workers` (falls back to `join_graphs.max_workers`) |
| 8 | `batch_size` | 10 | `--batch-size` (falls back to `join_graphs.batch_size`) |

## Run commands

```bash
# Extraction (agents 1–7)
.venv/bin/python cli/extract.py --provider openai            # full pipeline
.venv/bin/python cli/extract.py --file compliance-files/<batch>/<file>.pdf --provider openai
.venv/bin/python cli/extract.py --batch-dir <domain> --domain <domain> --target-rules 300 --workers 30
.venv/bin/python cli/extract.py --step 3 --provider openai   # single step

# Comparison (agents 7–10)
.venv/bin/python cli/compare.py --list
.venv/bin/python cli/compare.py --g1 <graphA> --g2 <graphB> --workers 15
```

## Related

- [agents/experimental/README.md](experimental/README.md) — non-pipeline prototypes
- [../README.md](../README.md) — pipeline app overview
- [../prompts/README.md](../prompts/README.md) — prompt packs and domain overrides
