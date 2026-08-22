# Pipeline Knowledge-Graph Re-extraction Plan

**Status:** proposed; implementation and re-extraction are unrun.

**Scope:** `apps/pipeline` only. This plan changes the six-agent extraction workflow, its prompt packs, graph contract, validation, optimization, reporting, and tests. It does **not** change PolicyIR, DMN, BPMN, or any downstream compiler. Those are consumers of a better graph and are outside this team's delivery. The `apps/pipeline-p2c` compiler that previously consumed this graph was removed from the repository; see [the NeurIPS execution plan](neurips-2027-execution-plan.md) for what that costs a study built on it.

## 1. Decision and outcome

The next extraction pass must produce a versioned, structured knowledge graph instead of treating prose fields as executable semantics. Every extracted rule is retained, including incomplete ones. A rule with an unmet requirement is marked `requires_review: true` and lists its failed requirement section numbers; it is never silently dropped or treated as final.

The work is complete when the optimized graph reports, for every rule, the eight readiness checks requested by the consuming team:

1. typed atomic conditions and variables;
2. dependency chains, conflicts, and recommended hit policy;
3. explicit versioning status;
4. source-derived applicability scope;
5. responsible party and counterparties;
6. structured exceptions and exception basis;
7. source-fidelity re-extraction where required; and
8. typed test vectors, including numeric boundaries.

This is a graph-quality contract. It does not claim that a downstream model can or will compile every graph rule.

## 2. Observed baseline

The committed Fannie Mae optimized graph contains 384 rules. Its current shape does not meet the requested contract:

