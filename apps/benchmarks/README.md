# Benchmarks

Legal- and privacy-domain NLP corpora used to evaluate the policy-to-knowledge
extraction pipeline: clause extraction, data-practice classification, and
document-level inference against expert gold annotations.

The corpora themselves are **not committed** — `data/` and `raw/` are git-ignored
(~595 MB extracted, ~259 MB of archives, and two of the four are
redistribution-restricted). [`datasets.json`](datasets.json) is the source of
truth: it pins every upstream URL, SHA-256, license, and the verified contents,
so a fresh clone reproduces byte-identical corpora.

## Fetch the datasets

```bash
cd apps/benchmarks
python3 scripts/download_benchmarks.py            # all four
python3 scripts/download_benchmarks.py cuad mapp  # a subset
python3 scripts/download_benchmarks.py --verify   # status + checksums, no download
python3 scripts/download_benchmarks.py --force    # re-download existing archives
```

Archives land in `raw/`, extracted trees in `data/<id>/`. Only `curl` and the
Python standard library are required.

## The corpora

| id | Dataset | Task | Extracted | License |
|----|---------|------|-----------|---------|
| `cuad` | CUAD v1 (Atticus Project) | Clause extraction / span QA | 174 MB | CC BY 4.0 |
| `opp-115` | OPP-115 (Usable Privacy) | Data-practice classification | 339 MB | Research use, cite |
| `contract-nli` | ContractNLI (Stanford NLP) | Document-level NLI + evidence | 84 MB | CC BY 4.0 |
| `mapp` | MAPP Corpus (Usable Privacy) | Bilingual EN/DE practice annotation | 8 MB | Research use, cite |

### CUAD v1 — `data/cuad/CUAD_v1/`

510 commercial contracts with 13,000+ expert labels across 41 clause categories
(governing law, change of control, exclusivity, IP ownership, …).

- `CUAD_v1.json` — SQuAD 2.0 format, 510 documents / 20,910 QA pairs
- `master_clauses.csv` — 83 columns × 510 rows, clause text plus normalized answers
- `full_contract_pdf/` — 510 source PDFs, grouped `Part_I`–`Part_III` by contract type
- `full_contract_txt/` — the same 510 contracts as plaintext
- `label_group_xlsx/` — 28 per-category label reports

> Hendrycks, Burns, Chen & Ball (2021). *CUAD: An Expert-Annotated NLP Dataset for
> Legal Contract Review.* NeurIPS Datasets & Benchmarks. DOI 10.5281/zenodo.4595826

### OPP-115 — `data/opp-115/OPP-115/`

115 website privacy policies, ~23,000 data practices annotated by legal experts
across 10 categories.

- `annotations/` — 115 per-policy annotation CSVs
- `sanitized_policies/` — 115 segmented HTML policies (the annotation targets)
- `original_policies/` — 228 as-crawled captures
- `consolidation/` — majority-vote gold at 0.5 / 0.75 / 1.0 overlap thresholds
- `pretty_print/`, `pretty_print_uniquified/` — human-readable renderings
- `documentation/` — annotation scheme and manual

> Wilson et al. (2016). *The Creation and Analysis of a Website Privacy Policy
> Corpus.* ACL 2016.

### ContractNLI — `data/contract-nli/contract-nli/`

607 NDAs, each evaluated against 17 fixed hypotheses — a three-way entailment
label plus the evidence spans supporting it.

- `train.json` (423 docs) · `dev.json` (61) · `test.json` (123)
- `raw/` — the 607 source documents
- `LICENSE`, `TERMS` — upstream terms, read before redistributing

> Koreeda & Manning (2021). *ContractNLI: A Dataset for Document-level Natural
> Language Inference for Contracts.* Findings of EMNLP 2021.

### MAPP Corpus — `data/mapp/MAPP_Corpus/`

Bilingual mobile-app privacy policies: 64 English and 91 German, annotated with
the same practice taxonomy so GDPR-era EU and US policies can be compared.

- `English_sanitized_policies/` (64) + `English_consolidation/` (64)
- `German_sanitized_policies/` (91) + `German_consolidation/` (91)
- `documentation/` — annotation scheme and manual

> Arora et al. (2022). *A Tale of Two Regulatory Regimes: Creation and Analysis of
> a Bilingual Privacy Policy Corpus.* LREC 2022.

## Licensing

CUAD and ContractNLI are CC BY 4.0. OPP-115 and MAPP are provided by the Usable
Privacy Policy Project for research use and require citing their papers. All four
are downloaded from their original upstream sources — nothing is re-hosted here.
Cite the papers above in any published evaluation, and check each corpus's own
`readme` / `TERMS` before redistributing.
