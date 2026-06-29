# Explorer — Backend Integration Tests

Pytest suite that exercises the Flask REST API against a **live stack**
(running server + JanusGraph + OpenSearch). These tests are not part of CI; the
top-level `pytest.ini` deliberately ignores this directory.

> This directory was previously named `e2etests/`. It is now `tests/integration/`.

## Prerequisites

| Dependency | Default | Purpose |
| --- | --- | --- |
| Explorer server | `http://localhost:5001` | Flask API under test |
| JanusGraph | port 8182 | Graph database |
| Python | ≥ 3.10 | Test runtime |

The server's base URL defaults to `http://localhost:5001` and can be overridden with
the `BASE_URL` environment variable. At least one loaded graph must contain data.

## Setup

Run everything from the **explorer app root** (`apps/explorer`) so `src` is importable.

```bash
.venv/bin/pip install -r tests/integration/requirements.txt
```

Start the data stack and a server on the expected port in separate terminals:

```bash
docker compose up -d
SERVER_PORT=5001 URL_PREFIX=/app .venv/bin/python -m src.server
```

## Running

```bash
# All tests
PYTHONPATH=. .venv/bin/pytest tests/integration -v

# A single file
PYTHONPATH=. .venv/bin/pytest tests/integration/test_graph_api.py -v

# Point at a different server
BASE_URL=http://localhost:5050 PYTHONPATH=. .venv/bin/pytest tests/integration -v

# Stop on first failure
PYTHONPATH=. .venv/bin/pytest tests/integration -v -x
```

## Test files

| File | Coverage |
| --- | --- |
| `conftest.py` | Shared fixtures (`base_url`, `api`, `any_node_id`, …) |
| `test_graph_api.py` | `GET /api/graph` |
| `test_vertex_api.py` | `GET /api/vertex/<id>`, `POST /api/vertex`, vertex schema |
| `test_edge_api.py` | `POST /api/edge`, connection suggestions |
| `test_search_api.py` | `GET /api/search/text`, `GET /api/search/semantic` |
| `test_task_api.py` | `GET /api/tasks`, `POST /api/tasks/<id>/complete` |
| `test_annotation_api.py` | CRUD on `/api/annotations/<node_id>` |
| `test_action_button_integrity.py` | Cross-graph integrity: task node IDs, annotation round-trips, reviewed/approved persistence, vertex/edge ID safety |
| `test_gremlin_api.py` | `GET /api/gremlin/examples`, `POST /api/gremlin/execute` |
| `test_reference_api.py` | `GET /api/reference/resolve`, `GET /api/reference/chunk` |
| `test_v2_kg_properties.py` | v2 knowledge-graph property handling |
| `test_publish_docs_copy.py` | Document publish / copy behavior |