- conditions, consequences, and exceptions are prose strings;
- `data_points_required` contains untyped names rather than typed variable objects (the request's term `entries` maps to this current field);
- 339 dependency edges exist, while `dependency_chains` and `conflicts` are empty;
- `expiration_date` and `superseded_by` are null for all rules;
- repeated loan and occupancy values indicate a scope fallback rather than per-rule source derivation;
- no rule identifies an accountable actor;
- “None stated” does not distinguish an explicit source statement from a missing extraction;
- some source references are unverified or have weak text-match scores; and
- examples are narrative, not machine-checkable test vectors.

The implementation must preserve original rule text and source references for traceability while introducing the v2 structured fields. A compatibility view may retain legacy display fields, but no new canonical field may depend on an untyped prose fallback.

## 3. Canonical v2 rule contract

Agent 3 emits the canonical candidate and subsequent agents preserve or enrich it. Names below are the required graph fields; field-level source evidence is needed wherever a value was extracted or inferred.

```json
{
  "schema_version": "2.0",
  "rule_id": "stable-rule-id",
  "condition_predicates": [
    {
      "predicate_id": "p1",
      "variable": "price_differential_amount",
      "operator": ">=",
      "value": "designated_threshold_amount",
      "value_type": "variable_reference"
    }
  ],
  "condition_logic": {"predicate_ref": "p1"},
  "variables": [
    {
      "name": "price_differential_amount",
      "type": "number",
      "unit": "USD",
      "allowed_range": [0, null],
      "role": "input"
    }
  ],
  "recommended_hit_policy": "UNIQUE",
  "versioning_status": "current_no_known_supersession",
  "expiration_date": null,
  "superseded_by": null,
  "versioning_evidence": {"corpus_run_id": "corpus-run-id", "section_id": "section-id", "section_revision_date": "YYYY-MM-DD", "evidence": []},
  "applicability_scope": {},
  "scope_basis": "inferred",
  "responsible_party": "SELLER_SERVICER",
  "counterparties": ["FANNIE_MAE"],
  "exceptions": [],
  "exception_basis": "explicitly_none_in_source",
  "test_vectors": [],
  "readiness": {
    "checks": {},
    "failed_sections": [],
    "requires_review": false
  }
}
```

### 3.1 Conditions and variables (requirement 1)

Each `condition_predicates` item represents exactly one atomic comparison for one variable. `operator` is constrained to a documented vocabulary such as `==`, `!=`, `>`, `>=`, `<`, `<=`, `in`, and `not_in`; it is never prose. `value_type` distinguishes a number, boolean, date, enum literal, string, range, list, or variable reference.

For a pure conjunction or disjunction, `condition_logic` may be `"AND"` or `"OR"`. Mixed logic must be an explicit tree whose leaves reference predicate IDs, for example:

```json
{
  "all": [
    {"predicate_ref": "p1"},
    {"any": [{"predicate_ref": "p2"}, {"predicate_ref": "p3"}]}
  ]
}
```

Every condition variable and every structured outcome variable must appear once in `variables`. Allowed canonical types are `number`, `boolean`, `enum`, `date`, `date_time`, `duration`, and `string`; `string` is permitted only for genuine free text. Numbers carry units where applicable, enums carry `allowed_values`, and each variable has an input, derived, or output role.

### 3.2 Dependencies, conflicts, and hit policy (requirement 2)

Agent 5 must construct dependency chains from the complete dependency graph, not a sampled batch. A chain is an ordered `rule_id` sequence and is emitted for prerequisite and conditional dependencies.

For simultaneously applicable rules on the same entity with incompatible or ambiguous outcomes, emit:

```json
{
  "rule_a": "rule-a",
  "rule_b": "rule-b",
  "conflict_type": "overlapping_scope",
  "resolution": "requires_manual_adjudication",
  "evidence": []
}
```

Each rule receives `recommended_hit_policy` from `UNIQUE`, `FIRST`, `PRIORITY`, `COLLECT`, or `ANY`, with a rationale and supporting dependency/conflict IDs. If the analyzer cannot establish one safely, it records `requires_manual_adjudication` and fails requirement 2; it must not default to `UNIQUE`.

### 3.3 Version and scope (requirements 3–4)

Every rule has either an explicit `expiration_date`/`superseded_by`, or `versioning_status: "current_no_known_supersession"`. The latter means that the checked source corpus contains no known replacement; it is not a claim about all external publications. Store the corpus run ID, section ID, section revision date, and comparison evidence used for that result.

`applicability_scope` is re-derived from the cited source text per rule. Its `scope_basis` is:

- `explicitly_universal_in_source` only when the source supports universality;
- `inferred` only with an `inference_reasoning` field and source evidence.

Silence is not evidence of universality. If neither value can be supported, the rule fails requirement 4 and remains in the review queue.

### 3.4 Parties and exceptions (requirements 5–6)

`responsible_party` and every `counterparties` item must resolve to an existing Agent-2 `entity_types` identifier. They also carry source evidence. If a source does not identify an accountable party, leave the field null, mark the rule for review, and do not guess from rule wording.

Exceptions use the same typed predicate contract as conditions. `exceptions: []` is permitted only with `exception_basis: "explicitly_none_in_source"` when the source establishes that result. Otherwise use `"not_found_in_chunk_recheck_needed"`, re-run against the full source document, and retain `requires_review: true` until resolved.

### 3.5 Source fidelity and test vectors (requirements 7–8)

When `text_match_score < 0.5` **or** `reference_verified` is false, Agent 3.5 queues re-extraction directly from `source_reference.chunk_path`. The recovered candidate replaces neither the original nor its audit history: it is linked as a new attempt, and the rule remains review-required until it passes.

Each rule has at least one typed test vector:

```json
{
  "inputs": {"mbs_pass_through_rate": 8.125, "original_trade_amount": 450000},
  "expected_output": {"maximum_number_of_pools": 3},
  "vector_basis": "source_attested | derived_from_source",
  "evidence": []
}
```

Every numeric rule also has a boundary vector at an attested threshold. A model may not invent test values or expected results: unsupported vectors fail requirement 8.

## 4. Agent-by-agent changes

| Stage | Change | Required output/control |
| --- | --- | --- |
| Agent 1 | Record stable document/chunk IDs, content hashes, section IDs, source path, and extractable text boundaries. | Immutable source manifest for re-extraction and revision comparison. |
| Agent 2 | Read the full corpus rather than the first ten documents only; emit typed entity types, actor candidates, variable definitions, units, enum values, and citations. | Existing entity vocabulary becomes the only allowed party vocabulary. |
| Agent 3 | Replace prose-only extraction with the v2 rule contract; use a shared schema in every base/domain prompt. | Structured condition/exceptions, variables, scope, parties, version evidence, and vectors. |
| Agent 3.5 | Validate all eight requirements; re-extract weak/unverified references; prevent false final status. | Per-rule checks, failed sections, rework attempts, and review queue. |
| Agent 4 | Merge entity data without flattening structured rule fields or losing field-level evidence. | Referential integrity and legacy-display fields derived from v2 only. |
| Agent 5 | Deduplicate only equivalent typed semantics; analyze all dependency batches plus cross-batch edges; generate chains/conflicts/hit policies. | Complete dependency details and no silent conflict default. |
| Agent 6 | Render structured fields and the readiness matrix in JSON/HTML. | Total counts reconcile: passed, review-required, and re-extraction pending. |

The existing Agent 3.5 continuation behavior is a defect for this contract. The pipeline may continue to produce a graph for review, but it must never label the output optimizer-final when unresolved requirement failures exist.

## 5. Prompt and routing work

`utils/prompt_manager.py` resolves a domain override before the base prompt. Therefore update the base prompt **and** all active domain copies:

- `prompts/business_rules_extraction.txt`;
- `domain-prompts/mortgage/business_rules_extraction.txt`;
- `domain-prompts/aml/business_rules_extraction.txt`;
- `domain-prompts/healthcare/business_rules_extraction.txt`; and
- `domain-prompts/commercial_lending/business_rules_extraction.txt`.

Likewise update `entity_extraction`, `entity_refinement`, `dependency_analysis`, `rule_deduplication`, and `validation_report` prompt families where they define or consume the changed fields. The implementation must eliminate the current domain-dependent core shapes, particularly AML's array/object variants and the other packs' prose-string variants.

The prompts define guidance, not trust. Agent code validates the model response against the v2 schema before persisting it.

## 6. Delivery sequence

1. **Contract and fixtures.** Add a versioned JSON Schema, migration rules, and fixtures for atomic conditions, nested logic, typed values, conflicts, versioning, scope, parties, exception recheck, weak citations, and numeric boundaries.
2. **Source identity and ontology.** Implement Agent-1 manifest fields and Agent-2 full-corpus typed vocabulary with deterministic tests.
3. **Structured extraction.** Update Agent 3, prompts, parsing, and Agent 4 preservation. Reject malformed structured responses into a reviewable failure record, not a prose fallback.
4. **Validation and rework.** Implement all eight checks, full-document exception recheck, the 0.5 source threshold, and non-final review status.
5. **Optimization.** Implement semantic-safe deduplication and complete dependency-chain/conflict/hit-policy analysis.
6. **Reporting and migration.** Update Agent 6, consumers, documentation, and legacy-display compatibility. Re-run the full corpus only after fixture and unit gates pass.

Each step is a dedicated pull request. No change is made directly on `main`, and each pull request remains open for human review and merge.

## 7. Acceptance criteria and validation

The implementation PRs must add offline deterministic tests covering:

- every domain prompt resolves to the same core v2 schema;
- nested `AND`/`OR` conditions preserve predicate references;
- all referenced variables are typed and every numeric boundary vector matches a typed threshold;
- no unsupported scope fallback becomes universal;
- missing party/exception/version evidence fails the appropriate section;
- `< 0.5` and unverified references queue re-extraction and set review status;
- dependency chains and conflicts are generated across more than one batch;
- deduplication cannot merge rules that differ by structured logic, scope, version, exception, party, output, or evidence; and
- Agent 6 reports every input rule exactly once as passed or review-required.

Run at least:

```bash
cd apps/pipeline
.venv/bin/python -m pytest tests/ -q
git diff --check
```

Before calling a corpus output final, produce a run manifest and a coverage report with the total rule count and counts for each readiness check, failed section, re-extraction outcome, dependency chain, conflict, and hit-policy. The report must reconcile to the input rule total.

## 8. Risks and non-goals

- This project does not infer facts absent from a source merely to improve coverage. Review-required records are a valid outcome.
- A source chunk may be insufficient for exception or version evidence; the prescribed full-document recheck is required before final status.
- Conflict and scope inference are high-risk model tasks. Their rationale and evidence must remain inspectable, and unresolved cases must remain manual.
- Existing generated graphs are historical inputs, not proof that newly structured fields are correct. A fresh manifest-backed re-extraction is required to validate the new contract.
- Downstream modeling, compilation, or runtime execution is explicitly outside this plan and must not be introduced as part of this pipeline change.
