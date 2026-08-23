# Knowledge to Code: Compiling the Knowledge Graph into Executable DMN and BPMN

## Goal

Turn a grounding-certified knowledge graph into **executable, standards-valid
DMN 1.3 decision models and BPMN 2.0 process models**, where "executable" means
a third-party engine can load the artifact and reproduce the same decisions the
graph asserts, and "correct" means every emitted artifact is verified against
the rules' own source-attested test vectors before it is published.

This complement changes `apps/pipeline` only. It consumes the Agent 5.7-certified
graph and the Agent 6 dependency DAGs; it does not modify any extraction stage.

---

## Feasibility verdict

**Feasible, with one hard precondition.** The v2 rule contract already carries
essentially everything DMN needs. I measured this rather than assumed it, by
building a throwaway generator and running it over a real 352-rule certified
graph (`pipeline-output/fannie_mae_readiness_20260821/`):

| Measurement | Result |
| --- | ---: |
| Rules with complete DMN-critical structure (`condition_predicates`, `condition_logic`, `outcomes`, `variables`, `test_vectors`, `recommended_hit_policy`, `execution`) | **352/352 (100%)** |
| Rules that emitted well-formed DMN 1.3 XML | **352/352 (100%)** |
| Predicate/outcome literals that could not be rendered as FEEL | **0 of 1,385** |
| Distinct operators in use (all FEEL-expressible) | 8 (`==`,`!=`,`<`,`<=`,`>`,`>=`,`in`,`not_in`) |
| Outcome operators in use | 1 (`=`) |
| Nested boolean logic → DMN rows via DNF expansion | 429 rows from 352 rules; **87.5% are single-row**; worst case 7 rows |
| Rules requiring negation handling (`none`/`not` nodes) | **0** |
| **Test vectors reproduced by the generated row logic** | **361/384 (94.0%)** |
| Vectors where a rule fired but produced a *wrong* value | **0** |

The 23 non-passing vectors are fully accounted for and none indicate a broken
condition→outcome mapping: 12 are *negative* vectors (they deliberately assert
the else-case, which a single-rule table has no row for), 3 are outcomes whose
value is a `variable_reference` rather than a literal, and the remainder are
artifacts of the spike's own pass/fail check rather than of the data.

**The hard precondition:** this only works on v2 graphs, and today almost no
graph in the repo is v2. See the next section — this is the real project risk,
not the DMN generation itself.

BPMN is a materially weaker story than DMN and is scoped accordingly below.

---

## What exists today

Verified by reading the code, not inferred from names.

| Capability | Status |
| --- | --- |
| v2 rule contract + validator (`utils/rule_contract.py`) | Implemented, unit-tested. Closed enums for operators, value types, variable roles, hit policies. |
| Typed predicates/outcomes/variables/test vectors per rule | Implemented (Agent 3 + `prompts/rule_contract_v2.txt`) |
| Four-invariant readiness gate (Agent 5.5) | Implemented: `corpus_integrity`, `naming_consistency`, `schema_consistency`, `referential_integrity` — all hard gates (`SystemExit(2)`) |
| Entity-local co-firing conflict analysis | Implemented (Agent 5.5); conflict remediation + forced `COLLECT` hit policy (Agent 5.6) |
| Independent claim-level grounding certification | Implemented (Agent 5.7), including claims over `recommended_hit_policy` and the `execution` block itself |
| Dependency DAG partition with 100% rule coverage | Implemented (Agent 6, `utils/dag_builder.py`) |
| **DMN/BPMN "projection"** | **Only a 12-line mechanical JSON hint** — `_project_execution()` in `agent_5_5_executable_readiness.py` emits `{targets, dmn:{input_columns, output_columns, hit_policy}, bpmn:{gateway_type, lane, true_path_outcome_variables}}` |
| DMN XML, BPMN XML, FEEL expressions, decision tables | **Do not exist anywhere in the repo.** Zero hits for `decision_table`, `FEEL`, DMN/BPMN XML generation. |

So the `execution` block is a *column manifest and a hint*, not a decision
model. Everything from there to an executable artifact is greenfield — which is
good news, because the manifest is exactly the right input for a compiler.

