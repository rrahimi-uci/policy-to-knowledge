# Semantic assembly implementation plan

## Objective

Make Policy IR the provenance-bound semantic package from which the knowledge-graph,
DMN, and BPMN views are projected.  A document is never treated as a workflow merely
because it contains an obligation.  Every extracted item is classified as graph-only,
decision, process, both, or unresolved, and executable projections remain fail-closed.

## Canonical package

The canonical package has three connected layers:

1. **Evidence layer** — documents, canonical text, chunks, offsets, and source spans.
2. **Semantic layer** — mentions, canonical concepts, data definitions, policy clauses,
   semantic relations, scope, authority, and time.
3. **Projection layer** — decision and process candidates that reference admitted
   semantic records.  DMN and BPMN are generated views, never authoring formats.

`SemanticRelation` is a first-class record.  It preserves relation type, endpoints,
qualifiers, provenance, derivation method, and evidence.  The legacy graph projection
must expose only relations admitted by the evidence gate.

## Domain profile contract

Domain variance is configuration, not compiler branching.  A versioned
`DomainProfile` declares:

- terminology and aliases used for normalization;
- permitted semantic relation types;
- scope dimensions and authority sources;
- supported source media types and language metadata; and
- profile-owned extraction guidance.

Profiles may make a candidate *stricter*, but cannot relax Policy IR schema,
provenance, type, DMN, or BPMN admission rules.  The built-in `generic` profile is
deliberately small and works for any English-language compliance corpus without
embedding mortgage, healthcare, or insurance vocabulary in compiler code.

## Agent boundary

An agent/provider can propose records only through a schema-constrained request.  The
application owns document hashes, offsets, evidence IDs, canonical IDs, and admission.
An agent may return zero candidates and must explicitly mark semantics it did not type.
The first integration is file-backed: request artifacts are emitted deterministically
and proposal artifacts are admitted with the same parser and gate as any future hosted
model provider.  Provider SDKs remain outside this deterministic compiler package.

## Delivery order

1. Add semantic relations and profiles to the canonical package and generated JSON
   Schema; validate them in the evidence gate and project admitted relations.
2. Add schema-constrained semantic request/proposal artifacts and a deterministic
   assembler that merges them with an ingested Policy IR.
3. Add conservative decision/process synthesis: only explicitly proposed, evidenced
   candidates may be assembled; classification alone never creates an executable
   decision row or BPMN sequence flow.
4. Add CLI commands for profiles, request emission, proposal assembly, reports, and
   review artifacts.
5. Add fixtures across generic, mortgage-like, healthcare-like, and insurance-like
   terminology; measure evidence precision, semantic coverage, abstention, and admitted
   DMN/BPMN coverage separately.

## Non-goals for this change series

The compiler will not infer legal correctness, silently resolve ambiguous terms, or
turn unsupported branches, loops, gateways, or OCR text into executable BPMN.  Those
features require new evidence fields, validators, fixtures, and explicit profile
support before an emitter is extended.
