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

### Closing that seam: the model extractor

`extraction/model_extractor.py` fills the seam described above. It posts one request per
chunk to the OpenAI Responses API with Structured Outputs in strict mode, so the reply is
schema-valid by construction rather than by validation.

```bash
# the whole pipeline: PDFs in, HTML report out
python -m cli.run_pipeline --input compliance-files/fannie_mae --output outputs

# a costed pilot before committing to a full corpus
python -m cli.run_pipeline --input compliance-files/fannie_mae --output outputs \
    --to model_extraction --limit 4

# re-run the free, deterministic tail after fixing a compiler
python -m cli.run_pipeline --output outputs --from admission
```

There is no SDK dependency: the transport is one `urllib` POST behind a
`Transport = Callable[[Mapping], Mapping]` alias, which keeps the app's zero-dependency
property and makes every test offline — the whole retry, refusal and accounting surface
is exercised through a fake transport.

**Strict mode accepts a narrow subset of JSON Schema**, so `extraction/strict_schema.py`
rewrites the generated schema into it: `oneOf` → `anyOf`, `const` → single-member `enum`,
every enum given an explicit `type`, every object closed with all properties required,
unreachable `$defs` pruned (37 → 19), and arrays never made nullable. Each of those rules
exists because the live API rejected the schema without it.

#### Narrowing beats refusing

Two failure classes came out of the first live run, and both were the same mistake — an
open slot the model filled reasonably and the parser then refused:

| Slot | What the model sent | Fix |
|---|---|---|
| `TemporalConstraint.duration` | `30`, `"four months"`, a nested expression | `DurationLiteral`: ISO 8601 days-and-time string, pattern-checked |
| `EffectivePeriod.start` / `end` | `"July 6, 2010"` | `YYYY-MM-DD`, pattern-checked |

The first cost **8 of the first 45 chunks — 18%**, each one a paid call. Constraining the
slot moves the failure from *refused after the fact* to *impossible to express*, which is
the same move the unit-index citation contract makes. Where the IR is legitimately more
expressive than the extractor needs — a duration can come from a variable at evaluation
time — the narrowing lives in the **extraction contract only**, not in the IR schema.

Months and years are still not expressible, deliberately: a month is not a fixed number
of days, and approximating one would silently change a deadline. The instructions tell the
model to record such a case in `missing` instead of converting it.

#### The model pass is the only stage that can lose work

It costs money and takes about an hour on a 1,200-page guide, so:

* **every reply is written the moment it arrives**, not at the end of the batch. An
  interrupted run keeps everything already paid for. (This was learned by losing 45
  chunks to a run that persisted only on completion.)
* **`--from`/`--to`/`--only`** re-run any contiguous span against artefacts on disk.
* **resume is the default**: a chunk with a successful reply is skipped, and a chunk with
  a *stored failure* is retried — so "fix the schema and re-run" costs only the chunks
  that still need calling. `--no-resume` forces the whole corpus, for a prompt change.
* raw replies are kept verbatim, so an admission or parsing fix re-runs for free.

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

## The nine stages

Each stage owns `outputs/<NN>_<stage_name>/`, reads from the directories before it, and
writes everything it produces into its own. The split follows where cost and risk are.

| # | Stage | Costs | Produces |
|---|---|---|---|
| 01 | `ingestion` | minutes | hashed canonical text, section-aligned chunks, coverage |
| 02 | `extraction_requests` | free | numbered units, per-chunk schema and prose contract |
| 03 | `model_extraction` | **money** | raw replies verbatim, parsed proposals, token accounting |
| 04 | `admission` | free | proposals resolved into evidenced clauses; refusals recorded |
| 05 | `semantic_assembly` | free | declared intent, what each clause still lacks, domain profile |
| 06 | `gate` | free | six statuses and every blocker, fail-closed |
| 07 | `governance` | free | reviewer queue for every refusal, coverage metrics |
| 08 | `projection` | free | knowledge graph, DMN, BPMN, traceability, run manifest |
| 09 | `visualization` | free | the interactive HTML report |

The semantic layer sits deliberately **before** the executable projections and is never
skipped. The knowledge graph is the canonical representation; DMN and BPMN are narrow
projections of the subset that qualifies for them. A clause that projects to neither — a
definition, an entity, a constraint — is still a full member of the graph, which is why
`clauses_with_no_declared_projection` is reported as a design outcome and not a gap.

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

## Open-benchmark evaluation

The repository contains adapters for existing public annotations, not a newly
labelled policy-to-workflow benchmark. They are deliberately separate from the
compiler: a benchmark adapter normalizes the official corpus and scores a submitted
system-output artifact. It does not download, redistribute, or silently relabel a
corpus, and it does not claim that a benchmark supplies a gold knowledge graph, DMN,
or BPMN model.