Available tooling: `lxml`, `Jinja2`, `pydantic` are all *present in the venv* but
**none is declared in `requirements.txt`** (they arrive transitively). A compiler
that emits XML must add its dependency explicitly rather than rely on that
accident. No FEEL/DMN engine exists — see design decision 3.

**Existing guard rail to respect:** `tests/test_inter_agent_contract_alignment.py`
contains two tests that runtime-call `_project_execution()` and assert its key
set is *exactly* what `final_rule_issues()` reads. The compiler must therefore
sit strictly downstream and treat `execution` as read-only input. Folding
compilation into `_project_execution` would break those tests and, worse, couple
artifact generation to the readiness gate.

---

## Blockers and preconditions

These are the findings that most change the shape of the plan. Two are
pre-existing defects that this work would otherwise silently inherit.

### P1 — Almost no graph in the repo is v2 (blocking)

All five canonical committed batches (`fannie_mae`, `freddie_mac`, `healthcare`,
`comercial_lending`, `_merged`) are **pure v1**: prose `conditions` /
`consequences` strings, no `condition_predicates`, no `outcomes`, no
`variables`, no `execution`. Exactly one directory in the repo has full v2
structure: the dated one-off `pipeline-output/fannie_mae_readiness_20260821/`.

A KG→code compiler is therefore not runnable on the standing corpus. Either the
canonical batches are re-run under the v2 contract, or the compiler is only ever
exercised on new runs. This is a cost/decision for you, not a technical
unknown — see Open question Q1.

### P2 — Contradictory extraction prompts undermine v2 reliability (pre-existing bug)

`agent_3_rules_extractor.py:300` builds the extraction prompt as
`f"{domain_prompt}\n\n{load_rule_contract_v2()}"`. For `mortgage`, `healthcare`,
`aml`, and `commercial_lending` there is no domain-specific
`business_rules_extraction_compact.txt`, so it falls back to the shared one —
which instructs the model to emit **v1 prose** `conditions, consequences,
exceptions`. The v2 contract appended immediately after instructs it to emit
**structured** `condition_predicates` / `condition_logic` / `outcomes` /
`variables` / `test_vectors`.

The model is handed two directly conflicting schemas in a single prompt. That
this produces usable v2 output at all is fortunate, not designed. Fixing it is
cheap and should precede any compiler work that depends on v2 fidelity.

### P3 — `contract_issues` on every rule are stale (pre-existing bug)

96.9% of rules in the certified run carry `contract_issues` (574 ×
`invalid_predicate_operator`, etc.) and 98% carry `requires_review: true`. These
are **stale**: they were annotated against pre-normalization raw model output and
never recomputed after `_normalise_rule_contract()` aliased the legacy operators
into canonical form. I verified zero predicates currently hold an invalid
operator and zero exceptions are missing a `predicate_id`; Agent 5.5's own
invariant agrees, reporting `schema_consistency: PASS — 352 rules checked; 0 v2
and 0 final-readiness contract violations`.

This matters here because a compiler must decide what to refuse. If it gates on
`contract_issues` or `requires_review` as-is, it refuses ~98% of a
structurally-clean graph. Recomputing (or clearing) the annotation after
normalization is a small fix with outsized value.

### P4 — Exception-list boolean semantics are unspecified (design blocker)

`exceptions` is an array of predicates that the contract deliberately keeps
**separate** from `condition_logic` and never merges. But nothing states whether
the array is an OR (any exception defeats the rule), an AND (all must hold), or
a set of independent single-predicate exceptions. In the corpus, 155/352 rules
have exceptions, and **125 of those introduce variables absent from
`condition_predicates`** — so the choice materially changes the DMN input
columns, not just the logic.

A compiler cannot be *correct* here by guessing. See Open question Q2.

### P5 — Not every DAG edge is a BPMN sequence flow (design blocker)

Agent 6's DAG edges carry `dependency_type`. Across the certified graph:
`prerequisite` 138, `complementary` 46, `conditional` 45, `sequential` 37,
`validation` 18, `override` 16, `contradictory` 5.

