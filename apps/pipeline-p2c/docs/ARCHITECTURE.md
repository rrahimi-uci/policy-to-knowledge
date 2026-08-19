# pipeline-p2c architecture

This document explains *why* the modules are shaped the way they are. The README
covers what the app does and how to run it.

## The one invariant

> No source-supported typed semantics, no executable model element.

Every design decision below follows from making that invariant enforceable rather
than merely stated.

## Records carry no verdicts

`policy_ir.models` records describe what an author believes and where the evidence
is. They have no `validation_status`, no `is_eligible`, no confidence-derived
admission. A compiler takes an IR **and** a `GateReport`, and consults the report.

The alternative — storing eligibility on the record — was rejected because a record
that can mark itself eligible makes fail-closed unenforceable. Any writer, agent or
human, could set the field, and the compiler would have no independent basis to
disagree. `tests/test_gate.py::test_a_clause_never_marks_itself_eligible` pins this.

Model confidence appears nowhere in admission. It is not evidence.

## Layering, and why `compilers/__init__.py` is empty

```text
policy_ir   →  (nothing)
ingestion   →  policy_ir
validation  →  policy_ir, ingestion
evaluation  →  policy_ir
compilers   →  policy_ir, validation
adapters    →  policy_ir
cli         →  everything
```

The expression AST's FEEL rendering (`policy_ir/feel.py`) and decision-table
decomposition (`policy_ir/tabular.py`) sit in `policy_ir`, not in `compilers`,
because the gate needs both: it must know whether an expression is tabular and
FEEL-expressible before it can call anything DMN-eligible. Leaving them in
`compilers` created a genuine import cycle (`validation → compilers → validation`).
Moving them removed the cycle and put them next to the grammar they describe.

`compilers/__init__.py` re-exports nothing, so importing `compilers.feel` cannot
drag `compilers.bpmn` — and therefore `validation` — into a half-initialised state.

## Provenance is content, not filenames

`ingestion/registry.py` identifies a document by the SHA-256 of its bytes *and* of
its canonical extracted text. Chunks are slices of that canonical text with real
character offsets.

This matters because chunking is a transport decision that changes between runs.
If a span's provenance were "chunk 4, words 12–19", re-chunking would silently
move it. Anchoring to document offsets plus a content hash means overlapping chunks
produce identical spans — asserted by
`test_contracts.py::test_offsets_survive_overlapping_chunks`.

`SourceRegistry.locate` refuses an ambiguous phrase rather than taking the first
occurrence. A phrase appearing twice is not evidence for either occurrence.

Normalisation is kept separate from the canonical text. The canonical text is what
offsets index and hashes cover and is never rewritten; `normalize_text` produces a
*comparison* form used only to grade a match as `normalized_exact`, which is
recorded as weaker than `exact`. Case is preserved, because "Lender" and "lender"
can be different defined terms.

## Identity is derived from content

Legacy rule IDs embed the extraction batch number, so reordering batches changes
identity. `policy_ir/ids.py` derives every ID from the document hash, the evidence
span, the normalised clause kind and the schema version.

`content_digest` length-prefixes each part before hashing. Without that,
`("ab", "c")` and `("a", "bc")` would hash identically and two different clauses
could share an ID. IDs are also coerced to XML `NCName`, because DMN and BPMN both
declare element IDs as `xsd:ID` — an ID starting with a digit makes the output
invalid.

## The non-overlap proof

`hitPolicy="UNIQUE"` asserts that no two rows can both match. `policy_ir/tabular.py`
tries to prove it: each row becomes a per-input constraint (an allowed set, an
excluded set, or an interval), and two rows are disjoint when *some* input's
constraints cannot both hold.

The prover is deliberately asymmetric. It answers "provably disjoint" only when
certain; anything it does not model — a presence test, a punctured interval — is
`OPAQUE` and reads as "may overlap". That costs coverage and protects correctness,
which is the trade the plan asks for: overlapping rows without stated priority must
be rejected, not relabelled.

`FIRST`/`PRIORITY` require `ordering_evidence_ids`; `COLLECT` requires a declared
aggregation. Nothing is ever inferred.

## Exceptions are folded, not dropped

A row fires when the condition holds *and* the exception does not, so
`row_condition()` folds `All((condition, Not(exception)))` before decomposition.
Folding in one shared place means the exception survives identically into the unary
tests, the overlap proof and the reference evaluator. An earlier version decomposed
only the condition and checked the exception separately for tabularity — which
silently dropped the exception from the emitted table.

## Three-valued evaluation

