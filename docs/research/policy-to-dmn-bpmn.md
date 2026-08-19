# Policy-to-DMN/BPMN Pipeline Redesign Plan

**Status:** proposed and unrun.

**Repository baseline reviewed:** `origin/main` at 5179de7. Nothing under `apps/` has changed between that commit and the current tip of `main`, so every observation below still holds; re-verify before implementation begins.

**Purpose:** change Policy-to-Knowledge from a prose-heavy graph generator into an evidence-bound policy compiler whose canonical intermediate representation can be projected deterministically into the existing knowledge graph, DMN 1.5, and a conservative BPMN 2.0.2 subset.

## 1. Executive decision

The current knowledge graph should not be sent directly to a DMN/BPMN exporter. Its rules are primarily natural-language records, its entity attributes are untyped names, and most execution relationships are LLM-inferred. A post-processing exporter would have to reinterpret prose and invent missing process semantics, reproducing the same uncertainty at a more dangerous executable layer.

Make a versioned **Policy IR v2** the canonical artifact. The existing graph becomes one projection of that IR. DMN and BPMN become two additional projections with strict compilation eligibility and explicit abstention.

```text
source documents
  -> immutable source/chunk registry
  -> evidence-anchored entity and clause candidates
  -> typed Policy IR v2
  -> fail-closed semantic and provenance validation
  -> canonicalization and evidence-preserving deduplication
  -> graph projection
  -> DMN compiler
  -> BPMN compiler
  -> traceability and compilation reports
```

The principal safety rule is: no source-supported typed semantics, no executable model element.

## 2. Review scope

This plan inspected:

- Agent 1 document organization and committed processing metadata;
- Agent 2 entity/relationship extraction, iterative refinement, default prompts, and four domain prompt families;
- Agent 3 rule extraction, source-reference recovery, IDs, confidence, and prompt schemas;
- Agent 3.5 validation and CLI continuation behavior;
- Agent 4 flattening, entity-name normalization, and merged output;
- Agent 5 deduplication and dependency inference;
- Agent 6 visualization/reporting;
- Explorer graph schema and current tests/consumer contracts; and
- all four committed optimized knowledge graphs and their Agent-1/Agent-2 artifacts.

This is a design and execution plan. It does not claim the proposed schema, compilers, tests, or evaluation results already exist.

## 3. Current pipeline: observed behavior

| Stage | Current behavior | Compilation consequence |
| --- | --- | --- |
| Agent 1 | Converts documents into text chunks and records source filename, chunk path, section hierarchy, and word counts. | Useful structure, but no immutable source/chunk SHA-256 or stable character/page offsets. Later text recovery can change word positions without a content-identity contract. |
| Agent 2 | Samples documents, asks the model for domain entities, attributes, examples, relationships, cardinality, and rule summaries, then iteratively refines them. | Entity attributes are untyped strings. The prompt explicitly encourages adding domain-knowledge attributes/examples, so observed and proposed concepts are not separated. |
| Agent 3 | Extracts a target number of rules, puts each into one domain-specific rule category, and stores condition, consequence, and exception semantics. | Most domains store executable logic as prose. A single rule_type mixes different axes such as calculation, process, prohibition, documentation, and eligibility. |
| Source recovery | Accepts a model-provided chunk/path/word range and may fuzzily search for source text to repair offsets. | Better than an unlinked citation, but unsuitable as immutable compilation evidence. Fuzzy recovery and content identity need separate, explicit status. |
| Agent 3.5 | Checks required fields, formats, sampled source-reference availability, and other quality signals. Contradiction detection is still a placeholder. | It does not prove that a condition/outcome/process model is semantically entailed. Pipeline execution can continue after validation failure. |
| Agent 4 | Flattens nested entity/relationship rules, normalizes selected entity names, and enriches rules with entity definitions. | Preserves legacy consumers, but does not create typed condition, decision, or process structures. |
| Agent 5 | Deduplicates rules and asks an LLM to infer prerequisite, sequential, conditional, complementary, contradictory, override, and validation dependencies. Cross-batch analysis samples rules. | Dependencies are useful hypotheses, not safe sequence flows or decision requirements. Truncated summaries and sampling can omit or invent execution ordering. |
| Agent 6 | Builds interactive graph/report outputs. | It is a visualization layer, not an OMG model compiler or conformance validator. |

Relevant implementation surfaces include:

- [agent_1_document_organizer.py](../../apps/pipeline/agents/agent_1_document_organizer.py)
- [agent_2_entity_extractor.py](../../apps/pipeline/agents/agent_2_entity_extractor.py)
- [agent_3_rules_extractor.py](../../apps/pipeline/agents/agent_3_rules_extractor.py)
- [agent_3_5_rule_validator.py](../../apps/pipeline/agents/agent_3_5_rule_validator.py)
- [agent_4_rules_with_entities_merger.py](../../apps/pipeline/agents/agent_4_rules_with_entities_merger.py)
- [agent_5_knowledge_graph_optimizer.py](../../apps/pipeline/agents/agent_5_knowledge_graph_optimizer.py)
- [agent_6_visualization_and_report.py](../../apps/pipeline/agents/agent_6_visualization_and_report.py)
- [utils/prompt_manager.py](../../apps/pipeline/utils/prompt_manager.py)
- [utils/config.py](../../apps/pipeline/utils/config.py)
- [cli/extract.py](../../apps/pipeline/cli/extract.py)
- [explorer/src/schema.py](../../apps/explorer/src/schema.py)

