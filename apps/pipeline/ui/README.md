# Pipeline UI

The FastAPI backend and React/Vite frontend that sit on top of the extraction
pipeline. The backend exposes REST and WebSocket endpoints for running the
pipeline and browsing results; the frontend is the operator interface (documents,
pipeline runs, graph explorer, and the Settings page that edits `config.json`).

## Start

From `pipeline/` (or use the wrapper `./ui/start.sh`):

```bash
./start.sh
```

This starts:

- backend at `http://localhost:8000`
- frontend at `http://localhost:5173`

## Manual Development

Backend (from `pipeline/`):

```bash
.venv/bin/uvicorn ui.backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Frontend (from `pipeline/ui/frontend/`):

```bash
npm install
npm run dev
```

## Tests

From `pipeline/ui/frontend/`:

```bash
npm test          # Vitest unit tests
npm run build     # production build
npm run test:e2e  # Playwright E2E
```

The frontend build and Vitest checks run in the root CI workflow
(`.github/workflows/ci.yml`).

## Structure

| Path | Purpose |
| --- | --- |
| `backend/main.py` | FastAPI app entrypoint |
| `backend/routers/` | REST endpoints (documents, pipeline, graphs, settings, …) |
| `backend/ws/` | WebSocket handlers (pipeline and impact-analysis streams) |
| `backend/services/` | Run storage and orchestration helpers |
| `frontend/src/` | React application |
| `frontend/tests/e2e/` | Playwright tests |