`evaluation/evaluator.py` returns `UNKNOWN` for absent inputs and propagates it
through Kleene logic. A conjunction with a definite `False` is still `False`; a
conjunction with an unknown and no false is `UNKNOWN`.

Two-valued logic would map "we have no income figure" onto "the applicant is
ineligible" — an unsupported decision wearing a supported decision's clothes. Null
handling is therefore a *declared* property of each `DataDefinition`
(`NullPolicy`), and DMN eligibility requires it to be stated.

## Why there are two evaluators

XSD validity proves shape, not meaning. `compilers/dmn_reference.py` reads the
emitted XML back and evaluates the table by parsing its FEEL unary tests. It shares
no code with the serialiser, so `tests/test_dmn.py` can assert agreement across an
input grid and have that agreement mean something. Round-tripping through the same
AST would prove only that the code is self-consistent.

## Structural verification is offline; XSD validation is opt-in

CI must be deterministic and offline, so `compilers/verify.py` implements the checks
that actually break in practice: duplicate IDs, unresolved `href`s, rows with the
wrong entry count, sequence flows pointing at absent nodes, business rule tasks
bound to decisions that were never emitted.

The normative OMG schemas are the authority on what the standards accept, but they
are OMG documents this repository does not redistribute. `schemas/PINNED.json`
records their URLs and SHA-256s, `scripts/fetch_schemas.py` reproduces exactly those
bytes or fails, and the `xsd`-marked tests run against them on request.

## The JSON Schema is generated

A hand-written schema beside hand-written parsers is two contracts, and they drift
toward the looser one. `policy_ir/jsonschema.py` derives the schema by introspecting
the dataclasses, so field names, optionality and enum vocabularies come from the same
definitions the parsers use. The committed copy is checked for drift by
`test_contracts.py::test_committed_json_schema_matches_the_dataclasses`.

The recursive expression grammar is written out by hand in `_expression_defs()`,
because introspection cannot express a recursive discriminated union and the grammar
is small and stable enough that stating it is clearer than generating it.

## The BPMN subset is narrow on purpose

One participant, one process, one start event, a validated chain of activities, one
end event. No gateways, no boundary events.

A gateway requires branch conditions and a declared default path. Nothing in the
evidence model currently carries evidenced branch semantics, so the gate refuses
branching (`branching_not_supported`) rather than letting the compiler pick a split.
Widening the subset means adding evidence requirements first, then the emitter —
in that order.

The DMN binding on a business rule task goes into `extensionElements` under this
project's own namespace. BPMN 2.0 has no standard `decisionRef`; the vendor
attribute everyone uses would make the canonical file engine-specific.

## The legacy adapter's job is to under-claim

`adapters/legacy_graph.py` imports historical graphs without fabricating anything:
no evidence spans (the original bytes are gone), no expressions (prose is not an
AST), no classifications it cannot read (`UNCLASSIFIED` exists for exactly this).

`eligibility` and `constraint` are deliberately absent from the kind map. Mapping
them to `DECISION_RULE` produced clauses that then failed their own contract —
a decision rule needs a typed condition and effect — and dropped out of the graph
entirely. On the Fannie Mae corpus that silently lost 137 of 384 rules. Leaving them
`UNCLASSIFIED` keeps every rule visible and honest about what is known.

Dependencies are downgraded to `RELATED` candidates with
`MODEL_ASSISTED_CANDIDATE` derivation, except declared contradictions and overrides
which keep their meaning. `prerequisite` is ambiguous between an information
requirement and a temporal precedence, and the gate would refuse either without
evidence anyway.

## Why canonical text is normalised, and offsets are mapped

The first instinct is to treat the extractor's output as canonical and cite into it
directly. That fails immediately on the real corpus: extractors wrap lines
mid-sentence, so "the Lender must pay the fee within 10 business days" does not occur
in the raw text as a contiguous string, and `SourceRegistry.locate` — correctly —
refuses to find it.

So canonical text is the whitespace-normalised form, and `canonical_text_sha256`
covers that. This is not a loss of fidelity: the raw bytes are hashed separately in
`source_sha256`, and `parser_version` names the transformation, so the chain from
bytes to offsets is fully recorded.

Section detection then has the opposite requirement — headings anchor at line starts,
which normalisation destroys. Rather than carry two texts with two coordinate systems,
`canonicalise()` builds the canonical text and translates a caller-supplied set of raw
offsets in the same pass. The caller passes the offsets it cares about instead of
getting a full index, because a full map over the largest document in the corpus would
be three million entries to answer eighty questions.

Zero-length chunks for image-only pages look odd until you consider the alternative.
The schema attaches coverage to a chunk, and a page that produced no text has no span
in the canonical text. Emitting nothing would make a 467-page document with 20 scanned
pages look fully processed. A zero-length chunk carrying the page number and
`extraction_failed` is the honest record: countable, attributable, and impossible to
confuse with content.