## 4. Artifact-level findings

The committed optimized graphs contain 1,481 rules:

| Corpus | Rules | Process-tagged rules | Unverified references | Dependencies |
| --- | ---: | ---: | ---: | ---: |
| Commercial lending | 386 | 0 | 134 | 397 |
| Fannie Mae | 384 | 62 | 27 | 339 |
| Freddie Mac | 371 | 123 | 25 | 214 |
| Healthcare | 340 | 0 | 70 | 380 |
| Total | 1,481 | 185 | 256 | 1,330 |

Observed structural facts:

- All 1,481 rules store conditions, consequences, and exceptions as strings.
- All have data_points_required, but those entries are names without declared data type, null behavior, units, allowed values, or derivation.
- Source references are not uniform: 73 rules use an array and 1,408 use an object.
- Agent-2 entity attributes are plain strings in all four corpora; none of the committed entity definitions has a typed entity category or typed attribute schema.
- The 185 process-tagged rules do not share a process contract containing trigger, actor, activity, input/output, precondition, postcondition, event, and end state.
- The 1,330 dependency edges are typed as prerequisite (603), conditional (249), complementary (179), override (110), sequential (95), validation (80), and contradictory (14), but all of them are model-generated hypotheses rather than source-validated control-flow semantics.
- Of 1,582 span records carrying a `text_match_score`, 247 have `reference_verified: true` while scoring below 0.6, the lowest at 0.008. The meanings of location recovery, exact match, fuzzy match, and semantic support are therefore not cleanly separated for downstream consumers.

These artifacts are historical engineering evidence. They must not be treated as proof that Policy IR v2 or generated DMN/BPMN is correct.

## 5. Prompt and schema problems to correct

### 5.1 Agent 2 mixes observation and invention

The entity prompt instructs the model to "Add 5-10 attributes per entity (use domain knowledge)" ([entity_extraction.txt](../../apps/pipeline/prompts/entity_extraction.txt)), and the refinement prompt scores entities on hitting that quota ([entity_refinement.txt](../../apps/pipeline/prompts/entity_refinement.txt)). This can improve a conceptual ontology, but it prevents a compiler from knowing which property is explicitly present in policy text.

Change the contract so every entity, attribute, event, actor, and relationship is one of:

- observed: directly supported by one or more source spans;
- normalized: deterministic normalization of an observed term;
- proposed: useful domain modeling suggestion with no source support;
- unresolved: ambiguous identity or type.

Only observed/normalized elements may participate in automatic DMN/BPMN compilation. Proposed elements remain visible in the Explorer but cannot become executable inputs, tasks, lanes, gateways, or outcomes.

### 5.2 Entity categories are missing

UPPER_CASE naming does not communicate semantics. Add explicit categories:

- actor or role;
- organization;
- system;
- business object;
- document or record;
- data element;
- event;
- activity;
- decision;
- outcome;
- authority or policy source;
- temporal concept; and
- jurisdiction or scope.

An attribute becomes a DataDefinition with:

- stable ID and display name;
- FEEL-compatible type: string, number, boolean, date, time, date-time, duration, or constrained list/context;
- unit/currency where relevant;
- allowed values or range;
- null/unknown policy;
- derivation formula reference, if explicit;
- owning entity and aliases; and
- clause-level evidence.

### 5.3 Rule type currently conflates independent dimensions

A rule can simultaneously be mandatory, prohibitive, temporal, process-related, and eligibility-related. The extraction prompt requires the model to "Classify each rule into exactly ONE of these 10 categories" ([business_rules_extraction.txt](../../apps/pipeline/prompts/business_rules_extraction.txt)), which loses information.

Replace it with orthogonal fields:

- modality: obligation, prohibition, permission, recommendation, definition;
- semantic_kind: decision_rule, calculation, validation, temporal_constraint, documentation_requirement, process_fragment, authority_statement;
- effect: allow, deny, require_action, produce_value, create_record, notify, escalate, no_direct_effect;
- lifecycle: active, future, expired, superseded, unknown;
- compilation_intent: dmn, bpmn, both, graph_only, unresolved; and
- risk classification retained as non-semantic metadata.

### 5.4 Conditions and effects are prose

The model currently returns condition/consequence/exception prose. Add a restricted expression AST:

```text
Expression =
  all(expressions)
  any(expressions)
  not(expression)
  comparison(left, operator, right)
  in(value, allowed_values)
  exists(variable)
  date_arithmetic(base, operator, duration)
  variable_ref(data_definition_id)
  literal(value, type, unit)
  function_ref(function_id, arguments)
```