Supported first-party formats are the official ShARC JSON split, ContractNLI JSON
split, and unpacked OPP-115 corpus. Obtain each data set under its own terms, keep
it outside the repository, and record the exact split and release in the paper.
The report records SHA-256 digests of the source annotations and submitted
predictions.

For a bounded development pilot, use `--case-ids` with a JSON list of case IDs.
The adapter selects only those already-labelled cases and records both the selection
manifest digest and count. Do not pass an incomplete full-split prediction file as a
subset: missing predictions are intentionally scored as abstentions. The case-ID list
must be retained with the run artifacts and should be defined without consulting gold
labels (for example, a fixed lexical-ID slice).

```bash
# Emit system-facing tasks and evidence-anchor IDs the system may cite. This file
# deliberately omits gold answers and gold evidence.
python -m evaluation.benchmarks \
  --benchmark sharc --input /data/sharc_dev.json \
  --emit-cases /tmp/sharc-cases.json

# Score JSON or JSONL predictions. Missing cases are explicit abstentions; unknown
# case IDs are a hard error, preventing an accidental split mismatch from passing.
python -m evaluation.benchmarks \
  --benchmark contract_nli --input /data/contract-nli/dev.json \
  --predictions results/contract-nli-predictions.jsonl \
  --run-manifest results/contract-nli-policy-ir-run.json \
  --out results/contract-nli-report.json

# OPP-115 must stay outside the repository. Use a policy-level JSON selection
# manifest, so examples from one policy cannot silently cross train/test splits.
python -m evaluation.benchmarks \
  --benchmark opp115 --input /data/OPP-115 \
  --opp115-policy-ids splits/opp115-test-policy-stems.json \
  --emit-cases /tmp/opp115-test-cases.json
```

Each prediction is an object with a `case_id`, an optional `answer`, and optional
`evidence_ids`. ContractNLI evidence IDs are source anchors such as `span:84`,
emitted by `--emit-cases`; the task export contains every source anchor, not only
gold anchors, and arbitrary rationale text is not accepted as evidence.
The report separates overall accuracy, accuracy on answered cases, coverage/
abstention, per-label macro-F1, and micro evidence precision/recall/F1. ShARC's
label can be `Yes`, `No`, `Irrelevant`, or a required follow-up question, so its
outcome scorer uses normalized exact matching rather than an LLM judge.

For a paper result, pass a versioned `--run-manifest` when scoring. It is a
secret-free JSON declaration that the scorer verifies against the actual corpus,
selection, and predictions before embedding it in the report. It binds the result
to a system identity, one of `direct_baseline`, `policy_ir`, or `ablation`, an
implementation revision, and the SHA-256 digest of a non-secret configuration;
it does not copy prompts, credentials, or configuration values into the report.

```json
{
  "schema_version": "p2c-evaluation-run-v1",
  "run_id": "contract-nli-dev-policy-ir-v1",
  "system": {
    "system_id": "policy-to-knowledge",
    "kind": "policy_ir",
    "implementation_revision": "<git-commit-or-immutable-image-digest>"
  },
  "configuration": { "sha256": "<64-hex-digest-of-non-secret-config>" },
  "benchmark": {
    "name": "contract_nli",
    "source_sha256": "<64-hex-digest-of-official-split>",
    "selection": {}
  },
  "predictions_sha256": "<64-hex-digest-of-submitted-predictions>"
}
```

The manifest is created after predictions exist, because the scorer refuses a
manifest whose prediction digest differs from the submitted artifact. The
selection must exactly match the corpus adapter's recorded selection (including
the OPP-115 policy-level manifest digest). A manifest is optional for exploratory
local scoring but required for any result represented as reproducible research.

### Local direct-baseline pilot

For a cost-free local baseline, `evaluation.ollama_runner` calls a locally running
Ollama model with only the system-facing document, question, and context. It is a
**direct baseline**, not a Policy IR system: it neither constructs Policy IR nor
claims an advantage over one. Model failures become explicit `null` predictions,
which the scorer reports as abstentions. The runner writes a label-safe prediction
artifact and a separate secret-free configuration record; it never reads API keys.

```bash
git_rev=$(git rev-parse HEAD)
python -m evaluation.ollama_runner \
  --benchmark sharc --input /data/sharc_dev.json --model qwen2.5:7b \
  --case-ids splits/sharc-dev-lexical-100.json \
  --implementation-revision "$git_rev" \
  --predictions-out results/sharc-qwen-direct.jsonl \
  --config-out results/sharc-qwen-direct-config.json
```

Afterward, create a `p2c-evaluation-run-v1` manifest whose `configuration.sha256`
is the SHA-256 digest of the emitted configuration record and whose prediction and
source digests match the emitted artifact and selected corpus. Score it with
`evaluation.benchmarks --run-manifest`; do not describe a run with this runner as
`policy_ir` or an ablation.