Only `prerequisite` and `sequential` (175 of 305) are genuine execution
ordering. `complementary` means "these work together" — not an order.
`contradictory` and `override` are precedence/conflict relations. Rendering all
305 edges as BPMN sequence flows would emit a confidently wrong process model.
This is the main reason BPMN is phased after DMN and scoped more narrowly.

### P6 — BPMN targeting is hardcoded to mortgage-shaped `rule_type` values (pre-existing bug)

`_project_execution()` adds a BPMN target only when
`rule_type in {"process", "validation", "compliance", "exception"}`. But
`rule_type` is **not constrained anywhere in the v2 schema or
`validate_rule_v2`** — it is a free-form string whose vocabulary each domain
prompt defines independently, and the vocabularies do not overlap. For example
`privacy_policy` uses `collection`/`sharing`/`user_choice`, and
`nda_confidentiality` uses `confidentiality_scope`/`permitted_use`.

Consequence: **for five of the eight domains, no rule can ever receive a BPMN
target**, so a BPMN compiler would silently produce nothing for them. Any
BPMN work must therefore either derive orchestration from domain-agnostic
signals (`execution.targets`, `variables[].role`, the DAG edges) or carry an
explicit per-domain `rule_type` mapping. Not a blocker for DMN, which is
domain-agnostic already.

---

## Design decisions

1. **Compile; do not re-infer.** The compiler is a deterministic
   transformation over already-certified structure. It makes **no LLM calls**.
   Every value it emits must trace to a field Agent 3–5.7 already produced and
   grounded. If the graph does not carry it, the compiler refuses rather than
   inventing it. This keeps the compliance chain intact: the model's claims were
   certified once, by Agent 5.7, against source.

2. **A separate CLI, not more extraction steps.** Add `cli/compile.py` as a
   third orchestrator beside `cli/extract.py` and `cli/compare.py`. Compilation
   is a different concern from extraction, has a different input (a *certified*
   graph, not documents), and is re-runnable independently.
   Use **prefixed stage ids `C1`–`C4`**, following the existing precedent of the
   publish flow's `P1`/`P2` ids in `WorkflowDiagram.tsx`. This deliberately
   avoids extending extraction's integer sequence into `8`/`9`, which already
   collide with `cli/compare.py`'s independent Agent 7–10 numbering (a collision
   this repo just absorbed once at step 7 — no reason to add two more).

3. **Write a bounded FEEL subset, do not adopt a FEEL engine.** The corpus uses
   8 operators, 7 variable types, and a single outcome operator. A complete FEEL
   implementation is a large dependency for a tiny surface. Instead implement
   `utils/feel.py` — a renderer plus a matching evaluator over exactly that
   subset — and make it **fail loudly** on anything outside it. The evaluator is
   what makes decision 4 possible. (A real engine can still be added later as an
   optional cross-check; see Phase C4.)

4. **Test vectors are the correctness gate, and they gate publication.** This is
   the core of the plan. Every rule carries `test_vectors` (389 over 352 rules,
   98.7% complete, `vector_basis` of `source_attested` or
   `derived_from_source`). The compiler replays every vector through the
   generated artifact and **refuses to emit** a decision whose own vectors it
   cannot reproduce. Schema-validity proves an engine will *load* the file;
   vector replay is the only thing that shows it will *decide correctly*. My
   spike already demonstrates the gate works and finds real defects (it
   surfaced the 3 `variable_reference` outcomes immediately).

   **Be precise about what this does and does not prove.** Vector replay
   establishes *artifact fidelity* — that the emitted DMN faithfully implements
   the rule as structured. It does **not** establish source fidelity, because
   Agent 5.7 LLM-verifies only 6 of its 12 claim types against actual corpus
   quotes (`description`, `condition`, `outcome`, `party`, `scope`,
   `exception`); `test_vector`, `condition_logic`, `variable`, `classification`,
   `entity_attachment`, and — notably — `execution` are checked only for
   internal self-consistency. So "5.7-certified" does not mean the DMN
   projection was verified as faithful to source text.

   The two guarantees chain, and that chain is the actual correctness argument:
   **5.7 verifies `condition_predicates` and `outcomes` against source; vector
   replay verifies the emitted DMN against `condition_predicates` and
   `outcomes`.** Neither link alone is sufficient, and the plan should not claim
   more than the composition gives.