Allowed comparison operators must be enumerated. The model must never emit raw FEEL, JavaScript, Python, SQL, or XML. A deterministic compiler serializes a validated AST into FEEL and XML.

Retain natural-language text for human display, but never compile from that display field.

### 5.5 IDs depend on batch position

Current rule IDs encode model-selected entity/category/batch/sequence: the prompt requires each `rule_id` to embed the batch number padded to three digits plus a sequence number. Reordering batches can change identity.

Create deterministic IDs from document hash, exact evidence span, normalized clause kind, and schema version. Maintain aliases from legacy rule IDs. A deduplicated canonical rule receives a new canonical ID plus a complete many-to-one lineage list; it never silently replaces source candidates.

### 5.6 Prompts drift by domain

The default, mortgage, AML, commercial-lending, and healthcare prompts have separate core output examples and sometimes different field shapes. Concretely, the [AML overlay](../../apps/pipeline/domain-prompts/aml/business_rules_extraction.txt) asks for `conditions` as an array and `consequences` as an object, while the base prompt and the mortgage, healthcare, and commercial-lending overlays all ask for those same fields as strings — and all 1,481 committed rules store them as strings.

Generate the core prompt contract from one versioned JSON Schema. Domain overlays may supply terminology, ontology seeds, valid scope values, and source-grounded examples, but may not redefine core field types.

## 6. Canonical Policy IR v2

Policy IR v2 is the source of truth. The graph, DMN, and BPMN files are deterministic build artifacts.

### 6.1 DocumentArtifact and EvidenceSpan

```text
DocumentArtifact:
  document_id
  source_uri
  source_sha256
  media_type
  retrieval_timestamp
  license_record_id
  parser_version

EvidenceSpan:
  evidence_id
  document_id
  chunk_id
  chunk_sha256
  page_start/page_end when available
  char_start/char_end in canonical extracted text
  exact_text
  section_path
  match_status: exact | normalized_exact | recovered | unresolved
  semantic_role: subject | condition | effect | exception | temporal | authority | cross_reference
```

Every atomic semantic claim references at least one EvidenceSpan. Word offsets may remain for compatibility, but character offsets plus content hashes become authoritative.

### 6.2 EntityType, EntityMention, and DataDefinition

Separate source mentions from canonical entities:

```text
EntityMention -> RESOLVES_TO -> EntityType
EntityType -> DECLARES -> DataDefinition
EvidenceSpan -> SUPPORTS -> EntityMention/DataDefinition
```

Entity resolution must preserve unresolved alternatives and evidence. It may not rewrite a source mention to a canonical entity without recording the mapping confidence and method.

### 6.3 AtomicPolicyClause

```text
AtomicPolicyClause:
  clause_id
  modality
  semantic_kind
  subject_ref
  action_ref
  object_ref
  condition_ast
  effect_ast
  exception_ast
  temporal_constraint
  jurisdiction_scope
  effective_period
  authority_ref
  evidence_ids by field
  validation_status
  compilation_eligibility
  abstention_reasons
```

Split compound source sentences into atomic clauses while retaining a shared source-group ID. Do not make one wide rule carry several independent conditions, actions, and exceptions.

### 6.4 DecisionModelCandidate

```text
DecisionModelCandidate:
  decision_id
  question
  input_data_refs
  output_definition
  decision_rule_refs
  required_decision_refs
  authority_refs
  proposed_hit_policy
  hit_policy_proof
  completeness_status
  dmn_eligibility
  blockers
```

A decision-table row references an AtomicPolicyClause. Hit policy is never guessed:

- UNIQUE only when non-overlap is proven by the normalized expressions;
- FIRST or PRIORITY only when source-supported ordering/priority exists;
- COLLECT only when multiple simultaneous outputs are semantically allowed and aggregation is defined;
- otherwise abstain or emit a non-executable review draft.

### 6.5 ProcessFragmentCandidate

```text
ProcessFragmentCandidate:
  fragment_id
  trigger_event
  participant_refs
  responsible_actor_ref
  activity
  input_refs
  output_refs
  precondition_ast
  postcondition_ast
  decision_ref
  temporal_constraint
  exception_or_escalation
  predecessor/successor refs
  end_state
  evidence_ids by field
  bpmn_eligibility
  blockers
```

A process tag alone is insufficient. Executable BPMN requires an explicit trigger or entry condition, an activity, responsible participant, and enough evidence to establish flow. Missing fields cause abstention or a clearly marked non-executable review fragment.

### 6.6 DependencyEdge

Replace one broad inferred-dependency space with typed layers:

- source_reference: one clause explicitly cites another source section;
- information_requirement: a decision needs input data or another decision;
- derivation: one value/formula produces another;
- temporal_precedence: one activity/event must occur before another;
- activation: one condition activates a clause/process;
- exception_to or override: one clause changes another under a condition;
- conflict: clauses cannot both hold in an overlapping scope;
- related: non-executable association.

Every edge records source, target, direction semantics, evidence, derivation method, and validation status. An LLM-inferred edge remains candidate status until deterministic/source checks admit it.

