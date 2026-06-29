# Explorer

The graph-serving application of the **Policy to Knowledge** monorepo. Explorer loads
knowledge-graph JSON into JanusGraph, indexes text and (optionally) embeddings, and
serves a Flask API plus a vanilla-JS/D3 UI for search, graph navigation, editing,
annotation, and an OpenAI-powered chat assistant.

## Stack

| Component | Technology | Default port |
| --- | --- | --- |
| Graph database | JanusGraph 1.0.0 | 8182 |
| Storage backend | Cassandra 4.1 | 9042 |
| Index & vector search | OpenSearch 2.17.1 | 9200 |
| Cache | Redis 7 | 6379 |
| API + UI | Flask 3.1 (`src/server.py`) + D3 UI (`ui/`) | 5000 |

The data stack runs via `docker compose` (`docker-compose.yml`). The Flask server runs
on the host (it is not containerized) under the URL prefix **`/app`**.

> On macOS, port 5000 is frequently taken by AirPlay/Docker. The suite scripts and
> tests commonly use `SERVER_PORT=5050` instead.

## Layout

| Path | Purpose |
| --- | --- |
| `conf/graphs.yaml` | Graph manifest — single source of truth for every served graph |
| `conf/config.py` | All tunable settings and their defaults |
| `scripts/generate_graph_config.py` | Regenerates JanusGraph config from the manifest |
| `src/main.py` | Setup / load / clean / serve CLI |
| `src/server.py` | Flask app, REST API, and SSE chat endpoints |
| `src/data_loader.py` | Loads knowledge-graph JSON into JanusGraph |
| `src/semantic_search.py` | OpenSearch k-NN semantic search (optional) |
| `ui/` | Explorer frontend (HTML/CSS/JS + D3) |
| `tests/` | Unit tests (pytest, CI) |
| `tests/integration/` | Live backend API tests (pytest) |
| `tests/e2e/` | Playwright UI tests |

## Required local data

No sample graph data ships with this repo. You must supply your own:

- `kgs/<graph>-kg.json` — the knowledge-graph JSON files referenced by `conf/graphs.yaml`
  (the `kgs/` directory is gitignored)
- `kbs/<graph>/` — source document chunks used for reference resolution
- a matching entry per graph in `conf/graphs.yaml`

The checked-in manifest defines two example graph slots: `sample_guidelines` and
`example_policies`.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Semantic search is **optional**. It requires `sentence-transformers` (included in
`requirements.txt`). When that dependency is absent, the server, setup, and the rest of
the app degrade gracefully — graph traversal, keyword search, and chat all keep working;
only the semantic-search endpoint returns `503`.

## Run

The simplest path is the bundled script, which brings up the data stack and the server:

```bash
./start.sh
```

| Mode | Effect |
| --- | --- |
| `./start.sh` | Incremental startup; preserves existing data |
| `./start.sh --fresh` | Clear and reload graphs, embeddings, SQLite, and Redis (keeps Docker volumes) |
| `./start.sh --clean` | Destroy all data stores (Docker volumes, Redis, `app.db`) and rebuild |

`./start.sh`:

1. Regenerates JanusGraph config from `conf/graphs.yaml`
2. Starts Cassandra, OpenSearch, Redis, and JanusGraph via `docker compose`
3. Loads empty or newly added graphs (`src.main setup-if-empty`)
4. Starts Flask at `http://<host>:${SERVER_PORT}${URL_PREFIX}` (defaults `:5000/app`)

### Manual startup

Bring up the data stack, then run the server standalone:

```bash
docker compose up -d
SERVER_PORT=5050 URL_PREFIX=/app .venv/bin/python -m src.server
```

Direct CLI entrypoints:

```bash
.venv/bin/python -m src.main setup            # full setup
.venv/bin/python -m src.main setup-if-empty   # load only when graphs are empty (preserves IDs)
.venv/bin/python -m src.main force-clean      # destroy ALL data, then rebuild
.venv/bin/python -m src.main serve            # run the Flask server
```

Load graph data directly:

```bash
.venv/bin/python -m src.data_loader all       # load every graph in the manifest
.venv/bin/python -m src.data_loader sample_guidelines   # load one graph
```

## Key runtime settings

Set overrides in `.env` or the shell. The most commonly changed values:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SERVER_PORT` | `5000` | Flask listen port |
| `URL_PREFIX` | `/app` | URL prefix the server is mounted under |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | Chat assistant model |
| `OPENAI_REASONING_EFFORT` | `low` | Reasoning effort (only applied to models that support it) |
| `MAX_TOOL_ROUNDS` | `3` | Max tool-calling rounds per chat turn |
| `JANUSGRAPH_*`, `CASSANDRA_*`, `OPENSEARCH_*`, `REDIS_*` | — | Backend hosts, ports, and tuning |

See [`conf/config.py`](conf/config.py) for the full list and defaults.

## Testing

Unit tests (offline, run in CI):

```bash
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python -m pytest tests/ -q
```

`pytest.ini` ignores `tests/integration` and `tests/e2e`, so CI stays unit-only.

Live suites require the Docker stack running and at least one loaded graph:

```bash
# Backend API tests (server must be running)
PYTHONPATH=. .venv/bin/pytest tests/integration -v

# Playwright UI tests
cd tests/e2e && npm install && BASE_URL=http://localhost:5050/app npx playwright test
```

## Related docs

- [docs/architecture.md](docs/architecture.md) — JanusGraph and service architecture
- [tests/integration/README.md](tests/integration/README.md) — backend API test notes
- [tests/e2e/README.md](tests/e2e/README.md) — Playwright UI test notes
