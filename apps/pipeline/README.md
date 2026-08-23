# Pipeline

The Pipeline app turns compliance policy documents into queryable knowledge
graphs. It bundles a FastAPI backend, a React/Vite UI, a 10-agent LLM extraction
pipeline, the prompt packs, and the generated outputs. This is the primary app
in the Policy to Knowledge suite.

- **Backend** — FastAPI API on port `8000`
- **Frontend** — React/Vite UI on port `5173`
- **Pipeline** — agents 1–6 extract a graph; agents 7–10 compare and merge graphs

## What Lives Here

| Path | Purpose |
| --- | --- |
| `cli/extract.py` | Extraction orchestrator (agents 1–6): documents → optimized knowledge graph |
| `cli/compare.py` | Comparison orchestrator (agents 7–10): compare/merge two graphs |
| `agents/` | Agent implementations (see `agents/README.md`) |
| `ui/backend/` | FastAPI API and WebSocket endpoints |
| `ui/frontend/` | React UI |
| `prompts/` | Base prompt templates |
| `domain-prompts/` | Domain-specific prompt overrides |
| `compliance-files/` | Local source documents (gitignored, user-supplied) |
| `pipeline-output/` | Generated artifacts (gitignored) |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp config.example.json config.json
cp .env.example .env
```

- `config.json` holds provider, model, batching, and directory settings. It is
  gitignored, so copy it from `config.example.json`. It is read by
  `utils/config.py`; override the path with `P2K_CONFIG_PATH`.
- The Settings UI writes changes back to `config.json`, so the file must exist
  before you use it.
- Add source documents under `compliance-files/<batch>/`.

The React frontend installs its own `node_modules` on first run. To do it
up front:

```bash
cd ui/frontend && npm install
```

## Run

### UI and API

```bash
./start.sh          # or: ./ui/start.sh
```

This serves the API on `http://localhost:8000` and the frontend on
`http://localhost:5173`.

### CLI

```bash
# Extraction (agents 1–6)
.venv/bin/python cli/extract.py --provider openai
.venv/bin/python cli/extract.py --file compliance-files/<batch>/<file>.pdf --provider openai
.venv/bin/python cli/extract.py --batch-dir <domain> --domain <domain> --target-rules 300
.venv/bin/python cli/extract.py --step 3 --provider openai

# Comparison (agents 7–10)
.venv/bin/python cli/compare.py --list
.venv/bin/python cli/compare.py --g1 <graphA> --g2 <graphB> --workers 15
```

### Full single-document run

Run this from `apps/pipeline/`. The checked-in performance profile selects
GPT-5.2 with medium reasoning, 40 local scheduling workers, six concurrent
documents, adaptive API concurrency, bounded retries, batched readiness work,
and checkpointed remediation. The repository-root `.env` is loaded
automatically; it must contain `OPENAI_API_KEY`.

```bash
KG_BATCH_NAME=fannie_mae_manual_20260821 \
../../.venv/bin/python cli/extract.py \
  --file compliance-files/fannie_mae/fannie_mae.pdf \
  --provider openai \
  --domain mortgage \
  --target-rules 300
```

Change `KG_BATCH_NAME`, `--file`, `--domain`, and `--target-rules` for a new
run. Outputs are stored under `pipeline-output/<KG_BATCH_NAME>/`. The CLI
streams each agent's output, including the long-running Agent 5 optimization
and Agents 5.5–5.7 readiness, remediation, and grounding passes in real time.
If the virtual environment lives inside `apps/pipeline`, replace
`../../.venv/bin/python` with `.venv/bin/python`.

The repeatable profile lives in `config.json` (local runtime) and
`config.example.json` (versioned defaults), so a normal CLI invocation does not
need a wall of environment flags. Environment variables remain optional,
per-run overrides. Forty workers keep local scheduling busy while the shared
adaptive limiter governs actual API pressure. Five rules and roughly 4,500
source words per extraction batch keep responses below the model output
ceiling; bounded retries and checkpoints recover individual failures without
repeating successful work.

Common `extract.py` flags:

| Flag | Description |
| --- | --- |
| `--file <path>` | Process a single document |
| `--batch-dir <domain>` | Process one `compliance-files/` subdirectory as a batch |
| `--domain <name>` | Domain prompt overrides (defaults to `config.json` `domain.active`) |
| `--target-rules <n>` | Target number of rules to extract |
| `--workers <n>` | Parallel LLM workers |
| `--step <stage>` | Run one stage (`1`, `2`, `3`, `3.5`, `4`, `5`, `5.5`, `5.6`, `5.7`, or `6`) |
| `--document-workers <n>` | Run independent documents in parallel subprocesses |
| `--skip-optimize` | Skip Agent 5 (Agent 6 uses Agent 4 output directly) |