## 7. Revised pipeline

### Stage 0 — immutable ingestion manifest

Add before Agent 1:

- hash original bytes and canonical extracted text;
- record parser/chunker versions, source URI, license, and retrieval time;
- assign stable document/chunk IDs;
- preserve page and character mappings where the parser supports them; and
- fail closed if a later stage references unknown content hashes.

### Stage 1 — evidence-preserving structure extraction

Retain section hierarchy and cross-references, but treat chunking as transport rather than provenance. Include overlapping context for extraction while ensuring every emitted span maps back to canonical document coordinates.

Add a coverage ledger for every section/chunk:

- processed;
- no policy semantics found;
- candidates emitted;
- extraction failed;
- intentionally excluded; or
- unresolved.

### Stage 2 — source-grounded ontology candidates

Replace first-sample domain modeling with two outputs:

1. observed ontology candidates from the complete indexed corpus; and
2. optional proposed ontology enrichments stored outside the executable namespace.

Extract mentions before canonical entities. Require evidence for entity category, attributes, actor role, event, activity, and relationship. Resolve aliases in a separate deterministic/assisted pass.

The domain prompt should answer: what is present in the text? It should not fill a desired quota of attributes.

### Stage 3A — atomic clause extraction

Extract source-bound candidate clauses with a schema-constrained model response:

- select evidence-span IDs provided by the application;
- copy subject/action/object/condition/effect/exception fields from those spans;
- split compound clauses;
- mark missing semantics explicitly;
- never generate examples for executable fields; and
- return zero candidates when the text contains no normative, decisional, definitional, or process semantics.

Remove the instruction to extract exactly N rules and the bias toward numeric rules. Qualitative obligations, definitions, and permissions can be important even when not directly DMN-compilable.

### Stage 3B — typed normalization

Normalize candidates to Policy IR with a restricted AST. The model can propose variable mappings and expression structure, but deterministic code verifies types, operators, units, references, and evidence coverage.

Use structured output/JSON Schema. Reject unknown fields and invalid enum values. No prompt-level self-check substitutes for schema validation.

### Stage 3.5 — fail-closed evidence and semantic gate

This stage must block executable projections when:

- any semantic field lacks evidence;
- an evidence span cannot be exactly located under its declared hash;
- a numeric value, unit, date, negation, quantifier, actor, condition, or exception differs from evidence;
- a reference target cannot be resolved;
- the AST is ill-typed;
- scopes/effective periods conflict;
- a required variable lacks a type; or
- process/decision completeness gates fail.

Separate statuses:

- schema_valid;
- provenance_exact;
- semantic_supported;
- graph_eligible;
- dmn_eligible;
- bpmn_eligible.

The CLI must have an explicit fail-closed research/compiler mode. Product compatibility mode may continue to generate the legacy graph, but it must not label failed candidates executable.

### Stage 4 — resolution and canonicalization

Resolve aliases, actors, activities, events, data definitions, decisions, and cross-references. Preserve candidate-to-canonical lineage.

Move rule/entity merging from mutation of free-form dictionaries to validated Pydantic/dataclass domain objects. Write JSON only after validation.

### Stage 5 — evidence-preserving optimization

Deduplication becomes semantic only when normalized AST, effect, scope, effective period, and exception behavior are equivalent. Preserve all supporting spans and legacy IDs.

Dependency discovery order:

1. explicit source cross-reference;
2. deterministic shared-variable/formula dependency;
3. explicit temporal language;
4. validated model-assisted candidate;
5. unresolved related association.

Remove first-N cross-batch sampling from any path that can produce executable edges. Cross-batch dependency analysis currently takes `min(20, batch_size // 4)` rules from the head of each batch and truncates descriptions to a configured length, so ordering decides which pairs are ever compared. Approximate sampling may remain for Explorer suggestions but must be labeled non-executable.

### Stage 5.5 — deterministic compilers

Add a non-agent compiler package:

```text
apps/pipeline/policy_ir/
  models.py
  schema/policy-ir-v2.schema.json
  validate.py
  legacy_adapter.py
  graph_projector.py

apps/pipeline/compilers/
  dmn/
    compiler.py
    eligibility.py
    feel.py
    validate.py
  bpmn/
    compiler.py
    eligibility.py
    validate.py
  traceability.py
```

The compilers consume only admitted Policy IR. They do not call an LLM.

### Stage 6 — visualization and review

Render the graph plus DMN Decision Requirements Diagrams and BPMN review diagrams. Show:

- source evidence;
- compilation status and blocker reasons;
- legacy versus canonical IDs;
- decision/process coverage;
- unresolved conflicts; and
- executable versus review-only artifacts.

Do not present a visually valid diagram as semantically executable.

## 8. Prompt redesign

### Common prompt architecture

Replace copied full-domain contracts with:

```text
prompts/v2/
  entity_mentions.txt
  atomic_policy_clauses.txt
  policy_ir_normalization.txt
  dependency_candidates.txt
  schemas/
    entity-mention-v2.schema.json
    atomic-clause-v2.schema.json
    policy-ir-v2.schema.json

domain-prompts/<domain>/v2/
  ontology.yaml
  terminology.yaml
  scope-values.yaml
  source-grounded-examples.json
```