5. **Model negative vectors explicitly.** 12 vectors assert an else-case
   outcome. A single-rule decision table has no else-row, so these must either
   drive emission of a default output row or be recognised and asserted as
   "must not fire". Silently counting them as failures (as the spike did) would
   make the gate untrustworthy and train people to ignore it.

6. **Preserve provenance into the artifact.** Each generated `<decision>` and
   BPMN element carries the originating `rule_id`, `source_reference.section_id`,
   and the Agent 5.7 grounding status as DMN `extensionElements` /
   documentation. A compliance artifact whose rows cannot be traced back to a
   cited source section is not much use in an audit.

7. **Refuse uncertified input by default.** Stage 6 (viz) already refuses to
   render an optimized graph without a matching Agent 5.7 certificate. The
   compiler adopts the same gate — emitting *executable* artifacts from
   unverified rules is strictly more dangerous than rendering a picture of them.
   An explicit `--allow-uncertified` escape hatch may exist for development, and
   must stamp every artifact it produces as uncertified.

8. **One decision per rule initially; consolidate as a separate, later step.**
   Grouping rules by output-variable signature yields 336 signatures for 352
   rules — 323 of them singletons, largest group 4. So the natural first
   emission is one small decision per rule, which is also the form that maps
   1:1 onto an independently verifiable test vector. Consolidating related
   decisions into richer multi-row tables is a genuine modelling improvement but
   a *separate* concern with its own correctness burden (see Phase C2), and it
   should not be entangled with getting provably-correct output at all.

---

## Target architecture

```text
                    Agent 5.7-certified KG            Agent 6 DAGs
                    (v2 rules + execution)        (ordering, cycle groups)
                              |                            |
        ┌─────────────────────┴────────────┬───────────────┘
        v                                  v
  [C1] DMN compiler                  [C3] BPMN compiler
   utils/feel.py                      lanes  <- responsible_party
   DNF -> rows                        tasks  <- rules (business rule task -> C1 decision)
   hit policy reconcile               flow   <- prerequisite/sequential edges ONLY
        |                                  |
        v                                  v
  agent-8-dmn/*.dmn                  agent-9-bpmn/*.bpmn
        |                                  |
        └──────────────┬───────────────────┘
                       v
        [C2] conflict-aware consolidation (optional, later)
                       v
        [C4] conformance gate: replay every test_vector;
             refuse to publish any artifact that fails
                       v
             compile_report.{json,md}
```

**Division of labour between the two standards** (this is the standard, correct
split, and the data supports it): DMN holds the *business logic* — every typed
condition→outcome mapping. BPMN holds only *orchestration* — which decision runs
when, in whose lane. A BPMN business-rule task invokes a DMN decision rather
than re-encoding its logic as gateways. This keeps the 148 BPMN-target rules
from duplicating logic already proven correct on the DMN side.

**Why the DAGs matter:** `execution.bpmn` alone gives a lane and
`gateway_type: "exclusive"` (the only value present, all 148 rules) — that is
not a process. The DAG supplies the missing ordering. Of 46 multi-rule DAGs, 32
contain at least one BPMN-target rule; 37 are single-lane (a plain process), 8
span two lanes, and 1 spans four (a collaboration with pools).

---

## Phased plan

Each phase is independently shippable and independently verifiable. Estimates
are relative effort, not calendar commitments.

### Phase C0 — Unblock the v2 path (precondition, small)

Fix the defects the compiler would otherwise inherit. Cheap, and valuable
regardless of whether the rest of this plan proceeds.

- Fix P2: give the affected domains a v2-consistent
  `business_rules_extraction_compact.txt`, or strip the prose
  `conditions`/`consequences` instruction from the shared fallback so it no
  longer contradicts the appended contract.
- Fix P3: recompute (or clear) `contract_issues` / `requires_review` after
  `_normalise_rule_contract()`, so downstream gates see live state. Add a
  regression test asserting no rule carries a `contract_issues` entry that its
  own current field values do not reproduce.
