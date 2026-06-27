# Policy to Knowledge — Web UI

A professional web interface for the knowledge graph extraction pipeline.

## Quick Start

```bash
# From the project root (pipeline/):
./start.sh

# Or from the ui/ directory entrypoint:
./ui/start.sh
```

This starts both servers:
- **Backend** (FastAPI): http://localhost:8000
- **Frontend** (React + Vite): http://localhost:5173

Open http://localhost:5173 in your browser.

If port 8000 is already in use on your machine, start the backend on a different port:

```bash
P2K_BACKEND_PORT=8001 ./start.sh
```

## Manual Start

### Backend
```bash
pip install fastapi uvicorn python-multipart
cd pipeline
uvicorn ui.backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend
```bash
cd ui/frontend
npm install
npm run dev
```

## UI Tests

Run the Playwright suite from the frontend workspace:

```bash
cd ui/frontend
npm run test:e2e
```

Open the Playwright UI runner:

```bash
cd ui/frontend
npm run test:e2e:ui
```

The same suite runs in GitHub Actions via `.github/workflows/ui-playwright.yml` for frontend-related pushes and pull requests.

## Architecture

```
Browser → React SPA (:5173) → Vite proxy → FastAPI (:8000) → Pipeline agents
                                                │
                                           WebSocket
                                        (live pipeline logs)
```

### Pages

| Page | Path | Description |
|------|------|-------------|
| Dashboard | `/` | Overview stats, recent runs, knowledge graph cards |
| Documents | `/documents` | Browse, upload, preview compliance documents |
| Pipeline | `/pipeline` | Configure & run extraction with live progress |
| Explorer | `/explorer` | Interactive KG visualization, rules table, entity browser |
| Compare | `/compare` | Set operations between two knowledge graphs |
| Run History | `/runs` | Past pipeline runs with expandable details |
| Settings | `/settings` | LLM provider config, pipeline parameters, domain selection |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/documents` | List compliance documents |
| POST | `/api/documents/upload` | Upload documents |
| POST | `/api/pipeline/start` | Launch extraction pipeline |
| GET | `/api/pipeline/{id}/status` | Pipeline run status |
| WS | `/ws/pipeline/{id}` | Real-time log streaming |
| GET | `/api/graphs` | List knowledge graphs |
| GET | `/api/graphs/{name}/visualization` | Serve interactive HTML |
| POST | `/api/compare` | Launch graph comparison |
| GET | `/api/runs` | Pipeline run history |
| GET/PUT | `/api/settings` | Read/update configuration |

## Tech Stack

- **Backend**: Python 3.11, FastAPI, SQLite (run metadata), WebSocket
- **Frontend**: React 19, TypeScript, Tailwind CSS, Vite, Lucide icons
- **Visualization**: Embeds existing vis.js HTML outputs from Agent 6 / Agent 10
- **UI Testing**: Playwright with mocked API fixtures for stable end-to-end coverage