PromptManager should assemble a shared versioned contract plus the selected overlay and include prompt/schema hashes in every run manifest.

### Agent 2 prompt changes

Remove:

- “add 5–10 attributes” quotas;
- unsupported domain-knowledge enrichment in observed output;
- high-level business rules without evidence; and
- generic process entities that conflate an activity type with an observed process occurrence.

Add:

- evidence-span IDs;
- explicit entity category;
- mention/canonical separation;
- typed attributes;
- observed/proposed status; and
- abstention/unresolved alternatives.

### Agent 3 prompt changes

Remove:

- exactly-N rule targets;
- requirement that every rule name contain a number;
- one mutually exclusive rule_type;
- free-text-only condition/consequence/exception output;
- model-generated executable examples;
- batch-number identity; and
- self-confidence as admission evidence.

Add:

- atomic clause boundaries;
- modality and semantic kind;
- subject/action/object;
- condition/effect/exception AST;
- typed variables and units;
- explicit temporal semantics;
- field-level evidence;
- decision/process candidates;
- missing-information flags; and
- zero-output permission.

### Dependency prompt changes

Send complete normalized clause signatures, not truncated descriptions. Ask only for candidate typed edges and supporting evidence IDs. Reject edges that cite text not supplied to the call.

Never ask a model to decide BPMN gateways, DMN hit policies, sequence flow, or executable FEEL directly.

## 9. Deterministic DMN 1.5 mapping

