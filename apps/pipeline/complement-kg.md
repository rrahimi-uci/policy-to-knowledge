# Executable Knowledge-Graph Readiness Complement

## Goal

Make each final business rule directly consumable as a DMN decision-table row,
a BPMN gateway, or both. A rule is `ready` only when its conditions and
outcomes are typed and deterministic, its entity-local interactions have been
analysed, its scope and exceptions have been resolved from the available source
corpus, and every identifier and reference is valid in the final graph.

This complement changes `apps/pipeline` only.

## Design decisions

1. **Add a post-optimizer readiness completion stage (Agent 5.5).** Agent 3
   continues to extract candidate rules and Agent 5 continues to deduplicate
   and propose dependency edges. Agent 5.5 is the sole authority that stamps
   execution readiness and emits the final self-report. This avoids falsely
   treating a candidate extraction as an executable rule.
2. **Use deterministic graph and corpus checks wherever possible.** The stage
   snapshots the input cited-section set before transformation, derives chains
   from the final dependency graph, validates every reference, and validates
   one uniform schema. An LLM is used only for evidence interpretation:
   full-document exception/scope review and entity-local co-firing analysis.
3. **Never silently manufacture certainty.** A model result must cite a source
   chunk. If the complete available corpus cannot resolve a rule, the rule is
   retained, marked `requires_review: true`, and receives a machine-readable
   failure reason naming the unmet readiness requirement and evidence limit.
4. **Preserve, rather than count, the corpus.** Deduplication may merge rules,
   but their cited sections are unioned into the surviving provenance. The
   output compares input and final cited-section sets. Any difference leads
   with `Sections added`, `Sections removed`, and a reason per section.
5. **Certify the final graph independently (Agent 5.7).** Grounding is checked
   only after Agent 5.5 completion and any Agent 5.6 remediation, so the
   verifier sees the exact claims delivered to DMN/BPMN consumers. Agent 5.7
   cannot rewrite a failed claim; it can only certify it or return a concrete
   contradiction/evidence limitation.

## Final rule contract additions

All v2 rules will use the same field types and will include:

```json
{
  "execution": {
    "targets": ["DMN", "BPMN"],
    "dmn": {
      "input_columns": ["declared_input_variable"],
      "output_columns": ["declared_output_variable"],
      "hit_policy": "UNIQUE"
    },
    "bpmn": {
      "gateway_type": "exclusive",
      "lane": "CANONICAL_ENTITY_TYPE_ID",
      "true_path_outcome_variables": ["declared_output_variable"]
    }
  },
  "exception_verification": {
    "status": "explicit_in_source | explicitly_none_in_source | unresolved",
    "searched_document_ids": ["document identifier"],
    "searched_chunk_count": 0,
    "evidence": [],
    "unresolved_reason": null
  },
  "scope_derivation": {
    "status": "explicit | explicitly_universal | genuinely_unscoped | unresolved",
    "evidence": [],
    "unresolved_reason": null
  },
  "readiness": {
    "status": "ready | review_required",
    "failed_requirements": [],
    "review_reason": null
  }
}
```

`exception_basis` becomes one of `explicit_in_source`,
`explicitly_none_in_source`, or `unresolved_after_full_document_search`.
The deprecated `not_found_in_chunk_recheck_needed` is invalid in final output.
An unresolved value is not a gap label: it requires a deterministic record of
the source corpus searched plus a specific evidence limit and always fails
readiness.

`scope_basis` becomes one of `explicit`, `explicitly_universal_in_source`,
`genuinely_unscoped`, or `unresolved_after_source_review`. Inferred empty scope
is invalid in the final output. `applicability_scope` always has list-valued
`loan_types`, `occupancy_types`, and `transaction_types` keys.

## Stage 5.5 algorithm

### Inputs

- Agent 4 graph, immediately before optimizer deduplication (corpus baseline).
- Agent 5 optimized graph and dependency edges.
- The organized documents for the active run, indexed by document and chunk.

### A. Corpus, schema, names, and references

1. Build an input `CorpusManifest`: all cited `section_id` values plus every
   rule ID and reference edge from Agent 4.
2. Build the final cited-section set and compare it to the manifest. Preserve
   merged-rule references; report additions/removals and reasons prominently.