### Executable-readiness artifacts

After Agent 5 optimizes the graph, Agent 5.5 performs the mandatory
DMN/BPMN-readiness pass. It writes these files under
`pipeline-output/<run>/agent-5-optimized/`:

- `optimized_compliance_knowledge_graph.json` — final rules, including DMN/BPMN
  projections, source-derived scope and exception-verification records.
- `kg_readiness_report.json` and `.md` — required conflict, dependency-chain,
  exception, scope, and four-invariant self-report.
- `corpus_manifest.json` — input/final cited-section comparison.

The extraction command exits nonzero if Agent 5.5 finds an invariant violation
or any rule still requires review. The evidence artifacts are still written so
the precise source limitation can be corrected and the pass rerun.

After changing only deterministic Agent 5.5 normalization or validation code,
replay the saved evidence and conflict results instead of repeating model calls:

```bash
KG_BATCH_NAME=<existing-run> \
KG_READINESS_SKIP_EVIDENCE=1 \
KG_READINESS_SKIP_CONFLICTS=1 \
PYTHONPATH=. ../../.venv/bin/python agents/agent_5_5_executable_readiness.py
```

Use these two skip flags only when the selected run already contains completed
full-document evidence and entity-conflict analyses. A normal/new document run
must leave both flags unset.

If Agent 5.5 reports review-required rules, run only the focused remediation
stage; Agents 1-5 do not need to be repeated:

```bash
KG_BATCH_NAME=<existing-run> \
PYTHONPATH=. ../../.venv/bin/python cli/extract.py \
  --step 5.6 --provider openai --workers 40 --domain <domain>
```

Agent 5.6 processes only failed exception/scope rules and unresolved conflict
pairs. It checkpoints model results in `agent_5_6_checkpoint.jsonl`, stops when
a pass makes no further rules ready, reruns all deterministic invariants, and
never clears `requires_review` without passing those gates. The full pipeline
launches 5.6 automatically when Agent 5.5 requests remediation.

### Independent grounding certification

Agent 5.7 runs after all Agent 5.5/5.6 mutations. It does not repair or rewrite
rules. Instead, it projects every description, condition, condition-logic
expression, outcome, party, scope, exception, and test vector into atomic
claims and asks an independent verification prompt to classify each claim as
`supported`, `contradicted`, or `insufficient_evidence`. A supported or
contradicted result is accepted only when its exact quote can also be located
deterministically in the organized source corpus.

The stage fails closed if a claim is missing, duplicated, contradicted, or
insufficient; if the verifier returns an unexpected rule/claim ID; or if any
cited evidence text cannot be found in its source chunk. It writes:

- `kg_grounding_report.json` and `.md` — graph-level pass/fail counts and
  rule-level failure explanations.
- `agent_5_7_grounding_checkpoint.jsonl` — content-keyed batch results reused
  only while the model, reasoning effort, claim packets, and corpus hash match.
- `metadata.grounding_certification` in the optimized graph — the corpus and
  graph hashes certified by the pass.

Run the verifier alone after a focused remediation or other optimized-graph
change:

```bash
KG_BATCH_NAME=<existing-run> \
PYTHONPATH=. ../../.venv/bin/python cli/extract.py \
  --step 5.7 --provider openai --workers 40 --domain <domain>
```

Stage 6 refuses to visualize an optimized graph unless the Agent 5.7 report
passes and its graph/corpus hashes still match. The explicit `--skip-optimize`
path may visualize Agent 4 output, but labels that path as uncertified.

### Throughput and stable defaults

Agents 2 and 3 remain sequential because Agent 3 consumes Agent 2's entity
catalog. The pipeline safely overlaps read-only Agent 3.5 validation with Agent
4, batches four Agent 5.5 evidence checks per request, checkpoints Agent
2/5.5/5.6/5.7 progress, and shares an adaptive API limiter across subprocesses.
The limiter starts at twelve requests, increases after three successes, caps
at 32, and halves on throttling or transport backpressure — so a burst of 429s
or connection errors self-corrects back down instead of hanging the run. Each
run writes `llm_performance.json`; watch `current_limit`/`total_throttled`
there and lower the `KG_GLOBAL_LLM_CONCURRENCY_*` variables below if your
OpenAI project's rate limits sit below these defaults.