Target the current formal [OMG DMN 1.5 specification](https://www.omg.org/spec/DMN/1.5/About-DMN) (`formal/24-01-01`, adopted August 2024), not the DMN 1.6 or 1.7 beta revisions that OMG also lists. Validate generated XML using the official DMN 1.5 XSD and diagram-interchange schema.

| Policy IR | DMN 1.5 element |
| --- | --- |
| DataDefinition | itemDefinition and inputData |
| DecisionModelCandidate | decision |
| Decision dependency | informationRequirement |
| Authority/policy source | knowledgeSource and authorityRequirement where semantically appropriate |
| Reusable explicit formula/function | businessKnowledgeModel |
| Atomic decision clauses | decisionTable rules or literalExpression |
| Condition AST | deterministic FEEL unary tests/expressions |
| Output definition/effect | output clause/result |
| Explicit priority/aggregation semantics | hit policy |
| Evidence and lineage | external traceability manifest plus standards-valid extension metadata when used |

DMN eligibility requires:

- typed inputs and output;
- complete expression AST;
- defined null/unknown behavior;
- a provable hit policy;
- no unresolved conflict/exception;
- exact evidence for every row; and
- successful XSD, FEEL parse, and reference evaluation tests.

If the rule is qualitative, advisory, or lacks a decision output, retain it in the graph and compilation report; do not force it into a decision table.

## 10. Conservative BPMN 2.0.2 mapping

Target the current formal [OMG BPMN 2.0.2 specification](https://www.omg.org/spec/BPMN/2.0.2/) (`formal/13-12-09`, January 2014, still the latest formal BPMN release) and validate against its normative XSDs (`BPMN20.xsd`, `Semantic.xsd`, `BPMNDI.xsd`, `DI.xsd`, `DC.xsd`).

| Policy IR | BPMN 2.0.2 element |
| --- | --- |
| Explicit trigger | start event or intermediate catch event |
| Actor/organization | participant and lane when responsibility is explicit |
| Activity | task/subprocess; subtype only when source semantics support it |
| DMN-backed decision invocation | business rule task plus portable external binding metadata |
| Condition branches | exclusive/inclusive gateway only when branch semantics are complete |
| Concurrent required activities | parallel gateway only when concurrency is explicit |
| Deadline/wait | timer event only when event semantics, not merely a policy date, are explicit |
| Communication | message flow only for explicit cross-participant communication |
| Exception/escalation | boundary/intermediate event only with source-supported triggering behavior |
| Temporal precedence | sequence flow only after validated process ordering |
| Completion condition | end event only when an end state is known |

BPMN eligibility requires:

- an explicit process boundary and entry;
- actor/participant responsibility;
- at least one activity;
- validated ordering;
- branch conditions that are mutually understood and have a default/incomplete-path policy;
- reachable completion or explicitly modeled continuation;
- no dangling flow nodes; and
- field-level evidence for every task, event, gateway condition, participant, and sequence relation.

A rule stating “records must be retained for five years” is an obligation and temporal constraint, not automatically a five-year timer process. A rule stating “after receiving notice, the lender must send the report within five business days” may support a process fragment if actor, trigger, activity, and timing are all evidenced.

Initial BPMN output should support two profiles:

- review: standards-valid diagram fragment with unresolved items clearly annotated;
- executable_subset: only the restricted, fully admitted subset.

Do not add vendor-specific engine extensions to the canonical file. Put engine bindings in optional profiles derived from the portable artifact.

## 11. Outputs and compatibility

Per run, produce:

```text
agent-3-policy-ir-candidates/
  candidates.jsonl
  coverage.json

agent-3-5-policy-ir-validation/
  admitted.jsonl
  rejected.jsonl
  validation-report.json

agent-4-policy-ir/
  policy-ir-v2.json
  lineage.json

agent-5-optimized/
  optimized-policy-ir-v2.json
  legacy optimized_compliance_knowledge_graph.json

agent-5-5-formal-models/
  decisions.dmn
  processes-review.bpmn
  processes-executable.bpmn when nonempty
  graph-v2.json
  traceability.json
  compilation-report.json
  manifest.json
```

Keep existing business_rules/entity_types outputs during migration. Add policy_ir_version and artifact_role to metadata. Existing Explorer/API consumers read the legacy projection until a versioned API is ready.

A legacy adapter may parse historical records into incomplete Policy IR candidates, but it must not fabricate typed expressions. Expected outcome for many legacy rules is graph_only or review_required, not automatic DMN/BPMN.

## 12. Tooling and CLI changes

Add configuration/CLI controls:

- --policy-ir-version 2
- --compile graph,dmn,bpmn
- --compiler-profile review or executable_subset
- --fail-on-invalid-ir
- --fail-on-unresolved-reference
- --legacy-output enabled during migration
- --prompt-contract-version
- --manifest-output

Pin and hash:

- JSON Schemas;
- DMN/BPMN XSDs;
- prompt templates and domain overlays;
- model IDs/parameters;
- source/chunk artifacts;
- compiler/scorer versions; and
- generated outputs.

The UI prompt editor must not allow a prompt to silently change the output schema version. A prompt/schema incompatibility fails before an API call.

## 13. Test strategy

### Contract and provenance tests

- JSON Schema accepts every valid Policy IR fixture and rejects unknown fields/types.
- Every admitted field maps to exact evidence under source/chunk hashes.
- Character offsets survive chunk overlap and normalization.
- Wrong hash, wrong span, ambiguous match, and unresolved cross-reference fail closed.
- Multi-span clauses preserve semantic roles and order.
- Legacy source_reference object/array forms import without silent loss.

### Expression and semantic tests

- AND, OR, NOT, nested exceptions, comparisons, ranges, lists, dates, durations, and units round-trip.
- Type errors such as comparing date to number fail.
- Unit conversion is allowed only through declared deterministic conversion.
- Missing/null/unknown semantics are explicit.
- Negation, modality, actor, quantity, and exception mutations change the IR or cause abstention.
- Definitions and advisory language do not become decision outputs or process tasks.

### DMN tests

- XML validates against pinned OMG DMN 1.5 XSDs.
- IDs/references are unique and resolvable.
- Generated FEEL parses without model-authored code.
- Decision tables have justified hit policies.
- Policy-IR evaluator and an independent DMN evaluator agree on conformance fixtures.
- Same admitted IR produces byte-stable canonical output.
- Overlapping rules without priority are rejected rather than assigned FIRST/PRIORITY.

### BPMN tests

- XML validates against pinned OMG BPMN 2.0.2 XSDs.
- All sequence flows connect existing flow nodes.
- Executable-subset processes have admitted entry, reachable activities, and completion/continuation.
- Gateways have valid conditions and declared defaults where required.
- Message flows cross participants; sequence flows do not cross pools.
- Business rule tasks resolve to emitted DMN decision IDs.
- A deadline alone does not create a timer event.
- Missing actor, trigger, order, or outcome prevents executable compilation.
- Same admitted IR produces byte-stable canonical output.

### Compatibility tests

- Existing graph endpoints and Explorer views continue to read the legacy projection.
- Rule/entity counts and stable legacy aliases are reported across migration.
- No source span disappears during deduplication.
- Graph v2, DMN, BPMN, and traceability files point to the same canonical IDs.
- Rollback consists of disabling v2 projection; historical v1 outputs remain readable.

Engineering conformance fixtures may be author-written because they test software semantics, not empirical paper performance. They must be labeled fixtures and never presented as a new human-labeled benchmark.

### Semantic assurance and governance boundary

Automated checks do not prove that a policy interpretation is legally correct. Keep three statuses separate:

- conformance_verified: schema, hashes, offsets, types, references, XSDs, FEEL syntax, and graph topology pass deterministic checks;
- semantically_supported: the normalized meaning passes preregistered benchmark/perturbation tests and any independent verifier, with its uncertainty recorded; and
- governance_approved: an authorized policy/process owner has approved deployment in a named operational context.

The paper may study the first two statuses without collecting new labels, using public benchmark labels and known-oracle fixtures. It must not imply governance approval. Likewise, executable_subset means technically executable under the restricted compiler profile; it does not mean legally approved or safe for unattended production deployment.

## 14. Stress-test matrix

| Threat | Test | Required result |
| --- | --- | --- |
| Prompt invents an attribute | Supply a policy with no stated account type. | Proposed attribute is isolated from executable namespace; no DMN input is generated. |
| Compound clause loses logic | “A and B unless C, except when D.” | AST preserves grouping and all exceptions or abstains. |
| Modal flip | Change must to may or must not. | Modality/effect changes; old decision/process cannot remain admitted. |
| Numeric/unit drift | Change 5 days to 5 business days or $5,000 to €5,000. | Type/unit/calendar difference is preserved or compilation blocks. |
| Scope leakage | Change state or actor. | Scope/participant/input changes; no stale model element remains. |
| Unproven hit policy | Two decision rows overlap with different outputs. | Executable DMN rejected until explicit priority/aggregation exists. |
| False process inference | Input contains a retention obligation with no workflow. | No start event, task sequence, or timer process is invented. |
| Missing process actor | Trigger/action are present, actor absent. | Review fragment may be emitted; executable BPMN is blocked. |
| Wrong dependency direction | Reverse source/target on an explicit prerequisite. | Type/direction validator rejects the edge. |
| Inferred sequence from related rules | Two rules share an entity but contain no before/after semantics. | Related graph edge allowed; BPMN sequence flow forbidden. |
| Broken cross-reference | Referenced section does not exist. | Candidate rejected or unresolved; no DMN/BPMN reference emitted. |
| Deduplication erases exception | Similar clauses differ only by exception. | They are not merged unless normalized semantics are equivalent. |
| Fuzzy evidence falsely accepted | Similar phrase exists in multiple chunks. | Match remains ambiguous/unresolved; exact compilation gate fails. |
| Domain prompt schema drift | Overlay changes core field type. | Prompt assembly fails before model invocation. |
| Legacy import overclaims | Import current prose rule through adapter. | Incomplete fields remain unknown; graph_only/review_required status. |
| XML injection/syntax | Source text contains XML/FEEL-like text. | Content is escaped as data; model text is never executed. |
| Non-deterministic generation | Compile identical admitted IR repeatedly. | Canonical DMN/BPMN hashes match exactly. |

A stress test passes only when the expected result is executable and asserted. If a row requires subjective human interpretation, move it to qualitative review and narrow the compiler claim.

## 15. Plan stress-test conclusions

The design was challenged against the current architecture:

1. **Can an exporter alone solve the problem?** No. It would parse prose again and invent decision/process semantics. Policy IR must be introduced before optimization.
2. **Can every policy rule become DMN?** No. Definitions, broad obligations, qualitative guidance, and incomplete decisions remain graph-only.
3. **Can every process-tagged rule become BPMN?** No. The present category does not guarantee trigger, actor, order, or end state.
4. **Can inferred Agent-5 dependencies become flow?** No. Sampled/truncated model inference remains candidate evidence, not control flow.
5. **Will a v2 schema break the product?** It would if replaced atomically. Dual projection and a legacy adapter provide a reversible migration.
6. **Can model confidence decide execution?** No. Admission depends on deterministic schema/provenance/semantic checks and conformance tests.
7. **Can domain customization remain?** Yes, as overlays that cannot change the central schema.
8. **Can existing artifacts validate correctness?** No. They can test import behavior and refusal boundaries; controlled fresh runs with manifests are required for claims.
9. **Does abstention reduce usefulness?** It reduces automatic coverage but makes the executable subset defensible. Coverage and blocker distributions must be reported.
10. **Is standards-valid XML enough?** No. XSD validity, reference consistency, semantic eligibility, evaluator agreement, and provenance are separate gates.

The plan is internally consistent only if these boundaries remain enforced during implementation.

## 16. Go/no-go gates

| Gate | Pass evidence | Stop condition |
| --- | --- | --- |
| 0 — contract | Policy IR v2 schema, DMN/BPMN mapping table, restricted profiles, and conformance fixtures reviewed. | A field needed for compilation has no typed/evidenced representation. |
| 1 — ingestion | Source/chunk hashes and exact canonical offsets survive parsing/chunking. | Accepted evidence cannot be reproduced from immutable content. |
| 2 — extraction | Agent 2/3 structured outputs validate; observed/proposed separation and coverage ledger work. | Prompts still invent executable semantics or require exactly-N output. |
| 3 — gate | Negative mutations fail closed; validation failure cannot reach compilers. | Any unsupported semantic field enters admitted IR. |
| 4 — graph migration | Legacy graph projection and Explorer/API compatibility tests pass. | V2 silently changes/deletes legacy semantics or lineage. |
| 5 — DMN | XSD, FEEL, hit-policy, deterministic hash, and evaluator-equivalence tests pass. | Compiler guesses a hit policy or emits unresolved decision logic. |
| 6 — BPMN review | XSD, topology, participant, and DMN-reference tests pass. | Compiler invents process boundary, actor, event, sequence, or exception. |
| 7 — executable subset | End-to-end controlled fixtures execute with expected outcomes and exact traceability. | Execution differs from Policy IR evaluator or loses provenance. |
| 8 — research run | Clean controlled run records source, prompts, schemas, models, A1–A5 manifests, compiler hashes, and failures. | Only historical artifacts or unmanifested runs support claims. |

## 17. Implementation sequence as reviewable PRs

1. **PR 1 — contracts and fixtures:** Policy IR v2 schemas, mapping specification, conformance fixtures, schema tests, no runtime switch.
2. **PR 2 — immutable ingestion:** source/chunk hashes, canonical offsets, manifest, and migration metadata.
3. **PR 3 — observed ontology:** Agent-2 mention/entity split, typed attributes, observed/proposed separation, domain overlays.
4. **PR 4 — atomic clauses:** Agent-3 structured output, deterministic IDs, coverage ledger, AST models, shared prompt contract.
5. **PR 5 — fail-closed gate:** field-level evidence validation, semantic invariants, explicit eligibility/blockers, CLI research mode.
6. **PR 6 — canonicalization/projector:** Agent-4/5 typed objects, evidence-preserving deduplication, candidate dependency layers, legacy graph projection.
7. **PR 7 — DMN compiler:** portable DMN 1.5, FEEL serializer/parser tests, XSD validation, trace manifest.
8. **PR 8 — BPMN review compiler:** portable BPMN 2.0.2 review profile, topology validation, DMN references, abstention.
9. **PR 9 — executable subset:** only after Gate 6; independent execution/equivalence tests and optional engine adapters.
10. **PR 10 — UI/reporting:** compilation eligibility, blockers, traceability, diagrams, and versioned API exposure.
11. **PR 11 — controlled study:** clean corpora, frozen manifests, evaluation harness, failure/cost/coverage report, paper artifacts.

Each PR must keep the product usable, document migrations and rollback, and add tests for every new behavior.

## 18. Recommended first two weeks

### Week 1

- Freeze Policy IR v2 vocabulary and restricted DMN/BPMN profiles.
- Build eight to twelve small conformance fixtures covering decision, calculation, obligation, process, exception, conflict, missing actor, and no-process cases.
- Add source/chunk hashing and exact span model.
- Prototype AST validation and a deterministic Policy IR evaluator.
- Define compatibility metadata and legacy aliases.

### Week 2

- Generate Agent-2/Agent-3 structured prompt contracts from schemas.
- Implement one domain overlay without changing core types.
- Build the fail-closed validator and negative mutation suite.
- Compile one admitted decision fixture to DMN 1.5 and validate it against official XSDs.
- Compile one admitted process fragment that calls that decision to BPMN 2.0.2.
- Demonstrate that retention-only and missing-actor fixtures abstain.

Do not begin full-corpus model runs before Gates 0–3 pass.

## 19. Paper implications

This redesign can strengthen the proposed research contribution:

> Evidence-gated compilation of policy text into aligned Policy IR, knowledge graph, decision models, and process models with explicit refusal when execution semantics are unsupported.

The paper should measure:

- exact field-level provenance coverage;
- Policy IR schema validity;
- natural-rule task accuracy using public labels;
- DMN/BPMN compilation coverage and blocker distribution;
- semantic equivalence between Policy IR and DMN evaluation on conformance fixtures;
- unsupported-element false acceptance under mutations;
- deterministic build reproducibility;
- model/API cost and latency; and
- graph/DMN/BPMN lineage consistency.

Do not claim DMN/BPMN semantic accuracy from visual inspection, XML validity, or legacy P2K artifacts. If no independent open gold process/decision models are available, treat formal-model generation as a standards-conformance and case-study contribution while keeping public annotated policy tasks as the paper's empirical core.

## 20. Definition of done

The redesign is complete only when:

- Policy IR v2 is versioned, typed, and canonical;
- every admitted semantic field has exact hash-bound evidence;
- prompts cannot change the core schema by domain;
- validation failure cannot reach executable compilers;
- graph, DMN, BPMN, and traceability outputs share canonical IDs;
- DMN 1.5 and BPMN 2.0.2 files validate against pinned official schemas;
- generated FEEL and XML are deterministic and never authored directly by the model;
- DMN results agree with the Policy IR evaluator on conformance fixtures;
- BPMN executable-subset topology and references pass all admission tests;
- current APIs/Explorer retain a tested legacy projection during migration;
- refusal/graph-only/review-only outcomes are first-class and reported; and
- a clean controlled run contains complete source, prompt, schema, model, stage, and compiler manifests.

## Standards references

- [OMG Decision Model and Notation 1.5](https://www.omg.org/spec/DMN/1.5/About-DMN)
- [OMG DMN machine-readable schemas and examples](https://www.omg.org/spec/DMN/machine-readable)
- [OMG Business Process Model and Notation 2.0.2](https://www.omg.org/spec/BPMN/2.0.2/)
- [OMG BPMN machine-readable schemas](https://www.omg.org/spec/BPMN/machine-readable)

Recheck formal versions and normative schema URLs when implementation begins. Verified on 19 August 2026: DMN 1.5 (`formal/24-01-01`) is the formal DMN target while DMN 1.6 and 1.7 are listed by OMG as beta, and BPMN 2.0.2 (`formal/13-12-09`) remains the latest formal BPMN release.
