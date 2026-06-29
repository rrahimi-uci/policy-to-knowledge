# Prompt Templates

Base prompt templates for the 10-agent extraction pipeline. These are the **domain-agnostic baseline** prompts; each compliance domain ships its own overrides under `domain-prompts/<domain>/`, and the `PromptManager` resolves the domain version first, falling back to the templates here.

All prompts target the OpenAI models configured in `config.json` (reasoning `gpt-5.2`, optimizer `gpt-5.2`).

## Templates

| Template | Consumed by | Purpose |
|----------|-------------|---------|
| `document_structure_analysis.txt` | Agent 1 — Document Organizer | Segment a document into logical sections when no usable table of contents is present. |
| `entity_extraction.txt` | Agent 2 — Entity Extractor | Identify domain entities, attributes, and relationships from organized document sections. |
| `entity_refinement.txt` | Agent 2 — Entity Extractor (refinement loop) | Score and iteratively improve entity/relationship extractions across passes. |
| `entity_resolution.txt` | Entity reconciliation | Merge and reconcile duplicate or overlapping entities into a canonical set. |
| `business_rules_extraction.txt` | Agent 3 — Rules Extractor | Extract structured business rules (conditions, consequences, exceptions, source references) from document batches. |
| `validation_report.txt` | Agent 3.5 — Rule Validator | Produce a quality-assessment report over the extracted rules with actionable recommendations. |
| `rule_resolution.txt` | Rule reconciliation | Reconcile conflicting or overlapping rules during merge steps. |
| `rule_deduplication.txt` | Agent 5 — Knowledge Graph Optimizer | Identify and merge duplicate rules while preserving meaningful variations. |
| `dependency_analysis.txt` | Agent 5 — Knowledge Graph Optimizer | Map dependencies and relationships between business rules. |
| `rule_matcher.txt` | Agent 8 — Semantic Rule Matcher | Compare rules across two knowledge graphs for semantic equivalence (used by `cli/compare.py`). |
| `rule_matcher_batch.txt` | Agent 8 — Semantic Rule Matcher | Batched variant of the matcher for higher-throughput cross-graph comparison. |

The same 11 template names exist in every domain directory.

## Domains

Domain overrides live in `domain-prompts/<domain>/`. Each directory contains the full set of 11 templates, specialized with domain terminology, entity vocabularies, rule taxonomies, and worked examples.

| Directory | Domain | Focus |
|-----------|--------|-------|
| `prompts/` | Shared baseline | Domain-agnostic fallback templates. |
| `domain-prompts/mortgage/` | Mortgage lending | Agency/investor guidelines and lender overlays. |
| `domain-prompts/aml/` | Anti-money laundering | BSA/AML compliance — SAR, CTR, CDD, KYC. |
| `domain-prompts/commercial_lending/` | Commercial lending | Loan origination — collateral, covenants. |
| `domain-prompts/healthcare/` | Healthcare | HIPAA, patient and provider entities. |

The active domain is read from `config.json` (`domain.active`) and is configurable in the Settings UI.

## Resolution order

Prompts are loaded through `utils/prompt_manager.py`. For each requested template name, the resolver checks:

```text
1. domain-prompts/<active_domain>/<name>.txt   (domain-specific)
2. prompts/<name>.txt                          (shared fallback)
```

```python
from utils.prompt_manager import get_prompt_manager

# Singleton; resolves the active domain from Config automatically and
# rebuilds itself if the domain changes.
pm = get_prompt_manager()

# Load the raw template (domain version first, baseline fallback).
template = pm.load_prompt("business_rules_extraction")

# Or load and substitute parameters in one call.
prompt = pm.format_prompt(
    "business_rules_extraction",
    entity_context=entity_definitions,
    rules_per_batch=10,
    batch_num=1,
    sample_content=document_chunks,
)
```

Parameters are substituted with Python `str.format`, so template placeholders use `{name}` syntax.

## Adding a domain

1. Register the domain in `config.json` under `domain.available` and set `domain.active`.
2. Create the directory and copy the baseline templates:

   ```bash
   mkdir -p domain-prompts/insurance
   cp prompts/*.txt domain-prompts/insurance/
   ```

3. Edit each template to use domain-specific terminology, entity types, and examples.
4. Run the pipeline against the new domain:

   ```bash
   python3 cli/extract.py
   ```

   `PromptManager` loads the new domain's templates automatically.

## Authoring guidelines

- **Structured output.** Prompts requesting structured data specify an exact JSON schema and instruct the model to return JSON only (no Markdown fences).
- **Traceability.** Extraction prompts require source references (document section, page, clause) on every item.
- **Quality over quantity.** Prefer fewer complete items with all required fields over many partial ones; no placeholder or `TBD` values.
- **Consistent placeholders.** Keep `{parameter}` names aligned with the keyword arguments passed by the corresponding agent.

## Related

- [Agents README](../agents/README.md) — how each agent uses these prompts
- [Utils README](../utils/README.md) — `prompt_manager` and configuration
- [Main README](../README.md) — project overview
