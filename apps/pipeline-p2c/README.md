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
| A conformance harness with 21 fixtures and 493 offline tests | A benchmark or a labelled dataset |
| Standards-targeted: DMN 1.5 `formal/24-01-01`, BPMN 2.0.2 `formal/13-12-09` | A BPM engine, or a certified DMN implementation |

The LLM-facing stages the plan describes (Stage 2 ontology extraction, Stage 3A
clause extraction, prompt contracts) are **not** in this app. They belong in
`apps/pipeline`, which already owns the agents. What lives here is everything the
plan requires to be deterministic and non-agentic.

## Quick start

```bash
cd apps/pipeline-p2c
pip install -r requirements-dev.txt

# Ingest real PDFs into a Policy IR skeleton (hashes, offsets, sections, coverage)
python -m cli.compile_policy --ingest ../pipeline/compliance-files/**/*.pdf --out build/ingest/

# …and extract evidenced, untyped clauses from them (no model involved)
python -m cli.compile_policy --ingest ../pipeline/compliance-files/**/*.pdf --extract --out build/

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

## Ingesting documents

`--ingest` turns PDFs into a Policy IR skeleton: hashed canonical text,
section-aligned chunks with real character offsets, and a coverage ledger. It emits
`policy-ir-v2.json`, which is what clause extraction consumes next. No model is
involved — this stage is entirely deterministic.

Three decisions here were forced by what the real corpus does:

**Canonical text is the whitespace-normalised extraction.** PDF extractors wrap lines
mid-sentence, so a sentence-level citation cannot be anchored in the raw output at
all — the phrase simply does not occur in it. Normalising at ingestion and hashing
*that* makes offsets stable and citations readable. `parser_version` records exactly
how (`pypdf-6.16.1+normalize-1`), because a different extractor is a different
canonical text.

**Section detection runs before normalisation, then its offsets are mapped.** Headings
anchor at line starts, which normalisation destroys, so headings are found on the
line-preserving form and their offsets translated — rather than keeping two texts with
two coordinate systems. The patterns are drafting conventions, not domain terms:
`§ 1016.5(a)`, `Section 4.2`, `Chapter 3`, `Ch. 12`, `Part II`, `Appendix V`,
`Subpart C3`, `7.1`.

**Pages that yield no text are recorded, not skipped.** 21 pages across the committed
corpus are scanned images. Each becomes its own zero-length chunk with
`extraction_failed` in the coverage ledger — countable, attributable to a page,
impossible to mistake for content. A corpus that silently dropped them would look
complete when it is not. The placeholder's ID is derived from the page number rather
than its content, because every such page contributes the same content — nothing — and
hashing that would give all of them one identical ID.

Measured on the corpus:

| Document | Pages | Canonical chars | Headings | Chunks | No text |
| --- | ---: | ---: | ---: | ---: | ---: |
| `sop_technical_updates_effective.pdf` | 467 | 1,118,509 | 84 | 144 | 20 |
| `som107ap_v_emerg.pdf` | 68 | 169,883 | 48 | 51 | 0 |
| `bulletin_2013_9a.pdf` | 11 | 81,962 | 7 | 11 | 0 |

`pypdf` is the one optional dependency, imported lazily by `ingestion/pdf.py` alone.
Everything downstream of ingestion stays dependency-free, so a Policy IR document can
be compiled anywhere.

## Extracting clauses

`--extract` runs the deterministic, model-free extractor over the ingested chunks. It
finds normative sentences, cites them by offset, and emits clauses that assert almost
nothing: a modality, the text, and where that text is.

It types **no** condition, effect or threshold, so its output is graph-only by
construction and can never reach DMN or BPMN. That is deliberate — it gives the whole
pipeline a real input path over the real corpus today, and it is the baseline any
model-driven extractor has to beat.

Role carving is conservative. Two drafting shapes have unambiguous boundaries and are
recognised; anything else is cited whole as the effect rather than guessed at, because
a mis-carved region attaches a condition to the wrong clause:

```
"If the loan is a short-term loan, the Lender must notify the borrower."
   condition  [ 71,103] 'If the loan is a short-term loan'
   effect     [105,141] 'the Lender must notify the borrower.'