## Why scope became a decision-table column

The first design kept `jurisdiction_scope` as a tuple of strings on the clause. It
read fine and did nothing: the non-overlap prover only sees the condition AST, so two
overlays scoped to different states with overlapping score bands were reported as
overlapping and neither compiled. Scope was documentation.

Turning each axis into an input keyed `scope:<name>` fixed it without a special case.
The atoms a scope produces are ordinary membership atoms, so the existing prover
separates `Allowed({US-CA})` from `Allowed({US-NY})` for free, and the DMN compiler
emits the axis as an ordinary `inputData` column whose `itemDefinition` carries the
declared vocabulary. The `:` in the key cannot collide with a data-definition ID
because those are XML NCNames.

The axes are **derived** from the union of a decision's rows rather than declared on
the decision. Declaring them separately would create a second source of truth that
could fall out of step with the clauses; deriving them cannot.

## Why authority is an integer weight

Precedence between a statute, a regulation, a guide and a bulletin is a legal
judgement that differs by jurisdiction and industry. Inferring it from a document's
`kind` string would put that judgement inside the engine and get it wrong somewhere.
So a corpus declares `authority_weight` and the engine only compares — and `kind`
stays a free string precisely because a closed enum would encode one domain's
vocabulary.

Resolution order matters: scope disjointness is tested *before* authority, because two
rules that can never both apply need no precedence to separate them.

The subtle part is what a resolved conflict does to the decision. Refusing the losing
clause is not enough — the decision declared that clause as a row, so a naive
implementation reports `row_not_admitted` and blocks the table, meaning resolution
achieves nothing. `_ROW_EXCLUDED_BY_DESIGN` names the three reasons a row is
legitimately absent (outranked, superseded, out of force under `--as-of`), and a row
whose blockers fall entirely within that set is dropped silently.

## Why supersession is an edge and time is an argument

`Lifecycle.SUPERSEDED` describes a clause *now*. It cannot answer "what applied on 3
March 2026", and worse, treating it as a veto breaks historical queries outright — the
2025 standard *was* in force in 2025 even though it is superseded today. So
`clause_in_force_on` ignores the flag and `in_force_on` decides from the `SUPERSEDES`
edge plus the replacement's effective period.

Every temporal query takes the date as an explicit argument. Nothing reads the clock,
because a compiler whose output depends on when it ran cannot produce byte-stable
artefacts, and byte-stability is the property the whole reproducibility story rests
on.

## Why indexes are memoised

`PolicyIR` is a value: every field is a tuple, so the record cannot change after
construction. That makes a cached index safe by construction — it can never go stale —
and the cache lives in a plain attribute rather than a dataclass field, so equality,
hashing and ``to_dict()`` are unaffected.

The reason it matters is scale, and it was invisible in a fixture. Rebuilding an index
inside a loop over the items it indexes is O(n²), and three such loops existed: the gate
rebuilt the evidence, chunk and document indexes per span, the graph projection rebuilt
the evidence index per rule, and `_check_clause` rebuilt the clause-ID set and the FEEL
name map per clause. A synthetic run showed the time quadrupling on every doubling of
input, so a corpus of tens of thousands of clauses simply never finished.

Worse than any of those was chunk verification. `_verify_span` re-hashed the whole chunk
body to confirm its digest — per citation. On a 3,200-clause document that was 68% of
total gate time, because the same 60 KB body was hashed 3,200 times. A chunk's integrity
is a property of the chunk, not of each span that cites it, so it is now computed once
per run and consulted per span.

Together these took a 3,200-clause run from 2.83s to 0.04s and turned the growth curve
from 4x per doubling into 2x. `tests/test_scaling.py` guards all of it by counting
operations rather than measuring time, so the guards are deterministic: an index must
return the same object twice, and a single chunk must be hashed exactly once no matter
how many clauses cite it.

## Adding a check

1. Name the blocker in `validation/blockers.py`.
2. Implement it in `validation/evidence_gate.py`, and decide which statuses it
   removes. Structural failures block `schema_valid`; unverifiable provenance blocks
   `provenance_exact`; everything semantic blocks `semantic_supported`.
3. Add a fixture in `fixtures/library.py` whose `expect_codes` names it — one
   refusal per fixture, so a regression is a specific fixture flipping.
4. If it should still be reviewable, add the code to `REVIEWABLE_CODES` in
   `compilers/dmn.py`.
5. Add the row to `REFUSALS` in `tests/test_stress_matrix.py`.