| Variable | Default | Purpose |
| --- | ---: | --- |
| `pipeline.max_workers` | `40` | Local scheduling capacity; not API concurrency |
| `pipeline.document_workers` | `6` | Independent documents processed concurrently |
| `KG_LLM_CONCURRENCY` | `16` | Per-process safety gate above the shared limiter |
| `KG_GLOBAL_LLM_CONCURRENCY_INITIAL` | `12` | Measured stable starting request limit |
| `KG_GLOBAL_LLM_CONCURRENCY_MAX` | `32` | Adaptive ceiling across subprocesses |
| `KG_GLOBAL_LLM_SUCCESS_WINDOW` | `3` | Successes before increasing the ceiling |
| `KG_READINESS_WORKERS` | `40` | Local Agent 5.5 scheduling workers |
| `KG_READINESS_LLM_CONCURRENCY` | `16` | Local API gate; global limiter still applies |
| `KG_READINESS_RULES_PER_REQUEST` | `4` | Agent 5.5 evidence batch size |
| `KG_REMEDIATION_RULES_PER_REQUEST` | `4` | Agent 5.6 source-remediation batch size |
| `KG_REMEDIATION_PAIRS_PER_REQUEST` | `12` | Agent 5.6 conflict-pair batch size |
| `KG_REMEDIATION_WORKERS` | `40` | Local Agent 5.6 scheduling workers |
| `KG_REMEDIATION_LLM_CONCURRENCY` | `16` | Local API gate; global limiter still applies |
| `KG_REMEDIATION_MAX_PASSES` | `3` | Targeted passes, with no forced readiness |
| `KG_GROUNDING_RULES_PER_REQUEST` | `4` | Rules per independent verifier request |
| `KG_GROUNDING_CLAIMS_PER_REQUEST` | `48` | Claim ceiling per verifier request |
| `KG_GROUNDING_RELATIONSHIPS_PER_REQUEST` | `12` | Compact graph relationships per request |
| `KG_GROUNDING_WORKERS` | `40` | Local Agent 5.7 batch scheduling workers |
| `KG_GROUNDING_LLM_CONCURRENCY` | `24` | Local verifier API gate; global limiter still applies |
| `KG_ENTITY_EARLY_STOP` | `true` | Stop Agent 2 after measured convergence |
| `KG_ENTITY_MIN_ITERATIONS` | `2` | Minimum Agent 2 iterations |

Independent-document concurrency defaults to six; use `--document-workers
<n>` only to override it. Each file receives an isolated subprocess/output tree
while every file shares the adaptive limiter, so raising document concurrency
increases scheduling parallelism without bypassing the shared API ceiling.
Custom shared `--organized` or `--output` paths disable document concurrency
to prevent collisions.

If your OpenAI project's actual rate limit is lower than these defaults, the
adaptive limiter discovers that automatically (it halves `current_limit` and
backs off on the first 429/timeout) — but for a known-lower tier it's faster
to set `KG_GLOBAL_LLM_CONCURRENCY_INITIAL`/`_MAX` explicitly than to let the
first run rediscover it via throttling.

### Docker

```bash
docker compose up -d p2k-ui
docker compose run --rm p2k --provider openai
```

| Image | Built from | Purpose |
| --- | --- | --- |
| `p2k-ui` | `Dockerfile.api` | FastAPI API + built React UI on port `8000` |
| `p2k` | `Dockerfile.cli` | Batch extractor (entrypoint `cli/extract.py`), no UI |

## Inputs, Outputs, and Configuration

- **Inputs** — source documents in `compliance-files/`.
- **Extraction outputs** — `pipeline-output/<source>/agent-N-.../` (per document).
- **Comparison outputs** — `pipeline-output/_merged/<g1>_<g2>/agent-N-.../`.
- **Provider** — OpenAI only. Models are configured in `config.json`:
  reasoning `gpt-5.2`, optimizer `gpt-5.2`, optimizer agent `gpt-5-mini`,
  embeddings `text-embedding-ada-002`, `reasoning_effort: medium`.
- **Domains** — `mortgage`, `aml`, `healthcare`, `commercial_lending`. Base
  prompts live in `prompts/`; per-domain overrides in `domain-prompts/`. The
  checked-in default is `mortgage`.

## Testing

```bash
.venv/bin/python -m pytest tests/ -q     # backend unit tests (CI)
(cd ui/frontend && npm test)             # frontend unit tests (Vitest)
(cd ui/frontend && npm run build)        # production build
(cd ui/frontend && npm run test:e2e)     # Playwright E2E
```

## Related Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — pipeline architecture
- [docs/DOCKER.md](docs/DOCKER.md) — Docker workflows and deployment
- [docs/SETUP.md](docs/SETUP.md) — config and secrets setup
- [docs/PRODUCT_DEFINITION.md](docs/PRODUCT_DEFINITION.md) — product and use cases
- [agents/README.md](agents/README.md) — agent-level reference
- [prompts/README.md](prompts/README.md) — prompt packs and override rules
- [utils/README.md](utils/README.md) — shared utility modules
- [ui/README.md](ui/README.md) — FastAPI and React UI specifics