"A Seller may request an exception unless the property is in a restricted county."
   effect     [142,175] 'A Seller may request an exception'
   exception  [176,222] 'unless the property is in a restricted county.'
```

### The seam for a model-driven extractor

`--emit-requests DIR` writes, per chunk, the three things an extractor needs:

```
chunk_<id>.request.json       numbered text units with absolute offsets
chunk_<id>.schema.json        JSON Schema for the reply
chunk_<id>.instructions.md    the prose contract
```

A reply cites **unit indices**, never span IDs or offsets, and the generated schema
enumerates exactly the indices that request offered. So a citation to unseen text is not
"rejected downstream" — it is **unexpressible**, and a structured-output API will not
produce it:

```
99 is not one of [0, 1]
```

The application then builds every evidence span itself from offsets it already holds, so
an admitted clause's provenance is always something the application computed rather than
something a reply asserted. `--proposals FILE…` feeds replies back; ingestion is
deterministic, so re-ingesting rebuilds byte-identical requests and the indices still
resolve.

The request deliberately excludes the document's full text: an extractor able to read
past its units could reason about text it cannot cite.

### What both paths share

Three controls, each closing a way unsupported content could reach the IR:

| Control | Why |
| --- | --- |
| Citations must be spans the application **offered** | stops a proposal citing text it was never shown |
| A candidate has **no ID field** | identity is derived from document hash + spans + kind, so reordering a batch cannot change it |
| A field cannot be **asserted and disclaimed** together | makes `missing` meaningful instead of decorative |

Unknown keys and unknown enum values are refused, not ignored. Declaring `condition`
absent while citing a *condition span* is consistent, and is exactly what an untyped
extractor should say: "there is condition text here and I did not type it."

**One caveat.** The deterministic extractor reads modality from the same marker table
*and the same regions* the gate checks, so that check cannot fail for its output. A test
states this explicitly so a green gate is not mistaken for validation, and shows the
check biting the moment a modality is set independently. Nothing else is weakened:
provenance, offsets and hashes are verified exactly as for any other clause.

Getting that alignment right was not automatic. Reading modality from the whole sentence
while the gate reads only the subject, condition and effect regions produced **216
mislabels across the committed corpus** — every one a sentence whose only modal marker sat
inside its `unless` clause, so the gate correctly found the declared modality unsupported
by the parts carrying normative force. The fix is not to drop those sentences, since the
requirement inside the exception is real, but to recognise the carve as wrong and cite the
sentence whole.

### Measured on the whole corpus

```
17 PDFs · 5,633 pages · 18.5M characters · 408s
  → 4,350 chunks, 38,520 evidence spans, 29,343 clauses
  → 29,343 graph rules, 0 DMN, 0 BPMN, 0 gate blockers
  coverage: 2,599 candidates_emitted · 1,730 no_policy_semantics_found · 21 extraction_failed
  37.7% of 77,830 sentences are normative