- Decide Q1 (which corpora get re-run under v2).

**Exit criteria:** one domain re-runs end to end and lands a v2 graph whose
`contract_issues` are empty and whose four invariants pass.

### Phase C1 — DMN compiler (the core; medium)

- `utils/feel.py`: FEEL renderer + evaluator over the measured subset. Explicit
  `UnsupportedFeelConstruct` on anything else — including `duration` and `range`
  value types, which the schema permits but the corpus has not exercised.
- `utils/dmn_builder.py`: `condition_logic` → DNF → decision-table rows.
  Must handle the schema's bare-string `"AND"`/`"OR"` form (absent from this
  corpus, legal per contract) rather than silently treating it as vacuous truth.
- Hit-policy reconciliation: a multi-row DNF expansion cannot claim `UNIQUE`
  unless the rows are provably disjoint. Default to proving disjointness where
  cheap and downgrading to `FIRST` otherwise (42 rules hit this), recording the
  downgrade and its reason in the report.
- `variable_reference` handling: 13 predicate comparisons and 3 outcomes compare
  or assign one variable to another. In a table cell a FEEL identifier
  reference is fine; as an *outcome* it cannot be a literal and needs either a
  DMN literal expression or an explicit refusal.
- `agents/agent_8_dmn_compiler.py` + wiring into `cli/compile.py` as `C1`.
- Emit provenance extension elements (decision 6).

**Exit criteria:** 100% of certified rules emit schema-valid DMN; ≥99% of
positive test vectors replay green; every refusal names the rule and the reason.

### Phase C2 — Conflict-aware consolidation (optional; medium)

Only worth doing if 336 single-rule decisions proves unwieldy in practice.

- Group by output-variable signature; union heterogeneous input columns with `-`
  (irrelevant) cells — all 13 current multi-rule groups need this union.
- Feed Agent 5.5's 27 detected conflicts in as *known* overlap: two rules that
  co-fire onto the same output variable must not share a `UNIQUE` table. This is
  the one place the existing conflict analysis pays off directly.
- Re-run the full vector suite after consolidation; consolidation that breaks a
  previously-green vector is rejected automatically.

### Phase C3 — BPMN compiler (harder; medium-large)

- Process scope = one BPMN process per multi-rule DAG containing BPMN-target
  rules (32 candidates).
- Lanes from `responsible_party` / `execution.bpmn.lane`; pools when a DAG spans
  participants (9 DAGs do).
- **Sequence flow from `prerequisite` and `sequential` edges only** (P5).
  `complementary` becomes no flow (or an unordered parallel branch);
  `contradictory` / `override` are reported as modelling notes, never edges.
  This filtering must be explicit and reported, since it is the single easiest
  place to emit something confidently wrong.
- Each BPMN business-rule task references its C1 decision by id — no logic is
  restated in BPMN.
- Cycle groups from Agent 6 cannot be a well-formed acyclic process; emit them
  as an explicitly flagged manual-review region rather than inventing an order.

**Exit criteria:** every emitted `.bpmn` parses against the BPMN 2.0 schema; no
process contains a cycle; every task resolves to an existing decision id.

### Phase C4 — Conformance gate and reporting (small-medium)

- Replay every vector through the *emitted artifacts* (not just the in-memory
  model), so the gate tests what actually ships.
- `compile_report.{json,md}`: per-rule emitted/refused status, hit-policy
  downgrades, unsupported constructs, vector pass/fail, and unmapped
  dependency-type edges.
- Nonzero exit on any regression, matching how stages 5.5/5.7 already fail closed.
- *Optional cross-check:* run the emitted DMN through a real third-party engine
  and diff against the internal evaluator. This is the strongest possible
  evidence and the honest answer to "is our FEEL subset right?" — but it adds a
  dependency, so it is a separate opt-in step, not a gate.

---

## Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| v2 corpus barely exists (P1) | **High** | Phase C0; treat re-running as an explicit, budgeted decision (Q1) |
| Exception semantics unspecified (P4) | **High** | Do not guess. Decide Q2, encode the choice in the contract, and let vector replay confirm it |
| BPMN edges over-interpreted (P5) | **High** | Whitelist ordering edge types; report every filtered edge |
| Extraction prompt contradiction (P2) | Medium | Phase C0; regression test that the assembled prompt names one schema |
| Compiler trusts stale review flags (P3) | Medium | Phase C0; gate on live validation, not stored annotations |
| BPMN emits nothing for 5 of 8 domains (P6) | Medium | Derive orchestration from domain-agnostic fields, or add an explicit per-domain mapping |
| "Certified" over-read as source-verified DMN | Medium | Decision 4's chain framing; report which claim types were LLM-verified vs. structural |
| XML dependency undeclared in `requirements.txt` | Low | Declare `lxml` explicitly in Phase C1 rather than relying on a transitive install |
| Consolidation silently changes semantics | Medium | Vector suite must stay green across consolidation (C2) |
| FEEL subset diverges from real engines | Medium | Bounded subset + loud failures; optional engine cross-check (C4) |
| Grounding failures on real runs | Medium | The certified run had 345/352 rules grounding-failed. Decision 7 refuses these by default — expect to confront grounding quality before shipping artifacts |
| Value types permitted but unexercised (`duration`, `range`) | Low | Fail loudly rather than guess a rendering |

---

## Open questions (need your decision)

**Q1 — Which corpora get re-run under the v2 contract?** The compiler cannot run
on the five canonical v1 batches. Options: re-run all five (highest cost, gives
a v2 standing corpus and DAG/DMN coverage everywhere), re-run one as a reference
(cheap, proves the path), or only ever compile new runs (no cost, no regression
corpus). This is a spend decision, so I did not assume one.

**Q2 — What do `exceptions` mean logically?** Given 125 rules whose exceptions
introduce new variables, the choice changes emitted input columns. My reading of
the data is that they are *defeaters* — any exception predicate holding means the
rule does not apply, i.e. effective condition = `condition_logic AND NOT(any
exception)`. In the one example I traced fully, that reading makes the exception
exactly the negation of the condition (harmlessly redundant), which is
consistent but not proof. Confirm the intended semantics, or authorise me to
derive it empirically from the vector suite and then write it into the contract.

**Q3 — One decision per rule, or consolidated tables?** Decision 8 proposes
starting 1:1 (which the data's 323 singleton signatures already favour) and
treating consolidation as optional Phase C2. Confirm, or say up front that
consolidated tables are the deliverable and C2 becomes mandatory.

**Q4 — Is BPMN in scope now, or DMN first?** DMN is demonstrated at 100%
emission / 94% vector replay today. BPMN needs the P5 semantic decisions and
delivers a weaker guarantee. I would ship C0+C1+C4 first and treat C3 as a
follow-on, but if the BPMN process model is the actual point of the exercise,
that reorders the plan.

**Q5 — Add a real DMN engine dependency?** Optional in C4. It is the only way to
truly prove engine compatibility, at the cost of a heavier dependency and a
Java/containerised runtime for most mature engines.

---

## What I verified vs. what I assumed

Stated plainly, so the plan can be trusted where it is strong and challenged
where it is thin.

**Verified by direct measurement on the real certified graph:** all field
coverage percentages; the operator/type/hit-policy inventories; DNF row counts
and worst-case blowup; FEEL literal mappability; 352/352 well-formed DMN
emission; the 361/384 vector replay and the full classification of every
non-pass; DAG/lane/dependency-type distributions; the staleness of
`contract_issues`; the absence of any existing DMN/BPMN/FEEL code.

**Read in code, not executed:** the four invariant definitions; `_project_execution`;
the v2 contract enums and validation severities; the prompt-assembly
contradiction (P2); the hardcoded `rule_type` BPMN gate (P6); which Agent 5.7
claim types reach the LLM verifier versus which are checked deterministically;
the two `_project_execution` shape tests that constrain where a compiler may sit.

**Not verified:** that a third-party engine accepts the emitted DMN (only
well-formedness and internal replay were checked — this is exactly what the
optional C4 cross-check exists to settle); BPMN emission of any kind, which is
design-only at this point; and whether re-running the v1 corpora under v2 yields
comparable rule quality.
