# Policy to Knowledge

Policy to Knowledge is a monorepo for turning compliance source material into
structured knowledge graphs and exploring the results through a browser-based
suite.

## Components

| Path | Purpose | Default URL |
| --- | --- | --- |
| `frontend/` | Suite shell that links the apps together | `http://localhost:4000` |
| `pipeline/` | Extraction pipeline, compare workflow, FastAPI API, and React UI | `http://localhost:8000`, `http://localhost:5173` |
| `assistant/` | Explorer backed by JanusGraph, Cassandra, OpenSearch, and Redis | `http://localhost:5000/app` |
| `video/` | Demo capture and narration assets | n/a |

## Quick Start

1. Copy the local config templates:

```bash
cp .env.example .env
cp pipeline/config.example.json pipeline/config.json
```

2. Create the Python environments expected by the launchers:

```bash
python3 -m venv pipeline/.venv
pipeline/.venv/bin/pip install -r pipeline/requirements-dev.txt

python3 -m venv assistant/.venv
assistant/.venv/bin/pip install -r assistant/requirements.txt
```

3. Add your local data:

- Put source documents under `pipeline/compliance-files/`.
- Put graph JSON files under `assistant/kgs/`.
- Put source document chunks under `assistant/kbs/`.
- Make sure `assistant/conf/graphs.yaml` matches those files.

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
- Pipeline only: `cd pipeline && ./start.sh`
- Explorer only: `cd assistant && ./start.sh`
- Extract one document: `cd pipeline && .venv/bin/python knowledge_graph_generation.py --file compliance-files/<batch>/<file>.pdf --provider openai`
- Run batch extraction: `cd pipeline && .venv/bin/python knowledge_graph_generation.py --batch --provider openai`
- Compare two graphs: `cd pipeline && .venv/bin/python join_graphs.py --g1 graphA --g2 graphB --workers 15`
- Incremental graph load without a full restart: `cd assistant && .venv/bin/python -m src.main setup-if-empty`

## Key Files

- `assistant/conf/graphs.yaml`: graph manifest and traversal-source names.
- `pipeline/config.json`: pipeline provider and runtime settings.
- `pipeline/domain-prompts/`: domain-specific prompt overrides.
- `pipeline-output/`: generated artifacts; gitignored.
- `.env`: shared local environment overrides; gitignored.

No sample proprietary data ships with this repository. The checked-in manifest
contains example graph names, but you must supply the actual KG JSON and source
chunks locally.

## Documentation Map

- [pipeline/README.md](pipeline/README.md): extraction pipeline, compare workflow, and UI/API.
- [assistant/README.md](assistant/README.md): Explorer runtime, data manifest, and graph loading.
- [pipeline/docs/ARCHITECTURE.md](pipeline/docs/ARCHITECTURE.md): pipeline architecture.
- [pipeline/docs/DOCKER.md](pipeline/docs/DOCKER.md): containerized pipeline workflows.
- [pipeline/docs/SETUP.md](pipeline/docs/SETUP.md): pipeline config and secrets.
- [video/README.md](video/README.md): demo-video generation.
- [CONTRIBUTING.md](CONTRIBUTING.md): local setup and test expectations.

## Testing

```bash
(cd pipeline && .venv/bin/python -m pytest tests/ -q)
(cd assistant && .venv/bin/python -m pytest tests/ -q)
(cd frontend && npm test)
(cd pipeline/ui/frontend && npm test)
```

Live Playwright and API E2E suites need the corresponding services running
first; see the component READMEs.
