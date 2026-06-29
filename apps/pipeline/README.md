# Pipeline

The Pipeline app turns source compliance documents into knowledge-graph
artifacts, comparison outputs, and HTML reports. This folder owns the CLI
orchestrators, the FastAPI backend, the React UI, the prompt packs, and the
generated outputs.

## What Lives Here

| Path | Purpose |
| --- | --- |
| `cli/extract.py` | Agents 1-6 extraction orchestrator (CLI) |
| `cli/compare.py` | Agents 7-10 comparison and merge orchestrator (CLI) |
| `agents/` | Agent implementations |
| `ui/backend/` | FastAPI API and WebSocket endpoints |
| `ui/frontend/` | React UI |
| `prompts/` | Shared prompt templates |
| `domain-prompts/` | Domain-specific prompt overrides |
| `compliance-files/` | Local input documents |
| `pipeline-output/` | Generated outputs; gitignored |

## Local Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp config.example.json config.json
cp .env.example .env
```

Add documents under `compliance-files/<batch>/`.

If you plan to use the settings UI, `config.json` must exist because the API
writes changes back to that file.

The React frontend installs its own `node_modules` automatically on first run.
If you want to do that up front:

```bash
cd ui/frontend && npm install
```

## Run

Local UI and API:

```bash
./start.sh
```

Equivalent wrapper:

```bash
./ui/start.sh
```

This starts the API on `http://localhost:8000` and the frontend on
`http://localhost:5173`.

CLI workflows:

```bash
.venv/bin/python cli/extract.py --provider openai
.venv/bin/python cli/extract.py --file compliance-files/<batch>/<file>.pdf --provider openai
.venv/bin/python cli/extract.py --batch --provider openai
.venv/bin/python cli/extract.py --step 3 --provider openai
.venv/bin/python cli/extract.py --domain aml --provider openai
.venv/bin/python cli/compare.py --list
.venv/bin/python cli/compare.py --g1 graphA --g2 graphB --workers 15
```

Docker workflows:

```bash
docker compose up -d p2k-ui
docker compose run --rm p2k --provider openai
```

`p2k-ui` serves the built UI and API together on port `8000`. `p2k` runs the
batch extractor without starting the interactive UI.

## Inputs, Outputs, and Configuration

- `compliance-files/`: source documents you supply
- `pipeline-output/<provider>/<name>/agent-*`: per-document artifacts and reports
- `pipeline-output/<provider>/_merged/<g1>_<g2>/`: graph-comparison artifacts
- `config.json`: provider, model, batching, and directory settings
- `domain-prompts/`: prompt overrides for `mortgage`, `aml`,
  `commercial_lending`, and `healthcare`

The checked-in `config.json` defaults to the `mortgage` domain.

## Testing

```bash
.venv/bin/python -m pytest tests/ -q
(cd ui/frontend && npm test)
(cd ui/frontend && npm run build)
```

Playwright E2E:

```bash
(cd ui/frontend && npm run test:e2e)
```

## Related Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): pipeline architecture
- [docs/DOCKER.md](docs/DOCKER.md): Docker workflows and deployment notes
- [docs/SETUP.md](docs/SETUP.md): config and secrets setup
- [docs/PRODUCT_DEFINITION.md](docs/PRODUCT_DEFINITION.md): product and use-case detail
- [agents/README.md](agents/README.md): agent-level reference
- [prompts/README.md](prompts/README.md): prompt packs and override rules
- [utils/README.md](utils/README.md): shared utility modules
- [ui/README.md](ui/README.md): FastAPI and React UI specifics
