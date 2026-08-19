# pipeline-p2c — evidence-bound policy compiler

`pipeline-p2c` turns a typed, evidence-anchored intermediate representation of
policy text into three deterministic projections: the legacy-compatible knowledge
graph, **DMN 1.5** decision models, and a conservative **BPMN 2.0.2** subset.

It implements the deterministic core of
[docs/research/policy-to-dmn-bpmn.md](../../docs/research/policy-to-dmn-bpmn.md).
One rule shapes everything here:

> **No source-supported typed semantics, no executable model element.**

The compiler would rather emit nothing than emit a decision table the source text
does not support. Abstention is a designed outcome, reported in full, not a
failure.

## What this app is, and is not

| It is | It is not |
| --- | --- |
| A deterministic compiler: Policy IR in, graph + DMN + BPMN out | An extraction pipeline. It calls no model and has no prompts |
| A fail-closed gate that decides what may be compiled | A legal-correctness checker |
| A conformance harness with 14 fixtures and 297 offline tests | A benchmark or a labelled dataset |
| Standards-targeted: DMN 1.5 `formal/24-01-01`, BPMN 2.0.2 `formal/13-12-09` | A BPM engine, or a certified DMN implementation |

The LLM-facing stages the plan describes (Stage 2 ontology extraction, Stage 3A
clause extraction, prompt contracts) are **not** in this app. They belong in
`apps/pipeline`, which already owns the agents. What lives here is everything the
plan requires to be deterministic and non-agentic.

## Quick start

```bash
cd apps/pipeline-p2c
pip install -r requirements-dev.txt

# Compile a built-in conformance fixture end to end
python -m cli.compile_policy --fixture notice_process --out build/

# See what the fixtures cover
python -m cli.compile_policy --list-fixtures

# Import a legacy knowledge graph as unevidenced candidates
python -m cli.compile_policy \
  --legacy-graph ../pipeline/pipeline-output/fannie_mae/agent-5-optimized/optimized_compliance_knowledge_graph.json \
  --compile graph --out build/legacy/

python -m pytest tests/ -q
```

A run writes `graph-v2.json`, `decisions.dmn`, `processes-executable.bpmn` (or
`processes-review.bpmn`), plus `traceability.json`, `compilation-report.json` and
`manifest.json`.

## How a compile run works

```text
Policy IR v2  ──►  evidence gate  ──►  admission report
                        │                    │
                        │      ┌─────────────┼─────────────┐
                        │      ▼             ▼             ▼
                        │  graph        DMN compiler   BPMN compiler
                        │  projection   (1.5)          (2.0.2 subset)
                        ▼
              traceability · compilation report · manifest
```

The gate runs first and its report is the **only** authority the compilers consult.
Policy IR records carry no verdicts of their own, so nothing can mark itself
eligible — that is what makes "fail closed" enforceable rather than aspirational.

### Layering

```text
policy_ir/     enums, expression AST, type checker, FEEL, tabular decomposition, IDs, JSON Schema
ingestion/     immutable source registry: hashes, canonical offsets, evidence spans
validation/    the fail-closed gate: provenance, semantics, eligibility, blockers
evaluation/    the reference Policy IR evaluator (three-valued logic)
compilers/     graph · DMN · BPMN · traceability · structural verification
adapters/      legacy knowledge graph → unevidenced IR candidates
fixtures/      14 conformance fixtures with declared expected outcomes
cli/           compile_policy
```

Dependencies point one way: `compilers → validation → ingestion/policy_ir`. There
are no import cycles, and `compilers/__init__.py` deliberately re-exports nothing
so it stays that way.

## The six statuses

Admission is not one boolean. Each element gets an independent set:

| Status | Means |
| --- | --- |
| `schema_valid` | Required fields present, enums known, no unknown keys |
| `provenance_exact` | Every cited span matches its document hash at its offsets |
| `semantic_supported` | Types check, numbers and modality are attested, references resolve |
| `graph_eligible` | May enter the legacy projection (deliberately permissive) |
| `dmn_eligible` | May become a decision-table row: tabular, typed, null policy declared |
| `bpmn_eligible` | May become a flow node: trigger, actor, order, end state all evidenced |

A clause can be `provenance_exact` and still fail `semantic_supported`. The graph
accepts far less than DMN does, which is how the product keeps working while the
executable subset stays small and defensible.

## What the compiler refuses to do

Each refusal below is enforced by a named blocker code and at least one test.

- **Guess a hit policy.** `UNIQUE` is emitted only when the rows are *provably*
  pairwise disjoint. The prover in `policy_ir/tabular.py` answers "provably
  disjoint" only when certain; every uncertainty reads as "may overlap", costs
  coverage and blocks the table. Overlapping rows are never quietly relabelled
  `FIRST`.
- **Turn a deadline into a timer.** A `temporal_constraint` never becomes a
  `timerEventDefinition`. "Records must be retained for 5 years" is an obligation,
  not a five-year timer process.
- **Invent a gateway.** The BPMN subset emits a single chain. Branching needs
  evidenced branch conditions and a default path, so it is refused
  (`branching_not_supported`) rather than guessed.
- **Accept a plausible number.** Every numeric, duration and date literal must
  appear in the cited evidence text. A `640` threshold cited to text saying `620`
  is refused (`literal_not_attested`).
- **Accept a flipped modal.** A clause declared `prohibition` over text that says
  "must pay" is refused (`modality_not_attested`). Negated obligations are
  stripped before obligation markers are tested, so "must not" cannot attest an
  obligation via its own substring.
- **Unify units.** A USD amount cannot be compared with a EUR threshold without a
  declared `UnitConversion`. Calendar days and business days never unify.
