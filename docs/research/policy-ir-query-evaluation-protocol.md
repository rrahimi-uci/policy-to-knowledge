# Evidence-Bounded PolicyIR Benchmark Protocol v1

**Status:** implementation-ready; no paper result has been run from this protocol.

This protocol evaluates whether an evidence-bounded PolicyIR intermediate layer is
useful for policy-question tasks without creating any new human labels. It does not
claim that ContractNLI, ShARC, or OPP-115 contain gold knowledge graphs, DMN, or BPMN.

## Locked comparison

The implementation locks the following values in `evaluation.protocol`:

- model: `gpt-5.2`;
- decoding: Responses API `temperature: 0.0`, `store: false`;
- direct prompt: `p2c-direct-policy-qa-v1`;
- PolicyIR prompts: `p2c-policy-ir-extraction-v1` and `p2c-policy-ir-query-v1`;
- paired bootstrap: 10,000 resamples, seed `20260819`.

Changing any of these is a new protocol revision, not a parameter change within a
result table. Each run writes a secret-free configuration file and a hash-bound run
manifest. The runner refuses another model or decoding setting.

## Method under test

```text
benchmark case (source + query; no gold fields)
  -> offered sentence units
  -> unit-index-only PolicyIR proposals
  -> application-built spans + evidence gate
  -> graph-eligible PolicyIR clause slice
  -> QueryIR: supported | contradicted | unknown
  -> deterministic benchmark projection + derived evidence anchors
```

The extraction call cannot name offsets, source anchors, or arbitrary evidence IDs.
It can only cite unit indices supplied in its schema. The application constructs the
evidence spans, derives clause IDs, and invokes the existing gate. The query call sees
the graph-eligible clauses and the benchmark question, but not source text or gold
annotations. It cannot emit benchmark labels: `QueryIR` uses a three-valued relation,
which deterministic code maps to each benchmark's public answer format. Unsupported
clause IDs, unsupported source anchors, invalid ShARC relation/resolution pairs, and
empty admissible PolicyIR slices produce explicit abstentions or hard errors.

This is a case-scoped evidence slice, not full-document semantic compilation. It is
therefore evidence for query-grounded PolicyIR, not evidence that a benchmark document
has been compiled to executable DMN/BPMN.

## Runs and measures

Run the paired systems on byte-identical corpus input and selection:

1. Direct structured baseline, with source text and query.
2. Evidence-bounded PolicyIR → QueryIR system, with two model calls.

Primary development comparison: full official **ContractNLI dev** split. It reports
accuracy, macro-F1, coverage/abstention, and corpus-provided exact evidence precision,
recall, and F1. ShARC is a secondary decision/follow-up comparison. OPP-115 is a
breadth diagnostic for category-level policy-practice detection; it does not support
an evidence-F1 claim in this adapter.

For every paired report, record:

- both run manifests, source digest, and selection;
- outcome accuracy, macro-F1, coverage, and abstentions;
- evidence P/R/F1 only where corpus anchors exist;
- case-level PolicyIR compiler-admission and QueryIR-admission rates;
- candidate-minus-baseline accuracy and a paired 95% bootstrap interval.

The earlier 20-case ShARC run is a runner smoke test only. It must not appear as a
headline result, be pooled with protocol runs, or influence a held-out claim. Treat
ShARC dev as development data once any scored result has been inspected; use a
separately locked, untouched split for a paper-level final estimate.

## Execution order

1. Obtain each corpus under its own terms and keep data, IDs, raw predictions, and
   generated results outside the repository.
2. Before scoring any new result, record the official source URL, release, license,
   local path, SHA-256, and split definition in an external run ledger.
3. Use the entire ContractNLI dev split for pipeline debugging only. Do not tune prompts
   or modify the protocol after seeing its score.
4. Run direct and PolicyIR variants on the same selected cases, each with immutable
   configuration and manifest artifacts.
5. Score only through `evaluation.paired`; it rejects manifest, corpus, selection,
   prediction-digest, and system-kind mismatches.
6. Run ShARC and OPP-115 under the unchanged protocol as secondary evidence. Do not
   average their heterogeneous task metrics.
7. Before a paper claim, freeze a new final protocol revision and evaluate it once on
   untouched official test splits, then report all failures and abstentions.

## Stress-test checklist

The automated tests cover the high-risk mechanism failures:

- model attempts to use an unoffered unit index;
- invalid or duplicate QueryIR clause references;
- a query response that attempts to return a benchmark answer field;
- non-empty answer with no admitted evidence for supported/contradicted relation;
- invalid ShARC truth/resolution combinations;
- an anchor reported without overlap with application-built evidence;
- mismatched source digest, selection, prediction digest, or system kind in paired runs;
- model/decoding drift from the locked protocol; and
- stochastic bootstrap drift from a changed seed or sample count.

Remaining scientific risks are deliberate limitations, not hidden engineering gaps:
the QueryIR relationship is model-proposed rather than independently semantically
proved; admission to the graph is weaker than DMN/BPMN eligibility; and repeated calls
to a hosted model can vary despite temperature zero. Report repeated-run variance if it
occurs, and never translate an admission rate into legal or executable correctness.
