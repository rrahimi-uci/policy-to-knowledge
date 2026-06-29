# Backend E2E Tests — Explorer

End-to-end tests for the Flask API backend. These tests run against a **live
server + JanusGraph** instance and exercise every public endpoint.

## Prerequisites

| Dependency | Purpose |
|---|---|
| JanusGraph (port 8182) | Graph database |
| Explorer server (port 5001) | Flask API under test |
| Python ≥ 3.10 | Test runtime |

## Setup

Run from the **explorer app root** (`apps/explorer`) so `src` is importable.

```bash
.venv/bin/pip install -r tests/integration/requirements.txt
```

## Running

```bash
# All tests (server must be running on localhost:5001)
PYTHONPATH=. .venv/bin/pytest tests/integration -v

# Specific test file
PYTHONPATH=. .venv/bin/pytest tests/integration/test_graph_api.py -v

# With BASE_URL override
BASE_URL=http://localhost:5001 PYTHONPATH=. .venv/bin/pytest tests/integration -v

# Stop on first failure
PYTHONPATH=. .venv/bin/pytest tests/integration -v -x
```

## Test files

| File | Endpoints covered |
|---|---|
| `conftest.py` | Shared fixtures (`base_url`, `api`, `any_node_id`, …) |
| `test_graph_api.py` | `GET /api/graph` |
| `test_vertex_api.py` | `GET /api/vertex/<id>`, `POST /api/vertex`, vertex schema |
| `test_edge_api.py` | `POST /api/edge`, connection suggestions |
| `test_search_api.py` | `GET /api/search/text`, `GET /api/search/semantic` |
| `test_task_api.py` | `GET /api/tasks`, `POST /api/tasks/<id>/complete` |
| `test_annotation_api.py` | CRUD on `/api/annotations/<node_id>` |
| `test_action_button_integrity.py` | Cross-graph data integrity: task node IDs exist in graph, annotation round-trips, reviewed/approved toggle persistence, vertex/edge ID safety |
| `test_gremlin_api.py` | `GET /api/gremlin/examples`, `POST /api/gremlin/execute` |
| `test_reference_api.py` | `GET /api/reference/resolve`, `GET /api/reference/chunk` |