```

Zero DMN and zero BPMN is the correct outcome: nothing was typed. The coverage ledger
accounts for every chunk, including the 21 image-only pages.

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
ingestion/     immutable source registry, PDF ingestion, section detection
extraction/    sentence segmentation, the offer/proposal seam, the model-free baseline
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

## Scope, authority and time

Three things decide *whether* a clause applies, and they are declared as data so the
engine stays domain-agnostic.

**Scope** is a list of named axes, not fixed fields. Mortgage scoping uses state,
product and channel; healthcare uses payer, facility type and state; insurance uses
line of business. Fixed fields would hard-code one domain, so a corpus declares its
axes as `ScopeDimensionDefinition` records and clauses constrain them:

```json
"scope": {"dimensions": [
  {"name": "jurisdiction", "values": ["US-CA"], "evidence_ids": ["ev_…"]}
]}
```

Scope is not metadata — it becomes an **input column** in the emitted decision
table. That is what makes it earn its place: a 660 rule for California and a 640 rule
for New York have overlapping score bands, so on their conditions alone `UNIQUE` is
refused and neither compiles. With the jurisdiction axis as an input, the same
non-overlap prover sees they can never both match, and both rules compile. The axes
are derived from the rows rather than declared separately, so a table's shape cannot
drift out of step with the clauses it is built from.

**Authority** breaks ties. A regulated corpus routinely holds a guide and a bulletin
that disagree, and which one wins is a stated fact, not a computable one — so
`AuthoritySource.authority_weight` is declared per corpus (higher wins) and the
engine only ever compares weights. It never infers a hierarchy from a document's
name or kind. A declared conflict then has three outcomes:

| Outcome | When | Effect |
| --- | --- | --- |
| No real conflict | the two scopes are provably disjoint | nothing blocked |
| Resolved | both can apply, one authority is heavier | loser stays in the graph, refused for execution; **the decision still compiles from the winner** |
| Unresolved | equal weight, or an authority missing | both refused, decision blocked |

That middle row is the point. Previously *any* declared conflict killed the whole
decision; now resolving one enables compilation instead of merely describing the
problem.

**Time** is an edge, not a flag. `Lifecycle.SUPERSEDED` records a status without
recording the replacement, which makes "what applied on 3 March 2026" unanswerable,
so supersession is a typed `SUPERSEDES` edge paired with the replacement's effective
period. A replacement whose start date is still in the future does not yet displace
what it supersedes, which lets a corpus hold both the current and the forthcoming
version of a rule.

`--as-of YYYY-MM-DD` restricts the executable projections to clauses definitely in
force on that date. It is always an explicit argument: the compiler never reads the
clock, because output that depends on when it ran cannot be byte-stable.

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
- **Accept an undeclared scope axis or value.** A limit narrows what a rule reaches,
  so the axis must be declared, its value must be in the declared vocabulary, and the
  limit must be evidenced.
- **Settle a conflict it was not told how to settle.** Equal authority weight, or a
  missing authority, leaves the conflict unresolved rather than picking a side.
- **Compile a superseded clause,** or one that is out of force under `--as-of`, or one
  whose in-force status cannot be determined.

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

- **The baseline extractor types nothing.** It produces evidenced graph-only clauses;
  turning prose into a typed condition is the model-driven path's job, and this one
  refuses to guess. Expect a corpus extracted this way to admit zero DMN and zero BPMN.
- **Role carving handles two drafting shapes.** A leading condition and a trailing
  qualifier; anything more complex is cited whole rather than mis-split.
- **Sentence segmentation is conservative** and will occasionally join two short
  sentences rather than risk splitting a requirement from its own condition.
- **Image-only pages need OCR, and OCR is deliberately absent.** OCR output is not
  deterministic across versions or platforms, which would break the byte-stability the
  rest of the design rests on. Those pages are recorded as `extraction_failed` and left
  out. If they are needed, OCR belongs behind an explicit flag with its own
  `parser_version`, and its spans capped at `match_status: recovered` — which the gate
  already refuses for anything executable.
- **Section labels are readability, not provenance.** A missed heading makes a citation
  harder to read; the document hash and character offsets are what anchor it.
- **Scope is clause-level.** A decision inherits applicability from its rows; there is
  no decision-level scope override yet.
- **Authority weights are flat integers.** `parent_authority_id` records a hierarchy
  for display but does not participate in comparison, so a deep authority tree has to
  be flattened into weights by hand.
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
python -m pytest tests/ -q                      # 493 offline tests
python -m pytest tests/ -q --xsd-dir schemas/omg  # + 8 XSD conformance tests
```

Test files map onto the plan's test strategy: `test_contracts.py` (contract and
provenance), `test_expressions.py` (expression and semantic), `test_scope.py`,
`test_authority.py`, `test_timeline.py`, `test_ingestion.py`, `test_extraction.py`,
`test_offer.py`, `test_dmn.py`, `test_bpmn.py`,
`test_compatibility.py`, `test_gate.py`, `test_stress_matrix.py` (one test per
stress-matrix row), `test_cli.py`, `test_xsd_conformance.py`.

`test_gate.py::test_the_engine_names_no_domain_actors` enforces the domain-agnostic
rule mechanically: no domain noun may appear in engine *code*, only in prose. It found
a real leak — a hard-coded `"no lender may"` prohibition marker, now a generic
`no <actor> may|shall|can` pattern that covers every industry.

Everything is deterministic and offline: no network, no credentials, no model
calls, no uncommitted local data.
