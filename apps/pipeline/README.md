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
.venv/bin/python cli/extract.py --batch-dir <domain> --domain <domain> --target-rules 300 --workers 30
.venv/bin/python cli/extract.py --step 3 --provider openai

# Comparison (agents 7–10)
.venv/bin/python cli/compare.py --list
.venv/bin/python cli/compare.py --g1 <graphA> --g2 <graphB> --workers 15
```

Common `extract.py` flags:

| Flag | Description |
| --- | --- |
| `--file <path>` | Process a single document |
| `--batch-dir <domain>` | Process one `compliance-files/` subdirectory as a batch |
| `--domain <name>` | Domain prompt overrides (defaults to `config.json` `domain.active`) |
| `--target-rules <n>` | Target number of rules to extract |
| `--workers <n>` | Parallel LLM workers |
| `--step <1-6>` | Run a single agent step |
| `--skip-optimize` | Skip Agent 5 (Agent 6 uses Agent 4 output directly) |

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