3. Establish canonical entity keys from `entity_types`. Resolve party aliases
   only through a single deterministic alias map; reject ambiguous aliases.
   Canonical keys are SCREAMING_SNAKE_CASE and all `responsible_party`,
   `counterparties`, and entity type keys must use them exactly.
4. Normalize each rule into the final v2 structure without dropping unknown
   source content. Validate field presence and JSON types for every rule.
5. Validate `depends_on_rule`, `dependent_rule`, `source_rule_id`, and
   `target_rule_id` against final rule IDs. Remove no edge silently: an invalid
   edge is retained as an invariant failure and marks both endpoint rules for
   review.

### B. Dependencies and conflicts

1. Construct the directed graph from the existing Agent 5 edges. Derive all
   bounded, canonical dependency chains deterministically using DFS; report
   cycles separately. Chains are graph output, not model invention.
2. Group rules by each attached canonical entity. For every group with more
   than one rule, send compact typed condition/outcome summaries to the
   entity-local conflict analyser. It must return one result for every reviewed
   pair: `conflict`, `non_conflict`, or `unresolved`, with rationale and cited
   rule IDs.
3. A `conflict` requires an explicit resolution: a source-supported precedence,
   mutually exclusive scope/conditions, or a BPMN/DMN routing decision. An
   unresolved conflict fails both rules. A recommended DMN hit policy is
   accepted only when supported by the conflict result and chain position.
4. Emit at least ten sampled non-conflict rationales in the report when there
   are ten multi-rule entities. The report always includes three conflicts and
   three confirmed non-conflicts when available; otherwise it states the
   actual population shortfall.

### C. Full-document exception verification

1. For each rule with the deprecated exception state, construct its full cited
   document corpus from every organized chunk for that document—not only the
   extraction chunk. The index records the count and stable digest of every
   searched chunk.
2. Search every chunk deterministically for lexical anchors from the rule,
   then present all matched passages plus the cited section to the completion
   prompt. The prompt must distinguish an explicit exception from no exception
   after corpus review; it may not call chunk silence proof.
3. Persist structured exception predicates with direct quotes for
   `explicit_in_source`; otherwise persist the completed document-search
   provenance for `explicitly_none_in_source`. If evidence is fragmented or
   the document cannot be resolved, persist an `unresolved` verification
   reason and mark the rule for review.

### D. Source-derived scope

1. Re-read the cited section and its neighboring section context, using the
   full-document index to retrieve lexical scope signals. The completion prompt
   must populate loan, occupancy, and transaction fields only from direct
   evidence.
2. Use `explicitly_universal_in_source` only with direct universal language;
   use `genuinely_unscoped` only after the relevant section/context review
   finds no scope signal. An unresolved scope is a review failure.
3. Persist before/after values and direct evidence. The final report includes
   five representative before/after examples.

### E. Executable projection and final status

1. Validate that every condition/output references a declared typed variable,
   every required enum has allowed values, and each execution target maps only
   to declared variables.
2. Generate DMN projection for decision rules and BPMN gateway projection for
   workflow/conditional rules. A rule may support either or both; it is not
   `ready` if it has neither.
3. Set `requires_review: true` only for rules with a concrete failed readiness
   requirement. Never set it blanket-wide. Rules passing every check have
   `requires_review: false` and `readiness.status: ready`.

## Output and reporting

Agent 5.5 writes:

- `optimized_compliance_knowledge_graph.json` — the final, normalized graph.
- `kg_readiness_report.json` — required counts, examples, unresolved-rule list,
  and explicit PASS/FAIL results for corpus integrity, naming consistency,
  schema consistency, and referential integrity.
- `kg_readiness_report.md` — reviewer-readable equivalent. If corpus changed,
  its first headings are `Sections added` and `Sections removed`, followed by
  reasons, before any aggregate metric.
- `corpus_manifest.json` — baseline/final section sets and per-section reasons.

## Implementation sequence

1. Extend the v2 JSON schema, contract validator, and extraction contract prompt
   with final field types and deprecated-state rejection.
2. Add a dependency/corpus utility with deterministic manifests, reference
   validation, canonical graph-chain derivation, and entity-name validation.
3. Add Agent 5.5 completion prompt and implementation. Keep LLM interactions
   injectable so tests never need a model/API key.
