# Policy to Knowledge

Policy to Knowledge is a monorepo for turning compliance source material into
structured knowledge graphs and exploring the results through a browser-based
suite.

## Components

| Path | Purpose | Default URL |
| --- | --- | --- |
| `apps/shell/` | Suite shell that links the apps together | `http://localhost:4000` |
| `apps/pipeline/` | Extraction pipeline, compare workflow, FastAPI API, and React UI | `http://localhost:8000`, `http://localhost:5173` |
| `apps/explorer/` | Explorer backed by JanusGraph, Cassandra, OpenSearch, and Redis | `http://localhost:5000/app` |
| `tools/video/` | Demo capture and narration assets | n/a |

## Project structure

```text
.
├── apps/
│   ├── shell/        # Suite shell — React + Vite (port 4000)
│   ├── pipeline/     # Extraction pipeline + FastAPI API + React UI
│   └── explorer/     # Graph explorer — Flask + vanilla JS UI
├── tools/
│   └── video/        # Demo capture & narration tooling
├── docs/             # GitHub Pages site (served from /docs)
├── assets/           # Shared brand assets (logo)
├── docker-compose.yml  # Full-stack local stack
├── start.sh / stop.sh  # One-command local orchestration
└── .github/workflows/  # CI (pytest + vitest + builds)
```

## Quick Start

1. Copy the local config templates:

```bash
cp .env.example .env
cp apps/pipeline/config.example.json apps/pipeline/config.json
```

2. Create the Python environments expected by the launchers:

```bash
python3 -m venv apps/pipeline/.venv
apps/pipeline/.venv/bin/pip install -r apps/pipeline/requirements-dev.txt

python3 -m venv apps/explorer/.venv
apps/explorer/.venv/bin/pip install -r apps/explorer/requirements.txt
```

3. Add your local data:

- Put source documents under `apps/pipeline/compliance-files/`.
- Put graph JSON files under `apps/explorer/kgs/`.
- Put source document chunks under `apps/explorer/kbs/`.
- Make sure `apps/explorer/conf/graphs.yaml` matches those files.

4. Start the full stack:

```bash
./start.sh
```

5. Open `http://localhost:4000`.

Stop everything with:

```bash
./stop.sh --all
```

`./start.sh` starts the Explorer Docker infrastructure, the Pipeline API and
UI, and the suite shell. The Node frontends install `node_modules` on first
run; the Python virtualenvs must already exist.

## Common Workflows

- Full suite: `./start.sh`
- Pipeline only: `cd apps/pipeline && ./start.sh`
- Explorer only: `cd apps/explorer && ./start.sh`
- Extract one document: `cd apps/pipeline && .venv/bin/python knowledge_graph_generation.py --file compliance-files/<batch>/<file>.pdf --provider openai`
- Run batch extraction: `cd apps/pipeline && .venv/bin/python knowledge_graph_generation.py --batch --provider openai`
- Compare two graphs: `cd apps/pipeline && .venv/bin/python join_graphs.py --g1 graphA --g2 graphB --workers 15`
- Incremental graph load without a full restart: `cd apps/explorer && .venv/bin/python -m src.main setup-if-empty`

## Key Files

- `apps/explorer/conf/graphs.yaml`: graph manifest and traversal-source names.
- `apps/pipeline/config.json`: pipeline provider and runtime settings.
- `apps/pipeline/domain-prompts/`: domain-specific prompt overrides.
- `pipeline-output/`: generated artifacts; gitignored.
- `.env`: shared local environment overrides; gitignored.

No sample proprietary data ships with this repository. The checked-in manifest
contains example graph names, but you must supply the actual KG JSON and source
chunks locally.

## Documentation Map

- [apps/pipeline/README.md](apps/pipeline/README.md): extraction pipeline, compare workflow, and UI/API.
- [apps/explorer/README.md](apps/explorer/README.md): Explorer runtime, data manifest, and graph loading.
- [apps/pipeline/docs/ARCHITECTURE.md](apps/pipeline/docs/ARCHITECTURE.md): pipeline architecture.
- [apps/pipeline/docs/DOCKER.md](apps/pipeline/docs/DOCKER.md): containerized pipeline workflows.
- [apps/pipeline/docs/SETUP.md](apps/pipeline/docs/SETUP.md): pipeline config and secrets.
- [tools/video/README.md](tools/video/README.md): demo-video generation.
- [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md): local setup and test expectations.

## Testing

Every suite emits [Allure](https://allurereport.org/) results and code coverage.

```bash
# Backend (pytest → coverage + allure-results/)
(cd apps/pipeline  && .venv/bin/python -m pytest)
(cd apps/explorer  && .venv/bin/python -m pytest)

# Frontend (vitest → coverage + allure-results/)
(cd apps/shell                 && npm test -- --coverage)
(cd apps/pipeline/ui/frontend  && npm test -- --coverage)
```

Generate a combined Allure report from all suites (requires the
[Allure CLI](https://allurereport.org/docs/install/)):

```bash
mkdir -p /tmp/allure
cp apps/*/allure-results/* apps/pipeline/ui/frontend/allure-results/* /tmp/allure/ 2>/dev/null
allure serve /tmp/allure
```

CI runs all four suites with coverage, uploads each suite's `allure-results`,
and publishes a merged **Allure report** artifact.

Unit tests focus on the logic layer (config, services, stores, hooks, pure
helpers). Data-heavy page components and live-backend modules are exercised by
the Playwright / API E2E suites, which need the corresponding services running
first; see the component READMEs.