- **Treat missing as false.** Absent inputs are `UNKNOWN` and propagate through
  Kleene three-valued logic. Collapsing unknown into false is the easiest way to
  turn "no income figure" into "ineligible".
- **Let a model write code.** The expression AST is a closed grammar; only
  `policy_ir/feel.py` writes FEEL, from a tree the type checker already accepted.
  Source text containing `<script>` or FEEL-like text is escaped as data.
- **Fabricate evidence on legacy import.** The adapter creates no spans and no
  expressions, and classifies nothing it cannot read.

### Two profiles

`--compiler-profile executable_subset` (default) emits only fully admitted
elements. `review` additionally emits artefacts blocked by *soft* failures —
unattested values, non-exact spans, a missing responsible actor — annotated with
`REVIEW ONLY` and the blocker codes, with `isExecutable="false"`. Structural and
provenance-integrity failures are refused by both profiles. `executable_subset`
means technically executable under a restricted compiler profile; it does not mean
approved for production.

## Standards conformance

Verified on 19 August 2026 against the normative OMG schemas:

| Target | Document | Namespace |
| --- | --- | --- |
| DMN 1.5 | `formal/24-01-01` (August 2024) | `https://www.omg.org/spec/DMN/20230324/MODEL/` |
| BPMN 2.0.2 | `formal/13-12-09` (January 2014) | `http://www.omg.org/spec/BPMN/20100524/MODEL` |

DMN 1.6 and 1.7 exist but OMG lists them as **beta**, so they are not targeted.

The schemas are not committed — they are OMG documents, and `schemas/PINNED.json`
records the URL and SHA-256 of each file this compiler was verified against.
Default tests are offline and use the structural validators in
`compilers/verify.py`. Full XSD validation is an explicit step:

```bash
python scripts/fetch_schemas.py --into schemas/omg
python -m pytest tests/ --xsd-dir schemas/omg
```

DMN and BPMN each ship their own `DC.xsd`/`DI.xsd` with **different** target
namespaces, so the fetch script keeps them in separate directories. Sharing one
directory makes the DMN schema fail to compile.

## Trusting the DMN output

XSD validity proves shape, not meaning. So the test suite reaches a decision's
semantics by two independent routes and requires them to agree:

1. `evaluation/evaluator.py` evaluates the Policy IR AST directly.
2. `compilers/dmn_reference.py` reads the emitted XML back, parses its FEEL unary
   tests, and evaluates the decision table.

They share no code. A serialiser bug shows up as a disagreement instead of two
matching wrong answers, which a round trip through the same AST would hide.
`tests/test_dmn.py` runs the cross-check over a grid of inputs per fixture.

This is a *reference* implementation, not a certified engine. Agreement with a
third-party DMN engine remains future work and is stated as such.

## Determinism

Identical Policy IR plus an identical profile produces byte-identical artefacts.
IDs are derived from content — document hash, evidence span, clause kind, schema
version — never from batch position, so reordering inputs cannot change identity.
Nothing writes a timestamp unless the caller passes `--run-timestamp`.
`tests/test_stress_matrix.py::test_non_deterministic_generation_is_ruled_out`
asserts it end to end.

## Legacy compatibility, measured

`tests/test_compatibility.py` runs the adapter over all four committed corpora —
1,481 real rules — and asserts the plan's predicted outcome:

| Corpus | Rules | Reach the graph | DMN | BPMN |
| --- | ---: | ---: | ---: | ---: |
| Commercial lending | 386 | 386 | 0 | 0 |
| Fannie Mae | 384 | 384 | 0 | 0 |
| Freddie Mac | 371 | 371 | 0 | 0 |
| Healthcare | 340 | 340 | 0 | 0 |

Every legacy rule keeps working in the graph and its historical `rule_id` survives
as an alias; none of them becomes executable, because none carries hash-bound
evidence or a typed expression. A change that made this table look better would be
the bug.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Run completed. Refusals are reported, not fatal |
| `1` | Something that *was* emitted failed a structural check |
| `2` | The Policy IR itself is malformed (with `--fail-on-invalid-ir`) |
| `3` | A `--fail-on-*` condition the caller asked about was met |

## Known limits

Stated plainly, because the whole point of the app is not overstating things:

- **Attestation is a surface check.** Finding "620" in a cited span does not prove
  the span *means* "credit score at least 620". It catches fabricated values, not
  misread ones.
- **Modality attestation is keyword-based.** It catches a flipped modal; it does
  not parse the sentence.
- **No gateways, no boundary events.** The BPMN subset is a single chain. Fragments
  needing branching or escalation are refused, not approximated.
- **Year/month durations are rejected.** `P1M` is calendar-dependent; guessing
  30 days would be exactly the drift the gate exists to stop.
- **Business-day arithmetic has no portable FEEL form.** It evaluates in the
  reference evaluator (Monday–Friday minus supplied holidays) but cannot be
  compiled; declare a deterministic function instead.
- **No third-party engine cross-check yet.** See "Trusting the DMN output".
- **`conformance_verified` ≠ `semantically_supported` ≠ `governance_approved`.**
  This app only ever claims the first, and every report says so.

## Testing

```bash
python -m pytest tests/ -q                      # 297 offline tests
python -m pytest tests/ -q --xsd-dir schemas/omg  # + 8 XSD conformance tests
```

Test files map onto the plan's test strategy: `test_contracts.py` (contract and
provenance), `test_expressions.py` (expression and semantic), `test_dmn.py`,
`test_bpmn.py`, `test_compatibility.py`, `test_gate.py`, `test_stress_matrix.py`
(one test per stress-matrix row), `test_cli.py`, `test_xsd_conformance.py`.

Everything is deterministic and offline: no network, no credentials, no model
calls, no uncommitted local data.