4. Invoke Agent 5.5 from the CLI after Agent 5 and before visualization; stream
   progress and write the reports to the run output.
5. Add unit/integration tests for all four invariants, every resolution state,
   conflict/non-conflict evidence, cycle-safe chain traversal, and report
   ordering. Update the pipeline README with the final artifact contract.

## Acceptance gates

A run fails the readiness pass if any invariant fails, a deprecated exception
state remains, an inferred-empty scope remains, any dangling reference exists,
an unresolved rule is not specifically explained, or a rule labelled `ready`
lacks an executable DMN/BPMN projection. The report may contain failing rules,
but it must clearly report the failed pass and preserve every input rule and
source citation.

## Focused remediation and performance complement

Agent 5.5 is followed by Agent 5.6 only when concrete review failures remain.
Agent 5.6 selects those rules and unresolved entity-local pairs by ID, batches
source work by cited section, may add the minimum source-backed typed inputs
needed to encode an explicit exception, and then reruns Agent 5.5's
deterministic schema, corpus, naming, reference, and readiness checks. It uses
append-only content-keyed checkpoints and stops after three passes or when the
review count no longer falls. Evidence insufficiency remains explicit review;
the stage never forces a 352/352 result.

When evidence establishes that a shared outcome is multi-valued (for example,
one special feature code is required in addition to any other applicable
codes), Agent 5.6 promotes that output to one graph-wide list contract. Every
rule using the same output name is normalized to the same type and COLLECT
policy before conflicts are re-evaluated. This prevents a source-supported
collection from remaining scalar in a neighboring rule and preserves the no
schema-drift invariant.

Pipeline throughput preserves the real dependency DAG: Agents 2 and 3 remain
sequential, Agent 3.5 overlaps Agent 4, independent documents run in isolated
subprocesses, Agents 5.5–5.7 use bounded batch requests, and a SQLite-backed
adaptive limiter coordinates subprocesses. Agent 2 stops only after measured
catalog convergence and saves its latest catalog after every iteration. The
normal CLI reads all throughput, retry, batch, token, and remediation limits
from `pipeline.performance`; environment variables are optional overrides.

## Independent grounding-certification complement

Agent 5.7 addresses a different failure mode from readiness completion. A rule
can be structurally valid, conflict-resolved, and executable while still
containing an invented threshold, inverted operator, wrong actor, unsupported
scope, or test vector that does not follow from the cited text. The verifier
therefore operates on a claim projection rather than on a single rule score.

For each final rule, the stage projects atomic claims from the description,
condition predicates and logic, outcomes, responsible party/counterparties,
scope, exceptions, and test vectors. It joins these with de-duplicated evidence
records from `source_reference`, `field_evidence`, exception verification, and
scope derivation. Before an LLM result can count, deterministic code resolves
the cited chunk and proves that the cited source text occurs in that chunk.

The independent prompt returns exactly one of `supported`, `contradicted`, or
`insufficient_evidence` for each `(rule_id, claim_id)`. Supported and
contradicted verdicts require a quote copied from the supplied evidence. The
runtime rejects invented evidence IDs/quotes, unexpected claims, duplicate
answers, and incomplete response coverage. A failure appends a specific
`grounding` readiness failure without altering the condition, outcome, scope,
exception, or party claim that caused it.

Verification is parallel at two bounded layers:

1. Claims are packed by both rule count and claim count, preventing unusually
   large rules from overflowing a request.
2. Up to 40 local batch workers schedule requests, while the shared adaptive
   limiter caps real API concurrency at the measured configured ceiling of 16
   and backs off under rate/transport pressure.

Every batch is checkpointed by model, reasoning effort, source-corpus hash, and
complete claim/evidence packet. A retry or resumed run reuses only identical
work. The final certificate binds both the organized-corpus digest and a digest
of the grounded graph. Stage 6 recomputes both digests and refuses optimized
input when the report failed, coverage is below 100%, any rule lacks certified
grounding, or either digest has drifted.

Agent 5.7 writes `kg_grounding_report.json`, `kg_grounding_report.md`, and
`agent_5_7_grounding_checkpoint.jsonl`, and embeds
`metadata.grounding_certification` into the optimized graph. These controls
reduce hallucination risk and make failures auditable; they are evidence-based
certification, not a claim that model verification is mathematically infallible.