`evaluation.openai_runner` provides the equivalent direct baseline through the
OpenAI Responses API. It obtains a key only from a named environment variable,
uses structured JSON output, and sends `store: false`; neither the key nor prompts
or API replies are written to its configuration record. It reads `OPENAI_API_KEY`
by default; use `--api-key-env NAME` only when the key is deliberately supplied
through a different environment-variable name. The paper protocol fixes this runner
to `gpt-5.2` and `temperature=0.0`; it writes its own run manifest so a direct run
can be paired without hand-assembling provenance.

```bash
git_rev=$(git rev-parse HEAD)
python -m evaluation.openai_runner \
  --benchmark sharc --input /data/sharc_dev.json --model gpt-5.2 \
  --case-ids splits/sharc-dev-lexical-100.json \
  --run-id sharc-dev-direct-v1 \
  --implementation-revision "$git_rev" \
  --predictions-out results/sharc-openai-direct.jsonl \
  --config-out results/sharc-openai-direct-config.json \
  --run-manifest-out results/sharc-openai-direct-manifest.json
```

### Evidence-bounded PolicyIR comparison

`evaluation.policy_ir_runner` is a separate paired-system variant. It creates a
case-scoped PolicyIR evidence slice from application-offered sentence units, lets the
query stage see only graph-eligible clauses plus the query, and maps a validated
tri-valued QueryIR relation to a public benchmark answer. It is not a claim that any
benchmark provides gold PolicyIR/DMN/BPMN. The runner emits prediction, safe admission
trace, configuration, and run-manifest artifacts; it never writes prompts, raw model
responses, or an API key.

```bash
git_rev=$(git rev-parse HEAD)
python -m evaluation.policy_ir_runner \
  --benchmark contract_nli --input /data/contract-nli/dev.json \
  --run-id contract-nli-dev-policy-ir-v1 \
  --implementation-revision "$git_rev" \
  --predictions-out results/contract-nli-policy-ir.jsonl \
  --trace-out results/contract-nli-policy-ir-trace.jsonl \
  --config-out results/contract-nli-policy-ir-config.json \
  --run-manifest-out results/contract-nli-policy-ir-manifest.json

python -m evaluation.paired \
  --benchmark contract_nli --input /data/contract-nli/dev.json \
  --baseline-predictions results/contract-nli-direct.jsonl \
  --baseline-run-manifest results/contract-nli-direct-manifest.json \
  --policy-ir-predictions results/contract-nli-policy-ir.jsonl \
  --policy-ir-run-manifest results/contract-nli-policy-ir-manifest.json \
  --policy-ir-trace results/contract-nli-policy-ir-trace.jsonl \
  --out results/contract-nli-paired-report.json
```

The paired report rejects anything other than a `direct_baseline` and `policy_ir`
manifest over the identical source bytes and selection. It reports both systems'
native metrics, PolicyIR compiler/query admission, and a fixed-seed paired bootstrap
accuracy interval. See [the protocol](../../docs/research/policy-ir-query-evaluation-protocol.md)
for the locked configuration, evidence boundaries, and final-test discipline.

The OPP-115 adapter uses the corpus's `threshold-0.5-overlap-similarity`
consolidation view and evaluates the ten original top-level data-practice
categories per policy segment. Its `Yes` labels are the consolidated annotations;
its `No` labels are the deterministic complement over that fixed category set. It
does not convert fine-grained attributes into an invented gold knowledge graph or
score evidence spans whose original indexing is documented as partially errant.
OPP-115 is for research, teaching, and scholarship use under the corpus's stated
terms; the data, annotations, and selection manifest must never be committed here.

This is evaluation infrastructure, not an experimental result. A paper must still
run a fixed release/split, publish the prediction artifacts and configuration, and
report failures and abstentions alongside outcome metrics. BPMN receives structural
and traceability validation in this repository, but no unsupported claim of gold
BPMN similarity is made.

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
`test_authority.py`, `test_timeline.py`, `test_ingestion.py`, `test_scaling.py`,
`test_extraction.py`,
`test_offer.py`, `test_dmn.py`, `test_bpmn.py`,
`test_compatibility.py`, `test_gate.py`, `test_stress_matrix.py` (one test per
stress-matrix row), `test_cli.py`, `test_xsd_conformance.py`.

`test_gate.py::test_the_engine_names_no_domain_actors` enforces the domain-agnostic
rule mechanically: no domain noun may appear in engine *code*, only in prose. It found
a real leak — a hard-coded `"no lender may"` prohibition marker, now a generic
`no <actor> may|shall|can` pattern that covers every industry.

Everything is deterministic and offline: no network, no credentials, no model
calls, no uncommitted local data.
