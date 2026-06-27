# Explorer

Explorer is the graph-serving side of Policy to Knowledge. It loads knowledge
graph JSON into JanusGraph, indexes text and embeddings, and exposes a Flask
plus vanilla-JS UI for search, graph navigation, editing, annotation, and
chat.

## What Lives Here

| Path | Purpose |
| --- | --- |
| `conf/graphs.yaml` | Source of truth for graph definitions |
| `scripts/generate_graph_config.py` | Regenerates JanusGraph config from the manifest |
| `src/main.py` | Setup, load, cleanup, and serve CLI |
| `src/server.py` | Flask app and streaming chat endpoints |
| `ui/` | Explorer frontend |
| `tests/` | Offline unit tests |
| `e2etests/` | Live backend API tests |
| `uitests/` | Playwright UI tests |

## Required Local Data

No sample graph data ships with this repo. You must supply:

- `kgs/<graph>-kg.json`: the knowledge graph JSON files referenced by `conf/graphs.yaml`
- `kbs/<graph>/`: source document chunks used for reference resolution
- matching entries in `conf/graphs.yaml`

The checked-in manifest currently defines `sample_guidelines` and
`example_policies` as example graph slots.

## Local Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

## Run

```bash
./start.sh
```

Useful modes:

- `./start.sh`: incremental startup, preserving existing data
- `./start.sh --fresh`: reload graphs and rebuild embeddings while keeping Docker volumes
- `./start.sh --clean`: wipe Docker volumes, Redis, and `app.db`, then rebuild

`./start.sh` does four things:

1. Regenerates JanusGraph config from `conf/graphs.yaml`
2. Starts Cassandra, OpenSearch, Redis, and JanusGraph with Docker
3. Loads empty or newly added graphs
4. Starts Flask at `http://localhost:5000/app`

Direct CLI entrypoints:

```bash
.venv/bin/python -m src.main setup
.venv/bin/python -m src.main setup-if-empty
.venv/bin/python -m src.main force-clean
.venv/bin/python -m src.main serve
```

## Key Runtime Settings

Set overrides in `.env` or your shell. The most commonly changed values are:

- `OPENAI_CHAT_MODEL`
- `OPENAI_REASONING_EFFORT`
- `MAX_TOOL_ROUNDS`
- `SERVER_PORT`
- `URL_PREFIX`
- `JANUSGRAPH_*`, `CASSANDRA_*`, `OPENSEARCH_*`, and `REDIS_*`

See [`conf/config.py`](conf/config.py) for the full list and defaults. Current
chat defaults are `gpt-4o-mini`, `low`, and `3`.

## Testing

Offline unit tests:

```bash
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests/ -q
```

Live suites:

```bash
(cd e2etests && ../.venv/bin/pip install -r requirements.txt && ../.venv/bin/pytest -v)
(cd uitests && npm install && npm test)
```

The live suites assume Docker infrastructure is running and at least one graph
contains data.

## Related Docs

- [architecture.md](architecture.md): detailed JanusGraph and service architecture
- [e2etests/README.md](e2etests/README.md): backend E2E test notes
- [uitests/README.md](uitests/README.md): Playwright UI test notes
