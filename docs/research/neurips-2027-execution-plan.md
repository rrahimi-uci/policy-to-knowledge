# Evidence-Gated Policy Graph Compilation: NeurIPS 2027 Execution Plan

**Status:** proposed and unrun as a paper study. The executable v1 comparison
protocol is [PolicyIR Query Evaluation Protocol](policy-ir-query-evaluation-protocol.md),
but it has produced no headline benchmark result. This remains a falsifiable research
plan, not a claim that the repository has achieved the proposed results.

**Primary target:** the NeurIPS Evaluations and Datasets (E&D) track, 2027 edition. Consider the main NeurIPS track only if the evidence-gating method yields a substantive cross-task algorithmic result. Do not target ICLR 2027: its [call for papers](https://iclr.cc/Conferences/2027/CallForPapers) sets an abstract deadline of 18 September 2026 and a paper deadline of 25 September 2026 (AoE), which leaves too little time to complete, reproduce, and audit the study. The NeurIPS 2027 call is not published yet, and E&D is itself a recent rename of the Datasets and Benchmarks track, so confirm at Gate 0 that the track still exists under that name and fix no dates until the official 2027 call is out.

## 1. Decision in one paragraph

Build and evaluate an **evidence-gated compiler** that turns long policy documents into auditable rule graphs. The contribution is not that LLM agents can make a graph. It is a measurable mechanism that either emits a source-supported, typed rule and graph edge or abstains when evidence, normalization, or cross-reference checks fail.

Evaluate only on public datasets with independent human annotations; create no new human-labeled benchmark. The repository's lending, housing, and healthcare graphs are useful case studies and audit inputs, but never gold truth or headline F1.

Proceed only if evidence gating improves supported correctness at comparable coverage on more than one independent benchmark family and survives preregistered robustness, cost, and reproducibility checks.

## 2. Current evidence boundary

| Area | Observed now | Not established | Paper consequence |
| --- | --- | --- | --- |
| Pipeline | `pipeline-p2c` has a typed PolicyIR, source-unit offer/proposal seam, deterministic graph/DMN/BPMN projections, and a case-scoped QueryIR experiment path. | End-to-end performance against external gold labels. | Treat it as a candidate system, not a validated paper method. |
| Validation | The p2c gate verifies application-built source spans and admits projections fail-closed; the QueryIR experiment uses graph eligibility only. | Semantic source fidelity beyond the closed checks, and real contradiction resolution. | Report compiler admission separately from answer correctness. |
| Provenance | Documents, chunks, evidence spans, candidate clauses, configurations, predictions, and runs are hash-bound. | Public, complete benchmark artifact releases under every corpus's terms. | Keep data external and publish only permitted digests/artifacts. |
| Existing graphs | Four case-study graphs contain hundreds of rules/dependencies. | Their text and outputs are independent labels. | Qualitative audit and regression fixtures only. |
| Tests | Offline adapters/scorers cover ShARC, ContractNLI, OPP-115, manifests, direct runs, PolicyIR/QueryIR contracts, and paired bootstrap mechanics. | Held-out paired results, repeated-run variance, and contamination audit. | Run the locked protocol before modifying it further. |

The implementation seams are the [rule extractor](../../apps/pipeline/agents/agent_3_rules_extractor.py), [validator](../../apps/pipeline/agents/agent_3_5_rule_validator.py), [graph optimizer](../../apps/pipeline/agents/agent_5_knowledge_graph_optimizer.py), [LLM client](../../apps/pipeline/utils/llm_client.py), [configuration](../../apps/pipeline/utils/config.py), and [extraction CLI](../../apps/pipeline/cli/extract.py). No proposed change below is implemented by this document.

## 3. Core claim, research questions, and failure conditions

### Proposed claim

For policy-like documents, source-span evidence gating plus typed normalization and calibrated abstention can reduce unsupported structured outputs relative to direct and multi-agent LLM extraction, while retaining useful coverage and downstream rule-reasoning performance.

This is not a claim of legal correctness or general policy understanding. It applies only to the evaluated data, model versions, prompts, and document transformations.

### Research questions

1. Does evidence gating improve entity/relation and rule-decision correctness over direct structured extraction and frozen P2K?
2. At matched coverage, does it reduce outputs whose cited span fails to support the emitted relation, decision, or answer?
3. Are acceptance and abstention scores calibrated enough for selective use, rather than merely hiding errors?
4. Does graph construction retain improvements on a downstream reasoning task?

### Falsification

The central claim fails if improvement is confined to one data family or prompt/model setting; disappears at matched coverage; arises solely from rejecting ordinary examples; requires hand repair after seeing test labels; fails provenance checks; or has a paired bootstrap confidence interval including no gain.

## 4. Scientific position with no new human labels

Do not recruit annotators, make a P2K pseudo-gold set, or score legacy output against itself. Instead, make a cross-benchmark method/evaluation paper using public expert annotations.

An adapter may deterministically translate a published schema into the compiler interface. It must be versioned before testing and may not repair individual test examples. Any mapping that needs test-label inspection or semantic hand correction fails the adapter gate.

Synthetic tests are permitted only as known-oracle robustness tests. A program can flip must/must-not, alter a deadline or quantity, add an exception, or break a cross-reference. These test expected behavior but are not human evidence and cannot be a headline score.

For every source, record upstream URL, version, license, retrieval date, SHA-256, and split definition: the official split where one is published, otherwise a preregistered deterministic split committed before test access. Do not chunk-split overlapping documents. Release adapters, prompts, hashes, aggregate results, and derived predictions only where terms permit; prefer download scripts and hashes over redistributing documents.

## 5. Public evaluation suite

No single resource measures extraction, evidence, reasoning, and policy QA. Do not collapse the following native metrics into one artificial policy-graph score.

| Track | Resource and role | Deterministic mapping | Headline metric | Guardrail |
| --- | --- | --- | --- | --- |
| Structured graph extraction | [CODE-ACCORD](https://arxiv.org/abs/2403.02231) ([Scientific Data version](https://www.nature.com/articles/s41597-024-04320-x)), building-regulation entities/relations. | Published entity/relation ontology becomes typed nodes/edges; keep the published split if one exists, otherwise preregister a deterministic split. | Entity and relation P/R/F1. | Freeze mapping and split before test access; report per type and micro/macro. The corpus is small (862 sentences, 4,297 entities, 4,329 relations), so report interval width and never rest a claim on it alone. |
| Evidence-grounded decision | [ContractNLI](https://stanfordnlp.github.io/contract-nli/), hypotheses, NLI labels, evidence. | Hypothesis becomes query over extracted rules with evidence span. | Label macro-F1 plus evidence P/R/F1. | Do not treat missing evidence as contradiction; report classes separately. |
| Applied normative reasoning | [DeonticBench](https://arxiv.org/abs/2604.04443), long-context deontic reasoning over tax, airline, immigration, and housing rules. | Compile context to typed deontic predicates; preserve the answer interface; the released reference Prolog programs are an audit oracle, not a label source. | Official accuracy/macro-F1 by domain. | Any synthetic subset is secondary, not independent gold. This is a 2026 preprint: confirm release artifacts, license, and official scoring at Gate 0 before it counts as a core family. |
| Policy QA | [PolicyQA](https://arxiv.org/abs/2010.02557) and, subject to terms, [PrivacyQA](https://arxiv.org/abs/1911.00841). | Retrieve graph rules then answer only from cited spans. | Official EM/F1; support rate where possible. | Score answer and support separately. |
| Transfer diagnostic | [Re-DocRED](https://arxiv.org/abs/2205.12696). | Published ontology becomes an out-of-domain graph diagnostic. | Relation F1/provenance diagnostics. | Cannot establish policy-domain performance. |

Add LegalBench or another resource only after it has a direct deterministic mapping and official scoring. Emerging/synthetic cross-reference resources belong in a clearly separate stress appendix, never in the primary claim.

## 6. Method: evidence-gated graph compiler

The pipeline should be:

1. Candidate generation: the LLM proposes typed rules and candidate source spans.
2. Deterministic normalization: parse actor, action, object, deontic type, negation, quantities/units, dates, conditions, exceptions, and jurisdiction/scope.
3. Evidence gate: verify structure and source support against immutable document bytes.
4. Abstention: emit an explicit reason when a candidate cannot be certified.
5. Graph projection: construct graph edges while preserving the source rule IDs and all supporting spans.
6. Task adapter: query the graph or source-linked rules without changing a benchmark's labels.

A candidate rule must at minimum include:

```text
rule_id; actor; deontic_type; action; object; conditions; exceptions;
temporal_scope; jurisdiction_or_scope; quantities; source_spans;
model_confidence; normalization_status; evidence_gate; gate_reasons
```

Source spans must include document SHA-256, chunk ID, character offsets, and text. A list of spans is first-class: each span is labeled primary support, exception, definition, or cross-reference target. Do not flatten multiple references into one field.

### Evidence-gate checks

The gate must deterministically verify:

1. required fields and allowed deontic type;
2. exact offsets into a content hash, not only filename/chunk name;
3. normalized source-text agreement with the cited span;
4. preservation of negation, quantities/units, dates, actor, scope, conditions, and exceptions;
5. resolution of any referenced section; and
6. incompatibility with another accepted rule under a declared contradiction policy.

Model confidence is not evidence. Fit calibration only on development data and freeze the threshold before test runs. A failure must be a machine-readable abstain/reject record with a reason. Research mode must be fail-closed: a validation failure cannot quietly flow to graph construction.

### Baselines and ablations

All systems receive identical document bytes, split, chunking budget, task prompt budget, and model settings.

1. Direct structured LLM, with a task-format prompt.
2. Chunked retrieval baseline, with citations but no rule graph.
3. Frozen current P2K workflow, with existing validation behavior declared.
4. P2K plus typed normalizer.
5. P2K plus evidence gate without abstention.
6. Full evidence-gated P2K: gate, calibrated abstention, and graph assembly.

Do not drop direct LLM, frozen P2K, or full method under resource pressure; drop optional diagnostics first. Compare a graph system with its graph projection bypassed so a gain is not falsely attributed to graph structure.

## 7. Protocol and reproducibility

Before the first paper-level test run, use the committed versioned protocol in
[`policy-ir-query-evaluation-protocol.md`](policy-ir-query-evaluation-protocol.md).
It freezes the initial model, decoding, prompts, bootstrap settings, and run-manifest
rules; the external source ledger must additionally freeze:

- source URLs, hashes, licenses, splits, and adapter versions;
- model IDs, decoding parameters, retry policy, prompts/prompt hashes, budgets;
- metrics, thresholds, ablations, inclusion/exclusion rules; and
- the expected test transformations and scoring scripts.

Each run writes a JSONL manifest with Git SHA, dirty-tree status, package-lock hashes, model and request settings, prompt hash, input/chunk hashes, schema/adapter/scorer version, per-example gate decision and offsets, token/cost/latency data, metrics, confidence intervals, and failed-example count.

Run each stochastic system at least three times where the provider permits it. Where a provider lacks deterministic seeds, explicitly report variance. Use paired 95% bootstrap intervals over the same examples/documents for every comparison. Development data alone selects prompts, thresholds, and final projection.

### Metrics

- CODE-ACCORD: entity and relation P/R/F1 by type and aggregate.
- ContractNLI: three-way macro-F1, class F1, evidence P/R/F1.
- DeonticBench: official metrics by domain; aggregate only as officially defined.
- Policy QA: official EM/F1 plus source-support and unsupported-answer rates.
- Applicable to every track: coverage, selective risk at fixed coverage, risk-coverage curve, abstention reason distribution, calibration ECE/Brier when probabilities are comparable, invalid-output rate, cost, and latency.

Compare accuracy at matched coverage. A system that answers fewer examples has no automatic advantage. Do not average unrelated task metrics.

## 8. Required stress tests

| Failure mode | Programmatic transformation | Expected behavior | Passing oracle | Protection |
| --- | --- | --- | --- | --- |
| Negation loss | Flip must/must not. | Polarity changes or candidate abstains. | No accepted rule retains old polarity. | Obligation/prohibition fidelity. |
| Quantity/date drift | Change a threshold, unit, date, deadline. | Normalized value changes exactly or abstains. | Exact transformed-field match; no stale value. | Operational faithfulness. |
| Exception omission | Add/remove unless clause. | Exception field/edge changes. | Graph diff contains expected exception change. | Conditionality preserved. |
| Role/scope swap | Exchange actor or jurisdiction. | Typed actor/scope changes or abstains. | No accepted output retains original value. | Graph is not surface-only. |
| Broken reference | Corrupt cited section ID. | Dependency unresolved; abstain/reject. | Zero accepted edge to invented target. | References are real. |
| Evidence mismatch | Pair candidate with plausible wrong span. | Gate rejects candidate. | Near-zero false acceptance with interval. | Citations are meaningful. |
| OCR/noise | Bounded Unicode/whitespace/OCR edits. | Recover normalized span or abstain, never silently alter meaning. | Zero accepted source-hash mismatch; report degradation. | Ingestion robustness. |
| Abstention gaming | Sweep development threshold. | Risk falls as coverage falls. | Main threshold preregistered; compare matched coverage. | Accuracy not bought by refusal. |
| Leakage | Hash/near-duplicate source check across splits/prompts. | Duplicates excluded under protocol. | Zero unresolved split duplicates. | Generalization. |

If expected behavior cannot be expressed as an executable oracle, narrow the claim or remove the test. If a failure needs human judgment, report it qualitatively; do not make it a blocking automated test under the no-new-label constraint.

## 9. Go/no-go gates

| Gate | Must pass | Stop or pivot |
| --- | --- | --- |
| 0. Feasibility/rights | At least three independent benchmark families have stable access, usable licenses, a frozen split definition (official where published, preregistered otherwise), and mapping sketches. Venue call, track name, and dates re-verified. | Fewer than three or no direct mapping: release an engineering/audit artifact, not a NeurIPS benchmark claim. |
| 1. Adapter validity | Deterministic adapters pass on train/dev fixtures and reproduce a simple published/baseline result when available. | Any test mapping needs new annotation or test-label inspection: exclude dataset. |
| 2. Method integrity | Schema, fail-closed mode, offset verifier, reference checks, manifest, and negatives work locally. | An accepted output bypasses a gate or cannot trace to hash: fix method before experiments. |
| 3. Pilot signal | Full method credibly improves support quality and one native metric over direct LLM and frozen P2K on locked development data. | Gain is only low coverage, one prompt, or one corpus: narrow claim or stop. |
| 4. Main result | Untouched tests show paired-CI-supported improvement on two or more core families; report support/coverage/cost. | No supported gain, material provenance failure, or one-dataset-only effect: do not claim general method. |
| 5. Reproducibility | Three-run variance, manifests, tests, license ledger, and clean rerun are complete. | Tables/figures cannot be regenerated or artifacts omit lineage: hold submission. |

A no-paper result is a successful scientific outcome: these gates prevent an attractive case study from masquerading as a validated general method.

## 10. Execution sequence

| Phase | Work | Deliverable | Exit |
| --- | --- | --- | --- |
| 0 — scope | Pick three core tracks; build license/source ledger; freeze claim/exclusions. | protocol and mapping draft. | Gate 0. |
| 1 — harness | Build adapters, split/hash checks, scorers, fixtures, and tests. | Reproducible adapter CLI and CI tests. | Gate 1. |
| 2 — method | Canonical schema, evidence verifier, reference/contradiction policy, fail-closed mode, manifests. | Experiment-flagged method and integration tests. | Gate 2. |
| 3 — pilot | Run all baselines on development; tune only there; select threshold and estimate budget. | Locked protocol revision/pilot table. | Gate 3. |
| 4 — main runs | Version-pinned repeated test runs and paired intervals. | Immutable manifests/raw-prediction pointers. | Gate 4. |
| 5 — audit | Execute all stress tests; inspect false accepts, duplicates, rights/release limits. | Stress report and qualitative appendix. | No critical integrity defect. |
| 6 — reproduce/write | Clean rerun; generate figures from manifests; write limitations before narrative. | Artifact package and paper draft. | Gate 5. |

### First seven working days

1. Build the source/license ledger and remove unavailable datasets before model work.
2. Write mappings for CODE-ACCORD, ContractNLI, and DeonticBench or PolicyQA; review them before test access.
3. Implement one minimal adapter validating download, hash, official split, and one record conversion using fixtures.
4. Define and validate the canonical candidate-rule schema.
5. Add an experiment-only fail-closed path; keep product behavior explicitly versioned until compatibility is decided.
6. Create wrong-span, broken-reference, and negation-flip negative fixtures.
7. Run a development-only cost/viability pilot and decide Gates 0–2 in writing.

A focused execution can take about twelve weeks after Gate 0; cost, model drift, and official venue dates may change that estimate.

## 11. Planned repository layout

This is a target layout after Gate 0, not an instruction to add everything now.

```text
research/neurips_2027/
  protocol.yaml          preregistration/model budgets
  sources.yaml           URLs, licenses, hashes, split metadata
  adapters/              deterministic corpus adapters
  evaluation/            scorers, bootstrap, reports
  fixtures/              known-oracle perturbations
  manifests/             ignored raw runs; committed indexes/hashes
  tests/                 split/schema/adapter/scorer tests
apps/pipeline/
  schemas/candidate_rule.json
  validation/evidence_gate.py
  cli/extract.py         explicit fail-closed research switch
```

Keep adapters outside product agents so task assumptions cannot leak into extraction. Keep normalization/gating deterministic and inspectable. Store content hashes plus offsets, not LLM-reported text alone. Preserve source rule records whenever graph projection collapses clauses. Version prompt, model config, schema, adapter, and scorer together.

## 12. Paper shape and venue rule

Suggested structure:

1. Problem: plausible policy prose can become unsupported operational rules.
2. Method: candidate generation, typed normalization, deterministic evidence gate, abstention, and provenance-preserving projection.
3. Evaluation design: public adapters, no new labels, matched coverage, audit controls.
4. Results: native metrics plus support/coverage/calibration/cost and ablations.
5. Robustness: transformations and failure analysis.
6. Limits: domain mismatch, provider drift, public-label limits, imperfect semantic checking, licensing, and no legal-correctness claim.
7. Legacy P2K graphs: case studies only, with artifact lineage.

Submit to **NeurIPS E&D** when the contribution is a rigorous evaluation framework, reusable adapters/artifacts, and credible evidence-supported findings. Consider **main NeurIPS** only for a strong repeated cross-task algorithmic result. Submit neither if the work remains an application demonstration without independent-label evidence; publish a reproducible systems/audit release instead.

The [NeurIPS 2026 E&D call](https://neurips.cc/Conferences/2026/CallForEvaluationsDatasets) treats evaluation as an object of study in its own right and emphasizes evaluation rigor, reusable artifacts, assumptions, and limitations. Its dates (abstracts 4 May 2026, papers 6 May 2026, notification 24 September 2026, per the [2026 dates page](https://neurips.cc/Conferences/2026/Dates)) are a shape reference only and say nothing about 2027 deadlines.

## 13. Risk register

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Benchmark mismatch | Some tasks do not naturally form a policy graph. | Exclude unless a frozen deterministic adapter is valid. |
| Test contamination | Documents may overlap splits; models may have seen text. | Hash/deduplicate sources, preserve official splits, log prompts, disclose unavoidable pretraining risk. |
| API drift | Hosted models can change between runs. | Pin IDs where possible; archive allowed raw predictions/settings; rerun before submission. |
| Cost/latency | Multi-agent runs may be impractical. | Predeclare budgets; report tokens/wall time/cost; pilot before full runs. |
| Gate too strict | Precision can come from near-total abstention. | Matched-coverage curves and fixed development threshold. |
| Gate too weak | Span/string checks can still accept semantic errors. | NLI evidence metric, adversarial mismatched spans, bounded claim. |
| License restrictions | Policy texts may not be redistributable. | Ledger, fetchers/hashes, and rights-aware artifact release. |
| Legacy ambiguity | Historical metadata may look like an experiment. | New clean experiment namespace/manifest; label old graphs historical. |

## 14. Definition of done

The paper is ready only when:

- three or more legally usable, independently labeled benchmark tracks have frozen adapters and frozen-split tests, using official splits wherever they are published;
- research mode enforces evidence gating and every accepted rule has hash-linked offsets and a decision record;
- baseline/full-method tables include repeated-run uncertainty, native task scores, support, coverage, calibration where applicable, cost, and latency;
- all stress tests and duplicate checks have recorded outcomes;
- a clean checkout regenerates every table/figure from immutable manifests; and
- the manuscript reports negative results and limitations required by the gates.

## Sources to verify at Gate 0

- [CODE-ACCORD preprint](https://arxiv.org/abs/2403.02231) and [Scientific Data article](https://www.nature.com/articles/s41597-024-04320-x)
- [ContractNLI project](https://stanfordnlp.github.io/contract-nli/)
- [DeonticBench preprint](https://arxiv.org/abs/2604.04443) — peer-review status, artifact release, and license unconfirmed
- [PolicyQA paper](https://arxiv.org/abs/2010.02557)
- [PrivacyQA paper](https://arxiv.org/abs/1911.00841)
- [Re-DocRED paper](https://arxiv.org/abs/2205.12696)
- [NeurIPS 2026 E&D call](https://neurips.cc/Conferences/2026/CallForEvaluationsDatasets) and [ICLR 2027 call for papers](https://iclr.cc/Conferences/2027/CallForPapers), as the venue-timing baseline to re-verify

Record access dates and final license decisions in sources.yaml. Recheck availability, terms, and submission requirements immediately before experiments and submission.
